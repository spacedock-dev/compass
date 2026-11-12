"""Outstanding questions a session asked, and their one-slot answer mailboxes.

A mailbox holds one outcome, not a queue: a question is answered, declined or
expired exactly once, and the first of those to land is the one the asking
session gets. Nothing here can revise it. A declined ask that could later read
as answered would hand an agent a choice the reader never made.

The answer is an index into the options recorded at registration, never a
string. An out-of-range index is refused rather than clamped, so the worst a
forged answer can do is choose the wrong one of the options the session itself
offered. `SECURITY.md` owns that contract.

This module imports nothing from the runtime, which is what lets `state` own the
registry while `http_api` and `aggregate` serve from it without a cycle, exactly
as `stream` does. The consequence worth knowing at the call site: it cannot
reach `records.safe_text`, so every caller must bound the untrusted question and
option text before handing it over. That happens at the HTTP ingress.
"""

from __future__ import annotations

import secrets
import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from _thread import LockType
    from collections.abc import Sequence

# The state name is one of answered, declined or expired, and it is a plain
# string rather than an enum because it is serialized straight into the poll
# response. Only answered carries an index; the other two carry None.
Outcome = tuple[str, int | None]


class PendingAsk:
    """One outstanding question and its one-slot answer mailbox."""

    def __init__(
        self,
        *,
        harness: str,
        session_id: str,
        project: str,
        question: str,
        options: Sequence[str],
        created: float,
        question_sent_chars: int | None = None,
        dropped_options: int = 0,
    ) -> None:
        # Generated here, and never accepted from a caller: an id chosen by the
        # peer that registers the ask would let one session address another's
        # question. It is not an authenticator, though. The protection against a
        # forged answer is the index rule, not the id.
        self.id = secrets.token_urlsafe(16)
        self.harness = harness
        self.session_id = session_id
        self.project = project
        self.question = question
        self.options: tuple[str, ...] = tuple(options)
        # What the card says about a cut: the question's length before it was
        # shortened (None when it was not), and how many options past the most a
        # card offers were never shown.
        self.question_sent_chars = question_sent_chars
        self.dropped_options = dropped_options
        self.created = created
        # Stamped by the registry the first time a sweep observes an outcome,
        # and read only by that sweep, which is what bounds how long a resolved
        # ask stays retrievable. Not recorded at resolution time: `resolve`,
        # `decline` and `expire` are handed no clock, and `created` comes from
        # the application's, so a `time.monotonic()` reading here would compare
        # two unrelated origins. It lives on the ask rather than in a side table
        # because a per-id table has to be cleaned on every path that drops an
        # ask, and the one path someone forgot would leak for the life of the
        # process.
        self.settled_seen: float | None = None
        self._condition = threading.Condition()
        self._outcome: Outcome | None = None

    @property
    def outcome(self) -> Outcome | None:
        with self._condition:
            return self._outcome

    @property
    def resolved(self) -> bool:
        with self._condition:
            return self._outcome is not None

    def resolve(self, index: int) -> bool:
        """Record the reader's choice. False when refused, for any reason.

        A negative index is out of range too: Python would happily read
        `options[-1]`, which is the wrong option rather than a refusal.
        """
        with self._condition:
            if self._outcome is not None:
                return False
            if not 0 <= index < len(self.options):
                return False
            self._outcome = ("answered", index)
            self._condition.notify_all()
            return True

    def decline(self) -> None:
        """Nobody will answer this one. Idempotent; an answer already in wins."""
        self._settle(("declined", None))

    def expire(self) -> None:
        """The deadline passed. Idempotent; an answer already in wins."""
        self._settle(("expired", None))

    def wait(self, *, timeout: float) -> Outcome | None:
        """The outcome, or None while the ask is still pending.

        The wait releases the condition's lock, so `outcome`, `resolved` and
        every registry read stay live while a poll is held. A waiter that held
        it would freeze the dashboard for the length of the poll.
        """
        with self._condition:
            if self._outcome is None:
                self._condition.wait(timeout)
            return self._outcome

    def _settle(self, outcome: Outcome) -> None:
        with self._condition:
            if self._outcome is not None:
                return
            self._outcome = outcome
            self._condition.notify_all()


class AskRegistry:
    """Every outstanding ask on one runtime, behind one short-held lock.

    The lock covers the table only. Resolving an ask takes that ask's own
    condition, and is always done outside this lock so that a notify never fans
    out under it. Reading an outcome does take an ask's condition under the
    table lock, which is safe because the order only ever runs that way: nothing
    holding an ask's condition calls back into the table.

    The same one-way rule reaches outside this module and is the reason the wake
    seam in `observation` is safe. `Observation._due` reads `count` while holding
    `Observation._lock`, so that is the order: `Observation._lock`, then this
    lock, then an ask's condition. Nothing here may ever call into `Observation`,
    and `Observation.note_ask` must therefore be called after `register` has
    returned, with no lock from this module held.

    The table maintains itself. `register` sweeps before it decides, and the
    budget counts only what could still need a slot, because the alternative was
    measured: with the sweep riding on `pending` alone, whose only caller is a
    collection, a dashboard with no browser tab open never swept and the lane
    wedged shut for the life of the process.
    """

    def __init__(self) -> None:
        self._lock: LockType = threading.Lock()
        self._asks: dict[str, PendingAsk] = {}

    @property
    def count(self) -> int:
        """How many asks could still need a slot, which means unresolved only.

        A resolved ask that its poller has not collected yet is stored but costs
        nothing: it draws no card and nobody is waiting on a reader. Counting it
        is what filled the budget with answers and refused every later
        registration while the payload reported no cards at all.
        """
        with self._lock:
            return self._unresolved()

    def register(self, ask: PendingAsk, *, limit: int, deadline: float, retention: float) -> bool:
        """Sweep, then store the ask or refuse past the budget.

        A hard cap rather than a queue, mirroring `StreamRegistry.register`:
        every *outstanding* ask costs a card on the page and a polling peer, so
        the honest answer past the cap is a refusal the caller turns into a 503.

        The sweep runs here and not only in `pending` because registration is the
        one event guaranteed to happen when the lane is in use. A reader, a
        browser tab and a collection are all optional, and on the run this
        feature exists for none of them is present.

        `ask.created` is the sweep's clock: it is minted at the call site from
        the application's clock, so reading a second one here could only
        disagree with the deadline this ask is about to be measured against.
        """
        expired = self._sweep(now=ask.created, deadline=deadline, retention=retention)
        with self._lock:
            accepted = self._unresolved() < limit
            if accepted:
                self._asks[ask.id] = ask
        # Outside the lock because `expire` notifies a waiter, and after the
        # decision because `_sweep` has already removed these rows: the budget
        # above was computed against the swept table, not against this loop.
        for stale in expired:
            stale.expire()
        return accepted

    def get(self, ask_id: str) -> PendingAsk | None:
        """The ask, resolved or not: its poller still has an outcome to collect."""
        with self._lock:
            return self._asks.get(ask_id)

    def answer(self, ask_id: str, index: int) -> bool:
        with self._lock:
            ask = self._asks.get(ask_id)
        return False if ask is None else ask.resolve(index)

    def release(self, ask_id: str) -> None:
        with self._lock:
            self._asks.pop(ask_id, None)

    def withdraw(self, ask_id: str) -> bool:
        """Decline and release in one step. False when the id is unknown.

        One step because the halves are not independently useful: taking a
        question off the board is telling the asking session that nobody will
        answer it, and a decline that left the row stored would keep publishing
        a card whose peer has already been told to give up.
        """
        with self._lock:
            ask = self._asks.pop(ask_id, None)
        if ask is None:
            return False
        ask.decline()
        return True

    def pending(self, *, now: float, deadline: float, retention: float) -> list[PendingAsk]:
        """The asks still worth showing, oldest first, after a sweep.

        Anything already resolved is left stored for its poller to collect but
        omitted here, because a card offering a choice that has already been made
        is a card nobody can honestly answer.
        """
        for stale in self._sweep(now=now, deadline=deadline, retention=retention):
            stale.expire()
        with self._lock:
            live = [ask for ask in self._asks.values() if ask.outcome is None]
        # Ordered on created, with the id as the tiebreak, so two asks made
        # inside one clock tick still render in a stable order.
        return sorted(live, key=lambda a: (a.created, a.id))

    def _sweep(self, *, now: float, deadline: float, retention: float) -> list[PendingAsk]:
        """Drop what no longer needs a slot. Returns the asks to expire.

        Expiring is left to the caller, and done outside the lock, because it
        notifies a waiter.

        An ask that already carries an outcome is never expired, whatever its
        age. The deadline is a promise to the reader about how long a question
        stays answerable, not a licence to delete an answer: with the age test
        applied first, an ask answered at t=299.7 against a 300-second deadline
        was deleted by the sweep at t=300.05 and its agent was told nobody had
        answered. So an outcome, once set, survives the retention window instead,
        measured from the first sweep that saw it.
        """
        expired: list[PendingAsk] = []
        with self._lock:
            for ask in list(self._asks.values()):
                if ask.outcome is not None:
                    if ask.settled_seen is None:
                        ask.settled_seen = now
                    elif now - ask.settled_seen > retention:
                        del self._asks[ask.id]
                elif now - ask.created > deadline:
                    del self._asks[ask.id]
                    expired.append(ask)
        return expired

    def _unresolved(self) -> int:
        """How many stored asks still need a slot. The caller holds `_lock`."""
        return sum(1 for ask in self._asks.values() if ask.outcome is None)

    def decline_all(self) -> None:
        """Wake and drop every waiter. Shutdown calls this.

        Dropping is safe for a waiter already parked in `wait`: it holds the ask
        itself and gets its decline regardless. Clearing the table is what stops
        a second `serve` in one process from publishing asks whose peer is gone.
        """
        with self._lock:
            asks = list(self._asks.values())
            self._asks.clear()
        for ask in asks:
            ask.decline()
