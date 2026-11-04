"""Registered native evidence worker; no final call, job settlement or publication."""

from __future__ import annotations

import math
import shutil
import time
from contextlib import ExitStack
from copy import deepcopy
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from . import annotations as annotation_store
from . import (
    reading,
    reading_ci_acquire,
    reading_long_context,
    reading_long_control,
    reading_long_execution,
    reading_long_inspection,
    reading_long_jobs,
    reading_long_markers,
    reading_long_progress,
    reading_map_series,
    reading_native,
    reading_policy,
    reading_preparation,
    reading_source_collect,
    supervise,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

    from .config import RuntimeConfig
    from .reading_passes import PacketPlan
    from .reading_source_inventory import Inventory


@dataclass(frozen=True)
class Mapped:
    state: str
    reason: str
    prepared: reading_native.Prepared | None
    series: reading_map_series.Series | None
    ci: reading_ci_acquire.Result | None
    usage: reading_source_collect.Usage
    progress: dict[str, Any]
    source_current: Callable[[], bool]
    snapshot: reading_source_collect.Snapshot
    budget: reading_preparation.Budget | None
    job_id: str


class _Source:
    def __init__(
        self,
        config: RuntimeConfig,
        context: reading_long_context.Context,
        collection: reading_source_collect.Collection,
    ):
        if collection.snapshot is None:
            raise ValueError("A verified snapshot is required")
        self.config, self.context, self.snapshot = config, context, collection.snapshot
        self.final_required = (collection.final or {}).get("outcome") == "whole"
        self.reason = ""
        self.checkpoint = reading_long_context.Checkpoint(config, context)

    def current(self) -> str:
        if self.reason:
            return self.reason
        self.checkpoint(force=True)
        reason = self.checkpoint.reason
        if not reason:
            checked = reading_source_collect.revalidate(self.snapshot, cancelled=self.checkpoint)
            if self.checkpoint.reason:
                reason = self.checkpoint.reason
            elif checked.snapshot is None:
                reason = "source-changed"
            elif self.final_required and not checked.final_valid:
                reason = "source-final-changed"
            else:
                self.snapshot = checked.snapshot
                self.checkpoint(force=True)
                reason = self.checkpoint.reason
        self.reason = reason
        return reason

    def short_current(self) -> bool:
        """Only a stamp predicate for a future finalizer's short publication section."""
        try:
            return not self.reason and all(
                reading_source_collect._snapshot_stamp(stream) == stream.stamp  # noqa: SLF001
                for stream in self.snapshot.streams
            )
        except (OSError, ValueError):
            return False


class _Passes:
    def __init__(
        self,
        config: RuntimeConfig,
        context: reading_long_context.Context,
        source: _Source,
        budget: reading_preparation.Budget,
        clock: Callable[[], float],
        runner: Any,
        binary_resolver: Any,
    ):
        self.config, self.context, self.source, self.budget = config, context, source, budget
        self.clock, self.runner, self.binary_resolver = clock, runner, binary_resolver
        self.progress = reading_long_progress.initial(budget.plan)
        self.staged: dict[int, dict[str, Any]] = {}
        self.reason = ""
        self.post = ExitStack()
        self.post_open = False

    def close_post(self) -> None:
        try:
            self.post.close()
        except reading_preparation.LimitError as error:
            self.reason = error.reason
        finally:
            self.post_open = False

    def publish(self) -> bool:
        usage = self.budget.account.usage
        self.progress["source"] = {
            "streams_total": len(self.source.snapshot.streams),
            "streams_verified": len(self.source.snapshot.streams),
            "bytes_read": usage.source_bytes,
            "pages_read": usage.source_pages,
        }
        inspected = reading_long_inspection.inspect(
            self.config, self.context.active.job.id, now=self.clock()
        )
        if reading.job_cancelled(self.context.active.job):
            # The UI owner deliberately freezes cancelled-job progress. This does
            # not prevent settling the already charged pass's real observation.
            return True
        if not reading_long_control.publish_progress(
            self.config, self.context.active, self.progress, inspected=inspected
        ):
            self.reason = "persistence-unresolved"
            return False
        self.progress = deepcopy(
            reading.published_jobs(self.config)[
                f"{self.context.active.job.harness}:{self.context.active.job.sid}"
            ]["progress"]
        )
        return True

    def observe(self, event: dict[str, Any]) -> bool:
        if self.reason:
            return False
        observation = event["observation"]
        ordinal = observation["ordinal"]
        # This emission occurs after the model returns, before parsing/indexing.
        # Keep its stage open through that work; close before the next source read.
        if observation["diagnostic"]["input"] is not None and not self.post_open:
            try:
                self.post.enter_context(self.budget.stage())
            except reading_preparation.LimitError as error:
                self.reason = error.reason
                return False
            self.post_open = True
        self.staged[ordinal] = observation
        marker = reading_long_markers._owned(self.config, self.context.active.owner)  # noqa: SLF001
        if marker is None:
            self.reason = "persistence-unresolved"
            return False
        if not any(slot["request"]["ordinal"] == ordinal for slot in marker["passes"]):
            accepted = True
            if event["ended"]:
                # An invoked-but-uncharged refusal ends its evidence position,
                # not a receipt. Do not try further positions against that refusal.
                self.progress["evidence"].update(ended=ordinal, current=None)
                accepted = self.publish()
                self.reason = self.reason or "refused"
            return accepted  # No marker slot exists before its fresh reservation.
        method = reading_long_markers.settle if event["ended"] else reading_long_markers.observe
        if not method(
            self.config, self.context.active.owner, observation=observation, now=self.clock()
        ):
            self.reason = "persistence-unresolved"
            return False
        if event["ended"]:
            self.progress["evidence"].update(ended=ordinal, current=None)
        return self.publish()

    def model_for(self, ordinal: int) -> reading_policy.GuardedModel:
        self.close_post()
        if self.reason or self.source.current():
            reading_long_execution._refuse(self.reason or self.source.reason)  # noqa: SLF001
        with self.budget.stage():
            self.progress["evidence"]["current"] = ordinal
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

        def spawned() -> None:
            job = self.context.active.job
            if job.phase == reading.PHASE_PREPARING:
                reading.advance_job(
                    self.config, f"{job.harness}:{job.sid}", reading.PHASE_WAITING, now=self.clock()
                )

        return reading_long_execution.guard(
            self.config,
            self.context,
            ordinal,
            clock=self.clock,
            runner=self.runner,
            binary_resolver=self.binary_resolver,
            on_reserved=reserved,
            source_current=lambda: not self.source.current(),
            on_spawn=spawned,
        )

    def stop(self) -> str | None:
        if reading.job_cancelled(self.context.active.job):
            return "cancelled"
        if reading_long_jobs.deadline_reason(
            self.context.active.owner.live, self.budget.plan["limits"]["job_ms"]
        ):
            return "job-deadline"
        return None

    def maps(self, prepared: reading_native.Prepared) -> reading_map_series.Series:
        with self.budget.stage() as stage:
            stage.keep(self.staged)

            def planned(plan: PacketPlan) -> bool:
                accepted = stage.accept_plan(plan)
                with self.budget.stage():
                    self.progress["stage"] = "evidence"
                    self.progress["evidence"]["planned"] = len(plan.packets)
                    published = self.publish()
                if plan.uncovered_primary or plan.reason != "complete":
                    self.reason = plan.reason
                    return False
                return accepted and published

            lines = reading.outcome_lines(prepared.inputs.revision)
            try:
                result = reading_map_series.run(
                    prepared.originals,
                    goal=str(prepared.inputs.revision["goal"]),
                    lines=lines,
                    clauses=("goal", *(f"line_{n}" for n in range(1, len(lines) + 1))),
                    plan=self.budget.plan,
                    model_for=self.model_for,
                    stop_reason=self.stop,
                    on_observation=self.observe,
                    frozen_context=prepared.context,
                    final=prepared.final,
                    on_plan=planned,
                    masked_values=prepared.inputs.tool_output.masked_values
                    if prepared.inputs.tool_output
                    else (),
                    scrub_partial=prepared.inputs.tool_output.masked_values_partial
                    if prepared.inputs.tool_output
                    else False,
                )
            finally:
                self.close_post()
        try:
            with self.budget.stage() as retain:
                retain.keep(result)
        except reading_preparation.LimitError as error:
            self.reason = error.reason
        return result


def _input_reason(
    config: RuntimeConfig,
    context: reading_long_context.Context,
    inventory: Inventory,
    collection: reading_source_collect.Collection,
    row: Mapping[str, Any],
    revisions: Sequence[Mapping[str, Any]],
    header: dict[str, Any],
    snapshot: reading_source_collect.Snapshot,
) -> str:
    reason = ""
    publication = header.get("publication", {})
    entry = annotation_store.find(
        annotation_store.load(config), str(row.get("harness")), str(row.get("sid"))
    )
    if (
        not revisions
        or entry is None
        or tuple(entry["revisions"]) != tuple(revisions)
        or (row.get("harness"), row.get("sid"), revisions[-1].get("n"))
        != (publication.get("harness"), publication.get("sid"), publication.get("revision"))
        or tuple(stream.cursor.frozen for stream in inventory.streams)
        != tuple(stream.frozen for stream in snapshot.streams)
    ):
        reason = "context-changed"
    goal = row.get("session_goal")
    goals = tuple(
        dict.fromkeys(
            text
            for text in (
                str(goal.get("text") or "") if isinstance(goal, dict) else "",
                str(revisions[-1].get("goal") or "") if revisions else "",
            )
            if text
        )
    )
    if context.route.ci_read == "on" and (
        collection.current_ci is None
        or tuple(dict.fromkeys(text for text in collection.current_ci.goal_texts if text)) != goals
    ):
        reason = "ci-context-unavailable"
    return reason


def run_maps(  # noqa: C901, PLR0912, PLR0913, PLR0915 - ordered fail-closed worker stages
    config: RuntimeConfig,
    context: reading_long_context.Context,
    inventory: Inventory,
    collection: reading_source_collect.Collection,
    *,
    row: Mapping[str, Any],
    revisions: Sequence[Mapping[str, Any]],
    clock: Callable[[], float] = time.time,
    runner: Any = supervise.run,
    ci_runner: Any = supervise.run,
    binary_resolver: Any = shutil.which,
    environ: Mapping[str, str] | None = None,
) -> Mapped:
    """Execute evidence only; a mapped result is never an assessment or completeness claim."""
    header = reading_long_jobs.live_header(context.active.owner.live)
    if header is None or collection.snapshot is None:
        raise ValueError("A live job and source snapshot are required")
    source = _Source(config, context, collection)
    try:
        budget = reading_preparation.Budget(collection.snapshot, header["plan"])
    except reading_preparation.LimitError as error:
        source.reason = error.reason
        return Mapped(
            "withheld",
            error.reason,
            None,
            None,
            None,
            collection.snapshot.account.usage,
            reading_long_progress.initial(header["plan"]),
            source.short_current,
            collection.snapshot,
            None,
            context.active.job.id,
        )
    passes = _Passes(config, context, source, budget, clock, runner, binary_resolver)
    ci = None
    prepared = None
    series = None
    reason = ""

    def remaining() -> float:
        job = context.active.owner.live.prepared
        elapsed = job.clock() - job.started_monotonic
        return (
            header["plan"]["limits"]["job_ms"] / 1000 - elapsed
            if math.isfinite(elapsed) and elapsed >= 0
            else 0
        )

    def ci_spawn(group: supervise.Group) -> None:
        if reading.hand_over(context.active.job, group):
            group.cancel()

    try:
        with budget.stage():
            reason = _input_reason(
                config, context, inventory, collection, row, revisions, header, collection.snapshot
            )
        reason = reason or source.current()
        if not reason and context.route.ci_read == "on":
            ci = reading_ci_acquire.acquire(
                config,
                collection,
                budget,
                current=source.current,
                cancelled=lambda: reading.job_cancelled(context.active.job),
                remaining_seconds=remaining,
                on_spawn=ci_spawn,
                now=clock(),
                environ=environ,
                runner=ci_runner,
            )
            if ci.state != "complete" and not reading_native.ci_not_applicable(collection, ci):
                reason = source.reason or ci.reason or "ci-context-unavailable"
        if not reason:
            route = context.route
            preparation = reading_native.prepare_calls(
                config,
                row,
                revisions,
                collection,
                {
                    "harness": route.harness,
                    "provider": route.provider,
                    "destination": route.tool_destination,
                    "label": context.active.job.label,
                    "ci_read": route.ci_read,
                },
                plan=header["plan"],
                now=clock(),
                ci_result=ci,
            )
            prepared, reason = preparation.prepared, preparation.reason
            if preparation.budget is not None:
                budget = preparation.budget
                passes.budget = budget
            if prepared is not None:
                if prepared.context.value()["safety"]["gaps"]:
                    reason = "context-unavailable"
                else:
                    series = passes.maps(prepared)
                    reason = (
                        passes.reason
                        or source.reason
                        or ("" if series.reason == "passes-ended" else series.reason)
                    )
    except reading_preparation.LimitError as error:
        reason = error.reason
    finally:
        passes.close_post()
    reason = reason or passes.reason or budget.reason or source.current()
    if not budget.reason:
        try:
            with budget.stage():
                if not passes.publish():
                    reason = reason or passes.reason
        except reading_preparation.LimitError as error:
            reason = reason or error.reason
    return Mapped(
        "withheld" if reason else "mapped",
        reason,
        prepared,
        series,
        ci,
        budget.account.usage,
        deepcopy(passes.progress),
        source.short_current,
        source.snapshot,
        budget,
        context.active.job.id,
    )
