"""Per-runtime Plan tracker refreshes. Only an admitted fetch can submit work."""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

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
        self._lock = threading.Lock()
        self._digest: str | None = None
        self._superseded = threading.Event()
        self._waiting: dict[SourceKey, Declaration] = {}
        self._active: set[tuple[str, SourceKey]] = set()
        self._cache: dict[SourceKey, _Cached] = {}
        self._fetch_sequence = 0
        self._observed_sequence = 0

    def begin_fetch(self) -> int:
        # The settings load happens outside this lock. A slow old fetch cannot restore a setting
        # after a later fetch has observed a change.
        with self._lock:
            self._fetch_sequence += 1
            return self._fetch_sequence

    def invalidate(self) -> None:
        with self._lock:
            self._fetch_sequence += 1
            self._observed_sequence = self._fetch_sequence
            self._use_digest(None)

    def _use_digest(self, digest: str | None) -> None:
        if digest == self._digest:
            return
        self._superseded.set()
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
        fetch: int | None = None,
    ) -> tuple[Observation, ...]:
        """Return current measurements and submit cold or expired sources without waiting."""
        with self._lock:
            if fetch is not None:
                if fetch < self._observed_sequence:
                    reason = (
                        tracker_cli.Reason.REFRESHING if enabled else tracker_cli.Reason.DISABLED
                    )
                    return tuple(Observation(reason=reason) for _ in sources)
                self._observed_sequence = fetch
            self._use_digest(digest if enabled and sources else None)
            now = self._clock()
            result = tuple(self._observe_source(digest, source, enabled, now) for source in sources)
            self._start_waiting()
            return result

    def _observe_source(
        self, digest: str, source: Declaration, enabled: bool, now: float
    ) -> Observation:
        if not enabled or source.provider not in self._adapters:
            return Observation(reason=tracker_cli.Reason.DISABLED)
        key = source.key
        cached = self._cache.get(key)
        if cached is not None and now < cached.valid_until:
            return cached.observation
        self._cache.pop(key, None)
        if (digest, key) not in self._active:
            self._waiting.setdefault(key, source)
        return Observation(reason=tracker_cli.Reason.REFRESHING)

    def _start_waiting(self) -> None:
        digest = self._digest
        if digest is None:
            return
        while self._waiting and len(self._active) < MAX_WORKERS:
            key = next(iter(self._waiting))
            source = self._waiting.pop(key)
            flight = (digest, key)
            self._active.add(flight)
            worker = threading.Thread(
                target=self._refresh,
                args=(digest, source, self._superseded, self._clock() + REFRESH_SECONDS),
                name="compass-plan-tracker",
                daemon=True,
            )
            try:
                worker.start()
            except RuntimeError:
                self._active.remove(flight)
                self._cache[key] = _Cached(
                    Observation(reason=tracker_cli.Reason.CLI_FAILED),
                    self._clock() + ERROR_BACKOFF_SECONDS,
                )

    def _measure(
        self, source: Declaration, superseded: threading.Event, deadline: float
    ) -> Observation:
        def check_current() -> None:
            # Also called inside supervise's launch lock. An Event check takes no runtime lock.
            if superseded.is_set():
                raise tracker_cli.TrackerError(tracker_cli.Reason.DISABLED)

        try:
            check_current()
            child = tracker_cli.TrackerCLI(
                source,
                deadline=deadline,
                clock=self._clock,
                environ=self._environment,
                runner=self._runner,
                check_current=check_current,
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

    def _refresh(
        self, digest: str, source: Declaration, superseded: threading.Event, deadline: float
    ) -> None:
        result = Observation(reason=tracker_cli.Reason.CLI_FAILED)
        try:
            result = self._measure(source, superseded, deadline)
        finally:
            with self._lock:
                self._active.remove((digest, source.key))
                if not superseded.is_set():
                    valid_until = (
                        result.observed_at + FRESH_SECONDS
                        if result.observed_at is not None
                        else self._clock() + ERROR_BACKOFF_SECONDS
                    )
                    self._cache[source.key] = _Cached(result, valid_until)
                # A settings change drops the queue and a late result cannot restore its data.
                self._start_waiting()
