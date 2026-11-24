"""What a stored check read, kept beside its reading so its level stands only while that holds.

The record the owner's amendment of 2026-11-24 adopted (cited below this docstring). A check's
level is recomputed on every request from what Compass can read now, which fails open when the
evidence that held a level back is lost: a direction only semantic history held, or later work a
truncation removed. So the press saves five word-free parts beside the reading, in the same entry
write, and the focused route draws a level only while every part still matches:

- `read_at`, which binds the record to its own reading;
- `project`, a digest of the project key the check was collected under (never the key, which can
  hold a path);
- `history`, the semantic-history bucket's lineage and generation after the press's own update;
- `transcript_bytes`, the size of the transcript the press stamped before it read;
- `direction_at`, the time of the reader's latest direction the check measured against, kept by
  value so a 24-hour prune cannot erase it.

The Not accurate mark is not a part: it lives on the same entry and is read live.

Nothing here is published, sent to a model, counted or written to session history. A record that
cannot be captured whole is not written at all, so a `direction_at` of None always means "the check
saw no open direction" and never "nobody looked".
"""

# [the record of what a check read](docs/design-reading-a-session.md#amended-2026-11-24-a-stored-check-keeps-the-record-of-what-it-read)  # noqa: E501

from __future__ import annotations

import hashlib
import math
import re
from typing import TYPE_CHECKING, Any, NamedTuple, TypedDict

from . import levels, reading

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

VERSION = 1
_HEX = re.compile(r"[0-9a-f]{32}")
# One past the largest integer every JSON reader holds exactly.
_INT_LIMIT = 2**53

PART_MISSING = "missing"
PART_UNREADABLE = "unreadable"
PART_OTHER_READING = "other-reading"
PART_DIRECTION = "direction"
PART_PROJECT = "project"
PART_HISTORY = "history"
PART_TRANSCRIPT = "transcript"
PARTS = (
    PART_MISSING,
    PART_UNREADABLE,
    PART_OTHER_READING,
    PART_DIRECTION,
    PART_PROJECT,
    PART_HISTORY,
    PART_TRANSCRIPT,
)


class History(TypedDict):
    lineage: str
    generation: int


class Record(TypedDict):
    v: int
    read_at: float
    project: str
    history: History
    transcript_bytes: int
    direction_at: float | None


class Held(NamedTuple):
    """Whether a stored level may stand, and, when not, the first part that failed."""

    ok: bool
    part: str = ""


def project_digest(key: str) -> str:
    """The project key as the record holds it: a digest, because a key can name a folder."""
    return hashlib.blake2b(key.encode("utf-8"), digest_size=16).hexdigest()


def project_key(row: Mapping[str, Any]) -> str:
    """The key the focused route and the press collect a session's project under."""
    return str(row.get("project_key") or row.get("project") or "")


def _time(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) and number > 0 else None


def _count(value: Any, low: int) -> int | None:
    return value if type(value) is int and low <= value < _INT_LIMIT else None


def _hex(value: Any) -> str | None:
    return value if isinstance(value, str) and _HEX.fullmatch(value) else None


def validate(value: Any) -> Record | None:
    """A record exactly as this build writes it, or None. Closed: an extra key is not one."""
    if not isinstance(value, dict) or set(value) != set(Record.__annotations__):
        return None
    history = value.get("history")
    if not isinstance(history, dict) or set(history) != set(History.__annotations__):
        return None
    lineage, generation = _hex(history.get("lineage")), _count(history.get("generation"), 1)
    read_at, project = _time(value.get("read_at")), _hex(value.get("project"))
    size = _count(value.get("transcript_bytes"), 0)
    direction = value.get("direction_at")
    direction_at = None if direction is None else _time(direction)
    if (
        type(value.get("v")) is not int
        or value["v"] != VERSION
        or lineage is None
        or generation is None
        or read_at is None
        or project is None
        or size is None
        or (direction is not None and direction_at is None)
    ):
        return None
    return {
        "v": VERSION,
        "read_at": read_at,
        "project": project,
        "history": {"lineage": lineage, "generation": generation},
        "transcript_bytes": size,
        "direction_at": direction_at,
    }


def _mark(value: Any, key: str) -> History | None:
    """A history mark for exactly this project key, or None."""
    if not isinstance(value, dict) or value.get("key") != key or not key:
        return None
    lineage, generation = _hex(value.get("lineage")), _count(value.get("generation"), 1)
    if lineage is None or generation is None:
        return None
    return {"lineage": lineage, "generation": generation}


def latest_direction(
    row: Mapping[str, Any], facts: Iterable[Any], *, floor: float | None, until: float
) -> float | None:
    """The time of the reader's latest direction after `floor` and at or before `until`.

    Settlement is not applied: a Keep is compared at read time against the record's time, so a
    Keep that is later undone cannot have hidden a direction here.
    """
    who = {"harness": row.get("harness"), "sid": row.get("sid")}
    times = [
        float(fact["at"])
        for fact in facts
        if isinstance(fact, dict)
        and fact.get("fact_id")
        and fact.get("source_session") == who
        and reading.unsettled_direction(fact, floor=floor, settled=None, until=until)
    ]
    return max(times, default=None)


def capture(
    row: Mapping[str, Any],
    facts: Iterable[Any],
    assessment: Mapping[str, Any] | None,
    *,
    floor: float | None,
    transcript_bytes: Any,
    mark: Any,
) -> Record | None:
    """The record of what this check read, or None when any part cannot be captured.

    `facts` must be the very list the check read, and `mark` the history mark of the update made
    while collecting them: a later collect could miss a direction the check saw.
    """
    key = project_key(row)
    read_at = _time(assessment.get("read_at")) if assessment else None
    history = _mark(mark, key)
    size = _count(transcript_bytes, 0)
    if read_at is None or history is None or size is None:
        return None
    return validate(
        {
            "v": VERSION,
            "read_at": read_at,
            "project": project_digest(key),
            "history": dict(history),
            "transcript_bytes": size,
            "direction_at": latest_direction(row, facts, floor=floor, until=read_at),
        }
    )


def held(  # noqa: PLR0911 - one answer per part, in the order the reader is told
    entry: Mapping[str, Any] | None,
    row: Mapping[str, Any],
    *,
    mark: Any,
    transcript_bytes: int | None,
    floor: float | None,
) -> Held:
    """Whether the entry's stored reading may keep the level recomputed for it now.

    Pure. A part that cannot be read now fails as surely as one that changed. A direction the check
    measured against that the reader has still not settled answers first, so its own sentence is
    shown; every other failure is "what this check read has changed since".
    """
    if not entry:
        return Held(False, PART_MISSING)
    if "reading_evidence" not in entry:
        return Held(False, PART_MISSING)
    record = validate(entry.get("reading_evidence"))
    if record is None:
        return Held(False, PART_UNREADABLE)
    assessment = entry.get("assessment")
    read_at = _time(assessment.get("read_at")) if isinstance(assessment, dict) else None
    if read_at is None or record["read_at"] != read_at:
        return Held(False, PART_OTHER_READING)
    at = record["direction_at"]
    settled = _time(row.get("annotation_settled_through"))
    if at is not None and floor is not None and at > floor and (settled is None or at > settled):
        return Held(False, PART_DIRECTION)
    key = project_key(row)
    if not key or record["project"] != project_digest(key):
        return Held(False, PART_PROJECT)
    now = _mark(mark, key)
    if (
        now is None
        or now["lineage"] != record["history"]["lineage"]
        or now["generation"] < record["history"]["generation"]
    ):
        return Held(False, PART_HISTORY)
    if type(transcript_bytes) is not int or transcript_bytes < record["transcript_bytes"]:
        return Held(False, PART_TRANSCRIPT)
    return Held(True)


def hold(rows: list[dict[str, Any]], verdict: Held) -> list[dict[str, Any]]:
    """The analysis rows with no level where the record no longer holds, On track included.

    A row that already shows no level keeps its own reasons, which say why better than this would:
    the gate takes away a level and has nothing to add where there is none.
    """
    if verdict.ok:
        return rows
    reason = (
        levels.REASON_LATER_DIRECTION
        if verdict.part == PART_DIRECTION
        else levels.REASON_RECORD_CHANGED
    )
    out = []
    for row in rows:
        if row.get("level") == levels.NOT_ENOUGH:
            out.append({**row, "evidence": verdict.part})
            continue
        out.append(
            {
                **row,
                "level": levels.NOT_ENOUGH,
                "reasons": [reason],
                "cites": [],
                "evidence": verdict.part,
            }
        )
    return out
