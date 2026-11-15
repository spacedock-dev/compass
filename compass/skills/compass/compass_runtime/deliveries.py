"""What became of each notification Compass raised.

The first precondition of
[DEC-18](docs/design-reading-a-session.md#dec-18-an-unasked-reading-is-permitted-and-gated-on-delivery-first),
and the one it kept as a build gate: a raise that records no delivery outcome is
exactly the defect the review view exists to show. Measured before this
existed, nothing recorded a raise at all. The only trace was
`state.last_popup`, a cooldown floor held in memory, one float per key
and overwritten on every raise, so a signal that never left the machine and one
handed to the operating system left the same mark.

Named for the outcome rather than the event, because `raise` already means
something else on this board: the control that switches a terminal to a session.

A leaf, shaped on `dismissals`: `config` for the paths and caps, `records` for
the untrusted-input discipline, `io` for the diagnostic sink. It reads nothing
else in the runtime, which is what lets `notifications`, `aggregate` and
`http_api` all consult it.

## Durable rather than in memory, and that is the decision

An outcome held on `RuntimeState` would be the defect [DRC-4547] recorded one
layer over: an observed session end lived only in the memory of the process that
saw it, so a restart made every finished session look like it merely went
quiet (`ends` now carries it across). The read here is deliberately later than
the write, because the whole
framing is that you walked away and came back, and a restart in between is the
expected case rather than an edge. An in-memory record would also make the
sentence for "no record" fire for every raise before the last restart, and that
sentence must mean "this predates the record" rather than "this board forgot".

Not session history: `history.appended` keeps one transition per `(harness,
sid)` and skips an unchanged row, so two raises on one session collapse into
one and an outcome settled later is not expressible. Not the annotation store:
its `_record` refuses a session nobody annotated, and a raise fires on every
active row.

[DRC-4547](https://linear.app/recce/issue/DRC-4547)

## What may be said, and what may not

Four outcomes, one sentence each and never a shared one, which is
`reading.WITHHELD`'s rule for the same reason: folding causes together makes the
least true of them read as the most reassuring. A fifth sentence covers a raise
this store has no record of, and it says so rather than saying undelivered.

Nothing here claims a person saw anything. `osascript` exiting zero means the
scripting bridge accepted the call; it exits zero under Do Not Disturb and with
the hosting application's notifications switched off. That is the whole reason
`HANDED_TO_OS` is worded the way it is.

Two further sentences report the browser lane, under
[DEC-19](docs/design-reading-a-session.md#dec-19-the-page-may-report-a-lane-never-a-delivery):
the page may say whether a notification lane exists in it, and may never
report a delivery. The
negative one says no lane has been REPORTED since a moment, never that the raise
did not reach the reader, because a tab that opens sends a report and a tab that
closes sends none, so absence is stale in one direction only.
"""

from __future__ import annotations

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

# Held across the read-modify-write in `record`, which is the half that was
# missing when this store was shaped on `dismissals` and `annotations`: both of
# those hold a lock on `RuntimeState` across exactly that sequence. Measured on
# this module without one, three threads recording 40 outcomes each against a
# 1024-entry store left 39 entries and caught the file mid-write in two
# unparseable states.
#
# A module lock rather than a field on `RuntimeState`, because the hazard is
# intra-process and this module reaches no state: the three lanes that record
# are the collection worker, the `/api/notify` handler thread and the
# `/api/ask` handler thread, all inside one server. Two dashboards are two
# processes and this lock does not reach across them; the shared atomic writer is
# what keeps their writes from interleaving, and the loser of a concurrent
# read-modify-write loses its record, which is the same bound `dismissals`
# accepts for the same reason.
_WRITE_LOCK: Final = threading.Lock()

# The five things a server-side attempt can end as. Tokens, not sentences: the
# notifier returns one of these and the prose is looked up, so no call site
# composes a claim about what happened.
OUTCOME_HANDED_OVER: Final = "handed-over"
OUTCOME_REFUSED: Final = "refused"
# Split from `refused` rather than folded into it. Both arrive from the same
# `try`, and they are different facts: one is the notification service running
# and rejecting the request, the other is the call never starting, which is what
# a missing binary or a denied exec looks like. Sharing a sentence would breach
# this module's own rule in the place it is easiest to breach it, and it would
# tell a reader their notification service rejected something it never saw.
OUTCOME_NOT_LAUNCHED: Final = "not-launched"
OUTCOME_DID_NOT_RETURN: Final = "did-not-return"
OUTCOME_NO_LANE: Final = "no-lane"

# Not a fifth outcome and deliberately not in `OUTCOMES`: it is the ABSENCE of
# one, on a raise that is otherwise readable. A write is still refused with it,
# because no caller may mint an unknown; only a read produces one.
OUTCOME_UNREADABLE: Final = ""

OUTCOMES: Final = (
    OUTCOME_HANDED_OVER,
    OUTCOME_REFUSED,
    OUTCOME_NOT_LAUNCHED,
    OUTCOME_DID_NOT_RETURN,
    OUTCOME_NO_LANE,
)

# One sentence per outcome and never a shared one. Each names the observation
# first and the consequence second, and each distinguishes itself from its
# nearest neighbour in its own words rather than by omission.
DELIVERY: Final[dict[str, str]] = {
    # Deliberately not "delivered" and not "shown". The call returning says the
    # notification service accepted the request and nothing about whether a
    # banner was drawn or anyone was at the desk.
    OUTCOME_HANDED_OVER: (
        "Handed to this machine's notification service, which accepted it. Whether it was "
        "displayed, and whether anyone saw it, is not something that call reports."
    ),
    OUTCOME_REFUSED: ("The notification service returned an error, so no banner was created."),
    OUTCOME_NOT_LAUNCHED: (
        "The notification command could not be started on this machine, so the request never "
        "reached the notification service."
    ),
    # A timeout is not a failure, and folding it into one is the same collapse
    # this module exists to refuse one level down.
    OUTCOME_DID_NOT_RETURN: (
        "The notification call was still running when its time limit expired, so what it did "
        "is unrecorded rather than known to have failed."
    ),
    OUTCOME_NO_LANE: (
        "This platform has no notification backend in this build, so nothing was sent from "
        "the server and no banner was attempted."
    ),
}

# A raise this build cannot read an outcome for. Reachable from exactly one
# place, `published`'s lookup default, and therefore from exactly one cause: a
# stored record whose outcome token is not in this build's closed set, which a
# later build's fifth outcome or a local process rewriting the file both
# produce. It used to say "predates the delivery record", which names a case
# that writes no record at all and so can never select this sentence.
#
# It says what is true, which is that the outcome is not readable here, and
# never that the raise went undelivered.
NO_RECORD: Final = (
    "This raise is on record but its outcome is not one this build can read, so what became of it "
    "is unknown rather than known to have failed."
)

# The absence of a raise, said out loud, and published on its own key rather
# than through `delivery_why`. A session nobody was raised about draws no panel
# at all and must keep drawing none; this sentence is only true BESIDE a
# departure, where silence would otherwise read as a raise the reader ignored.
# Measured on the board: the session page showed two departures and simply
# omitted the notifications block, so nothing on screen distinguished a raise
# that failed from a departure nobody was ever alerted to.
NO_RAISE_RECORDED: Final = (
    "No notification raise about this session is on record, so nothing here says one was "
    "attempted. The record is bounded and drops its oldest rows, so an older raise can have "
    "left it."
)

# The lane the unasked reading raises under. Duplicated from `unasked.LANE`
# rather than imported, because this module is a leaf and `unasked` reads it;
# `test_deliveries` asserts the two are the same token, so the copy cannot
# drift silently.
LANE_DEPARTURE: Final = "departure"

# The same absence, said at the scope the caller narrowed to. Keyed on the lane
# rather than composed, for the reason every other sentence here is a constant:
# the wording is the product.
#
# Measured on the board, and it is why the sentence above may not be reused for
# a narrowed call. With one hook refusal on record and no departure raise, the
# session page printed "No notification raise about this session is on record,
# so nothing here says one was attempted" inside the departure block and "One
# notification was raised about this session" in the NOTIFICATIONS block
# directly beneath it. Both were about the same session, one counted one lane
# and the other counted four, and nothing on screen said so.
NO_RAISE_BY_LANE: Final[dict[str, str]] = {
    LANE_DEPARTURE: (
        "No notification raise about a departure on this session is on record, so nothing here "
        "says one was attempted. Raises this board made about the session for other reasons are "
        "not counted here, and the record is bounded and drops its oldest rows, so an older "
        "raise can have left it."
    ),
}

# The outcomes that mean this board actually tried. Named positively rather than
# as "not no-lane": an unreadable outcome is not an attempt either, and a
# negative test would have counted one silently the day that case was added.
# `not-launched` belongs here, because an attempt is what THIS BOARD did and a
# hand-over is what the notification service accepted, which is the whole reason
# `counts` publishes two numbers.
ATTEMPTED: Final = frozenset(
    {OUTCOME_HANDED_OVER, OUTCOME_REFUSED, OUTCOME_NOT_LAUNCHED, OUTCOME_DID_NOT_RETURN}
)

# The two sentences of
# [DEC-19](docs/design-reading-a-session.md#dec-19-the-page-may-report-a-lane-never-a-delivery).
# Both sit BESIDE a `no-lane` outcome and never instead of one: the server
# saying it has no backend and the page saying whether it has one are
# different facts and the reader needs both.
# Three cases and not two, because a report has a time and the time changes what
# it is evidence of. Each carries the gap rather than only the fact, which is
# the half a flag cannot say: a lane reported three hours before a raise and one
# reported a minute before are different evidence and read alike without it.
BROWSER_LANE_REPORTED: Final = (
    "A dashboard tab reported a working notification lane {ago} before this raise, so the page "
    "may have raised one itself. Nothing reports back whether it did, and a tab that closes "
    "sends no report."
)
# A report that arrived AFTER the raise. It is about a later moment and says
# nothing at all about this one, which is worth saying rather than rendering the
# sentence above with a negative gap.
BROWSER_LANE_LATER: Final = (
    "The only report of a working notification lane arrived {ago} after this raise, so it says "
    "nothing about whether a tab was open when the raise happened."
)
# The second sentence is load bearing and must not be trimmed to fit. Without it
# the first reads as "this did not reach you", which is what
# [DEC-19](docs/design-reading-a-session.md#dec-19-the-page-may-report-a-lane-never-a-delivery)
# forbids.
BROWSER_LANE_UNREPORTED: Final = (
    "No dashboard tab has reported a notification lane. A tab that opens sends a report and a "
    "tab that closes sends none, so this says nothing about whether the page raised one."
)


# More than one raise about this session, and they did not all end alike. The
# panel prints ONE sentence, the latest raise's, so without this a session whose
# first raise was refused and whose second was handed over reads as two
# hand-overs. Naming the difference is cheaper than composing prose for a set,
# and it points at the record rather than summarizing it wrongly.
MIXED_OUTCOMES: Final = (
    "Earlier raises about this session did not all end the same way as this one."
)

# Bound exactly, and bound by prefix. The ask lane records under the session id
# the CALLER sent, which for Claude is the whole UUID, while the row carries the
# eight-character transcript prefix its collector publishes. Matching those
# exactly orphaned every ask-lane outcome from the row it was raised about, so
# the panel showed no raise for a question the reader had been alerted to. The
# prefix binding is what reunites them, and it is stated rather than hidden
# because a prefix can collide, which is `annotations.BINDING_BY_PREFIX`'s rule
# for the same identity and the hazard DRC-4508 named.
BINDING_EXACT: Final = ""
BINDING_BY_PREFIX: Final = (
    "Matched on an eight-character identity prefix, which is all this harness publishes as the "
    "session id. A raise about another session sharing it would be counted here."
)


class Delivery(TypedDict):
    """One raise and what became of it.

    `lane` is which producer raised it, so adding a lane later adds a value
    rather than changing this shape, which is what the issue asks for. `at` is
    the server's clock at the attempt and never a value a caller sent.
    """

    harness: str
    sid: str
    at: float
    lane: str
    outcome: str


def store_path(config: RuntimeConfig) -> str:
    """Beside the state file, but not per port.

    `lifecycle.state_path` is `compass-<port>.json` and is deleted on exit. What
    became of a raise is the reader's, not the instance's, so it survives both a
    restart and a different --port, for `dismissals.store_path`'s reason.
    """
    return os.path.join(config.state_home, "compass-deliveries.json")


def _entry(value: Any) -> Delivery | None:
    """One untrusted record, or nothing.

    Type-checked on the way in as well as on the way out. Any local process can
    rewrite this file, so an outcome outside the closed set is BLANKED rather
    than published: the page looks its sentence up by token, and publishing one
    a writer chose would let that writer choose what the board says.

    Blanked and not dropped, which is the half that took a correction. Dropping
    the row loses the raise as well as the outcome, and the row then reads as a
    session nobody was alerted about — which is the exact collapse this module
    exists to refuse, one turn of the screw further out. An unreadable outcome
    is an unknown, and `NO_RECORD` is the sentence for one. The case is not
    hypothetical: a store written by a later build carrying a fifth outcome
    reaches this function on every downgrade.
    """
    if not isinstance(value, dict):
        return None
    harness = records.safe_text(value.get("harness"), KEY_CAP_CHARS)
    sid = records.safe_text(value.get("sid"), KEY_CAP_CHARS)
    lane = records.safe_text(value.get("lane"), KEY_CAP_CHARS)
    outcome = value.get("outcome")
    at = records.norm_epoch(value.get("at"))
    if not harness or not sid or not lane or at <= 0:
        return None
    known = outcome if outcome in OUTCOMES else OUTCOME_UNREADABLE
    return {"harness": harness, "sid": sid, "at": at, "lane": lane, "outcome": known}


KEY_CAP_CHARS: Final = 200


def _bounded(entries: Iterable[Delivery], limit: int) -> tuple[Delivery, ...]:
    """The newest `limit` records, oldest evicted first.

    A count bound rather than a time to live, for `dismissals._bounded`'s
    reason and one of its own: the review surface reads across sessions, so an
    age bound would empty it exactly when a reader came back from a long
    absence, which is the case the whole feature is for.
    """
    ordered = sorted(entries, key=lambda entry: entry["at"])
    return tuple(ordered[-limit:]) if limit > 0 else ()


def load(config: RuntimeConfig) -> tuple[Delivery, ...]:
    """Every record on disk, or none if there is none to trust.

    Read to a cap with RecursionError caught, for `lifecycle.read_state`'s
    reason: deeply nested JSON blows the recursion limit rather than raising
    ValueError, and a corrupt store degrades to "no records" rather than taking
    down a collection. A malformed record is dropped on its own.
    """
    try:
        with open(store_path(config), "rb") as handle:
            raw = handle.read(config.delivery_read_cap_bytes + 1)
        if len(raw) > config.delivery_read_cap_bytes:
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
    return _bounded(parsed, config.delivery_max_entries)


def save(
    config: RuntimeConfig,
    entries: Iterable[Delivery],
    *,
    diagnostic_sink: Callable[[str], None] = print,
) -> bool:
    """Write the store, reporting whether it reached disk.

    Temp file plus `os.replace`, and `0o600` in the `os.open` call rather than a
    chmod afterwards, copied from `lifecycle.write_state`. `TypeError` and
    `RecursionError` are caught alongside the rest for `annotations.save`'s
    reason: an encoder that refuses a payload must not reach the caller as a
    dropped connection.
    """
    payload = {
        "v": SCHEMA_VERSION,
        "entries": [dict(entry) for entry in _bounded(entries, config.delivery_max_entries)],
    }
    target = store_path(config)
    try:
        runtime_io.atomic_write_owner_only(target, json.dumps(payload))
    except (OSError, ValueError, TypeError, RecursionError):
        runtime_io.diag(
            f"Compass: could not write the delivery record {target}; "
            "what became of this raise will not be readable later",
            diagnostic_sink,
        )
        return False
    return True


def record(
    config: RuntimeConfig,
    *,
    harness: str,
    sid: str,
    lane: str,
    outcome: str,
    now: float,
    diagnostic_sink: Callable[[str], None] = print,
) -> bool:
    """Append one outcome, and say whether it reached disk.

    Read-modify-write rather than an append, because the file is bounded and two
    dashboards may share it, and under `_WRITE_LOCK` because three threads in
    one process reach this. An outcome outside the closed set is refused here as
    well as on read-back: a caller inventing one would otherwise publish a token
    the page cannot look up.
    """
    if outcome not in OUTCOMES:
        return False
    entry = _entry({"harness": harness, "sid": sid, "at": now, "lane": lane, "outcome": outcome})
    if entry is None:
        return False
    with _WRITE_LOCK:
        return save(config, [*load(config), entry], diagnostic_sink=diagnostic_sink)


def counts(entries: Iterable[Delivery]) -> dict[str, int]:
    """Attempts and hand-overs, separately, and never one figure.

    Two numbers because they answer different questions and a single ratio
    answers neither. Neither is a compliance figure: an attempt is what this
    board did, and a hand-over is what the notification service accepted. What a
    person saw is not in here and cannot be derived from it.
    """
    rows = list(entries)
    # Named positively rather than as "not no-lane". An unreadable outcome is
    # not an attempt either, and a negative test would have silently counted one
    # the day that case was added.
    attempted = sum(1 for row in rows if row["outcome"] in ATTEMPTED)
    return {
        "raises": len(rows),
        "attempted": attempted,
        "handed_over": sum(1 for row in rows if row["outcome"] == OUTCOME_HANDED_OVER),
    }


def _span(seconds: float) -> str:
    """A gap in the coarsest unit that still reads as a duration.

    Coarse on purpose. The figure is evidence about how stale a report is, and
    a reader deciding whether a tab was plausibly open does not act on the
    difference between 184 and 187 minutes.
    """
    gap = max(0.0, seconds)
    if gap < 90:
        return "moments"
    for unit, size in (("minute", 60.0), ("hour", 3_600.0), ("day", 86_400.0)):
        if gap < size * 48 or unit == "day":
            count = round(gap / size)
            return f"{count} {unit}" if count == 1 else f"{count} {unit}s"
    raise AssertionError  # pragma: no cover - the day arm above always returns


def browser_lane_why(lane_reported_at: float, raised_at: float | None) -> str:
    """Which sentence this row earns under
    [DEC-19](docs/design-reading-a-session.md#dec-19-the-page-may-report-a-lane-never-a-delivery).

    Nothing at all when the row has no raise, and that is the correction rather
    than the obvious case. Every sentence here is RELATIVE to a raise: each one
    says how long before or after one the report arrived. A row with no raise
    has nothing to measure against, and an earlier version answered it with the
    positive wording and a fabricated gap, so a session nobody had ever been
    alerted about published "a dashboard tab reported a working notification
    lane a moment before this raise". The board-wide fact is published at the
    top of the payload, where it belongs and where it needs no raise.
    """
    if raised_at is None:
        return ""
    if lane_reported_at <= 0:
        return BROWSER_LANE_UNREPORTED
    gap = raised_at - lane_reported_at
    if gap < 0:
        return BROWSER_LANE_LATER.format(ago=_span(-gap))
    return BROWSER_LANE_REPORTED.format(ago=_span(gap))


def _mine(
    entries: Iterable[Delivery], harness: str, sid: str, *, by_prefix: bool, lane: str
) -> list[Delivery]:
    """This session's raises, under whichever binding the caller established.

    The prefix arm compares in one direction only: the ROW's sid is the short
    one, so a stored raise counts when its own sid starts with it. Comparing
    both ways would let an eight-character stored key claim every longer session
    that happens to begin with it.

    `lane` empty is every lane, which is what the NOTIFICATIONS block on the
    session page wants: it is about the notifications raised, whatever raised
    them. A caller printing a sentence BESIDE a departure passes the departure
    lane instead, because four lanes write this store and the sentence published
    is the latest raise's: measured, a departure handed over and an unrelated
    hook refusal an hour later printed "the notification service returned an
    error" beside the departure that got out.
    """
    rows = [row for row in entries if row["harness"] == harness]
    if lane:
        rows = [row for row in rows if row["lane"] == lane]
    if not sid:
        return []
    if not by_prefix:
        return [row for row in rows if row["sid"] == sid]
    return [row for row in rows if row["sid"] == sid or row["sid"].startswith(sid)]


def published(
    entries: Iterable[Delivery],
    harness: str,
    sid: str,
    *,
    lane_reported_at: float = 0.0,
    by_prefix: bool = False,
    lane: str = "",
) -> dict[str, Any]:
    """What one session's row says about the raises made against it.

    The browser lane rides here rather than at the top of the payload even
    though it is board-wide, because its sentence is relative to the raise it
    sits beside and a single top-level sentence could not carry that gap.

    `lane` narrows every figure and every sentence to one producer, and the key
    names are unchanged so a caller renders either scope with one body. See
    `_mine` for why a sentence printed beside a departure needs the narrow one.
    """
    mine = _mine(entries, harness, sid, by_prefix=by_prefix, lane=lane)
    latest = max(mine, key=lambda row: row["at"], default=None)
    raised_at = latest["at"] if latest else None
    return {
        "delivery_outcome": latest["outcome"] if latest else "",
        "delivery_why": DELIVERY.get(latest["outcome"], NO_RECORD) if latest else "",
        # Exactly one of these two carries a sentence. The absence one is
        # published on every row and printed only where a departure stands,
        # and it is the narrowed wording whenever the caller narrowed: a
        # sentence that counted one lane may not be worded as if it counted
        # every one. An unknown lane falls back to the board-wide wording,
        # which is why `test_deliveries` binds the one narrowing caller's
        # token to a key here.
        "delivery_none_why": ("" if latest else NO_RAISE_BY_LANE.get(lane, NO_RAISE_RECORDED)),
        "delivery_at": raised_at,
        "delivery_raises": len(mine),
        # Whether the sentence above is the whole story. One sentence is
        # published, the latest raise's, so a session whose first raise was
        # refused and whose second was handed over would otherwise read as two
        # hand-overs.
        "delivery_mixed": len({row["outcome"] for row in mine}) > 1,
        "delivery_mixed_why": (MIXED_OUTCOMES if len({row["outcome"] for row in mine}) > 1 else ""),
        # Stated rather than hidden, because a prefix can collide and the count
        # above is then a claim about somebody else's raise.
        "delivery_binding_why": (BINDING_BY_PREFIX if by_prefix and mine else BINDING_EXACT),
        "browser_lane": lane_reported_at > 0,
        "browser_lane_at": lane_reported_at or None,
        "browser_lane_why": browser_lane_why(lane_reported_at, raised_at),
    }
