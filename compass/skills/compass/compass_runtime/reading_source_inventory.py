"""Private, bounded inventory of native Claude stream endpoints.

Discovery observes metadata over an interval, not an atomic directory snapshot.
A gap says the remaining inventory is unknown; it has no invented byte extent,
stream count or timestamp. No source words are read, cached or persisted here.
"""

from __future__ import annotations

import math
import os
import stat
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

from . import project_context, reading_source_stream
from .config import SESSION_SOURCE_PAGE_MAX_SECONDS

if TYPE_CHECKING:
    from collections.abc import Callable

Reason = Literal["entries", "streams", "time", "unreadable"]
_MAX_ITEMS = 65_536


@dataclass(frozen=True)
class Stream:
    name: str
    cursor: reading_source_stream.Cursor


@dataclass(frozen=True)
class InventoryGap:
    reason: Reason


@dataclass(frozen=True)
class Inventory:
    streams: tuple[Stream, ...]
    entries_examined: int
    gaps: tuple[InventoryGap, ...] = ()

    @property
    def complete(self) -> bool:
        """Whether discovery exhausted the observed admitted directory shape."""
        return not self.gaps


class _DiscoveryStoppedError(Exception):
    def __init__(self, reason: Reason):
        self.reason = reason


@dataclass
class _Discovery:
    parent: reading_source_stream.Cursor
    max_entries: int
    max_streams: int
    deadline: float
    clock: Callable[[], float]
    examined: int = 0
    children: list[Stream] = field(default_factory=list)

    def check_time(self) -> None:
        if self.clock() >= self.deadline:
            raise _DiscoveryStoppedError("time")

    def admitted_directory(self, directory: str, depth: int) -> bool:
        try:
            info = os.stat(directory, follow_symlinks=False)
        except FileNotFoundError:
            if depth == 0:
                return False
            raise _DiscoveryStoppedError("unreadable") from None
        # The session directory is the canonical admission anchor; every
        # directory below it must remain link-free, just like child paths.
        anchor = self.parent.frozen.path[: -len(".jsonl")]
        return stat.S_ISDIR(info.st_mode) and os.path.realpath(directory) == os.path.join(
            os.path.realpath(anchor), os.path.relpath(directory, anchor)
        )

    def walk(self, directory: str, depth: int = 0) -> None:
        self.check_time()
        if not self.admitted_directory(directory, depth):
            return
        self.check_time()
        with os.scandir(directory) as entries:
            while True:
                self.check_time()
                # Do not consume an extra entry merely to prove exhaustion.
                # Reaching the exact cap is conservatively incomplete.
                if self.examined >= self.max_entries:
                    raise _DiscoveryStoppedError("entries")
                try:
                    entry = next(entries)
                except StopIteration:
                    return
                self.examined += 1
                self.check_time()
                if depth == 0 and entry.name == "workflows":
                    self.walk(entry.path, 1)
                elif depth == 1:
                    if entry.is_dir(follow_symlinks=False):
                        self.walk(entry.path, 2)
                elif entry.is_file(follow_symlinks=False):
                    self.admit(entry.path)
                self.check_time()

    def admit(self, path: str) -> None:
        if not project_context._admitted_subagent_path(self.parent.frozen.path, path):  # noqa: SLF001
            return
        if len(self.children) + 1 >= self.max_streams:
            raise _DiscoveryStoppedError("streams")
        cursor = reading_source_stream.freeze_child(self.parent, path)
        relative = os.path.relpath(path, self.parent.frozen.path[: -len(".jsonl")])
        name = relative.removeprefix("subagents" + os.sep).removesuffix(".jsonl")
        self.children.append(Stream(name, cursor))


def freeze(
    path: str,
    harness: str,
    sid: str,
    *,
    max_entries: int,
    max_streams: int,
    max_seconds: float,
    clock: Callable[[], float] = time.monotonic,
) -> Inventory:
    """Freeze parent first, then native children ordered as the canonical scan.

    Limits count all directory entries examined and all retained streams,
    including the parent. Discovery stops on its first gap; a partial selection
    is sorted but does not claim to contain the globally newest children.
    Limits are cooperative around filesystem operations, which cannot be
    preempted. Each retained stream still requires all three bounded raw passes
    (baseline, records, verification): reserve three times its frozen bytes.
    """
    if type(max_entries) is not int or not 0 <= max_entries <= _MAX_ITEMS:
        raise ValueError("invalid inventory entry allowance")
    if type(max_streams) is not int or not 1 <= max_streams <= _MAX_ITEMS:
        raise ValueError("invalid inventory stream allowance")
    if (
        isinstance(max_seconds, bool)
        or not math.isfinite(max_seconds)
        or not 0 <= max_seconds <= SESSION_SOURCE_PAGE_MAX_SECONDS
    ):
        raise ValueError("invalid inventory time allowance")
    deadline = clock() + max_seconds
    parent = reading_source_stream.freeze(path, harness, sid)
    discovery = _Discovery(parent, max_entries, max_streams, deadline, clock)
    gaps: tuple[InventoryGap, ...] = ()
    try:
        discovery.check_time()
        if parent.frozen.path.endswith(".jsonl"):
            discovery.walk(os.path.join(parent.frozen.path[: -len(".jsonl")], "subagents"))
        discovery.check_time()
    except _DiscoveryStoppedError as exc:
        gaps = (InventoryGap(exc.reason),)
    except (OSError, ValueError):
        # Includes metadata/admission races; an observed child was not safely
        # retained. Its missing extent and the unexamined remainder are unknown.
        gaps = (InventoryGap("unreadable"),)
    discovery.children.sort(
        key=lambda stream: (
            -stream.cursor.frozen.modified,
            os.path.relpath(stream.cursor.frozen.path, parent.frozen.path[: -len(".jsonl")]),
        )
    )
    return Inventory((Stream("parent", parent), *discovery.children), discovery.examined, gaps)
