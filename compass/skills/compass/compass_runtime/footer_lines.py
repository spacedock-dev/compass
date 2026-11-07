"""The dashboard's half of `--footer`: one small file per Claude session, for the status line.

A status line command runs on every refresh and cannot afford to reach the dashboard, so the
dashboard writes what it would say and the terminal client reads it. The shape and the freshness
rules are in
[R-1](docs/design-runtime-architecture.md#r-1-one-responsibility-per-file-and-the-launcher-owns-none);
the client keeps its own copy of the file name and the ceiling because it imports no runtime
module, and a test holds the two copies equal.
"""

from __future__ import annotations

import contextlib
import copy
import hashlib
import json
import os
import re
import threading
from collections import Counter
from typing import TYPE_CHECKING, Any, Final, Protocol

from compass_runtime import io as runtime_io
from compass_runtime import terminal_sessions

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

SHAPE_VERSION: Final = 1
DIRECTORY: Final = "footer"
# An unchanged file is rewritten this often, so its time says "confirmed this recently" rather
# than "last changed". The client's staleness ceiling is a multiple of this.
REFRESH_SEC: Final = 15.0
# A session that left the board stops being refreshed, and nothing reads its file once the
# client's ceiling passes. The sweep only removes what has been dead for an hour, because a
# session briefly absent from a window is still the same session.
SWEEP_AGE_SEC: Final = 3600.0
SWEEP_EVERY_SEC: Final = 3600.0
_OWNED_NAME = re.compile(r"[a-z][a-z0-9_-]{0,31}-[0-9a-f]{32}\.json")

Body = dict[str, Any]
Built = dict[tuple[str, str], Body]


class MonitorSource(Protocol):
    """Lease lookup is cheap; the page projection may read context and the newest record page."""

    def state(self, row: Mapping[str, Any]) -> Mapping[str, Any]: ...

    def view(
        self, collection: Mapping[str, Any], row: Mapping[str, Any], lease: Mapping[str, Any]
    ) -> Mapping[str, Any] | None: ...


def line_name(harness: str, sid: str) -> str:
    """The file for one session. An id comes from outside, so it is hashed and never joined."""
    digest = hashlib.sha256(sid.encode("utf-8", "replace")).hexdigest()[:32]
    return f"{harness}-{digest}.json"


def _rows(collection: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    sessions = collection.get("sessions")
    if not isinstance(sessions, list):
        return []
    return [
        row
        for row in sessions
        if isinstance(row, dict)
        and isinstance(row.get("harness"), str)
        and isinstance(row.get("sid"), str)
        and row["sid"]
    ]


def _harness_rows(collection: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    harnesses = collection.get("harnesses")
    if not isinstance(harnesses, list):
        return []
    return [h for h in harnesses if isinstance(h, dict) and isinstance(h.get("key"), str)]


def _blind_labels(harnesses: list[Mapping[str, Any]], rows: list[Mapping[str, Any]]) -> list[str]:
    """The board's labels for harnesses whose waits this count did not read.

    One that cannot report a wait is named only while it has an active row, so a harness the
    reader never uses does not decorate every line. One whose read failed is named too: its
    silence is not evidence of quiet.
    """
    active = {row["harness"] for row in rows if row.get("active") is True}
    labels: list[str] = []
    for harness in harnesses:
        label = harness.get("label")
        if not isinstance(label, str) or not label:
            continue
        failed = bool(harness.get("error"))
        cannot = harness.get("reports_needs_input") is not True and harness["key"] in active
        if failed or cannot:
            labels.append(label)
    return labels


def _identity(row: Mapping[str, Any]) -> str:
    """The id a status line will send for this row.

    A Claude row's `sid` is the first eight characters of the transcript stem, and the whole id is
    published beside it as `resume_id`. The status line sends the whole one, so that is the file's
    key whenever it extends the `sid`; a row with only the prefix is filed under the prefix and
    simply goes unmatched.
    """
    sid, resume = row["sid"], row.get("resume_id")
    if isinstance(resume, str) and len(resume) > len(sid) and resume.startswith(sid):
        return resume
    return sid  # type: ignore[no-any-return]


def build(collection: Mapping[str, Any], *, pid: int, now: float) -> Built:
    """What each Claude session's file says, from the board as the page-default snapshot has it.

    `waiting` counts the needs of the board's Attention queue other than this session's own, as
    `terminal_sessions.waiting_queue` defines them (the rule `--sessions waiting` lists by), and
    is None unless at least one harness that can report a wait was found and read: a zero there
    would be a statement about the schema rather than about the sessions. A pending ask is counted
    because it is a wait the board shows whether or not any row says `needs_input`.
    """
    rows = _rows(collection)
    harnesses = _harness_rows(collection)
    measured = any(
        h.get("reports_needs_input") is True and h.get("discovered") is True and not h.get("error")
        for h in harnesses
    )
    queue, owners = terminal_sessions.waiting_queue(collection)
    blind = _blind_labels(harnesses, rows)
    built: Built = {}
    for row in rows:
        key = (row["harness"], _identity(row))
        if key[0] != "claude" or key in built:
            continue
        own = (row["harness"], row["sid"]) in owners
        built[key] = {
            "v": SHAPE_VERSION,
            "at": now,
            "pid": pid,
            "waiting": queue - own if measured else None,
            "blind": list(blind),
            "monitor": False,
            "level": None,
            "last_end": None,
        }
    return built


def _content(body: Body) -> Body:
    return {k: v for k, v in body.items() if k != "at"}


class Lines:
    """Writes the files and keeps them fresh. Nothing here raises into a caller."""

    def __init__(
        self,
        home: str,
        *,
        pid: int | None = None,
        monitor: MonitorSource | None = None,
        diagnostic_sink: Callable[[str], None] | None = None,
    ) -> None:
        self.directory = os.path.join(home, DIRECTORY)
        self._pid = os.getpid() if pid is None else pid
        self._sink: Callable[[str], object] = diagnostic_sink or print
        self._lock = threading.Lock()
        # name -> (the body last written, when). The refresh and the unchanged-skip read this, so
        # most collections write nothing.
        self._written: dict[str, tuple[Body, float]] = {}
        # The names the latest board still has. Only these are refreshed: a session that left
        # must be allowed to go stale rather than be vouched for for ever.
        self._current: set[str] = set()
        self._last_sweep: float | None = None
        self._said = False
        self._monitor = monitor
        self._collection: Body = {}
        self._generation = 0
        self._sessions: dict[str, Mapping[str, Any]] = {}
        self._ambiguous: set[str] = set()
        # Desired bodies survive write failure. In particular, an end must never fall back to
        # restamping the previous live body when a replacement fails.
        self._desired: dict[str, Body] = {}
        self._retired: set[str] = set()
        self._levels: dict[str, tuple[object, str | None]] = {}
        self._attempted: dict[str, float] = {}
        self._inflight: set[str] = set()

    def update(self, collection: Mapping[str, Any], now: float) -> None:
        """Publish counts and lease state under collection's lock; never project here."""
        try:
            snapshot = copy.deepcopy(dict(collection))
            built = build(snapshot, pid=self._pid, now=now)
            sessions = {
                line_name("claude", _identity(row)): row
                for row in _rows(snapshot)
                if row["harness"] == "claude"
            }
            # Two rows with one lease identity cannot be assigned an unambiguous page view.
            identities = Counter((r["harness"], r["sid"]) for r in _rows(snapshot))
            ambiguous = {
                name
                for name, row in sessions.items()
                if identities[(row["harness"], row["sid"])] != 1
            }
            with self._lock:
                if {k: v for k, v in snapshot.items() if k != "generated"} != {
                    k: v for k, v in self._collection.items() if k != "generated"
                }:
                    self._generation += 1
                    self._levels.clear()
                for name in self._current - sessions.keys():
                    body = self._desired[name]
                    previous = self._written.get(name)
                    if body["monitor"] is True or (
                        previous is not None and previous[0]["monitor"] is True
                    ):
                        lease = self._state(self._sessions[name])
                        self._desired[name] = {
                            **body,
                            "monitor": False,
                            "level": None,
                            "last_end": lease.get("last_end"),
                        }
                        self._retired.add(name)
                    elif name not in self._retired:
                        self._desired.pop(name, None)
                    self._levels.pop(name, None)
                self._collection = snapshot
                self._sessions = sessions
                self._ambiguous = ambiguous
                self._current = set(sessions)
                for (harness, sid), body in built.items():
                    name = line_name(harness, sid)
                    self._retired.discard(name)
                    self._desired[name] = body
                    row = sessions[name]
                    if name not in self._ambiguous:
                        self._apply_state(name, self._state(row))
                self._flush(now)
        except Exception as exc:  # noqa: BLE001 — a status line file must never fail a request
            self._report(exc)

    def _state(self, row: Mapping[str, Any]) -> Mapping[str, Any]:
        return self._monitor.state(row) if self._monitor is not None else {"on": False}

    def _apply_state(self, name: str, lease: Mapping[str, Any]) -> None:
        body = self._desired[name]
        on = lease.get("on") is True
        cached = self._levels.get(name)
        body["monitor"] = on
        body["last_end"] = None if on else lease.get("last_end")
        body["level"] = (
            cached[1]
            if on and cached is not None and cached[0] == lease.get("started_at")
            else None
        )
        if not on:
            self._levels.pop(name, None)

    def _flush(self, now: float) -> None:
        wrote = False
        for name in sorted(self._current | self._retired):
            body = {**self._desired[name], "at": now}
            wrote |= self._write(name, body, now)
            previous = self._written.get(name)
            if (
                name in self._retired
                and previous is not None
                and _content(previous[0]) == _content(body)
            ):
                self._retired.remove(name)
                self._desired.pop(name, None)
        if wrote:
            self._sweep(now)

    def touch(self, now: float) -> None:
        """Service ends every pass, and project at most once per session per refresh.

        The coordinator calls this after collection has released its non-reentrant lock. Reserve
        attempts before releasing our lock, so concurrent touches cannot multiply transcript reads.
        Recheck both lease episode and collection generation before accepting a slow answer.
        """
        try:
            jobs = []
            with self._lock:
                for name, row in self._sessions.items():
                    lease = self._state(row) if name not in self._ambiguous else {"on": False}
                    self._apply_state(name, lease)
                    if (
                        lease.get("on") is True
                        and name not in self._inflight
                        and now - self._attempted.get(name, -float("inf")) >= REFRESH_SEC
                    ):
                        self._attempted[name] = now
                        self._inflight.add(name)
                        jobs.append((name, row, lease, self._collection, self._generation))
                self._flush(now)
            for name, row, lease, collection, generation in jobs:
                view = None
                try:
                    with self._lock:
                        current = (
                            self._state(self._sessions[name])
                            if name in self._current and name not in self._ambiguous
                            else {"on": False}
                        )
                        ready = (
                            current.get("on") is True
                            and current.get("started_at") == lease.get("started_at")
                            and generation == self._generation
                        )
                    if ready and self._monitor is not None:
                        view = self._monitor.view(collection, row, current)
                except Exception as exc:  # noqa: BLE001 - a projection failure costs only its level
                    self._report(exc)
                finally:
                    with self._lock:
                        self._inflight.discard(name)
                        if name in self._current:
                            current = (
                                self._state(self._sessions[name])
                                if name not in self._ambiguous
                                else {"on": False}
                            )
                            if (
                                current.get("on") is True
                                and current.get("started_at") == lease.get("started_at")
                                and generation == self._generation
                            ):
                                pill = view.get("pill") if view is not None else None
                                level = pill.get("level") if isinstance(pill, dict) else None
                                self._levels[name] = (lease.get("started_at"), level)
                            self._apply_state(name, current)
                            self._flush(max(now, self._written.get(name, ({}, now))[1]))
        except Exception as exc:  # noqa: BLE001
            self._report(exc)

    def remove_all(self) -> None:
        """Remove what this instance wrote. A crash leaves the rest to the ceiling and the sweep."""
        with self._lock:
            for name in list(self._written):
                with contextlib.suppress(OSError):
                    os.unlink(os.path.join(self.directory, name))
            self._written.clear()
            self._current.clear()
            self._sessions.clear()
            self._ambiguous.clear()
            self._desired.clear()
            self._retired.clear()
            self._levels.clear()
            self._attempted.clear()
            self._generation += 1

    def _write(self, name: str, body: Body, now: float) -> bool:
        previous = self._written.get(name)
        if previous is not None:
            now = max(now, previous[1])
            body = {**body, "at": now}
        if (
            previous is not None
            and _content(previous[0]) == _content(body)
            and now - previous[1] < REFRESH_SEC
        ):
            return False
        try:
            runtime_io.atomic_write_owner_only(
                os.path.join(self.directory, name), json.dumps(body, separators=(",", ":"))
            )
        except OSError as exc:
            self._report(exc)
            return False
        self._written[name] = (body, now)
        return True

    def _sweep(self, now: float) -> None:
        if self._last_sweep is not None and now - self._last_sweep < SWEEP_EVERY_SEC:
            return
        self._last_sweep = now
        try:
            with os.scandir(self.directory) as entries:
                for entry in entries:
                    if entry.name in self._current or _OWNED_NAME.fullmatch(entry.name) is None:
                        continue
                    with contextlib.suppress(OSError):
                        if now - entry.stat(follow_symlinks=False).st_mtime >= SWEEP_AGE_SEC:
                            os.unlink(entry.path)
                            # Forgotten with its file, so a later `remove_all` and the refresh
                            # never name a file that is gone.
                            self._written.pop(entry.name, None)
                            self._attempted.pop(entry.name, None)
        except OSError:
            return

    def _report(self, exc: BaseException) -> None:
        if self._said:
            return
        self._said = True
        runtime_io.diag(f"Compass: the status line footer could not be written: {exc}", self._sink)
