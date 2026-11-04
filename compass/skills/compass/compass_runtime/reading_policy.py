"""Remembered reading permission and durable, atomic rolling spend admission.

The transaction is the bound on concurrent tabs and daemons, not the browser's
button state. No session identities or content enter this store.
See [DEC-21](docs/design-reading-a-session.md#dec-21-a-reading-works-the-first-time-you-ask).
"""

from __future__ import annotations

import contextlib
import json
import math
import os
import time
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, NotRequired, Protocol, TypedDict, cast

from . import analyze_diagnostics, reading_long_jobs, supervise
from . import io as runtime_io

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping
    from pathlib import Path

    from .config import RuntimeConfig

DAY_SEC = 86_400.0
DAILY_CAP = 100
# How long the job ledger keeps the id each charge was made for (DRC-4713).
# Far past `DAY_SEC`, because the budget reads only `spends`: a restart more
# than a day after a crash must still find the row, or it would call a charged
# attempt uncharged. A marker older than this is answered "cannot say".
JOB_LEDGER_SEC = 30 * DAY_SEC
# One answer per receiver (DRC-4650): allowing Codex to send a reader's words
# to OpenAI is not allowing Claude Code to send them to Anthropic. Codex keeps
# the original single-row table, so an answer saved before there were two
# providers reads as the Codex answer it was, and an older build reading this
# store still sees it. Every other provider has a row in its own table.
PROVIDERS = ("codex", "claude")
LEGACY_PROVIDER = "codex"
_SQL_ERROR = getattr(runtime_io.sqlite_module, "Error", RuntimeError)
# How long a write waits behind other processes' writes before it is refused
# as store-unavailable. Every write holds the lock for one short transaction,
# so the wait is the length of the queue, and a slow disk lengthens every place
# in it. At 2 s, three of 24 reservations from four processes were refused on a
# Windows runner while under the cap (DRC-4707), and a reader sees that as a
# refused Analyze. A read for the board keeps the short wait, so a collect does
# not stall behind a queue of presses.
WRITE_WAIT_SEC = 10.0
READ_WAIT_SEC = 2.0
# The line the consent step opens with when an Allow is on record that does
# not cover today's destination: one written before the binding, or one given
# while the words went somewhere else (owner, 2026-10-02). The server's words,
# so the page never composes a claim about what the store holds.
DESTINATION_CHANGED = "Where your words go has changed since you allowed this, so allow it again."
# The reason a job's reservation is refused when the destination moved after
# the press was admitted: the token the press answers `409` with.
DESTINATION_MOVED = "destination-changed"
# The content epoch serves both notices and legacy explicit coverage. Epoch 2 added agent
# messages, 3 added the newest final reply whole within 4,096 bytes, and 4 repaired the
# ambiguity of a version-3 Allow written from a narrower harness disclosure. Words-only
# routes and the unasked lane retain epoch 1. Epoch 5 widens requested person messages;
# epoch 6 also widens requested agent messages. Reader-started calls renew the notice when
# the epoch changes; Codex unasked calls retain the explicit coverage boundary.
CONTENT_VERSION = 6
# Wider requested person messages renew consent without widening the unasked lane.
REQUESTED_WORDS_CONTENT_VERSION = 5
WORDS_CONTENT_VERSION = 1
NOTICE_KINDS = ("reading", "goal", "summary", "monitor")
CONTENT_CHANGED = "What a reading sends has changed since you allowed this, so allow it again."


@dataclass(frozen=True)
class LongPermission:
    """A long job's permission snapshot, independent of content and Summary epochs."""

    lineage: str
    epoch: int


def _valid_long_permission(value: Any) -> bool:
    return (
        type(value) is LongPermission
        and isinstance(value.lineage, str)
        and len(value.lineage) == 32
        and all(char in "0123456789abcdef" for char in value.lineage)
        and type(value.epoch) is int
        and 0 <= value.epoch < 2**63
    )


def _long_permission_schema(db: Any) -> LongPermission:
    db.execute(
        "CREATE TABLE IF NOT EXISTS long_permission "
        "(id INTEGER PRIMARY KEY CHECK(id=1), lineage TEXT NOT NULL, epoch INTEGER NOT NULL)"
    )
    db.execute(
        "INSERT OR IGNORE INTO long_permission (id, lineage, epoch) VALUES (1, ?, 0)",
        (uuid.uuid4().hex,),
    )
    for table in ("permission", "provider_permission"):
        for event in ("INSERT", "UPDATE"):
            # These fire in older builds too. As with `_off`, a zero beside an
            # Allow is not a global pause; Summary's own switch is independent.
            db.execute(
                f"CREATE TRIGGER IF NOT EXISTS long_permission_off_{table}_{event.lower()} "  # noqa: S608 - fixed identifiers
                f"AFTER {event} ON {table} WHEN NEW.allowed = 0 "
                "AND NOT EXISTS (SELECT 1 FROM permission WHERE allowed = 1) "
                "AND NOT EXISTS (SELECT 1 FROM provider_permission WHERE allowed = 1) "
                "BEGIN UPDATE long_permission SET epoch = epoch + 1 WHERE id = 1; END"
            )
    row = db.execute("SELECT lineage, epoch FROM long_permission WHERE id=1").fetchone()
    token = LongPermission(*row)
    if not _valid_long_permission(token):
        raise ValueError("Invalid long-reading permission lineage")
    return token


class Notice(TypedDict):
    kind: str
    provider: str
    destination: str
    content: int
    tool_output: str
    at: float


class Status(TypedDict):
    generation: NotRequired[int]
    consent: bool
    off: bool
    notices: dict[str, dict[str, Notice]]
    used: int
    limit: int
    retry_at: float | None
    reason: str
    # Which receivers an Allow covers today, so the page can tell whether the
    # provider its route names still needs one. An Allow covers a provider only
    # while its destination is the one the Allow was given for (owner,
    # 2026-10-02). Reader admission no longer depends on this legacy coverage.
    providers: dict[str, bool]
    # Provider to `DESTINATION_CHANGED`, for each Allow on record that does not
    # cover today's destination. Never for a refusal, which holds anywhere.
    rebind: dict[str, str]
    # The tool-output grants, provider to the destinations the reader allowed
    # it to reach, item 7 of the ruling `reading.build_ledger` cites.
    # Its own table: no answer in the two above is
    # ever read as one, so an Allow given before tool output was named cannot
    # cover it, and a destination that moves is asked about again.
    tool_output: dict[str, list[str]]
    # The same answer as `providers` for a press that carries no agent words,
    # read at `WORDS_CONTENT_VERSION`: what the page reads for a session on a
    # harness the agent's messages are never read from.
    words: dict[str, bool]


PERMISSION_TABLES = frozenset({"permission", "provider_permission"})


@dataclass(frozen=True)
class LongReservation:
    """Only a fresh reservation authorizes launch; charge evidence is True or unknown."""

    outcome: str
    status: Status
    charged: bool | None = None

    @property
    def launch(self) -> bool:
        return self.outcome == "reserved"


@dataclass(frozen=True)
class LongRegistration:
    outcome: str
    status: Status
    live: reading_long_jobs.LiveJob | None = None

    @property
    def launch(self) -> bool:
        return False


_PASS_REQUEST_FIELDS = frozenset(
    {
        "version",
        "job_id",
        "started_at",
        "ordinal",
        "kind",
        "max_evidence_passes",
        "plan_sha256",
        "prompt_sha256",
        "prompt_bytes",
        "destination_sha256",
        "provider",
        "content",
    }
)


def _hex(value: Any, size: int) -> bool:
    return (
        isinstance(value, str)
        and len(value) == size
        and all(c in "0123456789abcdef" for c in value)
    )


def _pass_request(value: Any, now: float) -> dict[str, Any] | None:
    if not isinstance(value, dict) or set(value) != _PASS_REQUEST_FIELDS:
        return None
    if (
        any(
            type(value[key]) is not int
            for key in (
                "version",
                "ordinal",
                "max_evidence_passes",
                "prompt_bytes",
                "content",
            )
        )
        or value["version"] != 1
        or not 1 <= value["max_evidence_passes"] <= 16
        or not 1 <= value["ordinal"] <= value["max_evidence_passes"] + 1
        or not 0 < value["prompt_bytes"] < 2**53
        or value["content"] not in (REQUESTED_WORDS_CONTENT_VERSION, CONTENT_VERSION)
        or value["provider"] not in PROVIDERS
        or not _hex(value["job_id"], 32)
        or not all(
            _hex(value[key], 64)
            for key in (
                "plan_sha256",
                "prompt_sha256",
                "destination_sha256",
            )
        )
        or type(value["started_at"]) not in (int, float)
        or not math.isfinite(value["started_at"])
        or not 0 < value["started_at"] <= now
    ):
        return None
    kind = "reconciliation" if value["ordinal"] == value["max_evidence_passes"] + 1 else "evidence"
    return dict(value) if value["kind"] == kind else None


def _pass_ledger(db: Any, now: float) -> float:
    """Keep absence conservative after pruning, SQL deletion or a missing table."""
    columns = {row[1] for row in db.execute("PRAGMA table_info(long_permission)")}
    if "pass_ledger_since" not in columns:
        db.execute("ALTER TABLE long_permission ADD COLUMN pass_ledger_since REAL")
    since = db.execute("SELECT pass_ledger_since FROM long_permission WHERE id=1").fetchone()[0]
    if since is None:
        # Not IF NOT EXISTS: an orphaned ledger is uncertainty, not a new ledger.
        db.execute(
            "CREATE TABLE long_pass_reservations (job TEXT NOT NULL, ordinal INTEGER NOT NULL, "
            "binding TEXT NOT NULL, at REAL NOT NULL, PRIMARY KEY(job, ordinal))"
        )
        db.execute("UPDATE long_permission SET pass_ledger_since=0 WHERE id=1")
    elif type(since) not in (int, float) or not math.isfinite(since) or since < 0:
        raise ValueError("Invalid long-pass ledger watermark")
    # A direct DELETE, including a prune, loses charge evidence. Fence starts
    # at or before that receipt, even when clocks/timestamps are equal.
    db.execute(
        "CREATE TRIGGER IF NOT EXISTS long_pass_deleted AFTER DELETE ON long_pass_reservations "
        "BEGIN UPDATE long_permission SET pass_ledger_since=max(pass_ledger_since, OLD.at) "
        "WHERE id=1; END"
    )
    db.execute("DELETE FROM long_pass_reservations WHERE at <= ?", (now - JOB_LEDGER_SEC,))
    db.execute(
        "UPDATE long_permission SET pass_ledger_since=max(pass_ledger_since, ?) WHERE id=1",
        (now - JOB_LEDGER_SEC,),
    )
    return float(
        db.execute("SELECT pass_ledger_since FROM long_permission WHERE id=1").fetchone()[0]
    )


def validate_long_request(value: Any, *, now: float) -> dict[str, Any] | None:
    """Copy closed pass metadata for durable markers; grants no reservation authority."""
    return _pass_request(value, now)


def _reserve_pass(
    db: Any,
    answer: Status,
    now: float,
    request: dict[str, Any],
    live: reading_long_jobs.LiveJob | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> LongReservation:
    since = _pass_ledger(db, now)
    if live is not None:
        reason = _registered_pass_reason(db, now, live, request, since)
        if reason:
            db.execute("COMMIT")
            return LongReservation("refused", {**answer, "reason": reason})
    row = db.execute(
        "SELECT binding, at FROM long_pass_reservations WHERE job=? AND ordinal=?",
        (request["job_id"], request["ordinal"]),
    ).fetchone()
    binding = json.dumps(request, sort_keys=True, separators=(",", ":"))
    if row is not None:
        # A corrupt row is not authoritative charge evidence for either binding.
        stored = _pass_request(json.loads(row[0]), now)
        if (
            stored is None
            or type(row[1]) not in (int, float)
            or not math.isfinite(row[1])
            or row[1] <= 0
        ):
            raise ValueError("Invalid long-pass receipt")
        same = stored == request
        reason = "already-reserved" if same else "reservation-conflict"
        db.execute("COMMIT")
        return LongReservation(
            "already-reserved" if same else "conflict", {**answer, "reason": reason}, True
        )
    if request["started_at"] <= since:
        db.execute("COMMIT")
        return LongReservation("unknown", {**answer, "reason": "pass-ledger-unknown"})
    if answer["reason"]:
        db.execute("COMMIT")
        return LongReservation("refused", answer)
    job_ms = 0
    if live is not None:
        value = reading_long_jobs.live_header(live)
        if value is None:
            raise ValueError("Invalid live job")
        receipts = _registered_receipts(db, live, value, now)
        reason = reading_long_jobs.allocations(request, value, receipts)
        if reason:
            db.execute("COMMIT")
            return LongReservation("refused", {**answer, "reason": reason})
        job_ms = value["plan"]["limits"]["job_ms"]
    db.execute(
        "INSERT INTO long_pass_reservations VALUES (?, ?, ?, ?)",
        (request["job_id"], request["ordinal"], binding, now),
    )
    # The receipt and spend commit together under the existing supervision
    # admission barrier. Shutdown rolls back both; replay never reaches it.
    charged = _commit_charge(db, answer, now, "", live=live, job_ms=job_ms, cancelled=cancelled)
    return (
        LongReservation("refused", charged)
        if charged["reason"]
        else LongReservation("reserved", charged, True)
    )


def _registered_pass_reason(
    db: Any, now: float, live: reading_long_jobs.LiveJob, request: dict[str, Any], pass_since: float
) -> str:
    value = reading_long_jobs.live_header(live)
    if value is None:
        return "invalid-live-job"
    if not reading_long_jobs.matches(request, value, live.prepared.job_id):
        return "job-binding-changed"
    if value["started_at"] <= pass_since:
        return "pass-ledger-unknown"
    since = reading_long_jobs.ledger(db, now, JOB_LEDGER_SEC)
    return reading_long_jobs.registered(db, live, value, since)


def _registered_receipts(
    db: Any, live: reading_long_jobs.LiveJob, value: dict[str, Any], now: float
) -> list[dict[str, Any]]:
    receipts: list[dict[str, Any]] = []
    for ordinal, binding, at in db.execute(
        "SELECT ordinal, binding, at FROM long_pass_reservations WHERE job=? LIMIT 18",
        (live.prepared.job_id,),
    ):
        checked = _pass_request(json.loads(binding), now)
        if (
            checked is None
            or checked["ordinal"] != ordinal
            or not reading_long_jobs.matches(checked, value, live.prepared.job_id)
            or type(at) not in (int, float)
            or not math.isfinite(at)
            or at <= 0
        ):
            raise ValueError("Incomplete registered pass receipts")
        receipts.append(checked)
    if len(receipts) > value["plan"]["max_calls"]:
        raise ValueError("Invalid registered pass count")
    return receipts


def _register_job(
    db: Any, answer: Status, now: float, job: reading_long_jobs.PreparedJob
) -> LongRegistration:
    value = reading_long_jobs.header(job)
    if value is None:
        raise ValueError("Invalid registration")
    pass_since = _pass_ledger(db, now)
    since = reading_long_jobs.ledger(db, now, JOB_LEDGER_SEC)
    if value["started_at"] <= since:
        outcome = "job-ledger-unknown"
    elif value["started_at"] <= pass_since:
        outcome = "pass-ledger-unknown"
    elif answer["reason"]:
        outcome = answer["reason"]
    else:
        outcome = reading_long_jobs.register(db, job, value, since)
    db.execute("COMMIT")
    if outcome == "registered":
        return LongRegistration(outcome, answer, reading_long_jobs.activate(job))
    return LongRegistration(outcome, {**answer, "reason": outcome})


def _long_operation(  # noqa: PLR0913 - cancellation joins the existing atomic reservation boundary
    db: Any,
    answer: Status,
    now: float,
    operation: str,
    permission: LongPermission | None,
    captured: LongPermission | None,
    request: dict[str, Any] | None,
    job: reading_long_jobs.PreparedJob | reading_long_jobs.LiveJob | None,
    *,
    cancelled: Callable[[], bool] | None,
) -> LongRegistration | LongReservation:
    if not _valid_long_permission(captured) or permission != captured:
        answer["reason"] = answer["reason"] or "permission-changed"
    elif job is not None and not _job_permission_matches(job, captured):
        answer["reason"] = answer["reason"] or "job-binding-changed"
    elif not answer["off"]:
        if operation == "register-long-job":
            if not isinstance(job, reading_long_jobs.PreparedJob):
                raise ValueError("Invalid prepared job")
            return _register_job(db, answer, now, job)
        if request is not None:
            live = job if isinstance(job, reading_long_jobs.LiveJob) else None
            return _reserve_pass(db, answer, now, request, live, cancelled)
    db.execute("COMMIT")
    return (
        LongRegistration("refused", answer)
        if operation == "register-long-job"
        else LongReservation("refused", answer)
    )


def store_path(config: RuntimeConfig) -> Path:
    return config.state_dir / "compass-reading-permission.sqlite3"


def _answer(
    dates: tuple[float, ...] = (),
    reason: str = "",
    providers: dict[str, bool] | None = None,
    tool_output: dict[str, list[str]] | None = None,
    rebind: dict[str, str] | None = None,
    words: dict[str, bool] | None = None,
    off: bool = False,
    notices: dict[str, dict[str, Notice]] | None = None,
) -> Status:
    full = len(dates) >= DAILY_CAP
    return {
        "consent": not off and reason not in {"run-disabled", "store-unavailable"},
        "off": off,
        "notices": notices or {},
        "used": len(dates),
        "limit": DAILY_CAP,
        "retry_at": min(dates) + DAY_SEC if full else None,
        # The pause first: it is the reader's own answer and lasts until Resume,
        # so a paused Analyze says model calls are paused even on a spent day
        # (owner, 2026-10-19, DRC-4915). The cap still precedes any one
        # provider's consent, which the page reads per provider (DRC-4666).
        "reason": reason or ("model-calls-paused" if off else "daily-cap" if full else ""),
        "providers": dict(providers) if providers else dict.fromkeys(PROVIDERS, False),
        "tool_output": {name: list(where) for name, where in (tool_output or {}).items()},
        "rebind": dict(rebind or {}),
        "words": dict(words) if words else dict.fromkeys(PROVIDERS, False),
    }


def tool_output_allowed(answer: Status, provider: str, destination: str) -> bool:
    """Whether this answer holds a grant for exactly this provider and destination."""
    return bool(destination) and destination in answer.get("tool_output", {}).get(provider, [])


def _connect(config: RuntimeConfig, wait: float) -> Any:
    if runtime_io.sqlite_module is None:
        raise RuntimeError("SQLite is unavailable")
    path = store_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise RuntimeError("Permission store is a symlink")
    # SQLite inherits this owner-only mode for its rollback journal too.
    fd = os.open(path, os.O_CREAT | os.O_WRONLY, 0o600)
    os.close(fd)
    return runtime_io.sqlite_module.connect(path, timeout=wait, isolation_level=None)


def _allowed(db: Any) -> dict[str, bool]:
    row = db.execute("SELECT allowed FROM permission WHERE id=1").fetchone()
    allowed = dict.fromkeys(PROVIDERS, False)
    allowed[LEGACY_PROVIDER] = row is not None and row[0] == 1
    for name, value in db.execute("SELECT provider, allowed FROM provider_permission"):
        if name in allowed and name != LEGACY_PROVIDER:
            allowed[name] = value == 1
    return allowed


def _off(db: Any, tables: frozenset[str] = PERMISSION_TABLES) -> bool:
    """A stored refusal with no Allow beside it.

    This build's off writes 0 for every provider and its Turn on clears them
    (`_clear_off`), so both values stand together only after an older build's
    Allow, which rewrote just the provider it allowed and left its own off's
    zeros on the rest. That reader's last answer was Allow, so it reads as on.
    """
    values = {
        value
        for table in sorted(tables & PERMISSION_TABLES)
        for (value,) in db.execute(f"SELECT allowed FROM {table}")  # noqa: S608 - fixed table names
    }
    return 0 in values and 1 not in values


def _notices(db: Any) -> dict[str, dict[str, Notice]]:
    notices: dict[str, dict[str, Notice]] = {}
    for kind, provider, destination, content, tool_output, at in db.execute(
        "SELECT kind, provider, destination, content, tool_output, at FROM notice"
    ):
        # Checked as `_disclosed` checks its rows: the page serialises these,
        # and a locally rewritten row of another type would break the board.
        if (
            kind in NOTICE_KINDS
            and provider in PROVIDERS
            and isinstance(destination, str)
            and isinstance(tool_output, str)
            and isinstance(content, int)
            and not isinstance(content, bool)
            and isinstance(at, float)
            and math.isfinite(at)
        ):
            notices.setdefault(kind, {})[provider] = Notice(
                kind=kind,
                provider=provider,
                destination=destination,
                content=content,
                tool_output=tool_output,
                at=at,
            )
    return notices


def notice_due(
    answer: Status, *, kind: str, provider: str, destination: str, content: int, tool_output: str
) -> bool:
    """Whether today's disclosure goes beyond the last notice for this kind and provider.

    A wider record covers a narrower press at the same destination: a lower
    tier, or no tool output where the record named it. Otherwise a reader
    alternating between a Claude Code session and one it reads on another
    harness's behalf would be shown the notice on every press.
    """
    previous = answer["notices"].get(kind, {}).get(provider)
    return (
        answer["consent"]
        and provider in PROVIDERS
        and (
            previous is None
            or previous["destination"] != destination
            or previous["content"] < content
            or (bool(tool_output) and previous["tool_output"] != tool_output)
        )
    )


def _bound(db: Any) -> dict[str, str]:
    """The destination each provider's Allow was given for; absent where none was recorded."""
    return {
        name: where
        for name, where in db.execute("SELECT provider, destination FROM permission_destination")
        if name in PROVIDERS and isinstance(where, str)
    }


def _disclosed(db: Any) -> dict[str, tuple[int, str]]:
    """The content version each provider's Allow was given under, and for where; absent
    before the table, and after any Turn off, this build's or an older one's."""
    return {
        name: (version, where)
        for name, version, where in db.execute(
            "SELECT provider, version, destination FROM permission_disclosure"
        )
        if name in PROVIDERS
        and isinstance(version, int)
        and not isinstance(version, bool)
        and isinstance(where, str)
    }


def _covered(
    allowed: dict[str, bool],
    bound: dict[str, str],
    today: Mapping[str, str],
    disclosed: Mapping[str, tuple[int, str]] | None = None,
    *,
    content: int = CONTENT_VERSION,
) -> tuple[dict[str, bool], dict[str, str]]:
    """Which Allows cover a press today, and the line for each that does not.

    Exact equality, with "" a value of its own: an Allow given while the
    destination could not be named covers presses only while it still cannot.
    A row with no recorded destination covers nothing. A press that needs
    `content` above `WORDS_CONTENT_VERSION` is covered only by an Allow given
    under that version for the destination bound now: an older build's Allow
    rebinds the destination and never writes the version, so it never passes.
    """
    known = disclosed or {}
    placed = {
        name: allowed[name] and name in bound and bound[name] == today.get(name, "")
        for name in allowed
    }
    current = {
        name: content <= WORDS_CONTENT_VERSION
        or (name in known and known[name][0] >= content and known[name][1] == bound.get(name))
        for name in allowed
    }
    covered = {name: placed[name] and current[name] for name in allowed}
    rebind = {
        name: DESTINATION_CHANGED if not placed[name] else CONTENT_CHANGED
        for name in allowed
        if allowed[name] and not covered[name]
    }
    return covered, rebind


def _tool_output(db: Any) -> dict[str, list[str]]:
    granted: dict[str, list[str]] = {}
    for name, where in db.execute(
        "SELECT provider, destination FROM tool_output_permission ORDER BY provider, destination"
    ):
        if name in PROVIDERS and isinstance(where, str) and where:
            granted.setdefault(name, []).append(where)
    return granted


def _write(db: Any, provider: str, allowed: bool) -> None:
    if provider == LEGACY_PROVIDER:
        db.execute("INSERT OR REPLACE INTO permission VALUES (1, ?)", (int(allowed),))
    else:
        db.execute(
            "INSERT OR REPLACE INTO provider_permission VALUES (?, ?)", (provider, int(allowed))
        )


def _notice_schema(db: Any) -> None:
    db.execute(
        "CREATE TABLE IF NOT EXISTS notice (kind TEXT NOT NULL, provider TEXT NOT NULL, "
        "destination TEXT NOT NULL, content INTEGER NOT NULL, tool_output TEXT NOT NULL, "
        "at REAL NOT NULL, PRIMARY KEY (kind, provider))"
    )
    for table in ("permission", "provider_permission"):
        for event in ("INSERT", "UPDATE"):
            # Pause model calls clears every notice, the summary's included, so Resume shows
            # each again on its next call (SECURITY.md). An earlier trigger of this branch kept
            # the summary's; it is replaced by name. Turn off summaries keeps its own handling.
            db.execute(f"DROP TRIGGER IF EXISTS reading_notice_off_{table}_{event.lower()}")
            db.execute(
                f"CREATE TRIGGER IF NOT EXISTS notice_off_{table}_{event.lower()} "  # noqa: S608
                f"AFTER {event} ON {table} WHEN NEW.allowed = 0 BEGIN "
                "DELETE FROM notice; END"
            )


def _store_notice(db: Any, answer: Status, operation: str | Notice) -> Notice | None:
    if not isinstance(operation, dict) or not notice_due(
        answer,
        kind=operation["kind"],
        provider=operation["provider"],
        destination=operation["destination"],
        content=operation["content"],
        tool_output=operation["tool_output"],
    ):
        return None
    db.execute(
        "INSERT OR REPLACE INTO notice VALUES (?, ?, ?, ?, ?, ?)",
        (
            operation["kind"],
            operation["provider"],
            operation["destination"],
            operation["content"],
            operation["tool_output"],
            operation["at"],
        ),
    )
    return operation


def _clear_off(db: Any, tables: frozenset[str] = PERMISSION_TABLES) -> None:
    for table in sorted(tables & PERMISSION_TABLES):
        db.execute(f"DELETE FROM {table} WHERE allowed = 0")  # noqa: S608 - fixed table names


def _change_permissions(
    db: Any,
    operation: str | Notice,
    provider: str,
    current: Mapping[str, str],
    content: int,
    tool_output: str,
    allowed: dict[str, bool],
) -> None:
    if operation in ("unasked-grant", "unasked-revoke") and _off(db):
        return
    if operation == "unasked-revoke":
        _clear_off(db)
        # Deleting the grant avoids writing a zero, which means Pause model calls
        # in older stores. Revocation must not pause reader-requested calls.
        table = "permission" if provider == LEGACY_PROVIDER else "provider_permission"
        column, value = ("id", 1) if provider == LEGACY_PROVIDER else ("provider", provider)
        db.execute(f"DELETE FROM {table} WHERE {column} = ?", (value,))  # noqa: S608 - fixed schema identifiers
        db.execute("DELETE FROM permission_destination WHERE provider = ?", (provider,))
        db.execute("DELETE FROM permission_disclosure WHERE provider = ?", (provider,))
        allowed[provider] = False
    if operation in ("allow", "unasked-grant") and provider in allowed:
        where = current.get(provider, "")
        previous = _disclosed(db).get(provider)
        version = content
        if (
            allowed[provider]
            and _bound(db).get(provider) == where
            and previous is not None
            and previous[1] == where
            and previous[0] <= CONTENT_VERSION
        ):
            # A narrower disclosure cannot widen consent, or erase an
            # earlier wider Allow that still covers this destination.
            version = max(content, previous[0])
        # An Allow clears the global off switch and grants the provider it names, the
        # unasked lane included. No reader press writes one (`http_api._reading_permission`
        # reads the stored answer only); Resume model calls clears the pause alone.
        if operation == "allow":
            _clear_off(db)
        _write(db, provider, True)
        allowed[provider] = True
        # Bound to the destination the Allow's disclosure named, which
        # the press has checked is today's (`http_api._reading_route`).
        db.execute("INSERT OR REPLACE INTO permission_destination VALUES (?, ?)", (provider, where))
        db.execute(
            "INSERT OR REPLACE INTO permission_disclosure VALUES (?, ?, ?)",
            (provider, version, where),
        )
        if tool_output:
            db.execute(
                "INSERT OR IGNORE INTO tool_output_permission VALUES (?, ?)",
                (provider, tool_output),
            )
    elif operation == "off":
        # Every receiver at once: "Pause model calls" and `--forget` name
        # no provider, and a revocation that left one allowed would not be
        # the answer the reader gave.
        for name in PROVIDERS:
            _write(db, name, False)
        allowed.update(dict.fromkeys(PROVIDERS, False))
        db.execute("DELETE FROM tool_output_permission")
        db.execute("DELETE FROM notice")
        # Every bound destination and disclosure goes too, by the triggers
        # the legacy row's write above fires, as for an older build's off.


def _transaction(  # noqa: PLR0913 - the optional long-job token joins the same reservation transaction
    config: RuntimeConfig,
    now: float,
    operation: str | Notice,
    provider: str,
    tool_output: str = "",
    job_id: str = "",
    today: Mapping[str, str] | None = None,
    content: int = CONTENT_VERSION,
    *,
    long_permission: LongPermission | None = None,
    long_request: dict[str, Any] | None = None,
    long_job: reading_long_jobs.PreparedJob | reading_long_jobs.LiveJob | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> tuple[Status, Notice | None, LongPermission | LongReservation | LongRegistration | None]:
    if not math.isfinite(now) or now <= 0:
        return _answer(reason="store-unavailable"), None, None
    wait = READ_WAIT_SEC if operation == "read" else WRITE_WAIT_SEC
    with contextlib.closing(_connect(config, wait)) as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute(
            "CREATE TABLE IF NOT EXISTS permission (id INTEGER PRIMARY KEY CHECK(id=1), "
            "allowed INTEGER NOT NULL CHECK(allowed IN (0,1)))"
        )
        db.execute(
            "CREATE TABLE IF NOT EXISTS provider_permission (provider TEXT PRIMARY KEY, "
            "allowed INTEGER NOT NULL CHECK(allowed IN (0,1)))"
        )
        db.execute(
            "CREATE TABLE IF NOT EXISTS tool_output_permission (provider TEXT NOT NULL, "
            "destination TEXT NOT NULL, PRIMARY KEY (provider, destination))"
        )
        # Where each provider's Allow was given for (owner, 2026-10-02). A
        # table of its own, for `spend_jobs`' reason below: an older build's
        # two-value `INSERT OR REPLACE INTO provider_permission` fails against
        # a third column, and it would then refuse every Allow. A row written
        # before this table existed has no destination here, so it stays
        # readable and covers no press.
        db.execute(
            "CREATE TABLE IF NOT EXISTS permission_destination "
            "(provider TEXT PRIMARY KEY, destination TEXT NOT NULL)"
        )
        # The content version each Allow was given under and the destination
        # it was given for, a table of its own for the same reason as the
        # destination's. An Allow written before it existed, or by an older
        # build after it, has no row here that matches, so it covers no press
        # that carries the agent's words until allowed again.
        db.execute(
            "CREATE TABLE IF NOT EXISTS permission_disclosure "
            "(provider TEXT PRIMARY KEY, version INTEGER NOT NULL, destination TEXT NOT NULL)"
        )
        db.execute("CREATE TABLE IF NOT EXISTS spends (at REAL NOT NULL)")
        # A table of its own rather than a column on `spends`: an older build's
        # `INSERT INTO spends VALUES (?)` fails against a second column, and a
        # rollback would then refuse every press as store-unavailable.
        db.execute("CREATE TABLE IF NOT EXISTS spend_jobs (job TEXT PRIMARY KEY, at REAL NOT NULL)")
        # How far back an absent row still means "no charge": from the
        # ledger's creation, raised on every prune. Without it, a row pruned
        # under a clock that ran ahead, or a store deleted and made again,
        # read as "never charged" for a job that was (review F2).
        db.execute(
            "CREATE TABLE IF NOT EXISTS spend_jobs_since "
            "(id INTEGER PRIMARY KEY CHECK(id=1), at REAL NOT NULL)"
        )
        db.execute("INSERT OR IGNORE INTO spend_jobs_since VALUES (1, ?)", (now,))
        # Schema, so it fires inside a pre-DRC-4650 build's own write: that
        # build's Turn off and `--forget` touch only the legacy row, and without
        # this the Claude Code answer survived a rollback (DRC-4666).
        for event in ("INSERT", "UPDATE"):
            db.execute(
                f"CREATE TRIGGER IF NOT EXISTS permission_off_{event.lower()} "  # noqa: S608 - two fixed words
                f"AFTER {event} ON permission WHEN NEW.allowed = 0 BEGIN "
                "UPDATE provider_permission SET allowed = 0; "
                "DELETE FROM tool_output_permission; END"
            )
            # Its own trigger, since `IF NOT EXISTS` never rewrites the one
            # above: an older build's Turn off forgets every bound destination
            # too, so its later Allow cannot cover a destination named before.
            db.execute(
                f"CREATE TRIGGER IF NOT EXISTS permission_destination_off_{event.lower()} "  # noqa: S608 - two fixed words
                f"AFTER {event} ON permission WHEN NEW.allowed = 0 BEGIN "
                "DELETE FROM permission_destination; END"
            )
            # And its own again, for the disclosure version: an older build's
            # Turn off then Allow, under a disclosure that never named the
            # agent's messages, must not find this build's version still on
            # record (final review, 2026-10-03).
            db.execute(
                f"CREATE TRIGGER IF NOT EXISTS permission_disclosure_off_{event.lower()} "  # noqa: S608 - two fixed words
                f"AFTER {event} ON permission WHEN NEW.allowed = 0 BEGIN "
                "DELETE FROM permission_disclosure; END"
            )
        _notice_schema(db)
        permission = (
            _long_permission_schema(db)
            if operation
            in (
                "capture-long",
                "reserve-long",
                "reserve-long-pass",
                "register-long-job",
                "reserve-registered-pass",
            )
            else None
        )
        allowed = _allowed(db)
        db.execute("DELETE FROM spends WHERE at <= ?", (now - DAY_SEC,))
        db.execute("DELETE FROM spend_jobs WHERE at <= ?", (now - JOB_LEDGER_SEC,))
        db.execute(
            "UPDATE spend_jobs_since SET at = max(at, ?) WHERE id = 1", (now - JOB_LEDGER_SEC,)
        )
        dates = tuple(float(row[0]) for row in db.execute("SELECT at FROM spends ORDER BY at"))
        if any(not math.isfinite(at) or at <= 0 for at in dates):
            raise ValueError("Invalid spend timestamp")
        current = dict(today or {})
        _change_permissions(db, operation, provider, current, content, tool_output, allowed)
        bound, disclosed = _bound(db), _disclosed(db)
        covered, rebind = _covered(allowed, bound, current, disclosed, content=content)
        words, _ = _covered(allowed, bound, current, disclosed, content=WORDS_CONTENT_VERSION)
        answer = _answer(
            dates,
            providers=covered,
            tool_output=_tool_output(db),
            rebind=rebind,
            words=words,
            off=_off(db),
            notices=_notices(db),
        )
        recorded = _store_notice(db, answer, operation)
        if operation in ("reserve-long-pass", "register-long-job", "reserve-registered-pass"):
            result = _long_operation(
                db,
                answer,
                now,
                operation,
                permission,
                long_permission,
                long_request,
                long_job,
                cancelled=cancelled,
            )
            return result.status, None, result
        if (
            operation == "reserve-long"
            and not answer["reason"]
            and (not _valid_long_permission(long_permission) or permission != long_permission)
        ):
            answer["reason"] = "permission-changed"
        if operation in ("reserve", "reserve-long") and not answer["reason"]:
            return _commit_charge(db, answer, now, job_id), None, None
        db.execute("COMMIT")
        captured = permission if operation == "capture-long" and not answer["reason"] else None
        return answer, recorded, captured


def _commit_charge(
    db: Any,
    answer: Status,
    now: float,
    job_id: str,
    *,
    live: reading_long_jobs.LiveJob | None = None,
    job_ms: int = 0,
    cancelled: Callable[[], bool] | None = None,
) -> Status:
    """Insert the charge and its job, and commit, unless the runner has shut.

    Under the lock a shutdown takes (DRC-4712). The wait for SQLite's write
    lock is already behind this, so `kill_all` waits one commit at most, and
    it never touches SQLite, so the two locks cannot be taken in both orders.
    """
    with supervise.admitting() as open_:
        if not open_:
            db.execute("ROLLBACK")
            return {**answer, "reason": "stopping"}
        if live is not None and (reason := reading_long_jobs.deadline_reason(live, job_ms)):
            db.execute("ROLLBACK")
            return {**answer, "reason": reason}
        if cancelled is not None and cancelled():
            db.execute("ROLLBACK")
            return {**answer, "reason": "cancelled"}
        db.execute("INSERT INTO spends VALUES (?)", (now,))
        if job_id:
            db.execute("INSERT OR IGNORE INTO spend_jobs VALUES (?, ?)", (job_id, now))
        db.execute("COMMIT")
    return {**answer, "used": answer["used"] + 1}


def _run(
    config: RuntimeConfig,
    now: float,
    operation: str,
    provider: str,
    tool_output: str = "",
    job_id: str = "",
    today: Mapping[str, str] | None = None,
    content: int = CONTENT_VERSION,
) -> Status:
    try:
        return _transaction(
            config, now, operation, provider, tool_output, job_id, today, content=content
        )[0]
    except (OSError, ValueError, RuntimeError, _SQL_ERROR):
        return _answer(reason="store-unavailable")


def status(
    config: RuntimeConfig,
    *,
    now: float,
    provider: str = LEGACY_PROVIDER,
    destinations: Mapping[str, str] | None = None,
    content: int = CONTENT_VERSION,
) -> Status:
    """Reader admission, recorded notices, and legacy explicit coverage for today's routes.

    A missing destination is unnamed (""), so it cannot inherit named explicit coverage.
    Reader admission depends on stored off, not on that coverage. `content` selects the
    legacy coverage tier; words-only callers use `WORDS_CONTENT_VERSION`.
    """
    if config.model_calls_disabled:
        return _answer(reason="run-disabled")
    if runtime_io.sqlite_module is None:
        return _answer(reason="store-unavailable")
    if not os.path.lexists(store_path(config)):
        return _answer()
    return _run(config, now, "read", provider, today=destinations, content=content)


def set_consent(
    config: RuntimeConfig,
    allowed: bool,
    *,
    now: float,
    provider: str = LEGACY_PROVIDER,
    tool_output: str = "",
    destination: str = "",
    destinations: Mapping[str, str] | None = None,
    content: int = CONTENT_VERSION,
) -> Status:
    """Resume model calls with one explicit Allow, or pause every provider.

    `destination` is where the press's disclosure said the words go, and the
    Allow covers presses only while they still go there. `tool_output` is the
    destination it named for tool output. Only an Allow that carried one
    grants tool output, and only to that destination. `destinations` is as
    `status` takes it, for the other providers in the answer returned. `content`
    is the tier the server's route disclosed, never a client-supplied version.
    A narrower Allow retains an earlier wider one only at the same destination.
    """
    today = {**(destinations or {}), provider: destination}
    operation = "allow" if allowed else "off"
    return _run(config, now, operation, provider, tool_output, today=today, content=content)


def set_unasked_grant(
    config: RuntimeConfig,
    allowed: bool,
    *,
    now: float,
    provider: str,
    destination: str,
    destinations: Mapping[str, str] | None = None,
) -> Status:
    """Grant or revoke words-only unasked coverage for one provider and destination.

    The only writer of that grant: no press, Analyze or Resume writes one. It never
    lifts Pause model calls, and while paused it changes nothing. A revoke deletes
    the provider's rows rather than writing a zero, which an older store reads as a
    pause. `destinations` is as `status` takes it, for the answer returned.
    """
    if provider not in PROVIDERS:
        raise ValueError("Unknown unasked provider")
    if config.model_calls_disabled or not config.unasked_enabled:
        return _answer(reason="run-disabled")
    answer = _run(
        config,
        now,
        "unasked-grant" if allowed else "unasked-revoke",
        provider,
        today={provider: destination},
        content=WORDS_CONTENT_VERSION,
    )
    if answer["reason"] not in {"", "daily-cap"}:
        return answer
    return status(config, now=now, destinations={**(destinations or {}), provider: destination})


def unasked_status(config: RuntimeConfig, *, now: float, provider: str, destination: str) -> Status:
    """Admission at the unasked seam, without spending the reader-requested budget."""
    if not config.unasked_enabled:
        return _answer(reason="run-disabled")
    answer = status(
        config,
        now=now,
        provider=provider,
        destinations={provider: destination},
        content=WORDS_CONTENT_VERSION,
    )
    # The lane's own durable check counts bound it; Analyze's budget cannot replace them.
    if answer["reason"] == "daily-cap":
        answer = {**answer, "reason": ""}
    # The accepted Claude producer needs no separate grant; Codex retains explicit coverage.
    # [DEC-18](docs/design-reading-a-session.md#amended-2026-10-20-unasked-checks-remain-reachable)
    if not answer["reason"] and (
        provider not in PROVIDERS
        or (provider != "claude" and not answer["words"].get(provider, False))
    ):
        answer = {**answer, "reason": "unasked-permission-required"}
    return answer


def resume(config: RuntimeConfig, *, now: float) -> Status:
    """Resume model calls: clear the stored pause without writing an Allow.

    An Allow would also cover Codex unasked checks, so Resume clears only refusal
    rows; their deliberate grant belongs to the separate toggle (owner, 2026-10-20). A run started
    with model calls disabled keeps the stored pause: the startup switch is not
    the reader's answer, and clearing it would lose theirs.
    """
    if config.model_calls_disabled:
        return _answer(reason="run-disabled")
    if runtime_io.sqlite_module is not None and os.path.lexists(store_path(config)):
        try:
            with contextlib.closing(_connect(config, WRITE_WAIT_SEC)) as db:
                db.execute("BEGIN IMMEDIATE")
                # Whichever permission tables exist: an older store may hold its
                # pause in one, and the read below creates the other.
                tables = _permission_tables(db)
                if tables and _off(db, tables):
                    _clear_off(db, tables)
                db.execute("COMMIT")
        except (OSError, ValueError, RuntimeError, _SQL_ERROR):
            return _answer(reason="store-unavailable")
    return _run(config, now, "read", LEGACY_PROVIDER)


def reserve(
    config: RuntimeConfig,
    *,
    now: float,
    provider: str = LEGACY_PROVIDER,
    job_id: str = "",
    destination: str = "",
    content: int = CONTENT_VERSION,
) -> Status:
    """Commit a charge before launch; uncertainty about spend never refunds it.

    One rolling budget whichever provider is admitted: two providers must not
    be a way to double a reader's daily readings. `job_id` commits with the
    charge, so a restart can ask `charged` whether that job's attempt was made.
    A shutdown before the commit answers `stopping` and charges nothing.
    `destination` and `content` retain the legacy coverage fields in the returned status.
    """
    today = {provider: destination}
    if config.model_calls_disabled:
        return status(config, now=now, provider=provider, destinations=today, content=content)
    return _run(config, now, "reserve", provider, job_id=job_id, today=today, content=content)


def capture_long_permission(config: RuntimeConfig, *, now: float) -> LongPermission | None:
    """Capture once at long-job start; failure is not permission to use ordinary reserve."""
    if config.model_calls_disabled:
        return None
    try:
        return cast(
            "LongPermission | None", _transaction(config, now, "capture-long", LEGACY_PROVIDER)[2]
        )
    except (OSError, ValueError, RuntimeError, _SQL_ERROR):
        return None


def long_permission_reason(  # noqa: PLR0911 - fail-closed stages of one read-only snapshot
    config: RuntimeConfig, permission: LongPermission
) -> str:
    """Read the captured permission without recapture, schema writes or quota admission.

    A committed last-budget call must still pass its execution checks. This
    checks only current permission; it grants no reservation or launch.
    """
    if config.model_calls_disabled:
        return "run-disabled"
    if not _valid_long_permission(permission):
        return "permission-changed"
    path = store_path(config)
    try:
        if runtime_io.sqlite_module is None or path.is_symlink() or not path.is_file():
            return "store-unavailable"
        with contextlib.closing(
            runtime_io.sqlite_module.connect(
                path.absolute().as_uri() + "?mode=ro",
                uri=True,
                timeout=READ_WAIT_SEC,
                isolation_level=None,
            )
        ) as db:
            db.execute("BEGIN")
            row = db.execute("SELECT lineage, epoch FROM long_permission WHERE id=1").fetchone()
            if row is None or not _valid_long_permission(current := LongPermission(*row)):
                return "store-unavailable"
            if current != permission:
                return "permission-changed"
            if _permission_tables(db) != PERMISSION_TABLES:
                return "store-unavailable"
            values = [
                value
                for table in sorted(PERMISSION_TABLES)
                for (value,) in db.execute(f"SELECT allowed FROM {table}")  # noqa: S608 - fixed tables
            ]
            if any(type(value) is not int or value not in (0, 1) for value in values):
                return "store-unavailable"
            return "model-calls-paused" if 0 in values and 1 not in values else ""
    except (OSError, ValueError, RuntimeError, _SQL_ERROR):
        return "store-unavailable"


def reserve_long(
    config: RuntimeConfig,
    *,
    permission: LongPermission,
    now: float,
    provider: str = LEGACY_PROVIDER,
    job_id: str = "",
    destination: str = "",
    content: int = CONTENT_VERSION,
) -> Status:
    """Charge only while the captured permission still holds under the SQLite write lock."""
    today = {provider: destination}
    if config.model_calls_disabled:
        return status(config, now=now, provider=provider, destinations=today, content=content)
    try:
        return _transaction(
            config,
            now,
            "reserve-long",
            provider,
            job_id=job_id,
            today=today,
            content=content,
            long_permission=permission,
        )[0]
    except (OSError, ValueError, RuntimeError, _SQL_ERROR):
        return _answer(reason="store-unavailable")


def reserve_long_pass(
    config: RuntimeConfig,
    *,
    permission: LongPermission,
    request: Any,
    now: float,
) -> LongReservation:
    """Atomically reserve a composite slot once; identical replay never authorizes launch.

    The caller owns the frozen job start, actual final prompt/destination/plan
    hashes and counts. They are binding metadata, not permission or evidence
    that those inputs were checked. Never change a start to reuse a lost key.
    There is no negative historical charge claim: absent evidence is unknown.
    """
    checked = _pass_request(request, now)
    if checked is None:
        return LongReservation("refused", _answer(reason="invalid-long-request"))
    if config.model_calls_disabled:
        return LongReservation("refused", _answer(reason="run-disabled"))
    try:
        answer, _, result = _transaction(
            config,
            now,
            "reserve-long-pass",
            checked["provider"],
            content=checked["content"],
            long_permission=permission,
            long_request=checked,
        )
        return result if isinstance(result, LongReservation) else LongReservation("refused", answer)
    except (OSError, ValueError, RuntimeError, _SQL_ERROR):
        return LongReservation("unknown", _answer(reason="store-unavailable"))


def prepare_long_job(
    *,
    permission: LongPermission,
    binding: Any,
    call_timeout_ms: int,
    clock: Callable[[], float] = time.monotonic,
) -> reading_long_jobs.PreparedJob | None:
    """Mint a bounded header identity and capture live time once; grants no execution."""
    if not _valid_long_permission(permission):
        return None
    return reading_long_jobs.prepare(
        binding, permission.lineage, permission.epoch, call_timeout_ms, clock
    )


def _job_permission_matches(job: Any, permission: Any) -> bool:
    value = (
        reading_long_jobs.live_header(job)
        if isinstance(job, reading_long_jobs.LiveJob)
        else reading_long_jobs.header(job)
    )
    return (
        value is not None
        and _valid_long_permission(permission)
        and (value["lineage"], value["epoch"]) == (permission.lineage, permission.epoch)
    )


def register_long_job(
    config: RuntimeConfig, *, permission: LongPermission, job: Any, now: float
) -> LongRegistration:
    """Persist one immutable job; only a fresh registration returns a live admission handle."""
    value = reading_long_jobs.header(job)
    if value is None or value["started_at"] > now:
        return LongRegistration("conflict", _answer(reason="invalid-long-job"))
    if config.model_calls_disabled:
        return LongRegistration("refused", _answer(reason="run-disabled"))
    try:
        answer, _, result = _transaction(
            config,
            now,
            "register-long-job",
            value["provider"],
            content=value["content"],
            long_permission=permission,
            long_job=job,
        )
        return (
            result if isinstance(result, LongRegistration) else LongRegistration("refused", answer)
        )
    except (OSError, ValueError, RuntimeError, _SQL_ERROR):
        return LongRegistration("unknown", _answer(reason="store-unavailable"))


def reserve_registered_pass(
    config: RuntimeConfig,
    *,
    permission: LongPermission,
    job: Any,
    request: Any,
    now: float,
    cancelled: Callable[[], bool] | None = None,
) -> LongReservation:
    """Admit one registered slot with aggregate allocations and a live final deadline check.

    Only use the handle returned by fresh registration. A stored header or a
    newly prepared replay is not a new monotonic window and cannot launch.
    The optional cancellation callback runs once at fresh charge admission,
    after SQLite and supervision lock waits. It must be a fast in-memory flag
    read: no disk I/O, annotation/file locks, or model work. A later cancellation
    cannot refund a committed charge; the caller still owns pre-spawn checks.
    """
    if reading_long_jobs.live_header(job) is None:
        return LongReservation("refused", _answer(reason="invalid-live-job"))
    checked = _pass_request(request, now)
    if checked is None:
        return LongReservation("refused", _answer(reason="invalid-long-request"))
    if config.model_calls_disabled:
        return LongReservation("refused", _answer(reason="run-disabled"))
    try:
        answer, _, result = _transaction(
            config,
            now,
            "reserve-registered-pass",
            checked["provider"],
            content=checked["content"],
            long_permission=permission,
            long_request=checked,
            long_job=job,
            cancelled=cancelled,
        )
        return result if isinstance(result, LongReservation) else LongReservation("refused", answer)
    except (OSError, ValueError, RuntimeError, _SQL_ERROR):
        return LongReservation("unknown", _answer(reason="store-unavailable"))


def charged(config: RuntimeConfig, job_id: str, *, started_at: Any, now: float) -> bool | None:
    """Whether the ledger holds a charge for this job, or None when it cannot say.

    A row is a charge whenever it was made. No row means no charge only for a
    job that started after the ledger's watermark: None for a start at or
    before it, older than the ledger keeps, or not a positive number, and for
    no id or a store that is missing, unreadable or older than the ledger. A
    caller counts None as spent: dropping a charged attempt silently is the
    loss DRC-4686 Q2 ruled out. Reads only; creates nothing.
    """
    if not job_id or runtime_io.sqlite_module is None:
        return None
    path = store_path(config)
    try:
        if path.is_symlink() or not path.is_file():
            return None
        with contextlib.closing(
            runtime_io.sqlite_module.connect(
                path.absolute().as_uri() + "?mode=ro",
                uri=True,
                timeout=READ_WAIT_SEC,
                isolation_level=None,
            )
        ) as db:
            row = db.execute("SELECT 1 FROM spend_jobs WHERE job = ?", (job_id,)).fetchone()
            since = db.execute("SELECT at FROM spend_jobs_since WHERE id = 1").fetchone()
    except (OSError, ValueError, RuntimeError, _SQL_ERROR):
        return None
    if row is not None:
        return True
    # A watermark that is not a finite number is damage, and damage cannot
    # vouch for an absent row. Raising here once let recovery delete the
    # marker and record nothing (verify N1).
    watermark = since[0] if since is not None else None
    if (
        not isinstance(watermark, (int, float))
        or not math.isfinite(watermark)
        or not isinstance(started_at, (int, float))
        or not math.isfinite(started_at)
        or started_at <= max(float(watermark), now - JOB_LEDGER_SEC, 0.0)
    ):
        return None
    return False


class RefusedError(Exception):
    def __init__(self, answer: Status) -> None:
        super().__init__(answer["reason"])
        self.answer = answer


class PromptPermit(Protocol):
    """Reservation authority for this invocation, independent of historical charges."""

    @property
    def launch(self) -> bool: ...

    @property
    def fresh_charge(self) -> bool: ...

    @property
    def reason(self) -> str: ...


_INVOKE_REFUSALS = frozenset(
    {"intent-changed", "permission-changed", "job-deadline", "job-clock-invalid"}
)


class GuardedModel:
    """Reserve at the actual model seam, after eligibility and evidence checks."""

    def __init__(  # noqa: PLR0913 (each hook is one keyword its caller names)
        self,
        config: RuntimeConfig,
        model: Callable[..., tuple[str, str]],
        clock: Callable[[], float],
        *,
        provider: str = LEGACY_PROVIDER,
        destination: str = "",
        resolve_destination: Callable[[], str] | None = None,
        on_reserved: Callable[[], None] | None = None,
        before_reserve: Callable[[], str | None] | None = None,
        cancelled: Callable[[], bool] | None = None,
        content: int = CONTENT_VERSION,
        unasked: bool = False,
        reserve_with: Callable[..., Status] | None = None,
        admit_prompt: Callable[[str], str | None] | None = None,
        reserve_prompt: Callable[[str, int], PromptPermit] | None = None,
        before_invoke: Callable[[], str | None] | None = None,
    ) -> None:
        if before_invoke is not None and reserve_prompt is None:
            raise ValueError("Before-invoke checks require prompt-aware reservation")
        if reserve_prompt is not None and (
            reserve_with is not None or before_reserve is not None or unasked
        ):
            raise ValueError("Prompt reservation requires its own requested-call reservation path")
        if reserve_with is not None and before_reserve is not None:
            # `before_reserve` returns the job id the charge is recorded under, and a ledger of
            # its own records none, so the pair would drop the marker's promise silently.
            msg = "A ledger of its own takes no job marker"
            raise ValueError(msg)
        self.config = config
        self.content = content
        self.unasked = unasked
        # A ledger of its own for a caller that must not spend Analyze's budget: the Live monitor
        # charges `reserve_monitor` here, at the same seam and in the same order.
        self.reserve_with = reserve_with
        self.reserve_prompt = reserve_prompt
        # A current-context/deadline refusal after a fresh charge, not authority.
        # Exceptions preserve the charge and never enter the model adapter.
        self.before_invoke = before_invoke
        self.admit_prompt = admit_prompt
        self.reserved = False
        self.analyze_diagnostic: dict[str, Any] | None = None
        self._model_invoked = False
        self.model = model
        self.clock = clock
        self.provider = provider
        self.destination = destination
        # Where the words go now, asked again at the reservation (consent F4,
        # ui5): a managed drop-in or remote settings file can move the endpoint
        # while the job collects the record, which takes seconds for a large
        # one, and a reservation against the press-time value would pass.
        self.resolve_destination = resolve_destination
        # A reading job is told the spend is committed (DRC-4686).
        self.on_reserved = on_reserved
        # And its marker before the reservation: a hook that raises here
        # stops the call with nothing spent. What it returns is the job id the
        # charge is recorded under, so the marker and the ledger row it
        # promises come from one place (DRC-4713).
        self.before_reserve = before_reserve
        # A reader's Cancel, asked here so one that lands before the
        # reservation spends nothing (owner, 2026-09-24; see the Cancel
        # section of docs/design-reading-a-session.md).
        self.cancelled = cancelled
        # Passed through, so the refusal names the CLI this press would have used.
        self.unavailable_reason: str | None = getattr(model, "unavailable_reason", None)

    def failure_reason(self) -> str:
        """The wrapped model's own account of its last failed call, or "" for none."""
        failure = getattr(self.model, "failure_reason", None)
        return str(failure()) if callable(failure) else ""

    def _reserve(self) -> Status:
        if self.reserve_with is not None:
            return self.reserve_with(self.config, now=self.clock())
        job_id = self.before_reserve() if self.before_reserve is not None else None
        return reserve(
            self.config,
            now=self.clock(),
            provider=self.provider,
            job_id=job_id or "",
            destination=self.destination,
            content=self.content,
        )

    def _preflight(self) -> str | None:
        available = getattr(self.model, "available", None)
        if available is not None and not available():
            return "unavailable"
        if supervise.closed():
            return "closed"
        if self.cancelled is not None and self.cancelled():
            return "cancelled"
        if self.resolve_destination is not None and self.resolve_destination() != self.destination:
            raise RefusedError(_answer(reason=DESTINATION_MOVED))
        return None

    def _admission(self, prompt: str) -> str | None:
        if self.admit_prompt is None and self.reserve_prompt is None:
            return None
        # Pause/consent precede capacity work. The reservation transaction
        # authoritatively checks them again before committing a charge.
        answer = status(
            self.config,
            now=self.clock(),
            provider=self.provider,
            destinations={self.provider: self.destination},
            content=self.content,
        )
        if answer["reason"]:
            raise RefusedError(answer)
        refusal = self.admit_prompt(prompt) if self.admit_prompt is not None else None
        if refusal is not None:
            return refusal
        # Configuration reads can take time. Recheck the live gates before
        # reaching either the job marker or the reservation.
        return self._preflight()

    def __call__(self, prompt: str, *, output_cap_bytes: int) -> tuple[str, str]:
        self.reserved = False
        self._model_invoked = False
        self.analyze_diagnostic = None
        if (self.admit_prompt is None and self.reserve_prompt is None) or self.unasked:
            return self._call(prompt, output_cap_bytes=output_cap_bytes)
        reset = getattr(self.admit_prompt, "reset", None)
        if callable(reset):
            reset()
        started = time.monotonic()
        outcome = "error"
        try:
            raw, status = self._call(prompt, output_cap_bytes=output_cap_bytes)
        except RefusedError:
            outcome = "refused"
            raise
        else:
            outcome = status if status in analyze_diagnostics.INPUT_OUTCOMES else "error"
            return raw, status
        finally:
            # Input is the already assembled argument, not source transcript
            # size. Invocation is not proof of transmission or provider use.
            # Elapsed time covers this seam, including its gates; source
            # collection happened before entry and is not timed here.
            self.analyze_diagnostic = {
                "kind": "actual-input",
                "prompt_bytes": len(prompt.encode("utf-8", "replace")),
                "elapsed_ms": max(0, round((time.monotonic() - started) * 1000)),
                "outcome": outcome,
                "attempt_reserved": self.reserved,
                "model_invoked": self._model_invoked,
            }

    def _reserve_call(self, prompt: str, output_cap_bytes: int) -> str | None:
        if self.reserve_prompt is not None:
            permit = self.reserve_prompt(prompt, output_cap_bytes)
            # A committed charge survives a failed marker write. Replay's
            # historical charge cannot count as this invocation's reservation.
            self.reserved = permit.fresh_charge is True
            answer = _answer(
                reason=permit.reason
                or ("" if permit.launch is True and self.reserved else "reservation-refused")
            )
        else:
            answer = self._reserve()
            self.reserved = not answer["reason"]
        if self.reserved and self.on_reserved is not None:
            self.on_reserved()
        if answer["reason"] == "stopping":
            return "closed"
        if answer["reason"]:
            raise RefusedError(answer)
        return None

    def _call(self, prompt: str, *, output_cap_bytes: int) -> tuple[str, str]:
        if refusal := self._preflight():
            return "", refusal
        if self.unasked:
            answer = unasked_status(
                self.config, now=self.clock(), provider=self.provider, destination=self.destination
            )
            if answer["reason"]:
                raise RefusedError(answer)
            return self.model(prompt, output_cap_bytes=output_cap_bytes)
        if refusal := self._admission(prompt):
            return "", refusal
        if refusal := self._reserve_call(prompt, output_cap_bytes):
            return "", refusal
        if self.reserve_prompt is not None and (refusal := self._before_invoke()):
            return "", refusal
        self._model_invoked = True
        raw, outcome = self.model(prompt, output_cap_bytes=output_cap_bytes)
        # A last-moment managed-policy change can stop the child after the
        # reservation. It must not inherit the initial refusal's unspent claim.
        if outcome == "context-config":
            outcome = "context-config-after-reserve"
        return raw, outcome

    def _before_invoke(self) -> str | None:
        """Recheck after reservation callbacks; this is adapter entry, not child spawn."""
        if refusal := self._preflight():
            return refusal
        if self.before_invoke is not None:
            reason = self.before_invoke()
            if reason is not None:
                if not isinstance(reason, str) or reason not in _INVOKE_REFUSALS:
                    raise ValueError("Invalid before-invoke refusal")
                raise RefusedError(_answer(reason=reason))
            # Context checks can block. A Cancel or destination change during
            # them still prevents entry, without undoing the committed charge.
            return self._preflight()
        return None


def note(
    config: RuntimeConfig,
    *,
    kind: str,
    provider: str,
    destination: str,
    content: int,
    tool_output: str,
    now: float,
) -> Notice | None:
    """Record a due notice atomically, refusing the call if the store cannot record it."""
    if config.model_calls_disabled:
        return None
    if kind not in NOTICE_KINDS or provider not in PROVIDERS:
        raise ValueError("Unknown notice kind or provider")
    notice = Notice(
        kind=kind,
        provider=provider,
        destination=destination,
        content=content,
        tool_output=tool_output,
        at=now,
    )
    try:
        if kind == "summary":
            answer, recorded = _summary_transaction(config, now, notice)
        else:
            answer, recorded, _ = _transaction(config, now, notice, provider)
    except (OSError, ValueError, RuntimeError, _SQL_ERROR):
        raise RefusedError(_answer(reason="store-unavailable")) from None
    if answer["reason"] == "store-unavailable":
        raise RefusedError(answer)
    return recorded


def retract(config: RuntimeConfig, notice: Notice) -> None:
    """Delete a recorded notice whose call never launched, so the next press shows it.

    Only that exact row, so a record a later press made is kept. Best effort:
    a store that cannot be written here shows nothing again, which is the
    failure the reader would have had anyway.
    """
    with (
        contextlib.suppress(OSError, ValueError, RuntimeError, _SQL_ERROR),
        contextlib.closing(_connect(config, WRITE_WAIT_SEC)) as db,
    ):
        db.execute(
            "DELETE FROM notice WHERE kind = ? AND provider = ? AND destination = ? "
            "AND content = ? AND tool_output = ? AND at = ?",
            (
                notice["kind"],
                notice["provider"],
                notice["destination"],
                notice["content"],
                notice["tool_output"],
                notice["at"],
            ),
        )


def forget(config: RuntimeConfig, *, now: float | None = None) -> bool:
    # Forgetting the answer cannot refill a rolling budget. No session content
    # is retained here, only the timestamps protecting the spend bound.
    when = time.time() if now is None else now
    reading = set_consent(config, False, now=when)
    summary = _summary_run(config, when, "forget")
    return reading["reason"] != "store-unavailable" and summary["reason"] != "store-unavailable"


def _summary_answer(
    config: RuntimeConfig,
    dates: tuple[float, ...] = (),
    *,
    off: bool = False,
    readings_off: bool = False,
    reason: str = "",
    generation: int = 0,
    notices: dict[str, dict[str, Notice]] | None = None,
) -> Status:
    answer = _answer(off=off, reason=reason, notices=notices)
    full = len(dates) >= config.session_summary_rolling_cap
    answer["used"] = len(dates)
    answer["limit"] = config.session_summary_rolling_cap
    answer["retry_at"] = min(dates) + DAY_SEC if full and dates else None
    answer["reason"] = reason or (
        "model-calls-paused"
        if readings_off
        else "daily-cap"
        if full
        else "summaries-off"
        if off
        else ""
    )
    answer["consent"] = answer["consent"] and not readings_off
    answer["generation"] = generation
    return answer


def _summary_transaction(
    config: RuntimeConfig, now: float, operation: str | Notice, receipt: str = ""
) -> tuple[Status, Notice | None]:
    if not math.isfinite(now) or now <= 0:
        raise ValueError("Invalid summary timestamp")
    with contextlib.closing(
        _connect(config, READ_WAIT_SEC if operation == "read" else WRITE_WAIT_SEC)
    ) as db:
        db.execute("BEGIN IMMEDIATE")
        # Independent rows preserve an explicit summary off through upgrades without changing
        # Analyze or goal answers: docs/design-session-summary.md#the-ruling.
        db.execute(
            "CREATE TABLE IF NOT EXISTS summary_permission (id INTEGER PRIMARY KEY CHECK(id=1), "
            "allowed INTEGER NOT NULL CHECK(allowed IN (0,1)), generation INTEGER NOT NULL)"
        )
        db.execute(
            "CREATE TABLE IF NOT EXISTS summary_spends (receipt TEXT PRIMARY KEY, at REAL NOT NULL)"
        )
        db.execute(
            "CREATE TABLE IF NOT EXISTS notice (kind TEXT NOT NULL, provider TEXT NOT NULL, "
            "destination TEXT NOT NULL, content INTEGER NOT NULL, tool_output TEXT NOT NULL, "
            "at REAL NOT NULL, PRIMARY KEY (kind, provider))"
        )
        db.execute("DELETE FROM summary_spends WHERE at <= ?", (now - JOB_LEDGER_SEC,))
        row = db.execute("SELECT allowed, generation FROM summary_permission WHERE id=1").fetchone()
        # A press is refused while paused, but `--forget` is not a press: it
        # stores summaries off whatever the pause says.
        if operation == "forget" or (operation in ("on", "off") and not _readings_off(db)):
            was_off = row is not None and row[0] == 0
            off = operation != "on"
            generation = (row[1] if row else 0) + int(was_off != off)
            db.execute(
                "INSERT OR REPLACE INTO summary_permission VALUES (1, ?, ?)",
                (int(not off), generation),
            )
            if off:
                db.execute("DELETE FROM notice WHERE kind = 'summary'")
            row = (int(not off), generation)
        dates = tuple(
            float(at)
            for (at,) in db.execute(
                "SELECT at FROM summary_spends WHERE at > ? ORDER BY at", (now - DAY_SEC,)
            )
        )
        if any(not math.isfinite(at) or at <= 0 for at in dates):
            raise ValueError("Invalid summary spend")
        answer = _summary_answer(
            config,
            dates,
            off=row is not None and row[0] == 0,
            readings_off=_readings_off(db),
            generation=row[1] if row else 0,
            notices=_notices(db),
        )
        recorded = _store_notice(db, answer, operation)
        if operation == "reserve" and not answer["reason"]:
            with supervise.admitting() as open_:
                if not open_:
                    answer["reason"] = "stopping"
                else:
                    db.execute("INSERT OR IGNORE INTO summary_spends VALUES (?, ?)", (receipt, now))
                    dates = tuple(
                        float(at)
                        for (at,) in db.execute(
                            "SELECT at FROM summary_spends WHERE at > ? ORDER BY at",
                            (now - DAY_SEC,),
                        )
                    )
                    answer["used"] = len(dates)
        elif (
            operation == "reserve"
            and answer["reason"] == "daily-cap"
            and db.execute("SELECT 1 FROM summary_spends WHERE receipt=?", (receipt,)).fetchone()
        ):
            # A retried receipt is already charged, including at the cap; no second spend.
            answer["reason"] = "summaries-off" if answer["off"] else ""
        db.execute("COMMIT")
        return answer, recorded


def _summary_read(config: RuntimeConfig, now: float) -> Status:
    """The summary answer without a write lock, for board collection and preflight.

    Every collection asks this, and dashboards on other ports share the store, so the read
    takes no `BEGIN IMMEDIATE` and creates or prunes nothing: the 24-hour window is the
    SELECT's own filter, and schema and pruning stay on the write paths.
    """
    if not math.isfinite(now) or now <= 0:
        raise ValueError("Invalid summary timestamp")
    with contextlib.closing(_connect(config, READ_WAIT_SEC)) as db:
        db.execute("BEGIN")
        tables = {
            name
            for (name,) in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name IN ('summary_permission', 'summary_spends', 'notice')"
            )
        }
        row = (
            db.execute("SELECT allowed, generation FROM summary_permission WHERE id=1").fetchone()
            if "summary_permission" in tables
            else None
        )
        dates = (
            tuple(
                float(at)
                for (at,) in db.execute(
                    "SELECT at FROM summary_spends WHERE at > ? ORDER BY at", (now - DAY_SEC,)
                )
            )
            if "summary_spends" in tables
            else ()
        )
        if any(not math.isfinite(at) or at <= 0 for at in dates):
            raise ValueError("Invalid summary spend")
        answer = _summary_answer(
            config,
            dates,
            off=row is not None and row[0] == 0,
            readings_off=_readings_off(db),
            generation=row[1] if row else 0,
            notices=_notices(db) if "notice" in tables else {},
        )
        db.execute("COMMIT")
        return answer


def _readings_off(db: Any) -> bool:
    # After Pause model calls no session summary call is made either
    # (docs/design-session-summary.md#job-and-grant-contract). The summary answer stays
    # its own, so `off` still reports only that.
    tables = _permission_tables(db)
    return bool(tables) and _off(db, tables)


def _permission_tables(db: Any) -> frozenset[str]:
    return frozenset(
        name
        for (name,) in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name IN ('permission', 'provider_permission')"
        )
    )


def _summary_off(config: RuntimeConfig) -> bool:
    """The stored summary off, read without writing; false when it cannot be read."""
    if runtime_io.sqlite_module is None or not os.path.lexists(store_path(config)):
        return False
    try:
        with contextlib.closing(_connect(config, READ_WAIT_SEC)) as db:
            row = db.execute("SELECT allowed FROM summary_permission WHERE id=1").fetchone()
    except (OSError, ValueError, RuntimeError, _SQL_ERROR):
        return False
    return row is not None and row[0] == 0


def _summary_run(config: RuntimeConfig, now: float, operation: str, receipt: str = "") -> Status:
    if config.model_calls_disabled and operation not in {"off", "on", "forget"}:
        return _summary_answer(config, off=_summary_off(config), reason="run-disabled")
    try:
        if operation == "read":
            return _summary_read(config, now)
        return _summary_transaction(config, now, operation, receipt)[0]
    except (OSError, ValueError, RuntimeError, _SQL_ERROR):
        return _summary_answer(config, reason="store-unavailable")


def summary_status(config: RuntimeConfig, *, now: float) -> Status:
    """The summary grant and its own rolling ledger; never Analyze's answer."""
    if not os.path.lexists(store_path(config)) and not config.model_calls_disabled:
        return _summary_answer(config)
    return _summary_run(config, now, "read")


def set_summary_consent(config: RuntimeConfig, allowed: bool, *, now: float) -> Status:
    return _summary_run(config, now, "on" if allowed else "off")


def reserve_summary(config: RuntimeConfig, *, now: float, receipt: str) -> Status:
    """Charge an attempted part exactly once, before the model seam."""
    if not receipt:
        raise ValueError("Summary attempts require an idempotent receipt")
    return _summary_run(config, now, "reserve", receipt)


def summary_receipts(config: RuntimeConfig, job_id: str) -> int | None:
    """Recover the charges committed even if the process died before its marker rewrite."""
    try:
        with contextlib.closing(_connect(config, READ_WAIT_SEC)) as db:
            return int(
                db.execute(
                    "SELECT count(*) FROM summary_spends WHERE receipt GLOB ?", (job_id + ":*",)
                ).fetchone()[0]
            )
    except (OSError, ValueError, RuntimeError, _SQL_ERROR):
        return None


# The Live monitor's ledger: its own table in this store and its own cap, so a tick never spends
# Analyze's `DAILY_CAP` and Analyze never spends a tick's. Charged before launch and never
# refunded, as every spend here is. Timestamps only: no session identity or content enters it.
# [DEC-26](docs/design-reading-a-session.md#amended-2026-10-23-owner-the-live-level-comes-from-a-haiku-check)  # noqa: E501


def _monitor_answer(
    config: RuntimeConfig,
    dates: tuple[float, ...] = (),
    *,
    paused: bool = False,
    reason: str = "",
) -> Status:
    answer = _answer(off=paused, reason=reason)
    full = len(dates) >= config.live_monitor_daily_cap
    answer["used"] = len(dates)
    answer["limit"] = config.live_monitor_daily_cap
    answer["retry_at"] = min(dates) + DAY_SEC if full and dates else None
    answer["reason"] = reason or ("model-calls-paused" if paused else "cap" if full else "")
    return answer


def _monitor_dates(db: Any, now: float) -> tuple[float, ...]:
    dates = tuple(
        float(at)
        for (at,) in db.execute(
            "SELECT at FROM monitor_spends WHERE at > ? ORDER BY at", (now - DAY_SEC,)
        )
    )
    if any(not math.isfinite(at) or at <= 0 for at in dates):
        raise ValueError("Invalid monitor spend")
    return dates


def _monitor_transaction(config: RuntimeConfig, now: float, operation: str) -> Status:
    with contextlib.closing(
        _connect(config, READ_WAIT_SEC if operation == "read" else WRITE_WAIT_SEC)
    ) as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute("CREATE TABLE IF NOT EXISTS monitor_spends (at REAL NOT NULL)")
        db.execute("DELETE FROM monitor_spends WHERE at <= ?", (now - DAY_SEC,))
        dates = _monitor_dates(db, now)
        answer = _monitor_answer(config, dates, paused=_readings_off(db))
        if operation == "reserve" and not answer["reason"]:
            with supervise.admitting() as open_:
                if not open_:
                    db.execute("ROLLBACK")
                    return {**answer, "reason": "stopping"}
                db.execute("INSERT INTO monitor_spends VALUES (?)", (now,))
                db.execute("COMMIT")
            return {**answer, "used": answer["used"] + 1}
        db.execute("COMMIT")
        return answer


def _monitor_run(config: RuntimeConfig, now: float, operation: str) -> Status:
    refusal = (
        "run-disabled"
        if config.model_calls_disabled
        else ""
        if math.isfinite(now) and now > 0
        else "store-unavailable"
    )
    if refusal:
        return _monitor_answer(config, reason=refusal)
    if operation == "read" and not os.path.lexists(store_path(config)):
        return _monitor_answer(config)
    try:
        return _monitor_transaction(config, now, operation)
    except (OSError, ValueError, RuntimeError, _SQL_ERROR):
        return _monitor_answer(config, reason="store-unavailable")


def monitor_status(config: RuntimeConfig, *, now: float) -> Status:
    """The monitor's own rolling answer: used and limit count ticks, never Analyze's readings."""
    return _monitor_run(config, now, "read")


def reserve_monitor(config: RuntimeConfig, *, now: float) -> Status:
    """Charge one tick before launch; a refusal, a pause or a shutdown charges nothing.

    The reason is `cap` at the board-wide rolling limit, `model-calls-paused` while paused,
    `run-disabled` under `--no-observer-model` and `stopping` once the runner has shut. An
    uncertain spend is never refunded by the caller, as `reserve` never refunds one.
    """
    return _monitor_run(config, now, "reserve")
