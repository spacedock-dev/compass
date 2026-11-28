"""Per-runtime Plan tracker refreshes. Only an admitted fetch can submit work."""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

from compass_runtime import supervise

from . import model, tracker_cli, tracker_github

if TYPE_CHECKING:
    import subprocess
    from collections.abc import Callable, Mapping

    from .tracker_source import Declaration, SourceKey

REFRESH_SECONDS = 8.0
FRESH_SECONDS = 30.0
ERROR_BACKOFF_SECONDS = 5.0
MAX_WORKERS = 4

TrackerData = model.TrackerData

type Adapter = Callable[[Declaration, tracker_cli.TrackerCLI], TrackerData]
_ADAPTERS: Mapping[str, Adapter] = MappingProxyType({"github": tracker_github.read})


@dataclass(frozen=True)
class Observation:
    data: TrackerData | None = None
    reason: tracker_cli.Reason | None = None
    observed_at: float | None = None


@dataclass(frozen=True)
class _Cached:
    observation: Observation
    valid_until: float


@dataclass
class _Flight:
    superseded: threading.Event
    group: supervise.Group | None = None


class TrackerRefresh:
    def __init__(
        self,
        *,
        adapters: Mapping[str, Adapter] | None = None,
        clock: Callable[[], float] = time.monotonic,
        environ: Mapping[str, str] | None = None,
        runner: Callable[..., subprocess.CompletedProcess[Any]] | None = None,
    ) -> None:
        self._adapters = _ADAPTERS if adapters is None else MappingProxyType(dict(adapters))
        self._clock = clock
        self._environment = tracker_cli.environment(os.environ if environ is None else environ)
        self._runner = runner
        # Keep the admitted settings load and its submission in the same order.
        self.settings_lock = threading.Lock()
        self._lock = threading.Lock()
        self._digest: str | None = None
        self._superseded = threading.Event()
        self._waiting: dict[SourceKey, Declaration] = {}
        self._active: dict[SourceKey, _Flight] = {}
        self._cache: dict[SourceKey, _Cached] = {}

    def invalidate(self) -> None:
        with self.settings_lock, self._lock:
            self._use_digest(None)

    def _use_digest(self, digest: str | None) -> None:
        if digest == self._digest:
            return
        previous = self._superseded
        previous.set()
        for flight in self._active.values():
            if flight.superseded is previous and flight.group is not None:
                flight.group.cancel()
        self._superseded = threading.Event()
        self._digest = digest
        self._waiting.clear()
        self._cache.clear()

    def observe(
        self,
        digest: str,
        sources: tuple[Declaration, ...],
        *,
        enabled: bool,
    ) -> tuple[Observation, ...]:
        """Return current measurements and submit cold or expired sources without waiting."""
        with self._lock:
            self._use_digest(digest if enabled and sources else None)
            now = self._clock()
            result = tuple(self._observe_source(source, enabled, now) for source in sources)
            self._start_waiting()
            return result

    def _observe_source(self, source: Declaration, enabled: bool, now: float) -> Observation:
        if not enabled or source.provider not in self._adapters:
            return Observation(reason=tracker_cli.Reason.DISABLED)
        key = source.key
        cached = self._cache.get(key)
        if cached is not None and now < cached.valid_until:
            return cached.observation
        self._cache.pop(key, None)
        active = self._active.get(key)
        if active is None or active.superseded.is_set():
            self._waiting.setdefault(key, source)
        return Observation(reason=tracker_cli.Reason.REFRESHING)

    def _start_waiting(self) -> None:
        if not self._waiting:
            return
        with supervise.admitting() as open_for_work:
            if not open_for_work:
                self._waiting.clear()
                return
            for key in tuple(self._waiting):
                if len(self._active) >= MAX_WORKERS:
                    break
                if key in self._active:
                    continue
                source = self._waiting.pop(key)
                flight = _Flight(self._superseded)
                self._active[key] = flight
                worker = threading.Thread(
                    target=self._refresh,
                    args=(source, flight, self._clock() + REFRESH_SECONDS),
                    name="compass-plan-tracker",
                    daemon=True,
                )
                try:
                    worker.start()
                except RuntimeError:
                    del self._active[key]
                    self._cache[key] = _Cached(
                        Observation(reason=tracker_cli.Reason.CLI_FAILED),
                        self._clock() + ERROR_BACKOFF_SECONDS,
                    )

    def _measure(self, source: Declaration, flight: _Flight, deadline: float) -> Observation:
        def check_current() -> None:
            # Also called inside supervise's launch lock. An Event check takes no runtime lock.
            if flight.superseded.is_set():
                raise tracker_cli.TrackerError(tracker_cli.Reason.DISABLED)

        def register(group: supervise.Group) -> None:
            with self._lock:
                flight.group = group
                if flight.superseded.is_set():
                    group.cancel()

        try:
            check_current()
            child = tracker_cli.TrackerCLI(
                source,
                deadline=deadline,
                clock=self._clock,
                environ=self._environment,
                runner=self._runner,
                check_current=check_current,
                on_spawn=register,
            )
            data = self._adapters[source.provider](source, child)
            now = self._clock()
            if now >= deadline:
                return Observation(reason=tracker_cli.Reason.TIMEOUT)
        except tracker_cli.TrackerError as exc:
            return Observation(reason=exc.reason)
        except Exception:  # noqa: BLE001 - adapter errors cannot leave a read permanently in flight
            return Observation(reason=tracker_cli.Reason.CLI_FAILED)
        return Observation(data=data, observed_at=now)

    def _refresh(self, source: Declaration, flight: _Flight, deadline: float) -> None:
        result = Observation(reason=tracker_cli.Reason.CLI_FAILED)
        try:
            result = self._measure(source, flight, deadline)
        finally:
            with self._lock:
                del self._active[source.key]
                if not flight.superseded.is_set():
                    valid_until = (
                        result.observed_at + FRESH_SECONDS
                        if result.observed_at is not None
                        else self._clock() + ERROR_BACKOFF_SECONDS
                    )
                    self._cache[source.key] = _Cached(result, valid_until)
                # A settings change drops the queue and a late result cannot restore its data.
                self._start_waiting()
