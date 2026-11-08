"""Shared sentence transport for full boards; focused answers keep their own words.

Only the named explanation slots participate. Reader-authored text, timestamps, counts and
varying lane reports are never interpreted as vocabulary tokens. This module stays stdlib-only
so terminal clients can resolve a board without importing the server or its stores.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

SLOTS = (
    "annotation_goal_why",
    "annotation_lines_why",
    "annotation_discarded_why",
    "annotation_binding_why",
    "delivery_why",
    "delivery_none_why",
    "delivery_mixed_why",
    "delivery_binding_why",
    "browser_lane_why",
    "departure_why",
)
DELIVERY_SLOTS = tuple(
    key for key in SLOTS if not key.startswith("annotation_") and key != "departure_why"
)


def _row(row: dict[str, Any], change: Callable[[Any], Any]) -> dict[str, Any]:
    result = dict(row)
    for key in SLOTS:
        if key in row:
            result[key] = change(row[key])
    for key, slots in (
        ("reading_eligibility", ("sentence",)),
        ("delivery_departure", DELIVERY_SLOTS),
    ):
        value = row.get(key)
        if isinstance(value, dict):
            result[key] = {
                name: change(text) if name in slots else text for name, text in value.items()
            }
    return result


def _top(payload: dict[str, Any], change: Callable[[Any], Any]) -> dict[str, Any]:
    discard = payload.get("annotate_discard")
    if not isinstance(discard, dict) or "record" not in discard:
        return {}
    return {"annotate_discard": {**discard, "record": change(discard["record"])}}


def compact(payload: dict[str, Any], vocabulary: dict[str, str]) -> dict[str, Any]:
    """Copy only transport-owned slots, retaining each row's varying values verbatim."""
    tokens = {sentence: token for token, sentence in vocabulary.items() if sentence}
    used: dict[str, str] = {}

    def change(value: Any) -> Any:
        token = tokens.get(value) if isinstance(value, str) else None
        if token is None:
            return value
        used[token] = value
        return token

    return {
        **payload,
        **_top(payload, change),
        "sessions": [_row(row, change) for row in payload["sessions"]],
        "explanations": used,
    }


def expand(payload: Any) -> Any:
    """Resolve full-board tokens once at a client boundary; accept older full-prose boards."""
    if not isinstance(payload, dict) or not isinstance(payload.get("explanations"), dict):
        return payload
    vocabulary = payload["explanations"]

    def change(value: Any) -> Any:
        if not isinstance(value, str) or not value.startswith("why:"):
            return value
        sentence = vocabulary.get(value)
        return sentence if isinstance(sentence, str) else ""

    rows = payload.get("sessions")
    if not isinstance(rows, list):
        return payload
    return {
        **payload,
        **_top(payload, change),
        "sessions": [_row(row, change) if isinstance(row, dict) else row for row in rows],
    }
