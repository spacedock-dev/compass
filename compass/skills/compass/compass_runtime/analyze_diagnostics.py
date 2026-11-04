"""Closed metadata for an Analyze outcome; never text or transmission proof.

Missing sections are unknown. In particular, no input measurement exists before
assembly, and a preflight refusal can have input bytes without a capacity result.
The store uses this validator on write, load and publication.
"""

from __future__ import annotations

from typing import Any

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


def validate(value: Any, *, spent: bool | None = None) -> dict[str, Any] | None:
    """Return an independent closed record, or None for absent/invalid metadata."""
    if (
        not isinstance(value, dict)
        or set(value) != {"version", "input", "capacity"}
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
    return {
        "version": 1,
        "input": dict(measured) if measured is not None else None,
        "capacity": dict(capacity) if capacity is not None else None,
    }
