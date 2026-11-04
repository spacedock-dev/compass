"""Cumulative native preparation and graph reservations on the source's shared account."""

from __future__ import annotations

import math
import time
from dataclasses import replace
from typing import TYPE_CHECKING, Any, Self

from . import reading_pass_types, reading_source_collect

if TYPE_CHECKING:
    from collections.abc import Callable
    from types import TracebackType

    from .reading_passes import PacketPlan


class LimitError(Exception):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


class Budget:
    """Native preparation shares source time and retained-graph allowances.

    Stages exclude model waits. Roots remain reserved while the job may retain them;
    fresh wrappers and source revalidation consume the same private snapshot account.
    Unknown timing/measurement exhausts that account rather than inventing fresh room.
    """

    def __init__(
        self,
        snapshot: reading_source_collect.Snapshot,
        plan: dict[str, Any],
        *,
        clock: Callable[[], float] = time.perf_counter,
    ):
        if type(snapshot) is not reading_source_collect.Snapshot:
            raise ValueError("A source snapshot and frozen plan are required")
        self.account = snapshot.account
        self.clock = clock
        self.reason = ""
        self.roots: list[Any] = []
        self.extra_bytes = self.extra_units = self.reserved_bytes = self.reserved_units = 0
        self.active = False
        with self.stage() as stage:
            declared = reading_pass_types.validate_plan(plan)
            if declared is None:
                raise ValueError("A frozen plan is required")
            self.plan = declared
            stage.keep(declared)
            self.account.limits = replace(
                self.account.limits,
                **{
                    key: min(value, declared["limits"][key])
                    for key, value in vars(self.account.limits).items()
                },
            )

    def stage(self) -> _Stage:
        return _Stage(self)


def _exhausted(budget: Budget) -> str:
    usage, limits = budget.account.usage, budget.account.limits
    if usage.source_bytes > limits.source_bytes:
        return "source-bytes"
    if usage.source_pages > limits.source_pages:
        return "source-pages"
    if not math.isfinite(usage.prepare_ms) or usage.prepare_ms >= limits.prepare_ms:
        return "prepare-time"
    if max(usage.retained_bytes, budget.account.retained_base_bytes) > limits.retained_bytes:
        return "retained-bytes"
    if max(usage.retained_units, budget.account.retained_base_units) > limits.retained_units:
        return "retained-units"
    return ""


def _refuse(budget: Budget, reason: str) -> None:
    """Persist failed measurements in shared allowance, never only this wrapper."""
    if not reason:
        return
    budget.reason = budget.reason or reason
    account, limits = budget.account, budget.account.limits
    if reason == "retained-bytes":
        account.retained_base_bytes = max(account.retained_base_bytes, limits.retained_bytes + 1)
    elif reason == "retained-units":
        account.retained_base_units = max(account.retained_base_units, limits.retained_units + 1)
    elif reason in {
        "prepare-clock-invalid",
        "retained-unmeasurable",
        "source-bytes",
        "source-pages",
    }:
        # Close an inadmissible account without fabricating usage. In particular,
        # unchanged-source revalidation must not reopen a declaration already exceeded.
        account.limits = replace(limits, prepare_ms=0)


def _moment(value: float) -> bool:
    try:
        return type(value) in {int, float} and math.isfinite(value) and value >= 0
    except OverflowError:
        return False


class _Stage:
    def __init__(self, budget: Budget):
        self.budget = budget
        self.sealed = False
        self.started = 0.0

    def __enter__(self) -> Self:
        budget = self.budget
        if budget.active or self.sealed:
            raise ValueError("Preparation stages cannot overlap or reopen")
        if not budget.account.lock.acquire(blocking=False):
            raise ValueError("Source preparation is already active")
        try:
            reason = budget.reason or _exhausted(budget)
            if reason:
                raise LimitError(reason)
            try:
                self.started = budget.clock()
            except BaseException as error:
                _refuse(budget, "prepare-clock-invalid")
                if not isinstance(error, Exception):
                    raise
                raise LimitError(budget.reason) from error
            if not _moment(self.started):
                _refuse(budget, "prepare-clock-invalid")
                raise LimitError(budget.reason)
            budget.active = True
            return self
        finally:
            if not budget.active:
                self.sealed = True
                budget.account.lock.release()

    def keep(self, value: Any) -> None:
        if self.sealed or not self.budget.active:
            raise ValueError("Preparation stage is not open")
        self.budget.roots.append(value)

    def accept_plan(self, plan: PacketPlan) -> bool:
        """Reserve the real plan plus the callback copy; seal before any model wait."""
        self.keep(plan)
        try:
            size, units = reading_source_collect._measure(plan, self.budget.account.limits)  # noqa: SLF001
            self.budget.extra_bytes += size
            self.budget.extra_units += units
        except reading_source_collect._StopError as error:  # noqa: SLF001
            _refuse(self.budget, error.reason.replace("_", "-"))
        except BaseException as error:
            _refuse(self.budget, "retained-unmeasurable")
            if not isinstance(error, Exception):
                self._close()
                raise
        return not self._close()

    def _retain(self) -> None:
        budget, account = self.budget, self.budget.account
        size, units = reading_source_collect._measure(budget.roots, account.limits)  # noqa: SLF001
        size += budget.extra_bytes
        units += budget.extra_units
        added_bytes = max(0, size - budget.reserved_bytes)
        added_units = max(0, units - budget.reserved_units)
        if account.retained_base_bytes + added_bytes > account.limits.retained_bytes:
            _refuse(budget, "retained-bytes")
        elif account.retained_base_units + added_units > account.limits.retained_units:
            _refuse(budget, "retained-units")
        else:
            account.retained_base_bytes += added_bytes
            account.retained_base_units += added_units
            budget.reserved_bytes, budget.reserved_units = size, units
            account.usage = replace(
                account.usage,
                retained_bytes=max(account.usage.retained_bytes, account.retained_base_bytes),
                retained_units=max(account.usage.retained_units, account.retained_base_units),
            )

    def _elapsed(self) -> None:
        budget, account = self.budget, self.budget.account
        try:
            ended = budget.clock()
        except BaseException as error:
            _refuse(budget, "prepare-clock-invalid")
            if not isinstance(error, Exception):
                raise
            return
        if not _moment(ended) or ended < self.started:
            _refuse(budget, "prepare-clock-invalid")
        else:
            elapsed = (ended - self.started) * 1000
            if not math.isfinite(elapsed):
                _refuse(budget, "prepare-clock-invalid")
                return
            account.usage = replace(
                account.usage,
                prepare_ms=account.usage.prepare_ms + elapsed,
            )

    def _close(self) -> str:
        if self.sealed:
            return self.budget.reason
        budget = self.budget
        try:
            try:
                self._retain()
            except reading_source_collect._StopError as error:  # noqa: SLF001
                _refuse(budget, error.reason.replace("_", "-"))
            except BaseException as error:
                _refuse(budget, "retained-unmeasurable")
                if not isinstance(error, Exception):
                    raise
            finally:
                self._elapsed()
            _refuse(budget, _exhausted(budget))
            return budget.reason
        finally:
            self.sealed = True
            budget.active = False
            budget.account.lock.release()

    def __exit__(
        self,
        kind: type[BaseException] | None,
        value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self.sealed:
            return
        reason = self._close()
        if reason and kind is None:
            raise LimitError(reason)
