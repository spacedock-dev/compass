"""Server-owned summary jobs, independent grants, durable markers and incremental saves.

The publication lock also guards revoke/delete/discard, so a reply returning after one of
those actions cannot recreate a summary. No source words enter a marker or the spend ledger.
See docs/design-session-summary.md#job-and-grant-contract.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import secrets
import shutil
import threading
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from . import io as runtime_io
from . import (
    observer,
    reading_jobs,
    reading_policy,
    reading_route,
    session_source,
    session_summary,
    summary_store,
    supervise,
)
from . import state as runtime_state

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from pathlib import Path

    from .config import RuntimeConfig

MARKER_DIR = "summary-jobs"
_LOCK = threading.RLock()
ACTIVE = {"running", "stopping"}
# A summary disclosure must not renew Analyze's notice when its content changes.
CONTENT_VERSION = 1


@dataclass
class Job:
    id: str
    harness: str
    sid: str
    started_at: float
    destination: str
    generation: int
    parts: int
    state: str = "running"
    part: int = 0
    reason: str = ""
    finished_parts: list[int] = field(default_factory=list)
    attempts: int = 0
    notice: reading_policy.Notice | None = None
    group: Any = None
    thread: threading.Thread | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "state": self.state,
            "part": self.part,
            "parts": self.parts,
            "reason": self.reason,
            "finished_parts": list(self.finished_parts),
            "attempts": self.attempts,
            "started_at": self.started_at,
            "notice": self.notice,
        }


def _key(harness: str, sid: str) -> str:
    return f"{harness}:{sid}"


def _marker(config: RuntimeConfig, harness: str, sid: str) -> Path:
    name = hashlib.sha256(_key(harness, sid).encode()).hexdigest()
    return config.state_dir / MARKER_DIR / f"{name}.json"


@contextlib.contextmanager
def _locked(application: reading_jobs.Application) -> Iterator[None]:
    with (
        _LOCK,
        runtime_io.held_file_lock(
            application.config.state_dir / "summary-jobs.lock",
            wait=application.config.summary_store_lock_wait_sec,
        ) as held,
    ):
        if held != runtime_io.LOCK_HELD:
            raise OSError("Summary publication lock unavailable")
        yield


def _write(application: reading_jobs.Application, job: Job) -> None:
    marker = {
        **job.as_dict(),
        "harness": job.harness,
        "sid": job.sid,
        "pid": os.getpid(),
        "destination": job.destination,
        "generation": job.generation,
    }
    runtime_io.atomic_write_owner_only(
        str(_marker(application.config, job.harness, job.sid)), json.dumps(marker)
    )


def _remember(application: reading_jobs.Application, job: Job) -> None:
    runtime_state.bounded_put(
        application.state.summary_jobs,
        _key(job.harness, job.sid),
        job,
        limit=application.config.max_cache_entries,
    )


def published(
    application: reading_jobs.Application, harness: str, sid: str
) -> dict[str, Any] | None:
    with _LOCK:
        job = application.state.summary_jobs.get(_key(harness, sid))
        return job.as_dict() if isinstance(job, Job) else None


def disclosure(destination: str) -> str:
    return (
        "Summaries send redacted session text in windows of at most 16 KiB: your words, "
        "text relayed in a person turn, the agent's replies, masked check titles with "
        "their per-check result words (failed, passed or not-recorded), and file-write "
        "display paths. Earlier phase titles provide context; cited entries are sent again "
        "for the lede. No tool output is sent: the source admits none. "
        "Sent through your Claude Code to "
        f"{destination or 'a destination Compass cannot name'}. "
        "Turn off summaries stops these calls; Turn summaries on restores them."
    )


def board(config: RuntimeConfig, *, now: float) -> dict[str, Any]:
    answer = reading_policy.summary_status(config, now=now)
    destination = reading_route.destination("claude")
    return {
        name: answer[name] for name in ("consent", "off", "used", "limit", "retry_at", "reason")
    } | {
        "notice_due": reading_policy.notice_due(
            answer,
            kind="summary",
            provider="claude",
            destination=destination,
            content=CONTENT_VERSION,
            tool_output="",
        ),
        "provider": "claude",
        "destination": destination,
        "disclosure": disclosure(destination),
        "notices": answer["notices"].get("summary", {}),
    }


def _refusal(reason: str, **extra: Any) -> tuple[int, dict[str, Any]]:
    code = (
        429
        if reason == "daily-cap"
        else 503
        if reason in {"run-disabled", "store-unavailable", "job-unrecorded", "no-thread"}
        else 403
        if reason == "summaries-off"
        else 422
    )
    return code, {"ok": False, "reason": reason, **extra}


def start(
    application: reading_jobs.Application,
    page: session_source.SourcePage,
    *,
    action: str,
    origin: str = "press",
    model: session_summary.Model | None = None,
    destination: str | None = None,
) -> tuple[int, dict[str, Any]]:
    config = application.config
    answer = reading_policy.summary_status(config, now=application.clock())
    if answer["reason"]:
        return _refusal(answer["reason"])
    if page.state != "ok" or page.coverage is None or page.snapshot is None:
        return _refusal("source-unavailable")
    prior = summary_store.get(config, page.harness, page.sid)
    if action == "update" and prior is None:
        return _refusal("no-summary")
    change = session_source.compare(prior.snapshot, page) if prior and action == "update" else None
    plan = session_summary.plan(
        page.entries,
        page.harness,
        config=config,
        prior=prior.summary if prior and change else None,
        change=change,
    )
    if plan.get("reason"):
        return _refusal(str(plan["reason"]), plan=plan, largest_read=plan.get("largest_read"))
    where = reading_route.destination("claude") if destination is None else destination
    try:
        return _admit(
            application,
            page,
            plan,
            where,
            prior if action == "update" else None,
            change,
            model,
            origin,
        )
    except (OSError, ValueError):
        return _refusal("job-unrecorded")


def _admit(
    application: reading_jobs.Application,
    page: session_source.SourcePage,
    plan: dict[str, Any],
    where: str,
    prior: summary_store.StoredSummary | None,
    change: session_source.SourceChange | None,
    model: session_summary.Model | None,
    origin: str,
) -> tuple[int, dict[str, Any]]:
    config = application.config
    with _locked(application):
        if origin == "open" and summary_store.get(config, page.harness, page.sid):
            return 409, {"ok": False, "reason": "summary-exists"}
        old = application.state.summary_jobs.get(_key(page.harness, page.sid))
        marker = _marker(config, page.harness, page.sid)
        if (isinstance(old, Job) and old.state in ACTIVE) or marker.exists():
            return 409, {
                "ok": False,
                "reason": "in-flight",
                "job": published(application, page.harness, page.sid),
            }
        answer = reading_policy.summary_status(config, now=application.clock())
        if answer["reason"]:
            return _refusal(answer["reason"])
        job = Job(
            secrets.token_hex(16),
            page.harness,
            page.sid,
            application.clock(),
            where,
            answer.get("generation", 0),
            int(plan["parts"]),
        )
        try:
            job.notice = reading_policy.note(
                config,
                kind="summary",
                provider="claude",
                destination=where,
                content=CONTENT_VERSION,
                tool_output="",
                now=application.clock(),
            )
        except reading_policy.RefusedError as exc:
            return _refusal(exc.answer["reason"])
        try:
            _write(application, job)
        except OSError:
            if job.notice is not None:
                reading_policy.retract(config, job.notice)
            raise
        _remember(application, job)
        started = job.as_dict()
    thread = threading.Thread(
        target=_run,
        args=(application, job, page, prior, change, model),
        name=f"compass-summary-{job.id}",
        daemon=True,
    )
    job.thread = thread
    try:
        thread.start()
    except RuntimeError:
        with _locked(application):
            job.state, job.reason = "refused", "no-thread"
            marker.unlink(missing_ok=True)
            if job.notice is not None:
                reading_policy.retract(config, job.notice)
        return _refusal("no-thread")
    # The notice is recorded before launch, so even a job that finishes before the response
    # leaves its first disclosure in this reply and in the published job.
    started["notice"] = job.notice
    return 202, {"ok": True, "job": started, **({"notice": job.notice} if job.notice else {})}


def _eligible(application: reading_jobs.Application, job: Job) -> str:
    marker = json.loads(
        _marker(application.config, job.harness, job.sid).read_text(encoding="utf-8")
    )
    if marker.get("reason"):
        return str(marker["reason"])
    answer = reading_policy.summary_status(application.config, now=application.clock())
    if answer["reason"] and answer["reason"] != "daily-cap":
        return answer["reason"]
    if answer.get("generation", 0) != job.generation:
        return "grant-changed"
    if reading_route.destination("claude") != job.destination:
        return "destination-changed"
    return job.reason


class GuardedSummaryModel:
    """Each actual attempt rechecks the grant and records one summary-only receipt."""

    def __init__(
        self, application: reading_jobs.Application, job: Job, model: session_summary.Model
    ) -> None:
        self.application, self.job, self.model = application, job, model

    def __call__(self, prompt: str, *, output_cap_bytes: int) -> tuple[str, str]:
        app, job = self.application, self.job
        with _locked(app):
            reason = _eligible(app, job)
            if reason:
                job.reason = reason
                raise reading_policy.RefusedError(
                    {**reading_policy.summary_status(app.config, now=app.clock()), "reason": reason}
                )
            if supervise.closed():
                job.reason = "stopping"
                return "", "closed"
            available = getattr(self.model, "available", None)
            if available is not None and not available():
                job.reason = "model-unavailable"
                return "", "unavailable"
            # The marker is durable before the atomic charge; a crash between them keeps a
            # job with zero attempts rather than losing a charged attempt.
            job.part = min(job.parts, len(job.finished_parts) + 1)
            _write(app, job)
            answer = reading_policy.reserve_summary(
                app.config, now=app.clock(), receipt=f"{job.id}:{job.attempts + 1}"
            )
            if answer["reason"]:
                job.reason = answer["reason"]
                raise reading_policy.RefusedError(answer)
            job.attempts += 1
            _write(app, job)
        _publish(app)
        text, status = self.model(prompt, output_cap_bytes=output_cap_bytes)
        # Admission already charged this attempt. A later local refusal cannot refund it in
        # the producer's spend while leaving the durable receipt charged.
        return text, "failed" if status in {"unavailable", "closed", "cancelled"} else status


class ClaudeSummaryModel:
    def __init__(self, application: reading_jobs.Application, job: Job) -> None:
        self.application, self.job = application, job

    def __call__(self, prompt: str, *, output_cap_bytes: int) -> tuple[str, str]:
        return observer.claude_exec(
            self.application.config,
            prompt,
            output_cap_bytes=output_cap_bytes,
            system_prompt=session_summary.SYSTEM_PROMPT,
            timeout=self.application.config.session_summary_call_timeout,
            on_spawn=self.spawned,
        )

    @staticmethod
    def available() -> bool:
        binary = shutil.which("claude")
        return bool(binary and os.path.isabs(binary))

    def spawned(self, group: supervise.Group) -> None:
        with _LOCK:
            self.job.group = group
            if self.job.reason:
                group.cancel()


def _save(
    application: reading_jobs.Application,
    job: Job,
    page: session_source.SourcePage,
    summary: session_summary.Summary,
    part: int,
    parts: int,
) -> None:
    with _locked(application):
        job.reason = _eligible(application, job)
        if job.reason:
            return
        job.parts = parts
        if part:
            if page.snapshot is None:
                raise ValueError("Summary has no source snapshot")
            outcome = summary_store.put(
                application.config,
                job.harness,
                job.sid,
                summary,
                page.snapshot,
                made_at=application.clock(),
                model_stamp=f"claude:{application.config.claude_reading_model}:"
                + hashlib.sha256(session_summary.SYSTEM_PROMPT.encode()).hexdigest(),
            )
            if outcome != "stored":
                job.reason = "store-" + outcome
            else:
                job.finished_parts.append(part)
        _write(application, job)
    _publish(application)


def _run(
    application: reading_jobs.Application,
    job: Job,
    page: session_source.SourcePage,
    prior: summary_store.StoredSummary | None,
    change: session_source.SourceChange | None,
    model: session_summary.Model | None,
) -> None:
    if page.coverage is None:
        return
    try:
        arguments: dict[str, Any] = {
            "config": application.config,
            "model": GuardedSummaryModel(
                application, job, model or ClaudeSummaryModel(application, job)
            ),
            "clock": time.monotonic,
            "on_part": lambda summary, part, parts: _save(
                application, job, page, summary, part, parts
            ),
        }
        if prior is not None and change is not None:
            result = session_summary.update(
                prior.summary, page.entries, page.coverage, change, **arguments
            )
        else:
            result = session_summary.summarize(
                page.entries, page.coverage, page.harness, **arguments
            )
        with _locked(application):
            job.reason = _eligible(application, job) or result.reason or ""
            job.state = (
                "cancelled"
                if job.reason in {"cancelled", "deleted", "discarded"}
                else "refused"
                if job.reason and not job.finished_parts
                else "partial"
                if job.reason or result.state != "ok"
                else "complete"
            )
    except Exception:  # noqa: BLE001 (the marker and completed parts survive any seam failure)
        job.state, job.reason = "interrupted", job.reason or "job-failed"
    finally:
        with contextlib.suppress(OSError), _locked(application):
            _marker(application.config, job.harness, job.sid).unlink(missing_ok=True)
        _publish(application)


def _publish(application: reading_jobs.Application) -> None:
    reading_jobs._publish(application)  # noqa: SLF001 (same snapshot/revision ordering as Analyze)


def _stop(application: reading_jobs.Application, harness: str, sid: str, reason: str) -> bool:
    job = application.state.summary_jobs.get(_key(harness, sid))
    path = _marker(application.config, harness, sid)
    if not path.exists():
        return False
    marker = json.loads(path.read_text(encoding="utf-8"))
    marker["reason"] = reason
    marker["state"] = "stopping"
    runtime_io.atomic_write_owner_only(str(path), json.dumps(marker))
    if isinstance(job, Job):
        job.reason, job.state = reason, "stopping"
        if job.group is not None:
            job.group.cancel()
    return True


def cancel(
    application: reading_jobs.Application, harness: str, sid: str, *, reason: str = "cancelled"
) -> bool:
    with _locked(application):
        accepted = _stop(application, harness, sid, reason)
    _publish(application)
    return accepted


def set_consent(application: reading_jobs.Application, allowed: bool) -> reading_policy.Status:
    with _locked(application):
        answer = reading_policy.set_summary_consent(
            application.config, allowed, now=application.clock()
        )
    _publish(application)
    return answer


def delete(application: reading_jobs.Application, harness: str, sid: str) -> str:
    with _locked(application):
        _stop(application, harness, sid, "deleted")
        outcome = summary_store.delete(application.config, harness, sid)
    _publish(application)
    return outcome


def recover(application: reading_jobs.Application, *, alive: Callable[[int], bool]) -> int:
    # Without markers there is nothing to recover, and taking the lock would
    # create `summary-jobs.lock` in a state directory nothing else has written.
    markers = application.config.state_dir / MARKER_DIR
    if not any(markers.glob("*.json")):
        return 0
    count = 0
    with _locked(application):
        for path in markers.glob("*.json"):
            try:
                marker = json.loads(path.read_text(encoding="utf-8"))
                current = application.state.summary_jobs.get(_key(marker["harness"], marker["sid"]))
                if (isinstance(current, Job) and current.state in ACTIVE) or (
                    marker["pid"] != os.getpid() and alive(marker["pid"])
                ):
                    continue
                job = Job(
                    marker["id"],
                    marker["harness"],
                    marker["sid"],
                    marker["started_at"],
                    marker["destination"],
                    marker["generation"],
                    marker["parts"],
                    state="interrupted",
                    part=marker["part"],
                    reason=marker["reason"] or "interrupted",
                    finished_parts=marker["finished_parts"],
                    attempts=max(
                        marker["attempts"],
                        reading_policy.summary_receipts(application.config, marker["id"]) or 0,
                    ),
                    notice=marker["notice"],
                )
                _remember(application, job)
                path.unlink()
                count += 1
            except (OSError, ValueError, KeyError, TypeError):
                continue
    return count
