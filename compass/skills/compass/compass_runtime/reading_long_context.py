"""Read-only checks of a registered long job's frozen execution context."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING

from . import annotations as annotation_store
from . import claude_settings, observer, reading, reading_route, settings, supervise
from . import reading_long_control as control
from . import reading_long_jobs as jobs
from . import reading_long_markers as markers
from . import reading_policy as policy

if TYPE_CHECKING:
    from .config import RuntimeConfig


@dataclass(frozen=True)
class Route:
    harness: str
    provider: str
    model: str
    destination: str
    tool_destination: str
    content: int
    preferences: settings.Settings
    controls_sha256: str
    system_sha256: str
    effort: str
    ci_read: str
    reason: str
    fallback: bool
    call_timeout_ms: int


def describe(config: RuntimeConfig, harness: str) -> Route | None:
    """Resolve the native requested route and effective settings; never choose a model anew."""
    if harness not in ("claude", "codex"):
        return None  # These are the registered header's content epochs 6 and 5.
    try:
        route = reading_route.resolve(harness, config=config)
        provider = route["provider"]
        if provider not in policy.PROVIDERS:
            return None
        claude = provider == "claude"
        controls = claude_settings.resolve(route["model"]) if claude else None
        return Route(
            harness,
            provider,
            route["model"],
            route["words_destination"],
            route["destination"],
            policy.CONTENT_VERSION
            if harness == "claude"
            else policy.REQUESTED_WORDS_CONTENT_VERSION,
            settings.load(config),
            jobs.digest(asdict(controls) if controls is not None else None),
            jobs.digest(observer.CLAUDE_READING_SYSTEM_PROMPT if claude else ""),
            observer.CLAUDE_READING_EFFORT if claude else observer.OBSERVER_MODEL_REASONING_EFFORT,
            route["ci_read"],
            route["reason"],
            route["fallback"],
            observer.OBSERVER_READING_TIMEOUT_SEC * 1000,
        )
    except (OSError, ValueError):
        return None


def scope_digest(route: Route, scope_sha256: str) -> str | None:
    """Bind an opaque frozen scope identity to the complete effective route descriptor.

    The caller owns what scope was frozen; this adds no source-completeness claim.
    Only the digest goes into the registered header, never configured text.
    """
    if (
        type(route) is not Route
        or not isinstance(scope_sha256, str)
        or len(scope_sha256) != 64
        or any(char not in "0123456789abcdef" for char in scope_sha256)
    ):
        return None
    return jobs.digest({"scope_sha256": scope_sha256, "route": asdict(route)})


def destination_digest(route: Route) -> str:
    """The canonical registered destination binding for this route."""
    return jobs.digest(route.destination)


@dataclass(frozen=True)
class Context:
    # A descriptor is not authority: every check requires the actual live owner.
    active: control.Active
    route: Route
    scope_sha256: str


def _current(config: RuntimeConfig, context: Context, *, terminal: bool = False) -> bool:
    active, route = context.active, context.route
    marker = markers._owned(config, active.owner)  # noqa: SLF001 - shared current-process owner check
    if (
        marker is None
        or marker["state"] != ("completed" if terminal else "active")
        or type(active.job) is not reading.Job
    ):
        return False
    header = marker["header"]
    publication = header.get("publication")
    return bool(
        publication is not None
        and (active.job.sealed is True if terminal else not active.job.sealed)
        and (active.job.harness, active.job.sid) == (publication["harness"], publication["sid"])
        and route.harness == publication["harness"]
        and active.job.id == marker["job_id"]
        and active.job.provider == route.provider == header["provider"]
        and reading.job(config, f"{route.harness}:{active.job.sid}") is active.job
        and header["content"] == route.content
        and header["scope_sha256"] == scope_digest(route, context.scope_sha256)
        and header["destination_sha256"] == destination_digest(route)
        and active.owner.live.prepared.call_timeout_ms == route.call_timeout_ms
        and (header["lineage"], header["epoch"])
        == (active.owner.permission.lineage, active.owner.permission.epoch)
    )


def _live_reason(config: RuntimeConfig, context: Context) -> str:
    if not _current(config, context):
        return "context-changed"
    if supervise.closed():
        return "closed"
    return "cancelled" if reading.job_cancelled(context.active.job) else ""


def check(config: RuntimeConfig, context: Context) -> str:
    """Return a closed refusal or empty string; never refresh, reserve, resume or launch.

    These separate reads do not make external settings atomic. The caller must
    check again at its execution boundary; publication keeps its own barriers.
    """
    if (
        type(context) is not Context
        or type(context.active) is not control.Active
        or type(context.route) is not Route
    ):
        return "context-changed"
    active = context.active
    if reason := _live_reason(config, context):
        return reason
    header = jobs.live_header(active.owner.live)
    if header is None or describe(config, context.route.harness) != context.route:
        return "context-changed"
    publication = header["publication"]
    target = annotation_store.LongTarget(publication["incarnation"], publication["revision"])
    if not annotation_store.long_target_current(
        config, publication["harness"], publication["sid"], target
    ):
        return "intent-changed"
    if reason := policy.long_permission_reason(config, active.owner.permission):
        return reason
    # Read work can block; shared ownership, Cancel/shutdown and full timeout
    # fit must still hold after it. Nothing here authorizes a new pass.
    return _live_reason(config, context) or jobs.deadline_reason(
        active.owner.live, header["plan"]["limits"]["job_ms"]
    )


class Checkpoint:
    """Preparation stop probe: immediate Cancel, throttled current-owner reads.

    Suitable for source page/record loops. A context/permission failure closes
    this probe permanently and retains its actual cause; it never fabricates an
    accepted reader Cancel or refreshes captured authority. Filesystem operations
    remain cooperative; force a check at every major preparation boundary.
    """

    def __init__(self, config: RuntimeConfig, context: Context):
        self.config, self.context = config, context
        self.reason = ""
        self._next: float | None = None

    def __call__(self, *, force: bool = False) -> bool:
        if self.reason:
            return True
        job = self.context.active.job
        if reading.job_cancelled(job):
            self.reason = "cancelled"
        elif supervise.closed():
            self.reason = "closed"
        else:
            try:
                now = self.context.active.owner.live.prepared.clock()
                if type(now) not in (int, float) or not math.isfinite(now):
                    self.reason = "job-clock-invalid"
                elif force or self._next is None or now >= self._next:
                    self.reason = check(self.config, self.context)
                    self._next = now + 0.25
            except Exception:  # noqa: BLE001 - failed preparation probes close the source reader
                self.reason = "context-changed"
        return bool(self.reason)


def _terminal_reason(config: RuntimeConfig, context: Context) -> str:
    if not _current(config, context, terminal=True):
        return "context-changed"
    if config.model_calls_disabled:
        return "run-disabled"
    if supervise.closed():
        return "closed"
    if reading.job_cancelled(context.active.job):
        return "cancelled"
    group = context.active.job.group
    if group is not None and (
        type(group) is not supervise.Group or group.cleanup_complete() is not True
    ):
        return "unstopped"
    return ""


def _publication_deadline(live: jobs.LiveJob, job_ms: int) -> str:
    prepared = live.prepared
    now, start = prepared.clock(), prepared.started_monotonic
    if (
        type(now) not in (int, float)
        or not math.isfinite(now)
        or type(start) not in (int, float)
        or not math.isfinite(start)
        or now < start
    ):
        return "job-clock-invalid"
    return "job-deadline" if (now - start) * 1000 > job_ms else ""


def check_publication(config: RuntimeConfig, context: Context) -> str:
    """Read terminal context; this is not permission or a publication transaction.

    The caller must already have sealed the current UI job through seal_job's
    accepted-Cancel boundary and completed its owned marker. No state is changed
    here. Native groups must have the supervisor's successful cleanup fact; we
    never poll, reap or signal them. The elapsed whole-job deadline applies,
    without allocating time for a new invocation.

    Final publication must hold marker barrier -> long_publication_permission
    SQL fence -> annotation lock. Permission is deliberately checked by that
    held fence, not a separate read here. Source validation/stamp checking and
    result qualification remain the caller's responsibility. Route/settings
    reads are separate filesystem snapshots, not an atomic external-settings lock.
    """
    try:
        if (
            type(context) is not Context
            or type(context.active) is not control.Active
            or type(context.route) is not Route
        ):
            return "context-changed"
        if reason := _terminal_reason(config, context):
            return reason
        header = jobs.live_header(context.active.owner.live)
        if header is None or describe(config, context.route.harness) != context.route:
            return "context-changed"
        publication = header["publication"]
        target = annotation_store.LongTarget(publication["incarnation"], publication["revision"])
        if not annotation_store.long_target_current(
            config, publication["harness"], publication["sid"], target
        ):
            return "intent-changed"
        # Reads can wait. Recheck current ownership/Cancel/cleanup and elapsed
        # deadline after them; no new-call timeout is needed to store a result.
        return _terminal_reason(config, context) or _publication_deadline(
            context.active.owner.live, header["plan"]["limits"]["job_ms"]
        )
    except Exception:  # noqa: BLE001 - failed terminal probes cannot certify publication
        return "context-changed"
