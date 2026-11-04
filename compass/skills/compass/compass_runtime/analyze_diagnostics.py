"""Closed metadata for an Analyze outcome; never text or transmission proof.

Missing sections are unknown. In particular, no input measurement exists before
assembly, and a preflight refusal can have input bytes without a capacity result.
The store uses this validator on write, load and publication.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

INPUT_OUTCOMES = frozenset(
    {
        "ok",
        "error",
        "timeout",
        "unavailable",
        "closed",
        "cancelled",
        "unstopped",
        "oversized",
        "refused",
        "context-admission",
        "context-small-window",
        "context-config",
        "context-no-room",
        "context-dynamic",
        "context-compaction",
        "context-fallback",
        "context-config-after-reserve",
    }
)
_INPUT_COUNTS = ("prompt_bytes", "elapsed_ms")
_INPUT_BOOL = ("attempt_reserved", "model_invoked")
_CAPACITY_COUNTS = (
    "prompt_bytes",
    "system_prompt_bytes",
    "maximum_prompt_bytes",
    "estimated_input_tokens",
    "estimated_system_tokens",
    "generation_reserve_tokens",
    "cli_reserve_tokens",
    "requested_maximum",
)
_CAPACITY_NULLABLE = ("window_tokens", "estimated_total_tokens")
_CAPACITY_LABELS = {
    "reason": {"allowed", "prompt-too-large", "context-no-room", "context-config", "no-route"},
    "window_source": {"documented", "configured", "unknown"},
    "estimate_method": {"utf8-bytes-div-3", "legacy-byte-cap"},
    "policy": {"analyze-context-v1"},
    "configuration_reason": {
        "",
        "context-config",
        "dynamic-policy",
        "compaction-policy-conflict",
        "fallback-policy-conflict",
    },
}
_SELECTION_COUNTS = (
    "eligible_entries",
    "selected_entries",
    "eligible_messages",
    "selected_messages",
    "serialized_message_bytes",
)
_SELECTION_NULLABLE = ("expanded_message_characters", "selected_source_characters")


def _count(value: Any) -> bool:
    return type(value) is int and 0 <= value < 2**53


def _input(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and set(value) == {*_INPUT_COUNTS, *_INPUT_BOOL, "kind", "outcome"}
        and all(_count(value[key]) for key in _INPUT_COUNTS)
        and all(type(value[key]) is bool for key in _INPUT_BOOL)
        and value["kind"] == "actual-input"
        and isinstance(value["outcome"], str)
        and value["outcome"] in INPUT_OUTCOMES
        and (not value["model_invoked"] or value["attempt_reserved"])
    )


def _capacity(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and set(value)
        == {
            *_CAPACITY_COUNTS,
            *_CAPACITY_NULLABLE,
            *_CAPACITY_LABELS,
            "allowed",
            "fit_verified",
            "policy_verified",
        }
        and all(_count(value[key]) for key in _CAPACITY_COUNTS)
        and all(value[key] is None or _count(value[key]) for key in _CAPACITY_NULLABLE)
        and all(
            isinstance(value[key], str) and value[key] in choices
            for key, choices in _CAPACITY_LABELS.items()
        )
        and type(value["allowed"]) is bool
        and value["allowed"] == (value["reason"] == "allowed")
        and value["fit_verified"] is False
        and value["policy_verified"] is False
    )


def _prepared(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and set(value) == {"prompt_bytes", "build_elapsed_ms"}
        and all(_count(item) for item in value.values())
    )


def _selection(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and set(value) == {*_SELECTION_COUNTS, *_SELECTION_NULLABLE}
        and all(_count(value[key]) for key in _SELECTION_COUNTS)
        and all(value[key] is None or _count(value[key]) for key in _SELECTION_NULLABLE)
        and value["selected_entries"] <= value["eligible_entries"]
        and value["selected_messages"] <= value["selected_entries"]
        and value["selected_messages"] <= value["eligible_messages"] <= value["eligible_entries"]
    )


def _construction(value: dict[str, Any]) -> bool:
    if "prepared" not in value:
        return True  # Earlier metadata has no preparation measurements.
    prepared, selection, measured = value["prepared"], value["selection"], value["input"]
    if prepared is None:
        return selection is None and measured is None
    return (
        _prepared(prepared)
        and _selection(selection)
        and selection["serialized_message_bytes"] <= prepared["prompt_bytes"]
        and (measured is None or measured["prompt_bytes"] == prepared["prompt_bytes"])
    )


def validate(value: Any, *, spent: bool | None = None) -> dict[str, Any] | None:
    """Return an independent closed record, or None for absent/invalid metadata."""
    if (
        not isinstance(value, dict)
        or set(value)
        not in (
            {"version", "input", "capacity"},
            {"version", "input", "capacity", "prepared", "selection"},
        )
        or type(value["version"]) is not int
        or value["version"] != 1
    ):
        return None
    measured, capacity = value["input"], value["capacity"]
    if measured is not None and not _input(measured):
        return None
    if measured is not None and spent is not None and measured["attempt_reserved"] != spent:
        return None
    if capacity is not None and (
        not _capacity(capacity)
        or measured is None
        or capacity["prompt_bytes"] != measured["prompt_bytes"]
    ):
        return None
    if not _construction(value):
        return None
    return {
        "version": 1,
        "input": dict(measured) if measured is not None else None,
        "capacity": dict(capacity) if capacity is not None else None,
        **{
            key: dict(value[key]) if value[key] is not None else None
            for key in ("prepared", "selection")
            if key in value
        },
    }


class Capture:
    """One producer invocation; snapshots contain only validated measurements."""

    def __init__(self, sink: Callable[[dict[str, Any]], None] | None) -> None:
        self.sink = sink
        self.value: dict[str, Any] = {
            "version": 1,
            "input": None,
            "capacity": None,
            "prepared": None,
            "selection": None,
        }
        self._publish()

    def _publish(self) -> None:
        if self.sink is not None and (checked := validate(self.value)) is not None:
            self.sink(checked)

    def start(self) -> float:
        return time.monotonic() if self.sink is not None else 0.0

    def prepared(self, prompt: str, selection: dict[str, Any] | None, started: float) -> None:
        if self.sink is None:
            return
        self.value.update(
            prepared={
                "prompt_bytes": len(prompt.encode("utf-8", "replace")),
                "build_elapsed_ms": max(0, round((time.monotonic() - started) * 1000)),
            },
            selection=selection,
        )
        self._publish()

    def called(self, model: Any) -> None:
        if self.sink is None:
            return
        self.value.update(
            input=getattr(model, "analyze_diagnostic", None),
            capacity=getattr(getattr(model, "admit_prompt", None), "measurement", None),
        )
        self._publish()
