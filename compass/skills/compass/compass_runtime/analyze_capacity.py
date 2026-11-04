"""Requested Analyze admission over the final assembled prompt, never a rebuild."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from . import claude_settings, reading_capacity


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

    def __call__(self, prompt: str) -> str | None:
        controls = (
            claude_settings.resolve(self.model)
            if self.provider == "claude"
            else claude_settings.Controls()
        )
        capacity = reading_capacity.assess(
            prompt,
            system_prompt=self.system_prompt,
            provider=self.provider,
            model=self.model,
            deployment=controls.deployment,
            window_limits=controls.window_limits,
            configuration_ambiguous=bool(controls.refusal),
        )
        self.measurement = {
            **asdict(capacity),
            "requested_maximum": self.requested_maximum,
            "configuration_reason": controls.refusal,
            "policy_verified": controls.policy_verified,
        }
        if controls.refusal:
            return {
                "dynamic-policy": "context-dynamic",
                "compaction-policy-conflict": "context-compaction",
                "fallback-policy-conflict": "context-fallback",
            }.get(controls.refusal, "context-config")
        return {
            "allowed": None,
            "prompt-too-large": "context-admission",
            "context-no-room": "context-no-room",
            "context-config": "context-config",
            "no-route": "unavailable",
        }[capacity.reason]
