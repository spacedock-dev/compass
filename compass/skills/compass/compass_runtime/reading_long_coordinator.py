"""One explicitly admitted long job owns preparation, terminal storage and teardown."""

from __future__ import annotations

import math
import shutil
import threading
import time
from copy import deepcopy
from dataclasses import replace
from itertools import chain
from typing import TYPE_CHECKING, Any

from . import ci_read, reading, reading_preparation, supervise
from . import reading_long_admission as admission
from . import reading_long_context as context_owner
from . import reading_long_control as control
from . import reading_long_diagnostics as diagnostics
from . import reading_long_finalize as finalize
from . import reading_long_inspection as inspection
from . import reading_long_jobs as jobs
from . import reading_long_markers as markers
from . import reading_long_reconcile as reconcile
from . import reading_long_worker as worker
from . import reading_source_collect as source

if TYPE_CHECKING:
    from collections.abc import Callable

    from .aggregate import Application


def _key(started: admission.Started) -> str:
    job = started.context.active.job
    return f"{job.harness}:{job.sid}"


def _clean(started: admission.Started) -> bool:
    group = started.context.active.job.group
    return group is None or (type(group) is supervise.Group and group.cleanup_complete() is True)


def _blocked(application: Application, started: admission.Started) -> None:
    if reading.block_long_job(application.config, _key(started), started.context.active.job):
        application.state.snapshot.clear()


def stop(application: Application, key: str, *, reason: str) -> bool:
    """Latch Clear/Pause before consulting the handover handle; never accept Cancel."""
    job = reading.job(application.config, key)
    if job is None:
        return False
    accepted, group = reading.stop_long_job(application.config, key, job, reason=reason)
    if accepted and group is not None:
        group.cancel()
    return accepted


def stop_all(application: Application) -> None:
    for key, value in reading.published_jobs(application.config).items():
        if value.get("mode") == "long":
            stop(application, key, reason="permission-changed")


def cancel(application: Application, key: str, job_id: str) -> bool:
    accepted, group = reading.cancel_job(application.config, key, job_id, now=application.clock())
    if accepted and group is not None:
        group.cancel()
    return accepted


def _goals(inputs: dict[str, Any]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    revision = inputs["entry"]["revisions"][-1]
    current = tuple(
        dict.fromkeys(
            value
            for value in (
                (inputs["row"].get("session_goal") or {}).get("text"),
                revision.get("goal"),
            )
            if isinstance(value, str) and value.strip()
        )
    )
    return tuple(dict.fromkeys((*current, *reading.outcome_lines(revision)))), current


def _collect(
    application: Application,
    started: admission.Started,
    inputs: dict[str, Any],
    checkpoint: context_owner.Checkpoint,
    prepare_started: float,
) -> source.Collection:
    header = jobs.live_header(started.context.active.owner.live)
    if header is None:
        raise ValueError("Long owner is unavailable")
    plan = header["plan"]
    limits = plan["limits"]
    goals, current = _goals(inputs)
    return source.collect(
        application.config,
        started.inventory,
        held_inputs=(started._inputs, inputs),  # noqa: SLF001 - admission's retained serialized data
        prepare_started=prepare_started,
        goal_texts=goals,
        current_ci_goals=current,
        limits=source.Limits(
            **{
                key: limits[key]
                for key in (
                    "source_bytes",
                    "source_pages",
                    "retained_bytes",
                    "retained_units",
                    "prepare_ms",
                )
            }
        ),
        clock=started.context.active.owner.live.prepared.clock,
        cancelled=checkpoint,
    )


def _outcome(
    started: admission.Started,
    inspected: inspection.Inspection,
    cause: str,
    diagnostic: dict[str, Any] | None = None,
    withheld_reason: str = "",
) -> tuple[str, str]:
    job = started.context.active.job
    spent = inspected.exact is not None and inspected.exact.calls > 0
    if reading.job_cancelled(job) and not job.cancelled_after_close:
        return (
            reading.WITHHELD_CANCELLED if spent else reading.WITHHELD_CANCELLED_UNSENT
        ), "cancelled"
    if supervise.closed() or cause == "closed":
        return (reading.WITHHELD_INTERRUPTED if spent else reading.WITHHELD_STOPPING), "interrupted"
    cause = reading.long_stop_reason(job) or cause
    if cause not in (
        "unresolved",
        "coverage-unresolved",
        "evidence-unresolved",
        "map-unresolved",
        "invalid-reply",
        "error",
        "timeout",
        "failed",
        "model-failed",
        "refused",
        "oversized",
        "unavailable",
    ):
        return reading.WITHHELD_LONG_INCOMPLETE, "withheld"
    if withheld_reason in reading.WITHHELD:
        return withheld_reason, "withheld"
    return _transport_reason(job.provider, spent, diagnostic), "withheld"


def _transport_reason(provider: str, spent: bool, diagnostic: dict[str, Any] | None) -> str:
    # Real per-invocation transport outcomes preserve their specific explanation.
    # An uncharged late pass must not describe earlier whole-job charges as zero.
    for slot in reversed((diagnostic or {}).get("observations") or ()):
        measured = (slot["observation"].get("diagnostic") or {}).get("input")
        if measured is None:
            continue
        outcome = measured["outcome"]
        if not isinstance(outcome, str):
            continue
        if outcome == "timeout" and provider == "claude":
            return reading.WITHHELD_CLAUDE_TIMED_OUT
        if outcome == "oversized":
            return reading.WITHHELD_OVERSIZED
        if outcome == "error":
            return (
                reading.WITHHELD_CLAUDE_FAILED
                if provider == "claude"
                else reading.WITHHELD_CODEX_FAILED
            )
        if (
            outcome.startswith("context-")
            and outcome in reading.WITHHELD
            and (not spent or measured["attempt_reserved"])
        ):
            return outcome
    return reading.WITHHELD_LONG_INCOMPLETE


def finish_withheld(
    application: Application,
    started: admission.Started,
    cause: str,
    *,
    collection: source.Collection | None = None,
    long_diagnostic: dict[str, Any] | None = None,
    withheld_reason: str = "",
) -> finalize.Finalized:
    """Store exact accounting while still owning the slot, then release only after cleanup.

    Unknown process cleanup preserves both slot and marker. A rejected target or
    ledger leaves its marker for explicit later recovery/disposition, never an
    inferred discard. No ordinary source collector runs to publish the result.
    """
    active, config = started.context.active, application.config
    if not _clean(started):
        _blocked(application, started)
        return finalize.Finalized(reason="unstopped")
    reading.seal_job(active.job)
    inspected = inspection.inspect(config, active.job.id, now=application.clock())
    reason, outcome = _outcome(started, inspected, cause, long_diagnostic, withheld_reason)
    markers.seal(
        config,
        active.owner,
        state="cancelled" if outcome == "cancelled" else "failed",
        now=application.clock(),
    )
    try:
        inspected = inspection.inspect(config, active.job.id, now=application.clock())
        marker = markers.load(config, active.job.id)
        if marker is None:
            return finalize.Finalized()
        if collection is not None and collection.snapshot is not None:
            collection = replace(collection, usage=collection.snapshot.account.usage)
        value = (
            deepcopy(long_diagnostic)
            if long_diagnostic is not None
            else diagnostics.derive(
                plan=marker["header"]["plan"],
                inventory=started.inventory,
                collection=collection,
                inspected=inspected,
                outcome=outcome,
                observations=[
                    {"observation": slot["observation"], "ended": slot["state"] == "settled"}
                    for slot in marker["passes"]
                    if slot["observation"] is not None
                ],
            )
        )
        value.update(outcome=outcome, complete=False)
        category = diagnostics.stop_reason(
            "cancelled"
            if outcome == "cancelled"
            else "closed"
            if outcome == "interrupted"
            else reading.long_stop_reason(active.job) or cause
        )
        if category is not None and (category != "unknown" or "stop_reason" not in value):
            value["stop_reason"] = category
        if collection is not None and value["source"] is not None:
            usage = collection.usage
            value["source"]["usage"] = {
                "io_bytes": usage.source_bytes,
                "pages": usage.source_pages,
                "retained_graph_peak_bytes": usage.retained_bytes,
                "retained_graph_peak_units": usage.retained_units,
                "prepare_ms": math.ceil(usage.prepare_ms),
            }
        return finalize.withheld_measured(
            config,
            application.state,
            active=active,
            reason=reason,
            now=application.clock(),
            long_diagnostic=value,
            diagnostic_sink=application.diagnostic_sink,
        )
    finally:
        reading.end_job(config, _key(started), expected_job=active.job)
        application.state.snapshot.clear()


def _completed(
    application: Application,
    started: admission.Started,
    collected: source.Collection,
    mapped: worker.Mapped,
    finished: reconcile.Finished,
) -> None:
    active, config = started.context.active, application.config
    if not _clean(started):
        _blocked(application, started)
        return
    if (
        finished.assessment is None
        or finished.result is None
        or finished.frozen_context is None
        or mapped.budget is None
        or finished.state not in ("resolved", "partial")
    ):
        finish_withheld(
            application,
            started,
            finished.reason,
            collection=collected,
            long_diagnostic=finished.diagnostic,
            withheld_reason=finished.withheld_reason,
        )
        return
    try:
        with mapped.budget.stage() as stage:
            # Actual original frozen facts, including the owned CI read; never
            # substitute the selected packet's ledger for the concern-clearing proof.
            ci = mapped.ci.value() if mapped.ci is not None else None
            ci_facts = (
                ci_read.facts(ci, active.job.harness, active.job.sid) if ci is not None else []
            )
            stage.keep(ci_facts)
            on_a_check = (
                reading.lines_on_a_check(
                    finished.assessment,
                    chain(collected.evidence.facts if collected.evidence else (), ci_facts),
                )
                if finished.state == "resolved"
                else frozenset()
            )
            stage.keep(on_a_check)
            progress = deepcopy(finished.progress)
            progress["stage"] = "publication"
            progress["evidence"]["current"] = None
            stage.keep(progress)
        usage = mapped.budget.account.usage
        finished.diagnostic["source"]["usage"].update(
            io_bytes=usage.source_bytes,
            pages=usage.source_pages,
            retained_graph_peak_bytes=usage.retained_bytes,
            retained_graph_peak_units=usage.retained_units,
            prepare_ms=math.ceil(usage.prepare_ms),
        )
    except reading_preparation.LimitError as error:
        finish_withheld(
            application,
            started,
            error.reason,
            collection=collected,
            long_diagnostic=finished.diagnostic,
        )
        return
    control.publish_progress(
        config,
        active,
        progress,
        inspected=inspection.inspect(config, active.job.id, now=application.clock()),
    )
    if reading.seal_job(active.job):
        finish_withheld(
            application,
            started,
            "cancelled",
            collection=collected,
            long_diagnostic=finished.diagnostic,
        )
        return
    markers.seal(config, active.owner, state="completed", now=application.clock())
    result = finalize.completed(
        config,
        application.state,
        context=started.context,
        result=finished.result,
        assessment=finished.assessment,
        frozen=finished.frozen_context,
        long_diagnostic=finished.diagnostic,
        source_current=finished.source_current,
        now=application.clock(),
        on_a_check=on_a_check,
        diagnostic_sink=application.diagnostic_sink,
    )
    # A durable acknowledgment may outlive retirement failure. Never overwrite it
    # with a second outcome merely because cleanup did not finish.
    if not result.acknowledged:
        # Publication itself failed. Earlier reconciliation coverage is not the
        # cause of this latest outcome; derive its closed category afresh.
        diagnostic = deepcopy(finished.diagnostic)
        diagnostic.pop("stop_reason", None)
        finish_withheld(
            application,
            started,
            result.reason,
            collection=collected,
            long_diagnostic=diagnostic,
        )
        return
    reading.end_job(config, _key(started), expected_job=active.job)
    application.state.snapshot.clear()


def _run(
    application: Application,
    started: admission.Started,
    binary_resolver: Callable[[str], str | None],
) -> None:
    collection = None
    checkpoint = context_owner.Checkpoint(application.config, started.context)
    try:
        prepare_started = started.context.active.owner.live.prepared.clock()
        inputs = started.inputs
        if checkpoint(force=True):
            finish_withheld(application, started, checkpoint.reason)
            return
        collection = _collect(application, started, inputs, checkpoint, prepare_started)
        checkpoint(force=True)
        if checkpoint.reason or collection.reason or collection.snapshot is None:
            finish_withheld(
                application, started, checkpoint.reason or collection.reason, collection=collection
            )
            return
        mapped = worker.run_maps(
            application.config,
            started.context,
            started.inventory,
            collection,
            row=inputs["row"],
            revisions=inputs["entry"]["revisions"],
            clock=application.clock,
            binary_resolver=binary_resolver,
        )
        finished = reconcile.finish(
            application.config,
            started.context,
            started.inventory,
            collection,
            mapped,
            clock=application.clock,
            binary_resolver=binary_resolver,
            stamp_text=(
                f"{started.context.route.model} · read at "
                f"{time.strftime('%H:%M', time.localtime(application.clock()))}"
            ),
        )
        _completed(application, started, collection, mapped, finished)
    except Exception:  # noqa: BLE001 - thread failures retain durable accounting, never raw exception words
        finish_withheld(
            application, started, checkpoint.reason or "preparation-failed", collection=collection
        )


def launch(
    application: Application,
    started: admission.Started,
    *,
    binary_resolver: Callable[[str], str | None] = shutil.which,
) -> threading.Thread:
    """Start once from actual admission; thread-start failure finalizes before slot release."""
    thread = threading.Thread(
        target=_run, args=(application, started, binary_resolver), daemon=True
    )
    try:
        thread.start()
    except Exception:
        finish_withheld(application, started, "thread-unavailable")
        raise
    return thread
