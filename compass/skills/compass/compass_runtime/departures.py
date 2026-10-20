"""Every unasked check Compass ran, and what each one found.

[DEC-18](docs/design-reading-a-session.md#dec-18-an-unasked-reading-is-permitted-and-gated-on-delivery-first)
permits an unasked reading and adds one amendment this module exists for: every
raise persists the annotation revision and the evidence cutoff it rested on. By
the time the reader comes back the annotation may be at a later revision and the
evidence window has moved, so a raise that does not carry its own baseline cannot
be understood on return.

EVERY check, not only the ones that found something, and that is the correction
rather than the obvious shape. A check that found nothing still spent a `codex`
subprocess at `reasoning_effort=max` against the reader's own capacity, and a
store of raises alone bounds nothing: measured on the raises-only version, five
healthy sessions ran 480 subprocesses in a simulated day against a daily cap of
12, because no reading ever advanced the count. It is also the only way the
board can say whether THIS session was checked, as against whether the lane was
switched on.

A check with no `constraint` is one that raised nothing. A check with one is a
departure, and only those render.

Durable, for `deliveries`' reason and one of its own: the whole framing is that
you were away, so the read is later than the write by design and a restart in
between is the expected case rather than an edge.

A leaf, shaped on `deliveries`: `config` for the paths and caps, `records` for
the untrusted-input discipline, `io` for the diagnostic sink. It reads nothing
else in the runtime, which is what lets `unasked`, `aggregate` and `http_api`
all consult it.

## The lock is not optional here

`deliveries` shipped this shape without one and lost records: an unlocked
read-modify-write with three threads reaching it, plus a temp name shared by
every thread in the process. Measured there, two barrier-synchronised writers
lost a record in 60 of 60 trials. This module has the lock and the per-thread
temp name from its first commit rather than after the same measurement.

## What may be said, and what may not

Only a departure is ever stored, because only a departure is ever raised. The
ruling at the top of this file refuses an unasked `consistent`: an unasked
reassurance is the output the evidence-floor ruling called most damaging, and it
has no value at all to someone away from the desk.

Nothing here is a rate. A count of departures on one session identifies a
session worth reading; it establishes nothing about whether the brief was poor,
the agent was poor, or Compass's own judgement was poor, and those three are
not separable from the number.

Nor is anything here permanent against the reader's own withdrawal. A raise
quotes the clause they typed, so clearing an annotation blanks the quotations
from the rows those words were read against and keeps the row for its spend.
`withdraw` carries the whole reasoning.
"""

from __future__ import annotations

import contextlib
import json
import os
import threading
from typing import TYPE_CHECKING, Any, Final, TypedDict

from . import io as runtime_io
from . import records

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    from .config import RuntimeConfig

SCHEMA_VERSION: Final = 1

KEY_CAP_CHARS: Final = 200
# The reading and its evidence line as the producer wrote them. Bounded because
# any local process can rewrite this file and the page renders what it holds.
TEXT_CAP_CHARS: Final = 600

# Held across the read-modify-write in `record`. See the module docstring: this
# is the half `deliveries` shipped without and had to be measured into.
_WRITE_LOCK: Final = threading.Lock()

# What the board says when the lane is on and has raised nothing on this
# session. Distinct from the exhausted sentence below, and that distinction is
# the second amendment of the ruling cited at the top of this file: the
# reader is by construction not present, so
# "nothing departed" and "nothing was checked" must never render alike.
# It names the goal because the goal is all an unasked check reads: the
# outcome lines never reach it (item 12 of the ruling
# `reading.MAX_OUTCOME_LINES` cites).
NOTHING_DEPARTED: Final = (
    "Compass has checked this session against your goal and found nothing to raise. Checks run "
    "while you were away read only your goal, not your expected outcome."
)
NEVER_CHECKED: Final = (
    "Compass has not checked this session against what you asked for. Nothing here says whether "
    "it would have found anything."
)
SESSION_EXHAUSTED: Final = (
    "This session has reached its limit of unasked checks, so no further check will run on it. "
    "That is a limit being spent, not a session found to be on track."
)
DAY_EXHAUSTED: Final = (
    "This board has reached its limit of unasked checks for the day, so no further check will run "
    "on any session. That is a limit being spent, not a board found to be on track."
)

# The window the per-day cap counts over. Rolling rather than calendar, because
# the reader this exists for walked away at an arbitrary hour: a midnight reset
# would hand a whole fresh allowance to a board nobody is watching, and a
# calendar day would need a timezone this runtime does not otherwise carry.
#
# Here rather than in `unasked` because `why` below is what applies it, and
# three surfaces now read that sentence. `unasked` re-exports the name.
DAY_SEC: Final = 86_400.0

# What a later check found about a constraint that departed, and never that the
# raise caused it. The issue's third prohibition is that a return to the goal is
# not evidence the flag worked, so each of these names what was found and stops:
# no sentence here has a causal clause.
#
# Derived from later CHECKS in this store, not from a second model call and not
# from a reader-requested reading. That is the affordable half and it is also
# the only half available: a stored reading carries its evidence cutoff as the
# producer's own sentence (`reading.Assessment.cutoff` is a string) and there is
# no number on it that could be compared with a departure's cutoff.
#
# They say a later check RAN, and not that it read later evidence. The store
# holds no evidence bound to support the stronger claim: both producer write
# sites record `cutoff` as the wall clock at the check (`unasked._departures`
# and `unasked._check`), so it bounds the evidence from above and is the same
# number on every row. An earlier version of these two sentences opened "A later
# check read evidence from after this raise", and the test that would have
# distinguished the cases compared two copies of one clock.
FOLLOW_UP_NO_LATER_CHECK: Final = (
    "No later check has read this session, so what happened after this raise is not recorded here."
)
FOLLOW_UP_NOT_RAISED_AGAIN: Final = (
    "A later check ran after this raise and did not raise this constraint again. That is what the "
    "later check found, and not an effect of the raise."
)
FOLLOW_UP_RAISED_AGAIN: Final = (
    "A later check ran after this raise and raised this constraint again. That is what the later "
    "check found, and not an effect of the raise."
)


class Check(TypedDict):
    """One unasked check, and the baseline it read against.

    `constraint` empty is a check that found nothing to raise. It is still a
    row, because it still spent the reader's capacity and it is still the
    evidence that this session was looked at.

    `revision`, `cutoff` and `cutoff_text` are the first amendment of the ruling
    cited at the top of this file: the annotation revision the reading read, and
    what it read. All three are recorded at check time and never re-derived,
    because by the time this is read none of them is recoverable.

    `cutoff` is the moment the reading ran, which BOUNDS the evidence from above
    rather than saying where it stops: the record it read was the record at that
    instant. It is not a second, comparable number -- both producer write sites
    record the same clock into it and into `at` -- so nothing here may compare
    two rows' cutoffs and report what one of them read. `cutoff_text` is the
    producer's own sentence about what it actually read, by count and by author,
    and it is kept verbatim because a reading resting entirely on the session's
    own account is a different thing from one a person's words corroborate.

    `withdrawn` marks a check whose words the reader has since cleared. The row
    stays for the spend it made and its quotations are gone; see `withdraw`.
    """

    harness: str
    sid: str
    at: float
    constraint: str
    clause: str
    reading: str
    evidence: str
    revision: int
    cutoff: float
    cutoff_text: str
    withdrawn: bool


def store_path(config: RuntimeConfig) -> str:
    """Beside the state file, and not per port, for `deliveries.store_path`'s reason."""
    return os.path.join(config.state_home, "compass-departures.json")


def _entry(value: Any) -> Check | None:
    """One untrusted record, or nothing.

    Type-checked on the way in as well as on the way out, because any local
    process can rewrite this file and every string here reaches the page.
    """
    if not isinstance(value, dict):
        return None
    harness = records.safe_text(value.get("harness"), KEY_CAP_CHARS)
    sid = records.safe_text(value.get("sid"), KEY_CAP_CHARS)
    at = records.norm_epoch(value.get("at"))
    # No `constraint` test. An empty one is a check that raised nothing, which
    # is a row this store exists to keep: dropping it is what made the caps
    # bound raises instead of spend.
    if not harness or not sid or at <= 0:
        return None
    revision = value.get("revision")
    return {
        "harness": harness,
        "sid": sid,
        "at": at,
        "constraint": records.safe_text(value.get("constraint"), KEY_CAP_CHARS),
        "clause": records.safe_text(value.get("clause"), KEY_CAP_CHARS),
        "reading": records.safe_text(value.get("reading"), TEXT_CAP_CHARS),
        "evidence": records.safe_text(value.get("evidence"), TEXT_CAP_CHARS),
        # 0 rather than a drop: a raise whose revision did not survive is still
        # a raise that happened, and the render says the baseline is missing
        # rather than hiding the row.
        "revision": revision if isinstance(revision, int) and not isinstance(revision, bool) else 0,
        "cutoff": records.norm_epoch(value.get("cutoff")),
        "cutoff_text": records.safe_text(value.get("cutoff_text"), TEXT_CAP_CHARS),
        # Absent on a file an older build wrote, and absent means not withdrawn:
        # a store that predates the mark holds no cleared session's words that
        # this build put there.
        "withdrawn": bool(value.get("withdrawn")),
    }


def _bounded(entries: Iterable[Check], limit: int) -> tuple[Check, ...]:
    """The newest `limit` records, oldest evicted first."""
    ordered = sorted(entries, key=lambda entry: entry["at"])
    return tuple(ordered[-limit:]) if limit > 0 else ()


def load(config: RuntimeConfig) -> tuple[Check, ...]:
    """Every record on disk, or none if there is none to trust."""
    return _load_at(config, store_path(config))


def _load_at(config: RuntimeConfig, path: str) -> tuple[Check, ...]:
    try:
        with open(path, "rb") as handle:
            raw = handle.read(config.departure_read_cap_bytes + 1)
        if len(raw) > config.departure_read_cap_bytes:
            return ()
        data = json.loads(raw or b"null")
    except (OSError, ValueError, RecursionError):
        return ()
    if not isinstance(data, dict):
        return ()
    entries = data.get("entries")
    if not isinstance(entries, list):
        return ()
    parsed = [entry for entry in (_entry(value) for value in entries) if entry is not None]
    return _bounded(parsed, config.departure_max_entries)


def save(
    config: RuntimeConfig,
    entries: Iterable[Check],
    *,
    diagnostic_sink: Callable[[str], None] = print,
) -> bool:
    """Write the store, reporting whether it reached disk."""
    return _save_at(config, entries, store_path(config), diagnostic_sink)


def _save_at(
    config: RuntimeConfig,
    entries: Iterable[Check],
    target: str,
    diagnostic_sink: Callable[[str], None],
) -> bool:
    payload = {
        "v": SCHEMA_VERSION,
        "entries": [dict(entry) for entry in _bounded(entries, config.departure_max_entries)],
    }
    # Per thread as well as per process, for `deliveries.save`'s measured
    # reason: a shared name means two writers open it `O_TRUNC` on independent
    # descriptors and `os.replace` renames the interleaving over the store.
    tmp = f"{target}.{os.getpid()}.{threading.get_ident()}.tmp"
    try:
        os.makedirs(config.state_home, mode=0o700, exist_ok=True)
        handle_fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(handle_fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)
        os.replace(tmp, target)
    except (OSError, ValueError, TypeError, RecursionError):
        runtime_io.diag(
            f"Compass: could not write the departure record {target}; "
            "what was raised while you were away will not be readable later",
            diagnostic_sink,
        )
        with contextlib.suppress(OSError, ValueError):
            os.unlink(tmp)
        return False
    return True


def record(
    config: RuntimeConfig,
    entries: Iterable[Check],
    *,
    diagnostic_sink: Callable[[str], None] = print,
) -> bool:
    """Append one reading's departures, and say whether they reached disk.

    Under `_WRITE_LOCK`, and a whole reading at once rather than one row per
    call: a reading's departures are one raise, and splitting them would let a
    restart between two writes publish half a raise.
    """
    fresh = [entry for entry in (_entry(dict(value)) for value in entries) if entry is not None]
    if not fresh:
        return False
    with _WRITE_LOCK:
        return save(config, [*load(config), *fresh], diagnostic_sink=diagnostic_sink)


def counts(entries: Iterable[Check], harness: str, sid: str, *, since: float) -> tuple[int, int]:
    """(this session's checks, this board's checks since `since`).

    CHECKS and not raises, which is the whole of what the caps bound. Counting
    raises bounds nothing: a healthy board raises nothing and would run readings
    forever, measured at 480 subprocesses in a simulated day against a daily cap
    of 12.

    Two numbers because the two caps are different questions: one session
    churning, and a whole board quietly spending a day's capacity.
    """
    rows = list(entries)
    mine = sum(1 for row in rows if row["harness"] == harness and row["sid"] == sid)
    return mine, sum(1 for row in rows if row["at"] >= since)


def checked(entries: Iterable[Check], harness: str, sid: str, *, has_words: bool) -> bool:
    """Whether THIS session has ever been checked against the words it holds now.

    Per session and not per board. The lane being attached says the feature is
    on; it says nothing about whether this row was ever read, and a session with
    no annotation is never read at all.

    A withdrawn check does not count. It read words the reader has since
    cleared, so nothing has been checked against what they are asking for now,
    and `NEVER_CHECKED` is the true sentence. The spend it made still counts,
    which is `counts` and not this.

    `has_words` is the same fact arriving by a second route, and it is a
    required argument rather than a defaulted one because a default of True
    keeps the defect at any call site that forgets it (DRC-4560). The lane
    itself never checks a wordless session, but the words can go afterwards:
    the `clear` beside a box empties it and the save after it mints a revision
    holding two empty strings, leaving the entry standing with nothing in it
    and the checks against the earlier revisions not withdrawn. This module is
    a leaf over config, io and records and cannot ask the annotation store, so
    it is told.
    """
    return has_words and any(
        row["harness"] == harness and row["sid"] == sid and not row["withdrawn"] for row in entries
    )


def why(
    config: RuntimeConfig,
    entries: Iterable[Check],
    harness: str,
    sid: str,
    *,
    has_words: bool,
    discarded: bool,
    now: float,
) -> str:
    """Which of the four absence sentences this session has earned, or none.

    Here rather than in `unasked` because three surfaces need it and none of
    them may reach the lane: the session page, the departure review on the
    Held-to tab, and the Intent log, which serves sessions that have left the
    board entirely. A second copy of this ladder is how a spent cap comes to be
    worded one way where the raise is shown and another where it is reviewed,
    and the whole point of these four is that they must never read alike.

    `discarded` is a required argument for `has_words`' reason, and it is not
    the same fact (DRC-4565). A discard record has no words, so `has_words` is
    already false and the ladder answers `NEVER_CHECKED` -- which is a claim
    about the past, wrong twice over. It is false whenever a check DID run
    before the discard, because withdrawal blanks the row and `checked` needs
    words. And it is a second account of a state the record beside it has
    already given in the board's own voice. All three surfaces print it, so
    the guard belongs here: it shipped on the Intent log alone and the session
    page and the Held-to tab went on saying it under the record.
    """
    if discarded:
        return ""
    stored = list(entries)
    mine, today = counts(stored, harness, sid, since=now - DAY_SEC)
    # Whether `published` is about to serve this session a row, on the same
    # test it selects them with. Read once and used twice, because the two
    # answers appear on one screen: every surface prints this sentence directly
    # beneath those rows.
    standing = any(
        row["harness"] == harness
        and row["sid"] == sid
        and row["constraint"]
        and not row["withdrawn"]
        for row in stored
    )
    if (
        not standing
        and not checked(stored, harness, sid, has_words=has_words)
        and mine < config.unasked_session_cap
    ):
        # Before the caps, deliberately. A session nobody has checked is not a
        # session held off by a spent cap, even when the board's day cap is
        # spent: the first says nothing was looked at here, and the second
        # implies something was.
        #
        # The session cap is the one exception, and only a WITHDRAWN session can
        # reach it: its checks spent the cap and then had their words cleared,
        # so nothing has been checked against the words it holds now AND no
        # further check will run. Saying only the first would read as "not
        # checked yet". A session with no rows at all has spent nothing, so this
        # test cannot change what it earns.
        #
        # `standing` is the second exception and it arrived with `has_words`:
        # a session whose box was emptied and saved keeps every raise made
        # against the earlier revisions, so this sentence would print under
        # rows quoting the words it says were never read. The figure stays
        # unmeasured either way -- `checked` is not consulted here -- which is
        # the half the sentence was wanted for.
        return NEVER_CHECKED
    if today >= config.unasked_daily_cap:
        return DAY_EXHAUSTED
    if mine >= config.unasked_session_cap:
        return SESSION_EXHAUSTED
    if standing:
        return ""
    return NOTHING_DEPARTED


def follow_up(entries: Iterable[Check], row: Check) -> str:
    """What a later check found about this constraint, from this store alone.

    `Unknown` is the default and the common answer, and it renders as a named
    reason rather than as a blank: a blank here would be read as nothing having
    gone wrong, which is the one thing this axis must not say.

    Ordered on when each check RAN, which is all this store supports and less
    than the surface once claimed. A second test compared the two rows' cutoffs
    and reported that the later check had "read evidence from after this raise";
    both write sites record `cutoff = now`, so that test was `at > at` written
    twice and the branch it guarded was reachable only from a hand-edited file.
    The two numbers this docstring said could tell the cases apart were one
    number stored twice. The sentences now say a later check ran, which is
    recorded, and the `cutoff` a row carries stays what it is: an upper bound on
    the evidence, printed beside the raise so the reader can see it.
    """
    later = [
        other
        for other in entries
        if other["harness"] == row["harness"]
        and other["sid"] == row["sid"]
        and other["at"] > row["at"]
        # A withdrawn row is a spend that finished no check (cancelled, failed,
        # or its words cleared), so it is no evidence about a later raise.
        # `counts` still charges it.
        and not other["withdrawn"]
    ]
    if not later:
        return FOLLOW_UP_NO_LATER_CHECK
    if any(other["constraint"] == row["constraint"] for other in later):
        return FOLLOW_UP_RAISED_AGAIN
    return FOLLOW_UP_NOT_RAISED_AGAIN


def published(entries: Iterable[Check], harness: str, sid: str) -> list[dict[str, Any]]:
    """This session's DEPARTURES, newest first, as the board renders them.

    A check that raised nothing is in the store and not in this list: it is
    what the caps count and what makes the checked sentence true, and rendering
    it as a row would fill the panel with absences. A WITHDRAWN check is out for
    a different reason -- its words are gone rather than never written -- and
    `withdraw` records why the row itself stays.
    """
    stored = list(entries)
    mine = [
        row
        for row in stored
        if row["harness"] == harness
        and row["sid"] == sid
        and row["constraint"]
        and not row["withdrawn"]
    ]
    served: list[dict[str, Any]] = []
    for row in sorted(mine, key=lambda row: row["at"], reverse=True):
        # `withdrawn` is a fact about the store and never leaves the server: a
        # served row is by construction not withdrawn, so the key would carry
        # one constant and invite a reader of the wire to think otherwise.
        out = {key: value for key, value in row.items() if key != "withdrawn"}
        # `follow_up` is derived here and never read off the record. The file is
        # writable by any local process, and a sentence about what happened
        # after a raise is the one a rewriter would most want to choose; the
        # explicit key also overwrites one a rewriter left in the file.
        out["follow_up"] = follow_up(stored, row)
        served.append(out)
    return served


def _withdrawn(row: Check) -> Check:
    """One check with the reader's words gone and the spend it made kept."""
    return {
        "harness": row["harness"],
        "sid": row["sid"],
        "at": row["at"],
        "constraint": "",
        "clause": "",
        "reading": "",
        "evidence": "",
        "revision": row["revision"],
        "cutoff": row["cutoff"],
        "cutoff_text": "",
        "withdrawn": True,
    }


def withdraw(
    config: RuntimeConfig,
    harness: str,
    sid: str,
    *,
    diagnostic_sink: Callable[[str], None] = print,
) -> bool:
    """Forget what this session's checks read, keeping only that they ran.

    A clear withdraws the reader's words, and a departure quotes them: `clause`
    is their own sentence and `reading` is a model's paragraph about it. Leaving
    either behind kept a withdrawn request readable, and `GET /api/annotations`
    serves sessions the board no longer carries, so `SECURITY.md`'s claim that
    words withdrawn with a clear are gone from that response was false the day
    the departure store joined it. Measured end to end: a goal cleared and
    replaced still served the old clause verbatim.

    The ROW stays, blanked and marked, rather than being deleted. Deleting would
    hand back the per-session and per-day caps those checks spent, and the caps
    are what bound a `codex` subprocess at `reasoning_effort=max`: measured on a
    version that counted raises rather than checks, five healthy sessions ran
    480 subprocesses in a simulated day against a daily cap of 12. A clear is a
    withdrawal, not a refund.

    Returns whether the store is in the wanted state, so a session with nothing
    to withdraw is a success and not a silent write.
    """
    with _WRITE_LOCK:
        stored = list(load(config))
        kept = [
            _withdrawn(row) if row["harness"] == harness and row["sid"] == sid else row
            for row in stored
        ]
        wanted = True
        if kept != stored:
            wanted = save(config, kept, diagnostic_sink=diagnostic_sink)
        return wanted
