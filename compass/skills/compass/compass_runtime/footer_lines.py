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
import hashlib
import json
import os
import re
import threading
from typing import TYPE_CHECKING, Any, Final

from compass_runtime import io as runtime_io

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

    `waiting` counts the other rows in `needs_input`, the state the page counts, and is None
    unless at least one harness that can report a wait was found and read without error: a zero
    there would be a statement about the schema rather than about the sessions.
    """
    rows = _rows(collection)
    harnesses = _harness_rows(collection)
    measured = any(
        h.get("reports_needs_input") is True and h.get("discovered") is True and not h.get("error")
        for h in harnesses
    )
    waiting = [(row["harness"], row["sid"]) for row in rows if row.get("state") == "needs_input"]
    blind = _blind_labels(harnesses, rows)
    built: Built = {}
    for row in rows:
        key = (row["harness"], _identity(row))
        if key[0] != "claude" or key in built:
            continue
        others = len(waiting) - waiting.count((row["harness"], row["sid"]))
        built[key] = {
            "v": SHAPE_VERSION,
            "at": now,
            "pid": pid,
            "waiting": others if measured else None,
            "blind": list(blind),
            # Left for the monitor to fill. The client prints no drift while `monitor` is not true.
            "monitor": None,
            "level": None,
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

    def update(self, collection: Mapping[str, Any], now: float) -> None:
        try:
            built = build(collection, pid=self._pid, now=now)
            with self._lock:
                self._current = {line_name(h, s) for h, s in built}
                wrote = False
                for (harness, sid), body in built.items():
                    wrote |= self._write(line_name(harness, sid), body, now)
                if wrote:
                    self._sweep(now)
        except Exception as exc:  # noqa: BLE001 — a status line file must never fail a request
            self._report(exc)

    def touch(self, now: float) -> None:
        """Refresh the time on files that are still current and have aged, content unchanged."""
        try:
            with self._lock:
                for name in sorted(self._current):
                    previous = self._written.get(name)
                    if previous is not None:
                        self._write(name, {**previous[0], "at": now}, now)
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

    def _write(self, name: str, body: Body, now: float) -> bool:
        previous = self._written.get(name)
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
                    if entry.name in self._written or _OWNED_NAME.fullmatch(entry.name) is None:
                        continue
                    with contextlib.suppress(OSError):
                        if now - entry.stat(follow_symlinks=False).st_mtime >= SWEEP_AGE_SEC:
                            os.unlink(entry.path)
        except OSError:
            return

    def _report(self, exc: BaseException) -> None:
        if self._said:
            return
        self._said = True
        runtime_io.diag(f"Compass: the status line footer could not be written: {exc}", self._sink)
