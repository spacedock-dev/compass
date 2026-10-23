"""The Live monitor's lease: who holds it, how long, and what ends it.

[DEC-26](docs/design-reading-a-session.md#amended-2026-10-23-owner-the-live-level-comes-from-a-haiku-check)
puts the TTL clock on the server, and the owner stopped the monitor when the reader leaves the
session, hides the tab, or the session ends. This module holds that in memory only: a restart
starts with no lease and makes no check until a page starts one. One lease per Claude Code
session, held by any number of tabs, so two tabs spend no more than one. A small ticker thread
walks the leases every few seconds and calls the check for one that is due; it never reads a
transcript or builds a prompt itself, which `live_monitor.tick` does.

A tab beats about every 20 seconds while it shows the session. A visible tab that stops beating
is gone (`left`) after `live_monitor_lapse_sec`, with no stop post and no beacon. A tab that says
it is hidden keeps the lease alive without ticks, until the TTL deadline, so the checks resume
when it is visible again within the TTL and no check is made while nobody watches.

The lease state is published on the focused context's `sources.work`, never on a session row.
"""

from __future__ import annotations

import dataclasses
import threading
import time
from typing import TYPE_CHECKING, Any

from . import io as runtime_io
from . import live_monitor, reading_policy, reading_route, supervise

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping

    from .config import RuntimeConfig

HARNESS = "claude"
SAMPLE_SID = "sample"
# Why a lease ended, each shown to the reader with a note of its own.
END_REASONS = ("ended", "left", "paused", "unanswered", "declined", "stopped", "cap")
# What a refused start says, and the reasons a lapsed end can be told apart by.
_ENDED_KEPT = 256
# `live_monitor.tick` refusals that end the lease, and the end each one is.
_REFUSAL_ENDS = {
    "cap": "cap",
    "window-ended": "unanswered",
    "model-calls-paused": "paused",
    "run-disabled": "paused",
    "not-monitored": "stopped",
}


@dataclasses.dataclass(frozen=True)
class Inputs:
    """What one check reads: the transcript, the session's record, the saved goal, the estimate."""

    transcript_path: str
    facts: Iterable[Mapping[str, Any]]
    intent: str
    estimate: Mapping[str, Any]


@dataclasses.dataclass
class _Holder:
    last_beat: float
    hidden: bool = False


@dataclasses.dataclass
class _Lease:
    holders: dict[str, _Holder] = dataclasses.field(default_factory=dict)
    last_attempt: float | None = None


class Leases:
    """The lease table and its ticker. Constructed with everything ambient injected."""

    def __init__(  # noqa: PLR0913 - each seam is one thing a test or the assembly supplies
        self,
        config: RuntimeConfig,
        *,
        clock: Callable[[], float] = time.time,
        row_for: Callable[[str, str], Mapping[str, Any] | None],
        inputs_for: Callable[[str, str, Mapping[str, Any]], Inputs | None],
        tick: Callable[..., live_monitor.Tick] = live_monitor.tick,
        runner: Any = supervise.run,
        binary_resolver: Callable[[str], str | None] | None = None,
        diagnostic_sink: Callable[[str], None] = print,
        start_thread: bool = True,
    ) -> None:
        self.config = config
        self._clock = clock
        # The row as the board publishes it, which is after `_apply_overlays`: only that pass
        # writes `ended_at`, so a row read before it always reads None and a session that ended
        # would be monitored for ever (AGENTS.md, Measured Invariants).
        self._row_for = row_for
        self._inputs_for = inputs_for
        self._tick = tick
        self._runner = runner
        self._binary_resolver = binary_resolver
        self._diagnostic_sink = diagnostic_sink
        self._lock = threading.Lock()
        self._leases: dict[str, _Lease] = {}
        self._ended: dict[str, dict[str, Any]] = {}
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        # The ticker starts with the first lease and not before, so a board nobody monitors
        # runs no thread at all.
        self._may_run = start_thread

    # -- the reader's presses -------------------------------------------------------------

    def start(self, harness: str, sid: str, tab_id: str) -> dict[str, Any]:
        """Take or join the lease for one session, or say why not."""
        now = self._clock()
        key = f"{harness}:{sid}"
        refusal = self._start_refusal(harness, sid, now)
        if not refusal:
            with self._lock:
                self._sweep_locked(now)
                if key not in self._leases:
                    self._ended.pop(key, None)
                    self._leases[key] = _Lease()
                lease = self._leases[key]
                lease.holders[tab_id] = _Holder(last_beat=now)
                live_monitor.begin_window(self.config, key, now=now, holder=tab_id)
                self._ensure_ticker_locked()
        return self._answer(harness, sid, refusal)

    def beat(self, harness: str, sid: str, tab_id: str, *, visible: bool = True) -> dict[str, Any]:
        """A tab's heartbeat; `visible=False` says it is hidden, which keeps the lease only."""
        now = self._clock()
        key = f"{harness}:{sid}"
        with self._lock:
            self._sweep_locked(now)
            lease = self._leases.get(key)
            if lease is not None:
                lease.holders[tab_id] = _Holder(last_beat=now, hidden=not visible)
        return self._answer(harness, sid, "" if lease is not None else "not-monitoring")

    def confirm(self, harness: str, sid: str, tab_id: str, *, yes: bool) -> dict[str, Any]:
        """The reader's answer to "Do you still want to monitor this session?".

        Valid only while the question stands, so a second tab answering after the first has
        changes nothing. Yes resets the window; No ends the lease `declined`.
        """
        now = self._clock()
        key = f"{harness}:{sid}"
        refusal = ""
        with self._lock:
            self._sweep_locked(now)
            lease = self._leases.get(key)
            window = live_monitor.window(self.config, key) if lease is not None else None
            if lease is None or window is None:
                refusal = "not-monitoring"
            elif window["banner_due_at"] <= now < window["deadline"]:
                if yes:
                    live_monitor.begin_window(self.config, key, now=now, holder=tab_id, renew=True)
                    lease.holders[tab_id] = _Holder(last_beat=now)
                else:
                    self._end_locked(key, "declined", now)
        return self._answer(harness, sid, refusal)

    def stop(self, harness: str, sid: str, tab_id: str) -> dict[str, Any]:
        """A tab leaves. The monitor stops when the last tab has."""
        now = self._clock()
        key = f"{harness}:{sid}"
        with self._lock:
            self._sweep_locked(now)
            lease = self._leases.get(key)
            if lease is not None:
                lease.holders.pop(tab_id, None)
                if lease.holders:
                    live_monitor.end(self.config, key, holder=tab_id)
                else:
                    self._end_locked(key, "stopped", now)
        return self._answer(harness, sid, "")

    def stop_all(self, reason: str) -> int:
        """End every lease for `reason` and kill a check in flight; how many leases ended."""
        now = self._clock()
        with self._lock:
            keys = list(self._leases)
            for key in keys:
                self._end_locked(key, reason, now)
        live_monitor.cancel_all(self.config, "model-calls-paused" if reason == "paused" else reason)
        return len(keys)

    # -- what is published ----------------------------------------------------------------

    def state(self, harness: str, sid: str, *, ended: bool | None = None) -> dict[str, Any]:
        """The lease for one session as the page reads it.

        `ended` is the row's own end, read by a caller that has the row after the overlay pass:
        a session that has ended ends its lease `ended` here as well as on the next pass.
        """
        now = self._clock()
        key = f"{harness}:{sid}"
        with self._lock:
            self._sweep_locked(now)
            if ended and key in self._leases:
                self._end_locked(key, "ended", now)
        return self._state(harness, sid, now)

    def running(self) -> bool:
        """Whether the ticker thread is alive."""
        return self._thread is not None and self._thread.is_alive()

    def close(self) -> None:
        """Stop the ticker, end every lease and kill any check in flight. Safe to repeat."""
        self._stop.set()
        self.stop_all("stopped")
        thread = self._thread
        if thread is not None and thread is not threading.current_thread() and thread.is_alive():
            thread.join(timeout=5)

    # -- the ticker -----------------------------------------------------------------------

    def step(self) -> None:
        """One pass: lapse, end and pause what has to, and run the check of each lease due."""
        now = self._clock()
        with self._lock:
            self._sweep_locked(now)
            keys = list(self._leases)
        if not keys:
            return
        answer = reading_policy.monitor_status(self.config, now=now)
        for key in keys:
            self._step_one(key, now, answer["reason"])

    def _ensure_ticker_locked(self) -> None:
        if self._may_run and not self._stop.is_set() and self._thread is None:
            self._thread = threading.Thread(
                target=self._run, name="compass-live-monitor", daemon=True
            )
            self._thread.start()

    def _run(self) -> None:
        while not self._stop.wait(self.config.live_monitor_ticker_sec):
            try:
                self.step()
            except Exception as exc:  # noqa: BLE001 (the ticker outlives any one pass)
                runtime_io.diag(
                    f"Compass: the Live monitor ticker failed: {exc}", self._diagnostic_sink
                )

    def _step_one(self, key: str, now: float, status_reason: str) -> None:
        harness, _, sid = key.partition(":")
        row = self._row_for(harness, sid)
        if row is None or row.get("ended_at"):
            self._end(key, "ended", now)
            return
        if status_reason in {"model-calls-paused", "run-disabled"}:
            self._end(key, "paused", now)
            return
        with self._lock:
            lease = self._leases.get(key)
            if lease is None or not self._due_locked(lease, now):
                return
        try:
            inputs = self._inputs_for(harness, sid, row)
            if inputs is None:
                return
            result = self._tick(
                self.config,
                key,
                now=now,
                transcript_path=inputs.transcript_path,
                facts=inputs.facts,
                intent=inputs.intent,
                estimate=inputs.estimate,
                runner=self._runner,
                binary_resolver=self._binary_resolver,
            )
        except Exception as exc:  # noqa: BLE001 (one session's failure is not the board's)
            runtime_io.diag(f"Compass: a Live monitor check failed: {exc}", self._diagnostic_sink)
            with self._lock:
                held = self._leases.get(key)
                if held is lease:
                    held.last_attempt = now
            return
        self._settle(key, lease, result, now)

    def _settle(self, key: str, lease: _Lease, result: live_monitor.Tick, now: float) -> None:
        end = (
            _REFUSAL_ENDS.get(result.reason) if result.status in {"refused", "cancelled"} else None
        )
        with self._lock:
            if self._leases.get(key) is not lease:
                return
            if end is not None and result.reason != "stopped":
                self._end_locked(key, end, now)
            elif result.status in {"ran", "failed", "skipped", "cancelled"}:
                lease.last_attempt = now

    # -- the table, under the lock ----------------------------------------------------------

    def _due_locked(self, lease: _Lease, now: float) -> bool:
        seen = any(self._visible(holder, now) for holder in lease.holders.values())
        waited = (
            lease.last_attempt is None
            or now - lease.last_attempt >= self.config.live_monitor_interval_sec
        )
        return seen and waited

    def _visible(self, holder: _Holder, now: float) -> bool:
        return not holder.hidden and now - holder.last_beat <= self.config.live_monitor_lapse_sec

    def _sweep_locked(self, now: float) -> None:
        """Lapse the tabs that stopped beating and end what ran out of window or tabs."""
        for key in list(self._leases):
            lease = self._leases[key]
            for tab, holder in list(lease.holders.items()):
                if (
                    not holder.hidden
                    and now - holder.last_beat > self.config.live_monitor_lapse_sec
                ):
                    del lease.holders[tab]
                    live_monitor.end(self.config, key, holder=tab)
            if not lease.holders:
                self._end_locked(key, "left", now)
                continue
            window = live_monitor.window(self.config, key)
            if window is None or now >= window["deadline"]:
                self._end_locked(key, "unanswered", now)

    def _end(self, key: str, reason: str, now: float) -> None:
        with self._lock:
            self._end_locked(key, reason, now)

    def _end_locked(self, key: str, reason: str, now: float) -> None:
        if self._leases.pop(key, None) is None:
            return
        self._ended[key] = {"reason": reason, "at": now}
        while len(self._ended) > _ENDED_KEPT:
            del self._ended[next(iter(self._ended))]
        live_monitor.end(self.config, key)

    def _start_refusal(self, harness: str, sid: str, now: float) -> str:
        if self.config.model_calls_disabled:
            return "no-observer-model"
        if harness != HARNESS:
            return "unsupported-harness"
        if sid == SAMPLE_SID:
            return "sample"
        if reading_policy.monitor_status(self.config, now=now)["reason"] in {
            "model-calls-paused",
            "run-disabled",
        }:
            return "paused"
        row = self._row_for(harness, sid)
        if row is None:
            return "unknown-session"
        return "ended" if row.get("ended_at") else ""

    def _answer(self, harness: str, sid: str, refusal: str) -> dict[str, Any]:
        state = self._state(harness, sid, self._clock())
        reason = refusal or ""
        return {"ok": not refusal, "reason": reason, "state": state}

    def _state(self, harness: str, sid: str, now: float) -> dict[str, Any]:
        key = f"{harness}:{sid}"
        with self._lock:
            lease = self._leases.get(key)
            last_end = dict(self._ended[key]) if key in self._ended else None
            window = live_monitor.window(self.config, key) if lease is not None else None
            visible = lease is not None and any(
                self._visible(holder, now) for holder in lease.holders.values()
            )
        on = lease is not None and window is not None
        where = reading_route.destination(live_monitor.PROVIDER) if on else None
        banner_due = window["banner_due_at"] if window else None
        deadline = window["deadline"] if window else None
        return {
            "on": on,
            "started_at": window["started_at"] if window else None,
            "banner_due_at": banner_due,
            "deadline": deadline,
            # The question stands from the banner's due time to the deadline.
            "confirm_by": (
                deadline
                if on
                and banner_due is not None
                and deadline is not None
                and banner_due <= now < deadline
                else None
            ),
            "visible": visible,
            "last_end": last_end,
            "level": live_monitor.published(self.config, key) if on else None,
            "label": live_monitor.SOURCE,
            "destination": where,
            "disclosure": live_monitor.disclosure(where) if where is not None else None,
            "model": self.config.claude_monitor_model,
            "interval_sec": self.config.live_monitor_interval_sec,
            "now": now,
        }
