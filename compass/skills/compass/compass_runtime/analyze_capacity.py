"""Requested Analyze admission over the final assembled prompt, never a rebuild."""

from __future__ import annotations

from dataclasses import asdict
from typing import TYPE_CHECKING, Any

from . import claude_settings, reading_capacity, settings

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path


def _assess(
    prompt: str,
    provider: str,
    model: str,
    system_prompt: str,
    *,
    environ: Mapping[str, str] | None = None,
    root: Path | None = None,
) -> tuple[reading_capacity.Capacity, claude_settings.Controls]:
    controls = (
        claude_settings.resolve(model, environ=environ, root=root)
        if provider == "claude"
        else claude_settings.Controls()
    )
    return reading_capacity.assess(
        prompt,
        system_prompt=system_prompt,
        provider=provider,
        model=model,
        deployment=controls.deployment,
        window_limits=controls.window_limits,
        configuration_ambiguous=bool(controls.refusal),
    ), controls


def _refusal(capacity: reading_capacity.Capacity, controls: claude_settings.Controls) -> str | None:
    if controls.refusal:
        return {
            "dynamic-policy": "context-dynamic",
            "compaction-policy-conflict": "context-compaction",
            "fallback-policy-conflict": "context-fallback",
        }.get(controls.refusal, "context-config")
    if (
        capacity.reason == "prompt-too-large"
        and capacity.maximum_prompt_bytes < settings.ANALYZE_PROMPT_MIN_BYTES
    ):
        return "context-small-window"
    return {
        "allowed": None,
        "prompt-too-large": "context-admission",
        "context-no-room": "context-no-room",
        "context-config": "context-config",
        "no-route": "unavailable",
    }[capacity.reason]


def preview(
    provider: str,
    model: str,
    system_prompt: str,
    *,
    environ: Mapping[str, str] | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    """A route's policy allowance, with no actual input or admission claim.

    The empty string computes the policy headroom only. None of its input
    counts, total estimate or allowed verdict is published as a measurement.
    """
    capacity, controls = _assess("", provider, model, system_prompt, environ=environ, root=root)
    return {
        "kind": "capacity-preview",
        "policy": capacity.policy,
        "maximum_prompt_bytes": capacity.maximum_prompt_bytes,
        "window_tokens": capacity.window_tokens,
        "window_source": capacity.window_source,
        "generation_reserve_tokens": capacity.generation_reserve_tokens,
        "cli_reserve_tokens": capacity.cli_reserve_tokens,
        "estimated_system_tokens": capacity.estimated_system_tokens,
        "estimate_method": capacity.estimate_method,
        "fit_verified": capacity.fit_verified,
        "policy_verified": controls.policy_verified,
        "configuration_reason": controls.refusal,
        "reason": _refusal(capacity, controls) or "estimated",
        "can_lower_prompt_setting": capacity.maximum_prompt_bytes
        >= settings.ANALYZE_PROMPT_MIN_BYTES,
    }


class Admission:
    """Resolve controls at the call; retain only word-free estimated measurements."""

    def __init__(
        self, provider: str, model: str, system_prompt: str, *, requested_maximum: int
    ) -> None:
        self.provider = provider
        self.model = model
        self.system_prompt = system_prompt
        self.requested_maximum = requested_maximum
        self.measurement: dict[str, Any] | None = None

    def reset(self) -> None:
        """A new invocation may stop before admission measures any capacity."""
        self.measurement = None

    def __call__(self, prompt: str) -> str | None:
        capacity, controls = _assess(prompt, self.provider, self.model, self.system_prompt)
        self.measurement = {
            **asdict(capacity),
            "requested_maximum": self.requested_maximum,
            "configuration_reason": controls.refusal,
            "policy_verified": controls.policy_verified,
        }
        return _refusal(capacity, controls)
