"""Steer back's correction, composed without a model (DRC-4681).

Item 7 of
[DEC-24](docs/design-reading-a-session.md#dec-24-your-intent-is-a-drafted-goal-and-a-checklist-and-a-correction-is-yours-to-copy)
fixes the fields: the goal, each outcome line with its state, and the cited entries' times. The
owner approved the template on 2026-09-28 as exact text, and ruled that the server writes each
entry as a placeholder the page fills with "#n" from its own numbering or drops, because a number
is recomputed on the page and never stored (item 11). So nothing here reads a summary, a command, a
check name, tool output or a message's words: a fact contributes its time and its id, and the id
travels only inside a placeholder. Two exceptions. By the owner's delegation of 2026-10-04, a claim
of the agent's that the record contradicts or does not show is quoted by its message's published
title, the first sentence the activity list already shows, and never by the words a reading read.
By the owner's ruling of 2026-10-20, each departure carries the stored reading's own `detail` on an
indented line labelled as Compass's reading, neutralised by `explanation` so a paste cannot turn it
into a command or a new block, by the
[amendment](docs/design-reading-a-session.md#amended-2026-10-20-owner-the-correction-carries-the-explanation).
By the owner's second ruling of that day (local time and quoted words,
[amended](docs/design-reading-a-session.md#amended-2026-10-20-owner-local-time-and-quoted-words)),
the times are the reader's local clock, a placeholder is drawn as nothing (an agent never saw the
activity list's numbers), and a departure cited at one of the agent's messages quotes that
message's published title, neutralised as the explanation is, so the agent can find the moment.

`compose` is pure. The route hands it the session's published row, its observed record and the
later-direction floor (`annotations.direction_floor`), and it answers the parts or why there are
none. A line's state is re-derived from the stored reading against the record as it stands now,
with the previous page's rules for whether a verdict survives
(`nextCockpitReadingCriterion`), so the text never claims a departure the panel beside it
has demoted.

The `next*` functions this module names are the previous page's. They survive only as the frozen,
study-bound parts under `scripts/frozen-page/` (`scripts/tests/test_frozen_page.py` pins them); the
React page ports the same rules under `frontend/src/drift/`.
"""

from __future__ import annotations

import datetime
import functools
import re
import time
import unicodedata
import zoneinfo
from typing import TYPE_CHECKING, Any

from . import copied_corrections, reading, records

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping

# The route's own cap, so a correction this composes is always one the copy route accepts.
CAP_CHARS = copied_corrections.CORRECTION_CAP_CHARS
# Two budgets, so carrying the explanations (owner, 2026-10-20) changes no refusal and drops no
# line: the template's own lines keep item 7's 2,000, measured without the explanations, and each
# explanation has a fixed room of its own. A correction that composed before still composes, with
# every explanation it is owed, and `CAP_CHARS` is the sum.
LINES_CAP_CHARS = 2000
# Labelled as Compass's reading in the card's own words, on its own indented line under the line it
# explains, so neither an agent nor the reader takes it for the reader's words.
EXPLANATION_LABEL = "\n  Why Compass reads this as drift: "
# The stored detail's bound, `RuntimeConfig.annotation_text_cap_chars` at its default, and not read
# from the config: the page mirrors the cap as a constant, so it cannot vary per run. A cut adds
# one "…", as the producer's own cut does.
EXPLANATION_TEXT_CHARS = 240
EXPLANATION_MAX_CHARS = len(EXPLANATION_LABEL) + EXPLANATION_TEXT_CHARS + 1
# What can carry one: the goal, every outcome line and a contradicted claim.
EXPLANATIONS_MAX = 2 + reading.MAX_OUTCOME_LINES
# The agent's own words where a departure is cited at its message (owner, 2026-10-20): the
# message's published title, the first sentence the activity list shows, at that title's own bound
# and one "…". The third budget, on the same terms as the explanations': the lines are measured
# without the quotes, so a correction that composed before still composes, and each quote has fixed
# room. The claim line quotes its title already, and a consistent line stands on a tool's report,
# so only the goal and the outcome lines can carry one.
QUOTE_LABEL = ', where you said "'
QUOTE_TEXT_CHARS = reading.CLAIM_TITLE_CAP_CHARS
QUOTE_MAX_CHARS = len(QUOTE_LABEL) + QUOTE_TEXT_CHARS + 1 + len('"')
QUOTES_MAX = 1 + reading.MAX_OUTCOME_LINES
# The reader's zone as the page sends it, minutes east of UTC. Bounded to the offsets civil time
# uses (UTC-12 to UTC+14), with a margin, so a request cannot ask for a date the clock cannot draw.
UTC_OFFSET_MAX_MINUTES = 16 * 60
# The reader's named zone as the page sends it (`Intl` `timeZone`), preferred over the offset so
# each time takes that zone's own rules, as the page's clock does, and a daylight-saving change
# between two cited times does not draw one of them an hour off (review, 2026-10-20). IANA names
# are under 32 characters; the bound only keeps a request from making the lookup read a long one.
TIME_ZONE_MAX_CHARS = 64
# Claude Code only, as the copy route is: a correction offered where a paste cannot be recognised
# coming back would count as the reader's own words.
HARNESSES = copied_corrections.HARNESSES

# Names what the 2,000 bounds, the goal and lines, since the page counts the whole text to the cap.
TOO_LONG = (
    "Your goal and lines would be longer than 2,000 characters. Shorten a line of your intent."
)
REASON_NOTHING = "nothing"
REASON_TOO_LONG = "too-long"

# A placeholder is drawn as nothing since the owner's ruling of 2026-10-20: " (entry #n in
# Compass's activity list)" named a list the agent never saw. It stays in the parts, because the
# page reads the cited ids from it to tell when a held correction went stale, and adds no width.

_DEPARTED = "departed"
_CONSISTENT = "consistent"
_NOT_SHOWN = "not-shown"
_SAID = "said"

Part = str | dict[str, str]

# Line breaks `records.safe_text` leaves in place (C1 controls, NEL and the Unicode line and
# paragraph separators, any of which can start a new line where the paste lands) and the C0 set it
# turns into spaces, made spaces here first so the opener strip below sees them as the spaces they
# become.
_BREAKS = re.compile("[\x00-\x1f\x7f-\x9f\u2028\u2029]+")
# Invisible characters, dropped before anything else reads the text (review, 2026-10-20): a leading
# BOM or word joiner hid an opener from the strip, and a run of tag characters rendered as nothing
# while it still reached the agent. Every format character (Cf, which holds the BOM, U+2060-2064,
# U+180E, the bidi controls and the tag block) except the two joiners some scripts spell words
# with, and the variation selectors, which are marks rather than format characters.
_JOINERS = frozenset({"\u200c", "\u200d"})
_SELECTORS = re.compile("[\ufe00-\ufe0f\U000e0100-\U000e01ef]")
# What could open the explanation and make it something else if the label were edited away, and
# only that (review, 2026-10-20): a slash command, a shell escape, a quotation, a table row, a
# heading, a list item and a fence. "#1234" and "-3 tests" are words and keep their first
# character. Repeated, so "> /clear" loses both.
_OPENERS = re.compile(r"^(?:\s+|[/!>|]+|#+(?=\s|$)|[-*+](?=\s|$)|\d+[.)](?=\s|$)|~{3,}|`{3,})")
# A credential the shape filter misses because a word character or a hyphen is joined to its front
# ("x-" and a key): `records.safe_text` anchors most shapes there, and the explanation is pasted
# into the agent where the reading it came from was only shown. Tried from each joint of a token.
_JOINED = re.compile(r"[A-Za-z0-9_-]*[-_][A-Za-z0-9_-]{7,}")
# Each swapped for one look-alike character, so neutralising never lengthens the text: a backtick
# opens code or a fence, an angle bracket a tag an agent may read as an instruction block, and an
# `@` at a word's start a file mention Claude Code reads in. After the opener strip, so a swapped
# character can never shield an opener behind it.
_SWAPS = str.maketrans({"`": "'", "<": "\u2039", ">": "\u203a"})
_MENTION = re.compile(r"(?<!\w)@")
# A double quotation mark inside quoted words, swapped for its single look-alike: the correction
# wraps the agent's words in ASCII double quotes and the reader pastes it as their own message, so
# a `"` in them would close the quotation early and carry on in the reader's voice (review,
# 2026-10-20). Curly ones too, because they read as the same delimiter.
_QUOTE_SWAPS = str.maketrans({'"': "'", "\u201c": "\u2018", "\u201d": "\u2019"})


def _visible(text: str) -> str:
    """The text with invisible characters dropped and every line break made a space."""
    kept = "".join(c for c in text if c in _JOINERS or unicodedata.category(c) != "Cf")
    return _BREAKS.sub(" ", _SELECTORS.sub("", kept))


def _strip_openers(text: str) -> str:
    while (stripped := _OPENERS.sub("", text, count=1)) != text:
        text = stripped
    return text


def _redact_joined(text: str) -> str:
    """`records.redact_secrets`, also tried behind each hyphen or underscore of a token."""

    def one(match: re.Match[str]) -> str:
        token = match.group(0)
        for k, char in enumerate(token):
            if char in "-_":
                tail = token[k + 1 :]
                if tail and (marked := records.redact_secrets(tail)) != tail:
                    return token[: k + 1] + marked
        return token

    return _JOINED.sub(one, records.redact_secrets(text))


def explanation(detail: object) -> str:
    """A stored reading's detail as the correction may carry it, or "" for none."""
    return neutralised(detail, EXPLANATION_TEXT_CHARS)


def neutralised(value: object, cap: int) -> str:
    """Text a model or an agent wrote, as the correction may carry it, or "" for none.

    Invisible characters and openers go first, so nothing hides an opener and a key behind a
    stripped "-" is whole when the redactor reads it; then `records.safe_text`, the redact-and-clip
    path every stored reading string takes; then the look-alike swaps. A redaction marker that
    finishes past the bound withholds the text rather than let it pass its room.
    """
    raw = value if isinstance(value, str) else ""
    prepared = _redact_joined(_strip_openers(_visible(raw)))
    text = records.safe_text(prepared, cap)
    # Cut, measured against the same text unbounded: a run of spaces collapses to one, so the raw
    # length would mark a whole sentence as cut.
    whole = records.safe_text(prepared, 2 * len(prepared) + 64)
    if len(whole) > len(text) and not text.endswith("…"):
        text = f"{text.rstrip()}…"
    text = " ".join(_MENTION.sub("\uff20", text.translate(_SWAPS)).split())
    if not text.strip("….' ") or len(text) > cap + 1:
        return ""
    return text


def clock_text(at: float) -> str:
    """Hours and minutes on this machine's clock, the previous page's `nextSessionClock`.

    The fallback for a request that sends no zone; the page sends the reader's (`zone_clock`).
    """
    then, today = time.localtime(at), time.localtime()
    pattern = "%H:%M" if then[:3] == today[:3] else "%Y-%m-%d %H:%M"
    return time.strftime(pattern, then)


def utc_offset(value: object) -> int | None:
    """A request's `utc_offset_minutes`, or None where it is not a whole offset in bounds."""
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if abs(value) <= UTC_OFFSET_MAX_MINUTES else None


@functools.cache
def _zone_names() -> frozenset[str]:
    # Empty where this Python has no time zone database (Windows without `tzdata`), and then every
    # name falls back to the offset.
    return frozenset(zoneinfo.available_timezones())


def time_zone(value: object) -> zoneinfo.ZoneInfo | None:
    """A request's `time_zone`, or None where this machine does not know that name.

    Only a name in `zoneinfo.available_timezones()` is opened, so a request cannot make the lookup
    read a path of its choosing.
    """
    if not isinstance(value, str) or len(value) > TIME_ZONE_MAX_CHARS or value not in _zone_names():
        return None
    try:
        return zoneinfo.ZoneInfo(value)
    except (zoneinfo.ZoneInfoNotFoundError, ValueError, OSError):
        return None


def zone_clock(
    zone: int | datetime.tzinfo, *, now: Callable[[], float] = time.time
) -> Callable[[float], str]:
    """`clock_text` on the reader's clock: a named zone, or minutes east of UTC.

    A named zone draws each time by its own rules, as the page does. An offset is one for every
    time in the text, the reader's now, so a daylight-saving change between two of its times draws
    one an hour off; it is the fallback for a page that sends no name this machine knows. The
    server never guesses a zone; it draws the one the page sent.
    """
    if isinstance(zone, int):
        zone = datetime.timezone(datetime.timedelta(minutes=zone))

    def clock(at: float) -> str:
        then = datetime.datetime.fromtimestamp(at, zone)
        today = datetime.datetime.fromtimestamp(now(), zone)
        return then.strftime("%H:%M" if then.date() == today.date() else "%Y-%m-%d %H:%M")

    return clock


def request_clock(payload: Mapping[str, Any]) -> Callable[[float], str] | None:
    """The clock a correction request asks for, or None where it must be refused with 400.

    The reader's zone, which the page knows and the server must not guess (owner, 2026-10-20).
    The named zone first; a name this machine does not know falls back to the offset rather than
    refusing a reader whose browser knows a newer zone than this Python's database. An offset that
    is not whole minutes in bounds, or a zone that is not text, is refused rather than drawn in a
    zone the request did not ask for. Neither sent, this machine's clock.
    """
    offset = utc_offset(payload.get("utc_offset_minutes"))
    if "utc_offset_minutes" in payload and offset is None:
        return None
    if "time_zone" in payload and not isinstance(payload.get("time_zone"), str):
        return None
    named = time_zone(payload.get("time_zone"))
    zone = named if named is not None else offset
    return clock_text if zone is None else zone_clock(zone)


def _placeholder(fact: Mapping[str, Any]) -> dict[str, str]:
    return {"entry": str(fact.get("fact_id") or "")}


def _quote(fact: Mapping[str, Any]) -> list[Part]:
    """The agent's own words at a cited message, or nothing for any other entry."""
    if fact.get("type") != reading.AGENT_MESSAGE_TYPE:
        return []
    # Its closing stop dropped, as the claim line drops it: the sentence around it keeps its own.
    text = neutralised(fact.get("summary"), QUOTE_TEXT_CHARS).translate(_QUOTE_SWAPS)
    text = text.rstrip(".").rstrip()
    # Marked rather than written as text, so the lines can be measured without it (`_joined`).
    return [{"quote": f'{QUOTE_LABEL}{text}"'}] if text else []


def _own(row: Mapping[str, Any], facts: Iterable[Any]) -> list[dict[str, Any]]:
    """This session's facts that carry an id, in the page's order: time, then id."""
    who = {"harness": row.get("harness"), "sid": row.get("sid")}
    own = [
        f
        for f in facts
        if isinstance(f, dict) and f.get("fact_id") and f.get("source_session") == who
    ]
    return sorted(
        own, key=lambda f: (reading.valid_prompt_time(f.get("at")) or 0.0, str(f["fact_id"]))
    )


def _as_evidence(fact: Mapping[str, Any], harness: str) -> dict[str, Any]:
    """A published fact in the names `reading.check_supports` and `demonstrates_work` read."""
    work = reading.WORK_EVIDENCE_BY_HARNESS.get(harness, frozenset())
    return {
        **fact,
        "stale": fact.get("before_last_change") is True,
        "work": str(fact.get("type") or "") in work,
    }


def _later_directions(facts: list[dict[str, Any]], floor: float | None) -> list[dict[str, Any]]:
    """The reader's own messages after the words, as `nextCockpitLaterDirections` took them."""
    if floor is None:
        return []
    return [
        f
        for f in facts
        if f.get("type") == "user_message"
        and reading.author_of(f) == reading.AUTHOR_PERSON
        and (at := reading.valid_prompt_time(f.get("at"))) is not None
        and at > floor
    ]


def _unsettled(row: Mapping[str, Any], later: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The later directions the reader has not settled with Keep."""
    settled = reading.valid_prompt_time(row.get("annotation_settled_through"))
    return [
        f
        for f in later
        if settled is None or (reading.valid_prompt_time(f.get("at")) or 0.0) > settled
    ]


def unsettled_directions(
    row: Mapping[str, Any], facts: Iterable[Any], *, floor: float | None, until: Any = None
) -> int:
    """How many later directions stand unsettled, by the rule `compose` steers from.

    The live estimate's `unsettled_directions` (DRC-4696), so the two never
    disagree about whether a direction is still open.
    """
    stopped = reading.valid_prompt_time(until)
    return sum(
        stopped is None or (reading.valid_prompt_time(f.get("at")) or 0.0) <= stopped
        for f in _unsettled(row, _later_directions(_own(row, facts), floor))
    )


def _failed_checks(
    facts: list[dict[str, Any]], window: float, person_at: float | None
) -> list[dict[str, Any]]:
    """One boundary with the levels: after the person's last recorded message."""
    return [
        dict(f) for f in reading.failed_checks_after_person(facts, anchor=person_at, floor=window)
    ]


def _reading_window(assessment: Mapping[str, Any]) -> float:
    """Where the reading's window opened, as `nextCockpitReadingShape` derived it."""
    stored = reading.valid_prompt_time(assessment.get("window_start"))
    if stored is not None:
        return stored
    field = (
        "goal_source_at"
        if assessment.get("goal_source") in reading.PROMPT_SOURCES
        else "revision_read_at"
    )
    return reading.valid_prompt_time(assessment.get(field)) or 0.0


class _Rows:
    """A stored reading of the current words, read against the record as it stands now."""

    def __init__(
        self,
        assessment: Mapping[str, Any],
        facts: list[dict[str, Any]],
        harness: str,
        *,
        unsettled: bool,
        lines_judged: bool,
        sid: str = "",
        line_requests: Mapping[str, float] | None = None,
        settled: frozenset[str] = frozenset(),
    ) -> None:
        criteria = assessment.get("criteria")
        self.criteria: Mapping[str, Any] = criteria if isinstance(criteria, dict) else {}
        self.window = _reading_window(assessment)
        self.scope = assessment.get("scope")
        self.by_id = {str(f["fact_id"]): _as_evidence(f, harness) for f in facts}
        self.facts = {str(f["fact_id"]): f for f in facts}
        self.harness = harness
        self.sid = sid
        self.unsettled = unsettled
        self.lines_judged = lines_judged
        self.line_requests = line_requests or {}
        # The reader's kept directions and the correction pasted back, which no departure stands on.
        self.settled = settled

    def state(self, name: str) -> tuple[str, dict[str, Any] | None]:
        """One constraint's state and the entry its time is read from."""
        row = self.criteria.get(name)
        # A stored `why` the page knows explains only a row its own rules already left
        # unverifiable, so it never demotes one here; one it does not know reads as unreadable
        # and demotes the row, as `nextCockpitReadingCriterion` did (injection F4).
        why = row.get("why") if isinstance(row, dict) else None
        if (
            self.unsettled
            or not isinstance(row, dict)
            or set(row) - set(reading.CRITERION_KEYS)
            or (why and (not isinstance(why, str) or why not in reading.WHY_TOKENS))
            or row.get("result")
            not in {
                reading.RESULT_DEPARTURE,
                reading.RESULT_CONSISTENT,
                reading.RESULT_NOT_REACHED,
            }
        ):
            return _NOT_SHOWN, None
        result = str(row.get("result") or "")
        raw = row.get("cites")
        cites = [
            self.by_id[c]
            for c in (raw if isinstance(raw, list) else [])
            if isinstance(c, str) and c in self.by_id
        ]
        cites = [
            f
            for f in cites
            if (at := reading.evidence_at(f) or 0.0) >= self.window
            and not (self.window > 0 and at <= 0)
            and reading.after_line_request(f, self.line_requests.get(name))
        ]
        if result == reading.RESULT_DEPARTURE:
            # What a steer dated the departure to was the steer itself (DRC-4920): a departure
            # is dated by what the agent did, and the reader's own words settled nothing.
            cites = [f for f in cites if str(f["fact_id"]) not in self.settled]
        if not cites or {reading.author_of(f) for f in cites} == {reading.AUTHOR_DERIVED}:
            return _NOT_SHOWN, None
        line = reading.is_outcome_line(name) or name == reading.CONSTRAINT_OUTPUT
        if line and not self.lines_judged:
            return _NOT_SHOWN, None
        timed = [f for f in cites if reading.valid_prompt_time(f.get("at")) is not None]
        if result == reading.RESULT_NOT_REACHED:
            standing = [
                f
                for f in timed
                if reading.check_supports(f, result, self.window)
                and (not line or reading.bears_on_output(f))
            ]
            return (
                (reading.RESULT_NOT_REACHED, standing[0])
                if reading.result_in_scope(result, self.scope) and standing
                else (_NOT_SHOWN, None)
            )
        if result == reading.RESULT_DEPARTURE:
            # On a line a departure stands on work or on one of the agent's own messages,
            # which are evidence of what it said (owner ruling, 2026-10-03), as the page's
            # rule 7 lets it. A consistent below keeps the tool's report alone.
            standing = [
                f
                for f in timed
                if reading.check_supports(f, result, self.window)
                and (not line or reading.bears_on_output(f))
            ]
            return (_DEPARTED, standing[0]) if standing else (_NOT_SHOWN, None)
        # "As the tool reported" is the only consistent form the template has, and on an
        # outcome line it is the only one the page lets stand (item 6).
        reported = [
            f
            for f in timed
            if f.get("type") == reading.TOOL_REPORT_TYPE
            and reading.check_supports(f, result, self.window)
            and reading.demonstrates_work(f)
        ]
        said = [
            f
            for f in timed
            if f.get("type") == reading.AGENT_MESSAGE_TYPE
            and reading.check_supports(f, result, self.window)
        ]
        state = (_SAID, said[0]) if said and line else (_NOT_SHOWN, None)
        return (_CONSISTENT, reported[0]) if reported and line else state

    def why(self, name: str) -> str:
        """The stored explanation of one constraint, as the correction may carry it.

        Asked only of a line `state` left departed, or a claim `claim` left contradicted, so it
        never explains a verdict the panel has withdrawn.
        """
        row = self.criteria.get(name)
        return explanation(row.get("detail")) if isinstance(row, dict) else ""

    def claim(self) -> tuple[str, dict[str, Any], dict[str, Any] | None] | None:
        """A claims departure or `unsupported` as (result, the agent's message, what
        contradicts it), or None.

        Re-resolved against the record as it stands now by the resolver that
        first accepted it, as `levels` re-reads a stored line, so the text never
        says a claim is unshown that the panel beside it has withdrawn. Not held
        back by an unsettled later direction: a claim is independent of the
        intent (review, PR C). Held back where the route cannot carry checks, as
        the page's limit holds the row.
        """
        row = self.criteria.get(reading.CONSTRAINT_CLAIMS)
        why = row.get("why") if isinstance(row, dict) else None
        if (
            not self.lines_judged
            or not isinstance(row, dict)
            or set(row) - set(reading.CRITERION_KEYS)
            or (why and (not isinstance(why, str) or why not in reading.WHY_TOKENS))
            or row.get("result") not in {reading.RESULT_DEPARTURE, reading.RESULT_UNSUPPORTED}
        ):
            return None
        raw = row.get("cites")
        # Each fact paired with the entry the ledger makes of it, so a lookup by
        # the entry's own (cleaned) id never misses its fact.
        wanted = {c for c in (raw if isinstance(raw, list) else []) if isinstance(c, str)}
        pairs: list[tuple[reading.LedgerEntry, dict[str, Any]]] = []
        for fact in self.facts.values():
            for entry in reading.build_ledger(
                [fact], self.harness, self.sid, tool_output={}, read_agent_words=True
            ):
                if entry["id"] in wanted:
                    entry["changed_after"] = fact.get("changed_after") is True
                    pairs.append((entry, fact))
        pairs.sort(key=lambda pair: pair[0]["at"])
        resolved = reading._resolve_one(  # noqa: SLF001 - the resolver's own rules, re-applied
            {
                "token": reading.token_for(row.get("result")),
                "cites": list(range(1, len(pairs) + 1)),
                "detail": "",
            },
            {k: entry for k, (entry, _fact) in enumerate(pairs, 1)},
            name=reading.CONSTRAINT_CLAIMS,
            clause="",
            detail_cap_chars=0,
            window_start=self.window,
        )
        result = resolved.get("result")
        if result not in {reading.RESULT_DEPARTURE, reading.RESULT_UNSUPPORTED}:
            return None
        kept = {str(c) for c in resolved["cites"]}
        standing = [
            fact
            for entry, fact in pairs
            if entry["id"] in kept and reading.valid_prompt_time(fact.get("at")) is not None
        ]
        said = [
            f
            for f in standing
            if f.get("type") == reading.AGENT_MESSAGE_TYPE and reading.claim_title(f)
        ]
        if not said:
            return None
        record = [f for f in standing if f.get("type") != reading.AGENT_MESSAGE_TYPE]
        checks = [f for f in record if f.get("subject") == reading.CHECK_SUBJECT]
        found = checks or record
        return str(result), said[0], found[0] if found else None


def _saved_lines(row: Mapping[str, Any]) -> list[tuple[int, str]]:
    lines = []
    for k in range(1, reading.MAX_OUTCOME_LINES + 1):
        text = str(row.get(f"annotation_line_{k}") or "")
        if text.strip():
            lines.append((k, text))
    return lines


def _current_rows(
    row: Mapping[str, Any],
    facts: list[dict[str, Any]],
    *,
    unsettled: bool,
    lines_judged: bool,
    line_requests: Mapping[str, float] | None = None,
    floor: float | None = None,
) -> _Rows | None:
    """The stored reading, only while it read the words saved now."""
    assessment = row.get("annotation_assessment")
    if row.get("annotation_not_accurate") is True:
        return None
    if not isinstance(assessment, dict) or set(assessment) - set(reading.ASSESSMENT_KEYS):
        return None
    read, current = assessment.get("revision_read"), row.get("annotation_revision")
    if isinstance(read, bool) or not isinstance(read, int) or read != current:
        return None
    return _Rows(
        assessment,
        facts,
        str(row.get("harness") or ""),
        unsettled=unsettled,
        lines_judged=lines_judged,
        sid=str(row.get("sid") or ""),
        line_requests=line_requests,
        settled=reading.settled_reader_words(
            facts,
            str(row.get("harness") or ""),
            str(row.get("sid") or ""),
            floor=floor,
            settled_through=row.get("annotation_settled_through"),
        ),
    )


def _width(parts: list[Part]) -> int:
    """The text's width: a placeholder is drawn as nothing."""
    return sum(len(part) for part in parts if isinstance(part, str))


def _joined(lines: list[list[Part]], *, quoted: bool) -> list[Part]:
    """The lines as one list of parts, adjacent text merged, each quote kept as text or dropped."""
    parts: list[Part] = []
    for index, line in enumerate(lines):
        for raw in [*line] if index == 0 else ["\n", *line]:
            if isinstance(raw, dict) and "quote" in raw:
                if not quoted:
                    continue
                part: Part = raw["quote"]
            else:
                part = raw
            if isinstance(part, str) and parts and isinstance(parts[-1], str):
                parts[-1] += part
            else:
                parts.append(part)
    return parts


def _body(
    lines: list[tuple[int, str]], rows: _Rows | None, at: Callable[[Mapping[str, Any]], str]
) -> list[tuple[str, list[Part], str]]:
    """One bullet per saved line, with its state, the placeholder its time rests on and, for a
    departure, its stored explanation."""
    body: list[tuple[str, list[Part], str]] = []
    for k, text in lines:
        name = reading.outcome_line(k)
        if rows is not None and name not in rows.criteria and len(lines) == 1:
            name = reading.CONSTRAINT_OUTPUT
        state, cited = rows.state(name) if rows is not None else (_NOT_SHOWN, None)
        if state == _DEPARTED and cited is not None and rows is not None:
            departed: list[Part] = [
                f"- {text}: departed at {at(cited)}",
                _placeholder(cited),
                *_quote(cited),
            ]
            body.append((state, departed, rows.why(name)))
        elif state == _CONSISTENT and cited is not None:
            said: list[Part] = [
                f"- {text}: consistent with {at(cited)}",
                _placeholder(cited),
                ", as the tool reported",
            ]
            body.append((state, said, ""))
        elif state == reading.RESULT_NOT_REACHED:
            body.append((state, [f"- {text}: not reached at this stop"], ""))
        elif state == _SAID:
            body.append(
                (_SAID, [f"- {text}: the session says this is done; not confirmed by a tool"], "")
            )
        else:
            body.append((_NOT_SHOWN, [f"- {text}: can you show evidence for this?"], ""))
    return body


def _explained(line: list[Part], why: str, *, explained: bool) -> list[Part]:
    """A line with its explanation under it, where it has one and the text carries them."""
    return [*line, f"{EXPLANATION_LABEL}{why}"] if explained and why else line


def _claim_line(
    claim: tuple[str, Mapping[str, Any], Mapping[str, Any] | None],
    at: Callable[[Mapping[str, Any]], str],
) -> list[Part]:
    """The one line a claim the record contradicts or does not show adds.

    Owner, 2026-10-04, wording delegated: "You said <claim, first sentence> at
    #n; the record does not show it." A contradicted claim ends "the record
    shows otherwise at #m" instead, naming what contradicts it (the arbiter's
    wording, PR C review). The claim is the message's published title, its
    first sentence, which the page already shows; never its words. Quoted, and
    its closing stop dropped, so it reads as what was said rather than as this
    sentence's own clause.
    """
    result, fact, record = claim
    title = reading.claim_title(fact).translate(_QUOTE_SWAPS).rstrip(".").strip()
    quoted = len(title.split()) > 2 and not title.startswith(("http://", "https://"))
    label = f'You said "{title}"' if quoted else "Your claim"
    said: list[Part] = [f"{label} at {at(fact)}", _placeholder(fact)]
    if result == reading.RESULT_DEPARTURE and record is not None:
        return [*said, f"; the record shows otherwise at {at(record)}", _placeholder(record), "."]
    quotation = f'"{title}"' if quoted else "what you said"
    return [f"Can you show evidence for {quotation} at {at(fact)}", _placeholder(fact), "?"]


def _latest_result(failed: list[dict[str, Any]]) -> dict[str, Any]:
    """The failed check whose result arrived last, as `nextDriftAnswer` picked it.

    By `reading.evidence_at`, so a check called first and returned last wins. `failed` is in the
    page's order (call time, then id) and a tie keeps the later entry, which the page's `>=` does.
    """
    latest = failed[0]
    for fact in failed[1:]:
        if (reading.evidence_at(fact) or 0.0) >= (reading.evidence_at(latest) or 0.0):
            latest = fact
    return latest


def _tail(
    failed: list[dict[str, Any]],
    clock: Callable[[float], str],
) -> list[list[Part]]:
    """The current failed check, followed by the closing request.

    The sentence is timed at the result; the entry stays the one the page numbers from its call.
    """
    tail: list[list[Part]] = []
    if failed:
        latest = _latest_result(failed)
        when = clock(reading.evidence_at(latest) or 0.0)
        tail.append([f"A check failed at {when}", _placeholder(latest), "."])
    tail.append(["Please continue from here."])
    return tail


def compose(
    row: Mapping[str, Any],
    facts: Iterable[Any],
    *,
    floor: float | None,
    lines_judged: bool,
    clock: Callable[[float], str] = clock_text,
    person_at: float | None = None,
    line_requests: Mapping[str, float] | None = None,
) -> dict[str, Any]:
    """The correction for one session, or why there is none.

    `lines_judged` is whether this harness's route can carry the checks a
    verdict on an outcome line rests on: where it cannot, the page demotes
    every such verdict (`nextReadingOutputLimit`), and so does this.

    `{"ok": True, "parts": [...]}`, each part text or `{"entry": fact_id}`;
    `{"ok": False, "reason": "nothing"}` with nothing to steer from; or the
    too-long refusal with its sentence.
    """
    own = _own(row, facts)
    goal = str(row.get("annotation_goal") or "")
    lines = _saved_lines(row)
    if not goal.strip() and not lines:
        return {"ok": False, "reason": REASON_NOTHING}
    assessment = row.get("annotation_assessment")
    read_at = assessment.get("read_at") if isinstance(assessment, dict) else None
    unsettled = unsettled_directions(row, own, floor=floor, until=read_at) > 0
    window = reading.valid_prompt_time(row.get("annotation_window_start")) or 0.0
    failed = _failed_checks(own, window, person_at)
    rows = _current_rows(
        row,
        own,
        unsettled=unsettled,
        lines_judged=lines_judged,
        line_requests=line_requests,
        floor=floor,
    )

    def at(fact: Mapping[str, Any]) -> str:
        return clock(reading.valid_prompt_time(fact.get("at")) or 0.0)

    body = _body(lines, rows, at)
    claim = rows.claim() if rows is not None else None
    departed = any(state == _DEPARTED for state, _, _ in body) or (
        rows is not None and rows.state(reading.CONSTRAINT_GOAL)[0] == _DEPARTED
    )
    if not departed and claim is None and not failed:
        return {"ok": False, "reason": REASON_NOTHING}
    head: list[list[Part]] = [[f"Back to my goal: {goal}"]] if goal.strip() else []
    if head and row.get("annotation_goal_source") in reading.PROMPT_SOURCES:
        adopted = reading.adopted_prompt(
            {
                "goal_source": row["annotation_goal_source"],
                "goal_source_at": row.get("annotation_goal_source_at"),
                "goal": goal,
            },
            own,
            str(row.get("harness") or ""),
            str(row.get("sid") or ""),
        )
        if adopted:
            head[0].append({"entry": adopted[0]})
        else:
            head[0][0] = f"Back to my goal: {goal.rstrip('…')}…"
    # A contradicted claim is a departure of the claims row; an unshown one is a question, and the
    # producer keeps no detail for it.
    said: list[tuple[list[Part], str]] = (
        [
            (
                _claim_line(claim, at),
                rows.why(reading.CONSTRAINT_CLAIMS)
                if rows is not None and claim[0] == reading.RESULT_DEPARTURE and claim[2]
                else "",
            )
        ]
        if claim is not None
        else []
    )
    tail = _tail(failed, clock)
    goal_gap = rows.state(reading.CONSTRAINT_GOAL) if rows is not None else (_NOT_SHOWN, None)
    goal_line: list[tuple[list[Part], str]] = (
        [
            (
                [
                    f"The session departed from my goal at {at(goal_gap[1])}",
                    _placeholder(goal_gap[1]),
                    *_quote(goal_gap[1]),
                    ".",
                ],
                rows.why(reading.CONSTRAINT_GOAL) if rows is not None else "",
            )
        ]
        if goal_gap[0] == _DEPARTED and goal_gap[1]
        else []
    )
    body.sort(key=lambda item: item[0] != _DEPARTED)

    def assemble(*, explained: bool) -> list[Part]:
        opening: list[Part] = ["Where it stands against what I expect:"]
        middle = [opening, *(_explained(line, why, explained=explained) for _, line, why in body)]
        return _joined(
            [
                *head,
                *(_explained(line, why, explained=explained) for line, why in goal_line),
                *(_explained(line, why, explained=explained) for line, why in said),
                *tail[:-1],
                *(middle if body else []),
                tail[-1],
            ],
            quoted=explained,
        )

    # The consistent lines go first, the last of them first, and nothing is ever cut short. The
    # lines are measured without their explanations and quotes, against the budget they had
    # before either.
    while _width(assemble(explained=False)) > LINES_CAP_CHARS:
        consistent = [i for i, (state, _, _) in enumerate(body) if state == _CONSISTENT]
        if not consistent:
            return {"ok": False, "reason": REASON_TOO_LONG, "why": TOO_LONG}
        del body[consistent[-1]]
    return {"ok": True, "parts": assemble(explained=True)}
