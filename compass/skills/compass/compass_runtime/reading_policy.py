"""Remembered reading permission and durable, atomic rolling spend admission.

The transaction is the bound on concurrent tabs and daemons, not the browser's
button state. No session identities or content enter this store.
See [DEC-21](docs/design-reading-a-session.md#dec-21-a-reading-works-the-first-time-you-ask).
"""

from __future__ import annotations

import contextlib
import math
import os
import time
from typing import TYPE_CHECKING, Any, NotRequired, TypedDict

from . import io as runtime_io
from . import supervise

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
# routes and the unasked lane retain epoch 1. Reader-started calls renew the notice when
# the epoch changes; Codex unasked calls retain the explicit coverage boundary.
CONTENT_VERSION = 4
WORDS_CONTENT_VERSION = 1
NOTICE_KINDS = ("reading", "goal", "summary")
CONTENT_CHANGED = "What a reading sends has changed since you allowed this, so allow it again."


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


def _transaction(
    config: RuntimeConfig,
    now: float,
    operation: str | Notice,
    provider: str,
    tool_output: str = "",
    job_id: str = "",
    today: Mapping[str, str] | None = None,
    content: int = CONTENT_VERSION,
) -> tuple[Status, Notice | None]:
    if not math.isfinite(now) or now <= 0:
        return _answer(reason="store-unavailable"), None
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
        if operation == "reserve" and not answer["reason"]:
            return _commit_charge(db, answer, now, job_id), None
        db.execute("COMMIT")
        return answer, recorded


def _commit_charge(db: Any, answer: Status, now: float, job_id: str) -> Status:
    """Insert the charge and its job, and commit, unless the runner has shut.

    Under the lock a shutdown takes (DRC-4712). The wait for SQLite's write
    lock is already behind this, so `kill_all` waits one commit at most, and
    it never touches SQLite, so the two locks cannot be taken in both orders.
    """
    with supervise.admitting() as open_:
        if not open_:
            db.execute("ROLLBACK")
            return {**answer, "reason": "stopping"}
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
    ) -> None:
        self.config = config
        self.content = content
        self.unasked = unasked
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

    def __call__(self, prompt: str, *, output_cap_bytes: int) -> tuple[str, str]:
        available = getattr(self.model, "available", None)
        if available is not None and not available():
            return "", "unavailable"
        if supervise.closed():
            # Compass is stopping and the call could never be sent, so it is
            # refused before the reservation rather than charged (verify N4).
            return "", "closed"
        if self.cancelled is not None and self.cancelled():
            return "", "cancelled"
        if self.resolve_destination is not None and self.resolve_destination() != self.destination:
            # The press-time notice cannot cover a destination that moved mid-job.
            raise RefusedError(_answer(reason=DESTINATION_MOVED))
        if self.unasked:
            answer = unasked_status(
                self.config, now=self.clock(), provider=self.provider, destination=self.destination
            )
            if answer["reason"]:
                raise RefusedError(answer)
            return self.model(prompt, output_cap_bytes=output_cap_bytes)
        job_id = self.before_reserve() if self.before_reserve is not None else None
        answer = reserve(
            self.config,
            now=self.clock(),
            provider=self.provider,
            job_id=job_id or "",
            destination=self.destination,
            content=self.content,
        )
        if answer["reason"] == "stopping":
            # The shutdown reached the reservation before its commit, so the
            # call is the stop the early look above would have refused.
            return "", "closed"
        if answer["reason"]:
            raise RefusedError(answer)
        if self.on_reserved is not None:
            self.on_reserved()
        return self.model(prompt, output_cap_bytes=output_cap_bytes)


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
        answer, recorded = (
            _summary_transaction(config, now, notice)
            if kind == "summary"
            else _transaction(config, now, notice, provider)
        )
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
