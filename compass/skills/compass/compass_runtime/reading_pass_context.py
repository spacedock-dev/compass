"""Closed immutable metadata for frozen intent; no source or request-floor derivation."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from . import reading

if TYPE_CHECKING:
    from collections.abc import Sequence

_MAX_ITEMS = 512
_MAX_BYTES = 65_536
_SECTIONS = {"revision", "provenance", "window", "settlement", "safety"}
_GAPS = {"source", "words", "context", "candidates", "adopted-goal"}


@dataclass(frozen=True)
class Frozen:
    encoded: str

    def value(self) -> dict[str, Any]:
        """Return an independent copy; the canonical representation is immutable."""
        return dict(json.loads(self.encoded))


def _object(value: Any, fields: set[str]) -> bool:
    return isinstance(value, dict) and set(value) == fields


def _time(value: Any, *, nullable: bool = False) -> bool:
    return (
        value is None
        if nullable and value is None
        else (type(value) in (int, float) and 0 <= value < 2**53 and math.isfinite(value))
    )


def _id(value: Any) -> bool:
    return isinstance(value, str) and 0 < len(value) <= 160 and all(ord(c) >= 32 for c in value)


def _list(value: Any) -> bool:
    return isinstance(value, list) and len(value) <= _MAX_ITEMS


def _ids(value: Any) -> bool:
    return _list(value) and all(_id(item) for item in value) and len(set(value)) == len(value)


def _refs(value: Any, *, checks: bool = False) -> bool:
    if not _list(value):
        return False
    seen: set[str] = set()
    for row in value:
        if (
            not isinstance(row, list)
            or len(row) != (6 if checks else 2)
            or not _id(row[0])
            or not _time(row[1])
            or row[0] in seen
        ):
            return False
        seen.add(row[0])
        if checks and (
            row[2] not in {"passed", "failed", "not-recorded", "unknown"}
            or any(type(flag) is not bool for flag in row[3:])
        ):
            return False
    return True


def _provenance(value: Any, lines: Sequence[str]) -> bool:
    if not _object(
        value, {"goal_source", "goal_source_at", "goal_saved_at", "goal_status", "lines"}
    ):
        return False
    rows = value["lines"]
    if (
        value["goal_source"] not in {"typed", *reading.PROMPT_SOURCES}
        or value["goal_status"] not in reading.COVERAGE_GOAL_SOURCES
        or not all(_time(value[key], nullable=True) for key in ("goal_source_at", "goal_saved_at"))
        or not isinstance(rows, list)
        or len(rows) != len(lines)
    ):
        return False
    for index, row in enumerate(rows, 1):
        if (
            not _object(row, {"id", "source", "source_id", "requested_at"})
            or row["id"] != reading.outcome_line(index)
            or row["source"] not in {"typed", "entry"}
            or not _time(row["requested_at"], nullable=True)
            or (row["source_id"] is not None and not _id(row["source_id"]))
            or (
                row["source"] == "typed"
                and (row["source_id"] is not None or row["requested_at"] is not None)
            )
            or (row["source"] == "entry" and row["source_id"] is None)
        ):
            return False
    return True


def _window(value: Any) -> bool:
    return (
        _object(value, {"start", "end", "scope", "end_kind", "open_call_at"})
        and _time(value["start"])
        and _time(value["end"], nullable=True)
        and _time(value["open_call_at"], nullable=True)
        and value["scope"]
        in {reading.SCOPE_FINAL, reading.SCOPE_LAST_TURN, reading.SCOPE_MID_FLIGHT}
        and value["end_kind"]
        in {"session-end", "turn-stop", "running", "unobservable", "idle-unknown"}
    )


def _safety(value: Any) -> bool:
    flags = {"record_failed", "checks_unsent", "agent_words_whole", "goal_whole"}
    if not _object(
        value,
        flags
        | {
            "unread_checks",
            "unread_failures",
            "unlisted",
            "newest_final",
            "source_complete",
            "gaps",
            "checks",
            "writes",
        },
    ):
        return False
    return (
        all(type(value[key]) is bool for key in flags)
        and (value["source_complete"] is None or type(value["source_complete"]) is bool)
        and value["newest_final"] in {None, "whole", "unfit", "unavailable"}
        and _refs(value["unread_checks"])
        and _refs(value["unread_failures"])
        and _refs(value["checks"], checks=True)
        and _refs(value["writes"])
        and _list(value["unlisted"])
        and all(_time(at) for at in value["unlisted"])
        and _ids(value["gaps"])
        and set(value["gaps"]) <= _GAPS
    )


def freeze(goal: str, lines: Sequence[str], metadata: Any) -> Frozen:
    """Validate/copy metadata already derived by the existing reading-policy owners.

    None request times and source completeness stay unknown. Never infer provenance,
    request ages, source coverage or semantic safety from these type/shape checks.
    All lists and encoded bytes have finite bounds; overflow refuses, never truncates.
    """
    try:
        valid = (
            isinstance(goal, str)
            and len(lines) <= reading.MAX_OUTCOME_LINES
            and all(isinstance(line, str) for line in lines)
            and _object(metadata, _SECTIONS)
            and _object(metadata["revision"], {"number", "at"})
            and type(metadata["revision"]["number"]) is int
            and 0 < metadata["revision"]["number"] < 2**53
            and _time(metadata["revision"]["at"])
            and metadata["revision"]["at"] > 0
            and _provenance(metadata["provenance"], lines)
            and _window(metadata["window"])
            and _object(metadata["settlement"], {"through", "uncitable"})
            and _time(metadata["settlement"]["through"], nullable=True)
            and _ids(metadata["settlement"]["uncitable"])
            and _safety(metadata["safety"])
        )
        if not valid:
            raise ValueError("Invalid frozen reading context")
        intent = json.dumps({"goal": goal, "lines": tuple(lines)}, ensure_ascii=False).encode(
            "utf-8"
        )
        encoded = json.dumps(
            {
                "version": 1,
                "intent_sha256": hashlib.sha256(intent).hexdigest(),
                **metadata,
            },
            ensure_ascii=False,
            sort_keys=True,
            allow_nan=False,
        )
        if len(encoded.encode("utf-8")) > _MAX_BYTES:
            raise ValueError("Frozen reading context exceeds its bound")
    except (TypeError, KeyError, UnicodeError, RecursionError):
        raise ValueError("Invalid frozen reading context") from None
    return Frozen(encoded)


def intent(goal: str, lines: Sequence[str], context: Frozen | None = None) -> dict[str, Any]:
    """The renderer-owned intent object, optionally bound to its exact frozen context."""
    value: dict[str, Any] = {"goal": goal, "lines": tuple(lines)}
    if context is None:
        return value
    try:
        if type(context) is not Frozen or len(context.encoded) > _MAX_BYTES:
            raise ValueError("Invalid frozen reading context")
        supplied = context.value()
        metadata = {
            key: item for key, item in supplied.items() if key not in {"version", "intent_sha256"}
        }
        if freeze(goal, lines, metadata) != context:
            raise ValueError("Frozen context does not match the exact intent")
    except (TypeError, KeyError, UnicodeError, RecursionError):
        raise ValueError("Invalid frozen reading context") from None
    value["context"] = supplied
    return value


def require_safety(context: Frozen, floor: reading.Selection) -> None:
    """The final caller cannot silently weaken the safety floor carried by every map."""
    rows = {
        row["id"]: row for row in (*floor.entries, *floor.unread_checks, *floor.unread_failures)
    }

    def refs(entries: Sequence[reading.LedgerEntry]) -> list[list[Any]]:
        return [[row["id"], row["at"]] for row in entries]

    expected = {
        key: getattr(floor, key)
        for key in (
            "record_failed",
            "checks_unsent",
            "newest_final",
            "agent_words_whole",
            "goal_whole",
        )
    }
    expected.update(
        unread_checks=refs(floor.unread_checks),
        unread_failures=refs(floor.unread_failures),
        unlisted=list(floor.unlisted),
        checks=[
            [
                row["id"],
                row["at"],
                row.get("result", "unknown"),
                row.get("stale", False),
                row.get("changed_after", False),
                row.get("read_incomplete", False),
            ]
            for row in rows.values()
            if row.get("subject")
            in {reading.CHECK_SUBJECT, reading.CI_SUBJECT, reading.CI_CHECK_SUBJECT}
        ],
        writes=refs([row for row in rows.values() if row.get("subject") == reading.WRITE_SUBJECT]),
    )
    actual = context.value()["safety"]
    if any(actual[key] != value for key, value in expected.items()):
        raise ValueError("Final safety floor differs from frozen map context")
