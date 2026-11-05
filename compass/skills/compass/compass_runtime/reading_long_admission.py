"""Fresh requested-long admission; no corpus, thread, model or publication work."""

from __future__ import annotations

import json
import math
import time
from copy import deepcopy
from dataclasses import asdict, dataclass, replace
from typing import TYPE_CHECKING, Any, cast

from . import annotations as annotation_store
from . import events, live_monitor, observer, reading, reading_route, settings, supervise
from . import reading_long_context as context
from . import reading_long_control as control
from . import reading_long_jobs as jobs
from . import reading_long_markers as markers
from . import reading_long_plan as plan_owner
from . import reading_long_preview as preview_owner
from . import reading_policy as policy
from . import reading_source_inventory as source_inventory
from .config import SESSION_SOURCE_PAGE_MAX_SECONDS

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from .aggregate import Application


@dataclass(frozen=True)
class Started:
    context: context.Context
    inventory: source_inventory.Inventory
    _inputs: str

    @property
    def inputs(self) -> dict[str, Any]:
        """Independent private row/entry/route copies, never a public progress payload."""
        return cast("dict[str, Any]", json.loads(self._inputs))


@dataclass(frozen=True)
class Admission:
    started: Started | None = None
    reason: str = ""
    # A failed post-registration check retains accounting for later explicit
    # finalization. This identifier neither grants authority nor acknowledges discard.
    unresolved_job_id: str | None = None


class _RefusedError(Exception):
    pass


@dataclass(frozen=True)
class _Captured:
    row: dict[str, Any]
    entry: annotation_store.Annotation
    route: reading_route.Route
    descriptor: context.Route
    plan: dict[str, Any]
    target: annotation_store.LongTarget
    permission: policy.LongPermission


def _shape(
    application: Application, row: Mapping[str, Any], payload: dict[str, Any], started: float
) -> None:
    if type(started) not in (int, float) or not math.isfinite(started):
        raise _RefusedError("job-clock-invalid")
    if (
        not preview_owner.valid_ingress(payload)
        or payload.get("mode") != "long"
        or payload.get("press") is not True
        or type(payload.get("observer_model")) is not int
        or payload["observer_model"] != 1
    ):
        raise _RefusedError("invalid-request")
    if payload["harness"] != "claude":
        raise _RefusedError("unsupported-source")
    if (
        len(payload["sid"]) > annotation_store.KEY_CAP_CHARS
        or events.normalize_session_id("claude", payload["sid"]) != payload["sid"]
        or (row.get("harness"), row.get("sid")) != ("claude", payload["sid"])
    ):
        raise _RefusedError("session-changed")
    if not application.config.annotations_enabled or application.config.model_calls_disabled:
        raise _RefusedError("run-disabled")
    if supervise.closed():
        raise _RefusedError("closed")


def _capture(
    application: Application, row: Mapping[str, Any], payload: dict[str, Any]
) -> _Captured:
    config, state = application.config, application.state
    fresh = annotation_store.fresh(config, state, application.diagnostic_sink)
    entry = annotation_store.find(fresh.entries or [], "claude", payload["sid"])
    if fresh.entries is None or entry is None:
        raise _RefusedError("intent-unavailable")
    route = reading_route.resolve("claude", config=config)
    preferences = settings.load(config)
    preview = plan_owner.describe(
        row=row,
        entry=entry,
        route=route,
        preferences=preferences,
        policy_status=None,
        source=None,
        now=application.clock(),
        settle_sec=config.reading_settle_sec,
    )
    if preview_owner.changed(payload, preview):
        raise _RefusedError("plan-changed")
    if not reading.press_eligibility(
        row, entry["revisions"], now=application.clock(), settle_sec=config.reading_settle_sec
    )["ok"]:
        raise _RefusedError("intent-ineligible")
    status = policy.status(config, now=application.clock())
    if status["reason"]:
        raise _RefusedError(status["reason"])
    permission = policy.capture_long_permission(config, now=application.clock())
    if permission is None:
        raise _RefusedError("permission-unavailable")
    target = annotation_store.capture_long_target(
        config, state, "claude", payload["sid"], diagnostic_sink=application.diagnostic_sink
    )
    if target is None or target.revision != payload["expected_revision"]:
        raise _RefusedError("intent-changed")
    descriptor = context.describe(config, "claude")
    if descriptor is None or (
        descriptor.provider,
        descriptor.model,
        descriptor.destination,
        descriptor.tool_destination,
        descriptor.preferences,
        descriptor.ci_read,
        descriptor.reason,
        descriptor.fallback,
    ) != (
        route["provider"],
        route["model"],
        route["words_destination"],
        route["destination"],
        preferences,
        route["ci_read"],
        route["reason"],
        route["fallback"],
    ):
        raise _RefusedError("context-changed")
    return _Captured(
        deepcopy(dict(row)),
        deepcopy(entry),
        deepcopy(route),
        descriptor,
        preview["plan"],
        target,
        permission,
    )


def _current(application: Application, captured: _Captured) -> str:
    config = application.config
    if supervise.closed():
        return "closed"
    if context.describe(config, "claude") != captured.descriptor:
        return "context-changed"
    if not annotation_store.long_target_current(
        config, "claude", captured.row["sid"], captured.target
    ):
        return "intent-changed"
    if reason := policy.long_permission_reason(config, captured.permission):
        return reason
    # Capture is not a reserved quota allocation. Another job may use the last
    # call while this press waits for priority; do not take its slot in that case.
    return policy.status(config, now=application.clock())["reason"]


def _register(
    application: Application,
    captured: _Captured,
    frozen: source_inventory.Inventory,
    *,
    started: float,
    clock: Callable[[], float],
    on_rejected: Callable[[Started, str], None] | None,
) -> Admission:
    config = application.config
    publication = {
        "harness": "claude",
        "sid": captured.row["sid"],
        "incarnation": captured.target.incarnation,
        "revision": captured.target.revision,
    }
    private = jobs.canonical(
        {"row": captured.row, "entry": captured.entry, "route": captured.route}
    )
    scope = jobs.digest(
        {
            "row": captured.row,
            "revision": captured.entry["revisions"][-1],
            "streams": [asdict(stream.cursor.frozen) for stream in frozen.streams],
        }
    )
    prepared = policy.prepare_long_job(
        permission=captured.permission,
        binding={
            "started_at": application.clock(),
            "plan": captured.plan,
            "scope_sha256": context.scope_digest(captured.descriptor, scope),
            "target_sha256": jobs.publication_digest(publication),
            "publication": publication,
            "destination_sha256": context.destination_digest(captured.descriptor),
            "provider": captured.descriptor.provider,
            "content": captured.descriptor.content,
        },
        call_timeout_ms=captured.descriptor.call_timeout_ms,
        clock=clock,
    )
    if prepared is None:
        return Admission(reason="context-changed")
    # This is the original trusted process-local start, never a replay renewal.
    prepared = replace(prepared, started_monotonic=started)
    reason = "in-flight"

    def start() -> control.Active | None:
        nonlocal reason
        reason = _current(application, captured)
        if reason:
            return None
        active = control.admit(
            config,
            f"claude:{captured.row['sid']}",
            provider=captured.descriptor.provider,
            label=captured.route["label"],
            job=prepared,
            permission=captured.permission,
            now=application.clock(),
        )
        reason = "" if active is not None else "admission-unavailable"
        return active

    active = live_monitor.start_with_priority(config, f"claude:{captured.row['sid']}", start)
    if active is None:
        return Admission(reason=reason)
    bound = context.Context(active, captured.descriptor, scope)
    try:
        reason = context.check(config, bound)
    except Exception:  # noqa: BLE001 - unknown post-registration state grants no source work
        reason = "context-changed"
    if reason:
        markers.seal(config, active.owner, state="failed", now=application.clock())
        try:
            if on_rejected is not None:
                on_rejected(Started(bound, frozen, private), reason)
        finally:
            reading.end_job(config, f"claude:{captured.row['sid']}", expected_job=active.job)
        return Admission(reason=reason, unresolved_job_id=active.job.id)
    return Admission(Started(bound, frozen, private))


def admit(
    application: Application,
    row: Mapping[str, Any],
    payload: dict[str, Any],
    *,
    clock: Callable[[], float] = time.monotonic,
    on_rejected: Callable[[Started, str], None] | None = None,
) -> Admission:
    """Capture a fresh requested shell, never start a worker or fall back to Analyze.

    The request owner supplies the current published row and owns prior explicit
    save/adoption/settlement semantics; this function does not perform them.
    All saved intent, route/settings and policy checks are fresh owner reads.
    Source inventory is metadata only; baseline/content verification remains
    the collector's job. Separate filesystem checks are not globally atomic.
    on_rejected can finalize a newly registered failed marker while its actual
    Job still owns the slot; teardown follows even if the callback fails. It
    must not restart execution or treat changed intent as acknowledged discard.
    """
    try:
        started = clock()
        _shape(application, row, payload, started)
        captured = _capture(application, row, payload)
        if reason := _current(application, captured):
            return Admission(reason=reason)
        path = observer.resolve_transcript(
            application.config, application.state, "claude", payload["sid"]
        )
        if not path:
            return Admission(reason="source-unavailable")
        frozen = source_inventory.freeze(
            path,
            "claude",
            payload["sid"],
            max_entries=65_536,
            max_streams=captured.plan["limits"]["source_pages"],
            max_seconds=SESSION_SOURCE_PAGE_MAX_SECONDS,
            clock=clock,
        )
        if not frozen.complete:
            return Admission(reason="source-unavailable")
        return _register(
            application, captured, frozen, started=started, clock=clock, on_rejected=on_rejected
        )
    except _RefusedError as exc:
        return Admission(reason=str(exc))
    except (OSError, ValueError, TypeError, KeyError, RecursionError):
        return Admission(reason="admission-unavailable")
