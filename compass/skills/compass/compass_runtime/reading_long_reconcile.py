"""One actual guarded final pass and qualified Assessment; no terminal publication."""

from __future__ import annotations

import hashlib
import math
import shutil
import time
from copy import deepcopy
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any

from . import (
    reading,
    reading_final_call,
    reading_long_context,
    reading_long_diagnostics,
    reading_long_execution,
    reading_long_inspection,
    reading_long_jobs,
    reading_long_markers,
    reading_long_worker,
    reading_native,
    reading_policy,
    reading_preparation,
    supervise,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from .config import RuntimeConfig
    from .reading_long_context import Context
    from .reading_pass_context import Frozen
    from .reading_source_collect import Collection, Snapshot, Usage
    from .reading_source_inventory import Inventory


@dataclass(frozen=True)
class Finished:
    state: str
    reason: str
    result: reading_final_call.Result | None
    assessment: reading.Assessment | None
    frozen_context: Frozen | None
    prompt_sha256: str | None
    prompt_bytes: int | None
    usage: Usage
    diagnostic: dict[str, Any]
    progress: dict[str, Any]
    source_current: Callable[[], bool]
    snapshot: Snapshot
    withheld_reason: str = ""


class _Final(reading_long_worker._Passes):  # noqa: SLF001 - shared registered pass mechanics
    prompt_sha256: str | None = None
    prompt_bytes: int | None = None
    responded = False

    def stop(self) -> str | None:
        if not self.responded:
            return super().stop()
        reason = reading_long_context.check_after_call(self.config, self.context)
        self.reason = self.reason or reason
        if reason == "cancelled":
            return "cancelled"
        if reason in {"job-deadline", "job-clock-invalid"}:
            return "job-deadline"
        return None  # Other actual causes remain latched; no Assessment can escape them.

    def observe(self, event: dict[str, Any]) -> bool:
        self.remember_failure(event["observation"])
        if self.reason:
            return False
        observation = event["observation"]
        diagnostic = observation["diagnostic"]
        if diagnostic["input"] is not None:
            self.responded = True
        if diagnostic["input"] is not None and not self.post_open:
            try:
                self.post.enter_context(self.budget.stage())
            except reading_preparation.LimitError as error:
                self.reason = error.reason
                return False
            self.post_open = True
            if diagnostic["input"]["outcome"] == "ok":
                job = self.context.active.job
                reading.advance_job(
                    self.config,
                    f"{job.harness}:{job.sid}",
                    reading.PHASE_CHECKING,
                    now=self.clock(),
                )
        ordinal = observation["ordinal"]
        self.staged[ordinal] = observation
        marker = reading_long_markers._owned(self.config, self.context.active.owner)  # noqa: SLF001
        if marker is None:
            self.reason = "persistence-unresolved"
            return False
        if any(slot["request"]["ordinal"] == ordinal for slot in marker["passes"]):
            method = reading_long_markers.settle if event["ended"] else reading_long_markers.observe
            if not method(
                self.config, self.context.active.owner, observation=observation, now=self.clock()
            ):
                self.reason = "persistence-unresolved"
                return False
        if event["ended"]:
            self.progress["reconciliation"]["state"] = "ended"
        return self.publish() if diagnostic["input"] is not None else True

    def model_for(self, ordinal: int) -> reading_policy.GuardedModel:
        if ordinal != self.budget.plan["max_calls"]:
            raise ValueError("Only the reserved final ordinal may run")
        if self.reason or self.source.current():
            reading_long_execution._refuse(self.reason or self.source.reason)  # noqa: SLF001
        with self.budget.stage():
            self.progress["reconciliation"]["state"] = "running"
            if not self.publish():
                reading_long_execution._refuse(self.reason)  # noqa: SLF001

        def reserved() -> None:
            with self.budget.stage():
                observation = self.staged.get(ordinal)
                if (
                    observation is None
                    or not reading_long_markers.observe(
                        self.config,
                        self.context.active.owner,
                        observation=observation,
                        now=self.clock(),
                    )
                    or not self.publish()
                ):
                    self.reason = "persistence-unresolved"
                    reading_long_execution._refuse(self.reason)  # noqa: SLF001

        self.current_model = reading_long_execution.guard(
            self.config,
            self.context,
            ordinal,
            clock=self.clock,
            runner=self.runner,
            binary_resolver=self.binary_resolver,
            on_reserved=reserved,
            source_current=lambda: not self.source.current(),
        )
        return self.current_model

    def invoke(self, mapped: reading_long_worker.Mapped) -> reading_final_call.Result:
        native, series = mapped.prepared, mapped.series
        if native is None or series is None:
            raise ValueError("A complete map preparation is required")
        with self.budget.stage() as stage:
            self.progress["stage"] = "reconciliation"
            self.progress["evidence"]["current"] = None
            if not self.publish():
                reading_long_execution._refuse(self.reason)  # noqa: SLF001

            def prepared(value: reading_final_call.Preparation) -> bool:
                stage.keep(value)
                if value.packet is not None:
                    encoded = value.packet.prompt.encode("utf-8")
                    self.prompt_sha256 = hashlib.sha256(encoded).hexdigest()
                    self.prompt_bytes = len(encoded)
                try:
                    stage.__exit__(None, None, None)
                except reading_preparation.LimitError as error:
                    self.reason = error.reason
                    return False
                return True

            return reading_final_call.run(
                native.originals,
                series,
                inputs=native.inputs,
                scope_floor=native.floor,
                final=native.final,
                plan=self.budget.plan,
                model_for=self.model_for,
                stop_reason=self.stop,
                detail_cap_chars=self.config.annotation_text_cap_chars,
                goal_cap_chars=self.config.annotation_goal_cap_chars,
                on_observation=self.observe,
                on_prepared=prepared,
            )


def _diagnostic(
    context: Context,
    inventory: Inventory,
    collection: Collection,
    mapped: reading_long_worker.Mapped,
    result: reading_final_call.Result | None,
    inspected: reading_long_inspection.Inspection,
    outcome: str,
) -> dict[str, Any]:
    header = reading_long_jobs.live_header(context.active.owner.live)
    if header is None:
        raise ValueError("Live final job is required")
    return reading_long_diagnostics.derive(
        plan=header["plan"],
        inventory=inventory,
        collection=collection,
        series=mapped.series,
        inspected=inspected,
        outcome=outcome,
        reconciliation_observations=[
            slot for slot in result.observations if slot["observation"]["kind"] == "reconciliation"
        ]
        if result is not None
        else None,
        binding=reading_long_diagnostics.bind_context(
            mapped.prepared.context, started_at=header["started_at"]
        )
        if mapped.prepared is not None
        else None,
    )


def finish(  # noqa: C901, PLR0912, PLR0913, PLR0915 - one closed final-call lifecycle
    config: RuntimeConfig,
    context: Context,
    inventory: Inventory,
    collection: Collection,
    mapped: reading_long_worker.Mapped,
    *,
    stamp_text: str,
    clock: Callable[[], float] = time.time,
    runner: Any = supervise.run,
    binary_resolver: Any = shutil.which,
) -> Finished:
    """Reuse the frozen map corpus once; return a publication candidate, never store it."""
    native, series, budget = mapped.prepared, mapped.series, mapped.budget
    source = reading_long_worker._Source(  # noqa: SLF001 - same source lineage, no new allowance
        config, context, replace(collection, snapshot=mapped.snapshot)
    )
    header = reading_long_jobs.live_header(context.active.owner.live)
    if header is None:
        raise ValueError("Live final job is required")
    reason = mapped.reason if mapped.state != "mapped" else ""
    if (
        mapped.job_id != context.active.job.id
        or collection.snapshot is None
        or collection.snapshot.account is not mapped.snapshot.account
        or (
            budget is not None
            and (budget.account is not mapped.snapshot.account or budget.plan != header["plan"])
        )
        or tuple(stream.cursor.frozen for stream in inventory.streams)
        != tuple(stream.frozen for stream in mapped.snapshot.streams)
    ):
        reason = "context-changed"
    if native is None or series is None or budget is None:
        reason = reason or "map-unavailable"
    result = None
    assessment = None
    final = None
    diagnostic = None
    progress = deepcopy(mapped.progress)
    try:
        if not reason and budget is not None:
            reason = source.current()
            final = _Final(config, context, source, budget, clock, runner, binary_resolver)
            final.progress = progress
            if not reason:
                result = final.invoke(mapped)
                reason = final.reason or ("" if result.criteria is not None else result.reason)
                # Capture.called already opened this stage after transport. Local
                # refusal paths open a bounded formatting stage without any wait.
                if not final.post_open:
                    final.post.enter_context(budget.stage())
                    final.post_open = True
                if not reason and native is not None and series is not None:
                    assessment = reading_native.assessment(
                        replace(native, usage=budget.account.usage),
                        series,
                        result,
                        now=clock(),
                        stamp_text=stamp_text,
                    )
                    if assessment is None:
                        reason = "assessment-unavailable"
                inspected = reading_long_inspection.inspect(
                    config, context.active.job.id, now=clock()
                )
                diagnostic = _diagnostic(
                    context,
                    inventory,
                    replace(collection, usage=budget.account.usage),
                    mapped,
                    result,
                    inspected,
                    "partial"
                    if assessment is not None and result.state == "partial"
                    else "completed"
                    if assessment is not None
                    else "withheld",
                )
                budget.roots.append((result, assessment, diagnostic))
    except reading_preparation.LimitError as error:
        reason = error.reason
    except reading_policy.RefusedError:
        reason = reason or "refused"
    finally:
        if final is not None:
            final.close_post()
            reason = reason or final.reason
    current_reason = source.current(after_call=True)
    reason = reason or current_reason
    if reason:
        assessment = None
    usage = mapped.snapshot.account.usage
    if diagnostic is None:
        # A closed resource gate still needs a bounded receipt/observation handoff;
        # this metadata cannot authorize another call or regain preparation room.
        diagnostic = _diagnostic(
            context,
            inventory,
            replace(collection, usage=usage),
            mapped,
            result,
            reading_long_inspection.inspect(config, context.active.job.id, now=clock()),
            "withheld",
        )
    # The last stage and source verification have now charged their elapsed work.
    # Refresh only these scalar measurements, not another evidence/formatting pass.
    diagnostic["source"]["usage"].update(
        io_bytes=usage.source_bytes,
        pages=usage.source_pages,
        retained_graph_peak_bytes=usage.retained_bytes,
        retained_graph_peak_units=usage.retained_units,
        prepare_ms=math.ceil(usage.prepare_ms),
    )
    if reason:
        diagnostic.update(
            outcome="cancelled" if reason == "cancelled" else "withheld", complete=False
        )
    cause = reading_long_diagnostics.stop_reason(
        reason or (result.reason if result is not None else mapped.reason),
        stage="reconciliation" if final is not None else "evidence",
    )
    if cause is not None:
        diagnostic["stop_reason"] = cause
    progress = deepcopy(final.progress if final is not None else progress)
    progress["source"].update(bytes_read=usage.source_bytes, pages_read=usage.source_pages)
    return Finished(
        result.state if assessment is not None and result is not None else "withheld",
        reason or (result.reason if result is not None else "map-unavailable"),
        result,
        assessment,
        native.context if native is not None else None,
        final.prompt_sha256 if final is not None else None,
        final.prompt_bytes if final is not None else None,
        usage,
        diagnostic,
        progress,
        source.short_current,
        source.snapshot,
        mapped.withheld_reason or (final.withheld_reason if final is not None else ""),
    )
