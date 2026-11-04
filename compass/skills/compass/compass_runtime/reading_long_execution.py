"""One registered long-pass Guard, with a final check at actual runner entry."""

from __future__ import annotations

import hashlib
import shutil
import threading
import time
from typing import TYPE_CHECKING, Any, NoReturn

from . import analyze_capacity, observer, reading, reading_route, supervise
from . import reading_long_context as context_gate
from . import reading_long_jobs as jobs
from . import reading_long_markers as markers
from . import reading_policy as policy

if TYPE_CHECKING:
    from collections.abc import Callable

    from .config import RuntimeConfig


def _refuse(reason: str) -> NoReturn:
    raise policy.RefusedError(policy._answer(reason=reason))  # noqa: SLF001 - internal closed refusal


def _request(
    header: dict[str, Any], job_id: str, ordinal: int, prompt: str, cap: int
) -> dict[str, Any]:
    plan = header["plan"]
    if type(cap) is not int or cap != plan["limits"]["reply_bytes"]:
        _refuse("invalid-long-request")
    try:
        encoded = prompt.encode("utf-8")
    except UnicodeEncodeError:
        _refuse("invalid-long-request")
    return {
        "version": 1,
        "job_id": job_id,
        "started_at": header["started_at"],
        "ordinal": ordinal,
        "kind": "reconciliation" if ordinal == plan["max_calls"] else "evidence",
        "max_evidence_passes": plan["max_evidence_passes"],
        "plan_sha256": jobs.digest(plan),
        "prompt_sha256": hashlib.sha256(encoded).hexdigest(),
        "prompt_bytes": len(encoded),
        "destination_sha256": header["destination_sha256"],
        "provider": header["provider"],
        "content": header["content"],
    }


def _require_slot(
    config: RuntimeConfig, owner: markers.MarkerOwner, ordinal: int, request: dict[str, Any] | None
) -> None:
    marker = markers._owned(config, owner)  # noqa: SLF001 - same owner as reservation
    slot = (
        next((slot for slot in marker["passes"] if slot["request"]["ordinal"] == ordinal), None)
        if marker is not None
        else None
    )
    if slot is None or slot["state"] != "charged" or slot["request"] != request:
        _refuse("context-changed")


def guard(  # noqa: C901, PLR0913 - bounded per-slot callbacks share the fresh permit and one runner entry
    config: RuntimeConfig,
    context: context_gate.Context,
    ordinal: int,
    *,
    clock: Callable[[], float] = time.time,
    runner: Any = supervise.run,
    binary_resolver: Any = shutil.which,
    on_reserved: Callable[[], None] | None = None,
    source_current: Callable[[], bool] | None = None,
    on_spawn: Callable[[], None] | None = None,
) -> policy.GuardedModel:
    """Build one slot's Guard; construction checks gates without charging or launching.

    Only a fresh durable marker permit can reach the runner once. Gate reads
    are separate snapshots, not atomic external settings; supervised handover
    still closes the Cancel window after process spawn.
    An optional source gate may revalidate the caller's frozen source at construction,
    reservation, post-charge and runner entry. on_spawn follows supervised handover.
    """

    def current() -> None:
        if reason := context_gate.check(config, context):
            _refuse(reason)
        if source_current is not None:
            if source_current() is not True:
                _refuse("context-changed")
            if reason := context_gate.check(config, context):
                _refuse(reason)

    current()
    active, route = context.active, context.route
    header = jobs.live_header(active.owner.live)
    if header is None:
        _refuse("context-changed")
    plan = header["plan"]
    if type(ordinal) is not int or not 1 <= ordinal <= plan["max_calls"]:
        raise ValueError("Invalid long-pass ordinal")
    request: dict[str, Any] | None = None
    authorized = False
    entry_lock = threading.Lock()

    def cancelled() -> bool:
        return reading.job_cancelled(active.job)

    def reserve(prompt: str, cap: int) -> markers.Permit:
        nonlocal request, authorized
        current()
        request = _request(header, active.job.id, ordinal, prompt, cap)
        permit = markers.reserve(
            config, active.owner, request=request, now=clock(), cancelled=cancelled
        )
        with entry_lock:
            authorized = permit.launch is True and permit.fresh_charge is True
        return permit

    def before_invoke() -> None:
        _require_slot(config, active.owner, ordinal, request)
        current()

    def before_runner() -> None:
        nonlocal authorized
        before_invoke()
        with entry_lock:
            if not authorized:
                _refuse("reservation-refused")
            if reason := jobs.deadline_reason(active.owner.live, plan["limits"]["job_ms"]):
                _refuse(reason)
            authorized = False

    def spawned(group: supervise.Group) -> None:
        if reading.hand_over(active.job, group):
            group.cancel()
        elif on_spawn is not None:
            on_spawn()

    checked_runner = observer.CheckedRunner(runner, before_runner)
    model = (
        reading.ClaudeReadingModel(
            config,
            runner=checked_runner,
            binary_resolver=binary_resolver,
            on_spawn=spawned,
            analyze=True,
        )
        if route.provider == "claude"
        else reading.CodexReadingModel(
            config, runner=checked_runner, binary_resolver=binary_resolver, on_spawn=spawned
        )
    )
    return policy.GuardedModel(
        config,
        model,
        clock,
        provider=route.provider,
        destination=route.destination,
        resolve_destination=lambda: reading_route.destination(route.provider),
        on_reserved=on_reserved,
        cancelled=cancelled,
        content=route.content,
        admit_prompt=analyze_capacity.Admission(
            route.provider,
            route.model,
            observer.CLAUDE_READING_SYSTEM_PROMPT if route.provider == "claude" else "",
            requested_maximum=route.preferences.analyze_prompt_bytes,
        ),
        reserve_prompt=reserve,
        before_invoke=before_invoke,
    )
