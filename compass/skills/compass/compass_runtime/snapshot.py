"""The published dashboard snapshot: one built response per variant, versioned.

The revision is a pair, not an integer. A counter alone restarts at zero with
the process, so a tab frozen at revision 512 across a dashboard restart would
treat every later revision as older and never refetch again. Pairing it with
the server start stamp makes a restart visibly discontinuous, and a client
discards its cursor when the first element changes.

The counter is per process rather than per variant, so it orders every
published state a client could hold a cursor against.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, NamedTuple

if TYPE_CHECKING:
    from _thread import LockType
    from collections.abc import Callable

# Keyed as the memo keyed it: window hours paired with the show-all flag, so the
# two response variants stay separate.
SnapshotKey = tuple[float, bool]
# The server start stamp paired with a per-process counter. See the module
# docstring for why a bare counter is not enough.
Revision = tuple[float, int]
# Harness, published session ID, and private working directory, in board order.
SessionFolders = tuple[tuple[str, str, str], ...]


class Entry(NamedTuple):
    revision: Revision
    body: bytes
    published_at: float
    published_monotonic: float | None
    validate: Callable[[], bool] | None
    folders: SessionFolders


def format_revision(revision: Revision) -> str:
    """The wire form: restart stamp, a dot, the counter."""
    started, counter = revision
    return f"{started:.0f}.{counter}"


class Snapshot:
    """One process's published responses, guarded by its own lock.

    The lock is held only across a dict read or write, never across collection
    and never across a socket write. A published entry is an immutable tuple, so
    a reader that has taken one cannot be torn by a concurrent publish.
    """

    def __init__(self, *, server_started: float) -> None:
        self.server_started = server_started
        self._lock: LockType = threading.Lock()
        self._counter = 0
        self._generation = 0
        self._entries: dict[SnapshotKey, Entry] = {}

    def generation(self) -> int:
        """How many times `clear` has run: read before collecting, passed to `publish`."""
        with self._lock:
            return self._generation

    def publish(
        self,
        key: SnapshotKey,
        body: bytes,
        *,
        now: float = 0.0,
        monotonic_now: float | None = None,
        generation: int | None = None,
        validate: Callable[[], bool] | None = None,
        folders: SessionFolders = (),
    ) -> tuple[Revision, bool]:
        """Mint a revision for `body`, and keep it unless a `clear` came after `generation`.

        Returns the revision and whether the body was kept: a body not kept is
        never served again, so the caller does not announce it.

        A body collected across a `clear` is answered to the request that
        collected it and never kept. A collection reads its stores near its
        start and publishes seconds later, so without this a save's clear
        landing in between was overwritten by the pre-save words with a fresh
        stamp, and the saving page's own refresh was served them (DRC-4760).
        The revision is still minted so the counter keeps ordering every body
        a client was handed.
        """
        with self._lock:
            self._counter += 1
            revision = (self.server_started, self._counter)
            kept = generation is None or generation == self._generation
            if kept:
                self._entries[key] = Entry(revision, body, now, monotonic_now, validate, folders)
            return revision, kept

    def current(self, key: SnapshotKey) -> tuple[Revision, bytes] | None:
        with self._lock:
            entry = self._entries.get(key)
        if entry is None:
            return None
        return entry.revision, entry.body

    def session_folders(self, key: SnapshotKey) -> SessionFolders | None:
        """Private folder evidence for the same board rows and generation as the payload."""
        with self._lock:
            entry = self._entries.get(key)
        return None if entry is None else entry.folders

    def fresh(
        self, key: SnapshotKey, *, now: float, max_age: float, monotonic_now: float | None = None
    ) -> tuple[Revision, bytes] | None:
        """Check evidence outside the lock and never reuse a response cleared during that check."""
        with self._lock:
            entry = self._entries.get(key)
        if entry is None:
            return None
        # After a setback, an old response can appear recent again once the wall clock catches up.
        if not 0 <= now - entry.published_at < max_age:
            return None
        if (
            monotonic_now is not None
            and entry.published_monotonic is not None
            and not 0 <= monotonic_now - entry.published_monotonic < max_age
        ):
            return None
        if entry.validate is not None:
            if not entry.validate():
                return None
            with self._lock:
                if self._entries.get(key) is not entry:
                    return None
        return entry.revision, entry.body

    def clear(self) -> None:
        """Drop every published variant, so the next read collects.

        The counter is deliberately not rewound. A client holding a cursor must
        see strictly higher revisions after an invalidation, or it would ignore
        the state that follows one. The generation moves too, so a collection
        already running is not kept over the drop (see `publish`).
        """
        with self._lock:
            self._entries.clear()
            self._generation += 1

    def age(self, key: SnapshotKey, *, now: float) -> float | None:
        """Seconds since this variant was published, or None if it never was.

        None rather than zero: zero reads as fresh, which would let a cold GET
        skip the collection it needs.
        """
        with self._lock:
            entry = self._entries.get(key)
        if entry is None:
            return None
        return now - entry.published_at
