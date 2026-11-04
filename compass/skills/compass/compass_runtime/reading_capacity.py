"""Pure, estimated Analyze capacity; no tokenizer, route discovery or execution.

The caller supplies the final assembled stdin and explicit system prompt. Byte
counts describe those strings, not the provider's full wire request. Dividing
UTF-8 bytes by three is a policy estimate, never a bound or proof of model fit.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final, Literal

LEGACY_BYTES: Final = 524_288
EXTENDED_BYTES: Final = 2_097_152
GENERATION_RESERVE: Final = 128_000
CLI_RESERVE: Final = 16_384
DOCUMENTED_WINDOW: Final = 1_000_000
# Exact ids only. Context windows and max output: Anthropic's models overview;
# Claude Code's model-config documents native 1M context for these families.
# https://platform.claude.com/docs/en/models/overview
# https://code.claude.com/docs/en/model-config#extended-context
_KNOWN_MODELS: Final = frozenset(
    ("claude-sonnet-5", "claude-sonnet-5-5", "claude-opus-5", "claude-opus-5-5")
)


@dataclass(frozen=True)
class Capacity:
    """Word-free policy result; a configured window is not a verified model limit."""

    allowed: bool
    reason: Literal["allowed", "prompt-too-large", "context-no-room", "context-config", "no-route"]
    prompt_bytes: int
    system_prompt_bytes: int
    maximum_prompt_bytes: int
    window_tokens: int | None
    window_source: Literal["documented", "configured", "unknown"]
    estimated_input_tokens: int
    estimated_system_tokens: int
    estimated_total_tokens: int | None
    estimate_method: Literal["utf8-bytes-div-3", "legacy-byte-cap"]
    policy: Literal["analyze-context-v1"] = field(default="analyze-context-v1", init=False)
    generation_reserve_tokens: int = field(default=GENERATION_RESERVE, init=False)
    cli_reserve_tokens: int = field(default=CLI_RESERVE, init=False)
    fit_verified: Literal[False] = field(default=False, init=False)


def assess(
    prompt: str,
    *,
    system_prompt: str,
    provider: str,
    model: str,
    deployment: str = "unknown",
    window_limits: tuple[int, ...] | list[int] = (),
    configuration_ambiguous: bool = False,
) -> Capacity:
    """Apply limits already decoded by the caller, without changing preference.

    ``direct`` means the caller established a direct Claude route and accounted
    for its applicable controls. Otherwise use ``unknown``, ``gateway`` or
    ``cloud``. No alias resolution, configuration reads or fallback occur here.
    Supply every applicable lower window restriction; positive values cannot
    increase a route's ceiling. Unresolved conflicting controls must set
    ``configuration_ambiguous``. Zero is a real bound, not a missing value.

    The generation reserve includes thinking and answer together. The separate
    CLI allowance is a policy reserve, not measured hidden prompt overhead.
    """
    prompt_bytes = len(prompt.encode("utf-8", "replace"))
    system_bytes = len(system_prompt.encode("utf-8", "replace"))
    input_tokens = (prompt_bytes + 2) // 3
    system_tokens = (system_bytes + 2) // 3
    invalid = (
        type(configuration_ambiguous) is not bool
        or configuration_ambiguous
        or not isinstance(provider, str)
        or not isinstance(model, str)
        or deployment not in ("direct", "gateway", "cloud", "unknown")
        or not isinstance(window_limits, (tuple, list))
        or any(type(limit) is not int or limit < 0 for limit in window_limits)
    )
    known = (
        not invalid and provider == "claude" and deployment == "direct" and model in _KNOWN_MODELS
    )
    window = DOCUMENTED_WINDOW if known else None
    source: Literal["documented", "configured", "unknown"] = "documented" if known else "unknown"
    if not invalid and window_limits:
        lower = min(window_limits)
        if window is None or lower < window:
            window, source = lower, "configured"
    maximum = EXTENDED_BYTES if known else LEGACY_BYTES
    total = None
    if window is not None:
        reserved = GENERATION_RESERVE + CLI_RESERVE + system_tokens
        maximum = min(maximum, 3 * max(0, window - reserved))
        total = reserved + input_tokens
    reason: Literal["allowed", "prompt-too-large", "context-no-room", "context-config", "no-route"]
    if invalid:
        maximum, reason = 0, "context-config"
    elif not provider:
        maximum, reason = 0, "no-route"
    elif maximum == 0:
        reason = "context-no-room"
    elif prompt_bytes > maximum:
        reason = "prompt-too-large"
    else:
        reason = "allowed"
    return Capacity(
        allowed=reason == "allowed",
        reason=reason,
        prompt_bytes=prompt_bytes,
        system_prompt_bytes=system_bytes,
        maximum_prompt_bytes=maximum,
        window_tokens=window,
        window_source=source,
        estimated_input_tokens=input_tokens,
        estimated_system_tokens=system_tokens,
        estimated_total_tokens=total,
        estimate_method="utf8-bytes-div-3" if window is not None else "legacy-byte-cap",
    )
