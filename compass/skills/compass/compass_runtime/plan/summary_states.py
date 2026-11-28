"""The lane states the board last published, saved for the SessionStart summary.

The summary hook starts no program, so it cannot read the tracker, which is read through Git.
The board saves what it published instead (owner ruling, 2026-11-27): each lane's state from the
closed published list, and which lanes serve each goal on the main branch. No plan text, goal
IDs, dates or paths. The file names the SHA-256 of the settings file it was built under. The hook
reads it through the guarded state read, and a file that is missing, damaged, older than a day or
saved under other settings leaves state and progress "not measured".
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Final

from compass_runtime import io

from . import grammar, markdown
from .settings import BOARD_GROUPS

if TYPE_CHECKING:
    from collections.abc import Mapping

FILENAME: Final = "compass-plan-states.json"
VERSION: Final = 1
# The owner's age limit. The board rewrites the file on every plan build, so a day-old file means
# no board has read the tracker since.
MAX_AGE_SECONDS: Final = 24 * 60 * 60
# A board and a hook on one machine share a clock; this only absorbs a small step backwards.
_FUTURE_SECONDS: Final = 60
# 200 briefs and 8 goals each fit in a few tens of KiB; the cap stops a planted file, not a plan.
MAX_BYTES: Final = 256 * 1024
_MAX_LANES: Final = 4096
_STATES: Final = frozenset((*BOARD_GROUPS, markdown.STATUS_UNKNOWN))
_DIGEST: Final = re.compile(r"[0-9a-f]{64}")


class StatesError(ValueError):
    """The file does not hold a valid saved state. Details stay out of every report."""


@dataclass(frozen=True)
class Snapshot:
    states: Mapping[str, str]
    goals: tuple[tuple[str, ...], ...]


def path(home: str) -> str:
    return os.path.join(os.path.abspath(home), FILENAME)


def from_published(projected: Mapping[str, Any]) -> Snapshot:
    """Only published lane IDs and states; draft goals are not counted beside primary ones."""
    states = {
        lane["id"]: lane["state"]
        for lane in projected["lanes"]
        if lane["state"] in _STATES and grammar.is_safe_lane_id(lane["id"])
    }
    goals = tuple(
        lanes
        for goal in projected["goals"]
        if goal["proposal"] is None
        and (lanes := tuple(dict.fromkeys(lane for lane in goal["lanes"] if _lane(lane))))
    )
    return Snapshot(MappingProxyType(states), goals)


def save(home: str, projected: Mapping[str, Any], *, now: float, settings: str) -> None:
    """Save the published states, bound to the digest of the settings that produced them."""
    snapshot = from_published(projected)
    document = {
        "v": VERSION,
        "written": now,
        "settings": settings,
        "lanes": dict(snapshot.states),
        "goals": [list(goal) for goal in snapshot.goals],
    }
    data = json.dumps(document, ensure_ascii=True, allow_nan=False, separators=(",", ":"))
    if len(data) > MAX_BYTES:
        raise StatesError
    io.atomic_write_owner_only(path(home), data, root=os.path.abspath(home))


def _lane(value: object) -> bool:
    return isinstance(value, str) and grammar.is_safe_lane_id(value)


def _unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise StatesError
        result[key] = value
    return result


def _constant(_text: str) -> object:
    raise StatesError


def _goal(value: object) -> tuple[str, ...]:
    # Every member is checked to be a lane ID before any is hashed.
    if not isinstance(value, list) or not 1 <= len(value) <= _MAX_LANES:
        raise StatesError
    if not all(_lane(lane) for lane in value) or len(set(value)) != len(value):
        raise StatesError
    return tuple(value)


def _parse(raw: bytes, now: float, settings: str) -> Snapshot:
    """Every type is checked before a value is compared, hashed or converted, so a damaged
    file is refused as a whole and never raises past `load`."""
    document = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique, parse_constant=_constant)
    if not isinstance(document, dict) or set(document) != {
        "v",
        "written",
        "settings",
        "lanes",
        "goals",
    }:
        raise StatesError
    version, written, digest = document["v"], document["written"], document["settings"]
    lanes, goals = document["lanes"], document["goals"]
    if type(version) is not int or version != VERSION:
        raise StatesError
    if type(written) not in (int, float) or not isinstance(digest, str) or digest != settings:
        raise StatesError
    # An int too large for a float compares exactly against floats, so it needs no conversion.
    if not now - MAX_AGE_SECONDS <= written <= now + _FUTURE_SECONDS:
        raise StatesError
    if not isinstance(lanes, dict) or len(lanes) > _MAX_LANES:
        raise StatesError
    if not all(_lane(lane) and isinstance(state, str) for lane, state in lanes.items()):
        raise StatesError
    if not all(state in _STATES for state in lanes.values()):
        raise StatesError
    if not isinstance(goals, list) or len(goals) > _MAX_LANES:
        raise StatesError
    return Snapshot(MappingProxyType(dict(lanes)), tuple(_goal(goal) for goal in goals))


def load(home: str, *, now: float, settings: str) -> Snapshot | None:
    """The saved states, or None for a file that is missing, unreadable, linked, damaged,
    stale or saved under other settings."""
    if not _DIGEST.fullmatch(settings):
        return None
    try:
        with os.fdopen(io.open_regular(path(home), root=os.path.abspath(home)), "rb") as stream:
            # A second name for the file is a link the guarded read does not refuse itself.
            if os.fstat(stream.fileno()).st_nlink != 1:
                return None
            raw = stream.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            return None
        return _parse(raw, now, settings)
    except (OSError, ValueError, RecursionError):
        return None


def forget(home: str) -> bool:
    """Delete the file, reporting whether there was one."""
    from compass_runtime.config import remove_state_file  # noqa: PLC0415 - only --forget needs it

    return remove_state_file(path(home))
