"""The one spend ledger for DRC-4666's qualification: every model call, charged first.

The owner authorized at most twenty real Claude Code readings for this
qualification (2026-09-24), later raised the ceiling to 23 scorer calls beside
26 Claude CLI invocations, the browser walk among them (DRC-4758), and on
2026-10-01 authorized one more five-case run past it: 28 scorer calls beside 31
CLI invocations (DRC-4666). So the scorer may make 28, across every run, every
packet directory and every producer, and this file is the only thing that
counts them.

Four properties, each closing a bypass the review of 2026-09-24 reproduced:

- **One fixed path.** It never follows `COMPASS_HOME`: a per-home ledger let a
  fresh, dated packet directory start again from zero. Nor does it follow
  `HOME`: the home is the account's own, from the password database, because
  `HOME=/tmp/x` gave a fresh ledger with the real CLI in verification (V1).
  Nothing reads an environment variable for it, because an override is the
  same bypass.
- **Fail closed.** A missing file is an empty ledger. A file that cannot be
  read, or reads as anything but this module's own shape, refuses every call:
  treating it as empty overwrote twenty charges with one.
- **Locked.** The cap check and the durable charge happen under an exclusive
  lock across processes, and every write goes through its own unique temporary
  file. Two unlocked runs made 24 calls against a cap of 20.
- **Bound to one packet.** Each charge records the digest of the marks and of
  the cases and rubric it was made under, and a charge under any other digest
  is refused. A mark rewritten after an output was seen is agreement, not a
  mark, and without this the re-score left no trace.

It holds case ids, times, statuses and digests. Never a session id, a prompt, a
check's output or anything a model said.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import math
import os
import re
import stat
import sys
import tempfile
import time
import uuid
from typing import IO, TYPE_CHECKING, Any

import store_paths

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping

    from analyze_campaign import Campaign


def real_home() -> str:
    """The account's home directory, which no environment variable can move.

    Windows has no password database, so there this falls back to
    `expanduser("~")`, which `USERPROFILE` moves. `home_moved` cannot detect
    a moved Windows profile; the V1 protection holds on POSIX only.
    """
    if sys.platform == "win32":
        return os.path.expanduser("~")
    import pwd  # noqa: PLC0415 - POSIX only

    return pwd.getpwuid(os.getuid()).pw_dir


def canonical_home() -> str | None:
    """Unavailable account authority stays absent, never replaced by environment HOME."""
    try:
        home = real_home()
    except (KeyError, OSError):
        return None
    return home if home and os.path.isabs(home) else None


def canonical_path(*parts: str) -> str | None:
    home = canonical_home()
    return None if home is None else os.path.join(home, *parts)


def canonical_store_path(*parts: str) -> str | None:
    home = canonical_home()
    return None if home is None else os.path.join(store_paths.default_home(home), *parts)


# The home this study's private state was written to, and stays in (DRC-4666, 2026-10-30).
# The rename moved `store_paths.default_home` to `~/.compass` and left the native ledger, the
# shared campaign ledger with its epochs, the replay ledger and every packet here. Following
# the default home read an empty ledger beside the real one, and moving them would need
# receipts of its own. This is a fixed path, not a fallback: nothing here reads `~/.compass`,
# and a file missing here reads exactly as a missing ledger always has.
STUDY_HOME = ".cargento"


def study_path(*parts: str) -> str | None:
    """A path under the study's fixed home in the account's own directory."""
    home = canonical_home()
    return None if home is None else os.path.join(home, STUDY_HOME, *parts)


def home_moved() -> bool:
    """Whether `HOME` names another directory than the account's own."""
    home = canonical_home()
    return home is None or os.path.realpath(os.path.expanduser("~")) != os.path.realpath(home)


# In the study's fixed home in the account's directory, never under COMPASS_HOME or HOME.
LEDGER_PATH = study_path("drc-4666-spend.json")
# The committed result whose ledger chain freezes the key even if the ledger is deleted.
CLAUDE_SUMMARY_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "docs",
    "abstention",
    "claude-results.json",
)
# Reviewed handoffs, one per continuation packet, each binding the failed result
# before it without moving that result or the account-home ledger. Absence of
# the first preserves the one-packet rule. Grant k authorizes packet k, so the
# original packet is generation 0. Eleven is a bound, not a budget: the cap below
# is what limits spend, and the bound keeps the chain a fixed, readable set of
# names rather than whatever a directory listing holds. The tenth and its one funded
# retry (owner, 2026-10-30) are the last two names.
MAX_GRANTS = 11
_ABSTENTION_DIR = os.path.dirname(CLAUDE_SUMMARY_PATH)
_GRANT_SHAPED = re.compile(r"claude-continuation.*\.json", re.DOTALL)


def _numbered(stem: str, k: int) -> str:
    return os.path.join(_ABSTENTION_DIR, f"{stem}.json" if k == 1 else f"{stem}-{k}.json")


# Grant k at index k-1: claude-continuation.json, then claude-continuation-<k>.json.
CONTINUATION_PATHS = tuple(_numbered("claude-continuation", k) for k in range(1, MAX_GRANTS + 1))
# Packet k's committed result at index k-1, which grant k+1 binds.
CONTINUATION_SUMMARY_PATHS = tuple(
    _numbered("claude-results-continuation", k) for k in range(1, MAX_GRANTS + 1)
)
# 28 scorer calls across every packet: the owner's 2026-10-01 ruling (DRC-4666)
# authorized one more five-case run past the DRC-4758 ceiling of 23, beside 31
# Claude CLI invocations overall, those five and the browser walk among them.
MAX_CALLS = 28
CLOSURE_CALLS = 31
CLOSURE_CAP = MAX_CALLS + CLOSURE_CALLS
SUCCESSOR_PREVIOUS_CALLS = 30
SUCCESSOR_CAP = SUCCESSOR_PREVIOUS_CALLS + CLOSURE_CALLS
LOGIN_RESUME_PREVIOUS_CALLS = 32
LOGIN_RESUME_CAP = LOGIN_RESUME_PREVIOUS_CALLS + CLOSURE_CALLS
CLAUSE_CONTINUATION_PREVIOUS_CALLS = 34
CLAUSE_CONTINUATION_CAP = CLAUSE_CONTINUATION_PREVIOUS_CALLS + CLOSURE_CALLS
CLAUSE_ISOLATION_PREVIOUS_CALLS = 36
CLAUSE_ISOLATION_CAP = CLAUSE_ISOLATION_PREVIOUS_CALLS + CLOSURE_CALLS
CONDITIONAL_PRIORITY_PREVIOUS_CALLS = 38
CONDITIONAL_PRIORITY_CAP = CONDITIONAL_PRIORITY_PREVIOUS_CALLS + CLOSURE_CALLS
# The tenth (owner, 2026-10-30): the ninth spent 30 of its 31, so its one held retry carries
# and thirty are renewed. 68 + 31 = 99; nothing else is added.
TENTH_PREVIOUS_CALLS = 68
TENTH_CARRIED_CALLS = 1
TENTH_RENEWED_CALLS = 30
TENTH_CAP = TENTH_PREVIOUS_CALLS + CLOSURE_CALLS
STATUSES = ("charged", "ok", "failed", "unavailable")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_CASE = re.compile(r"^[0-9a-f]{16}$")
_MISSING = object()


class LedgerError(Exception):
    """The ledger refuses: unreadable, invalid, full, or another packet's."""


class SpendCapError(LedgerError):
    """The cap is reached. No further call may be made under this authorization."""


class OtherPacketError(LedgerError):
    """The ledger holds calls charged under other marks or other inputs."""


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _empty() -> dict[str, Any]:
    return {"v": 1, "calls": [], "runs": []}


def _valid_call(call: Any) -> bool:
    return (
        isinstance(call, dict)
        and isinstance(call.get("id"), str)
        and bool(call["id"])
        and isinstance(call.get("case"), str)
        and bool(_CASE.fullmatch(call["case"]))
        and isinstance(call.get("producer"), str)
        and call.get("status") in STATUSES
        and all(
            isinstance(call.get(key), str) and bool(_DIGEST.fullmatch(call[key]))
            for key in ("marks_digest", "inputs_digest")
        )
        and isinstance(call.get("at"), (int, float))
        and not isinstance(call.get("at"), bool)
        and math.isfinite(call["at"])
    )


def _valid_run(run: Any) -> bool:
    return isinstance(run, dict) and all(
        isinstance(run.get(key), str) and bool(_DIGEST.fullmatch(run[key]))
        for key in ("records_digest", "marks_digest", "inputs_digest")
    )


def read(path: str | None) -> dict[str, Any]:
    """The ledger, or `LedgerError`. Only a file that does not exist reads as empty."""
    if path is None:
        raise LedgerError("the account's canonical home is unavailable")
    try:
        with open(path, encoding="utf-8") as handle:
            body = json.load(handle)
    except FileNotFoundError:
        return _empty()
    except (OSError, ValueError, RecursionError) as error:
        msg = f"the spend ledger at {path} cannot be read ({type(error).__name__})"
        raise LedgerError(msg) from error
    calls = body.get("calls") if isinstance(body, dict) else None
    runs = body.get("runs") if isinstance(body, dict) else None
    if (
        not isinstance(body, dict)
        or body.get("v") != 1
        or not isinstance(calls, list)
        or not isinstance(runs, list)
        or not all(_valid_call(call) for call in calls)
        or not all(_valid_run(run) for run in runs)
    ):
        msg = f"the spend ledger at {path} is not one this script wrote"
        raise LedgerError(msg)
    return body


def continuation(*, generation: int | None = None) -> dict[str, Any] | None:  # noqa: C901 - validate the entire chain before selecting a historical ancestor
    """The active reviewed handoff, bound to every committed failed result before it.

    The `marking` phase names only the new case digest. Once the owner has
    agreed to every mark and rubric entry, `sealed` also names the two digests
    the scorer charges under. Neither phase by itself authorizes a real call.

    Grant k may follow continuation k-1 once that also failed. It is honoured
    only while every earlier grant is sealed and each one's `next` key is the
    following grant's `previous`, so the chain reads original, first, second
    and on with no gap. A grant whose predecessor is missing is an error, as is
    one numbered past `MAX_GRANTS`. The returned grant carries `segments`: each
    earlier packet's last call count and its key, in ledger order.
    A historical selection still validates all later grants; it is for ancestor
    inspection and does not change the active packet used by native charging.
    """
    stray = _stray_grant()
    if stray:
        msg = (
            f"{stray} is not a grant name the chain reads: claude-continuation.json, "
            f"then claude-continuation-2.json up to -{MAX_GRANTS}.json"
        )
        raise LedgerError(msg)
    if generation is not None and (
        type(generation) is not int or not 1 <= generation <= MAX_GRANTS
    ):
        raise LedgerError("the requested continuation generation is invalid")
    selected: dict[str, Any] | None = None
    active: dict[str, Any] | None = None
    for k, path in enumerate(CONTINUATION_PATHS, start=1):
        grant = _grant(path, result_path(k - 1))
        if grant is None:
            later = [n for n in range(k + 1, MAX_GRANTS + 1) if grant_exists(n)]
            if later:
                msg = f"continuation grant {later[0]} has no grant {k} before it"
                raise LedgerError(msg)
            break
        segments = [_segment(grant["previous"])]
        if active is not None:
            if active["phase"] != "sealed" or {
                key: active["next"].get(key) for key in ("marks_digest", "inputs_digest")
            } != {key: grant["previous"][key] for key in ("marks_digest", "inputs_digest")}:
                raise LedgerError(f"continuation grant {k} does not follow grant {k - 1}")
            segments = [*active["segments"], *segments]
        allowance = grant.get("closure_allowance")
        if allowance is not None:
            valid = (
                k == 4
                and isinstance(allowance, dict)
                and grant["previous"]["ledger_chain"]["calls"] == MAX_CALLS
                and all(
                    type(allowance.get(key)) is int and allowance[key] == value
                    for key, value in (
                        ("additional_calls", CLOSURE_CALLS),
                        ("previous_calls", MAX_CALLS),
                        ("repeats", 3),
                        ("retry_calls", 1),
                    )
                )
                and all(
                    isinstance(allowance.get(key), str) and _DIGEST.fullmatch(allowance[key])
                    for key in ("model_binding", "campaign_binding")
                )
            )
            if not valid:
                raise LedgerError("the closure allowance is not a bound fourth grant")
        successor = _successor_allowance(grant, k)
        login_resume = _login_resume_allowance(grant, k)
        clause_continuation = _clause_continuation_allowance(grant, k)
        clause_isolation = _clause_isolation_allowance(grant, k)
        conditional_priority = _conditional_priority_allowance(grant, k)
        tenth = _tenth_allowance(grant, k)
        authorized = list((active or {}).get("authorized_allowances", []))
        if (
            allowance
            or successor
            or login_resume
            or clause_continuation
            or clause_isolation
            or conditional_priority
            or tenth
        ):
            authorized.append(
                {
                    "next": grant["next"],
                    "allowance": allowance
                    or successor
                    or login_resume
                    or clause_continuation
                    or clause_isolation
                    or conditional_priority
                    or tenth,
                    "cap": TENTH_CAP
                    if tenth
                    else CONDITIONAL_PRIORITY_CAP
                    if conditional_priority
                    else CLAUSE_ISOLATION_CAP
                    if clause_isolation
                    else CLAUSE_CONTINUATION_CAP
                    if clause_continuation
                    else LOGIN_RESUME_CAP
                    if login_resume
                    else SUCCESSOR_CAP
                    if successor
                    else CLOSURE_CAP,
                }
            )
        grant["authorized_allowances"] = authorized
        grant["generation"] = k
        grant["segments"] = segments
        active = grant
        if generation == k:
            selected = grant
    return active if generation is None else selected


def _successor_allowance(grant: dict[str, Any], generation: int) -> dict[str, Any] | None:
    value = grant.get("successor_allowance")
    if value is None:
        return None
    if (
        grant.get("closure_allowance") is not None
        or generation != 5
        or not isinstance(value, dict)
        or set(value)
        != {
            "additional_calls",
            "previous_calls",
            "repeats",
            "retry_calls",
            "model_binding",
            "campaign_binding",
        }
        or grant["previous"]["ledger_chain"]["calls"] != SUCCESSOR_PREVIOUS_CALLS
        or any(
            type(value.get(key)) is not int or value[key] != expected
            for key, expected in (
                ("additional_calls", 31),
                ("previous_calls", 30),
                ("repeats", 3),
                ("retry_calls", 1),
            )
        )
        or any(
            not isinstance(value.get(key), str) or not _DIGEST.fullmatch(value[key])
            for key in ("model_binding", "campaign_binding")
        )
    ):
        raise LedgerError("the successor allowance is not a bound fifth grant")
    return value


def _login_resume_allowance(grant: dict[str, Any], generation: int) -> dict[str, Any] | None:
    value = grant.get("login_resume_allowance")
    if value is None:
        return None
    if (
        generation != 6
        or grant.get("closure_allowance") is not None
        or grant.get("successor_allowance") is not None
        or not isinstance(value, dict)
        or set(value)
        != {
            "additional_calls",
            "previous_calls",
            "carried_calls",
            "renewed_calls",
            "repeats",
            "retry_calls",
            "model_binding",
            "campaign_binding",
        }
        or grant["previous"]["ledger_chain"]["calls"] != LOGIN_RESUME_PREVIOUS_CALLS
        or any(
            type(value.get(k)) is not int or value[k] != expected
            for k, expected in (
                ("additional_calls", 31),
                ("previous_calls", 32),
                ("carried_calls", 29),
                ("renewed_calls", 2),
                ("repeats", 3),
                ("retry_calls", 1),
            )
        )
        or any(
            not isinstance(value.get(k), str) or not _DIGEST.fullmatch(value[k])
            for k in ("model_binding", "campaign_binding")
        )
    ):
        raise LedgerError("the login recovery allowance is not a bound sixth grant")
    return value


def _clause_continuation_allowance(grant: dict[str, Any], generation: int) -> dict[str, Any] | None:
    value = grant.get("clause_continuation_allowance")
    if value is None:
        return None
    if (
        generation != 7
        or grant.get("clause_isolation_allowance") is not None
        or grant.get("closure_allowance") is not None
        or grant.get("successor_allowance") is not None
        or grant.get("login_resume_allowance") is not None
        or not isinstance(value, dict)
        or set(value)
        != {
            "additional_calls",
            "previous_calls",
            "carried_calls",
            "renewed_calls",
            "repeats",
            "retry_calls",
            "model_binding",
            "campaign_binding",
        }
        or grant["previous"]["ledger_chain"]["calls"] != CLAUSE_CONTINUATION_PREVIOUS_CALLS
        or any(
            type(value.get(k)) is not int or value[k] != expected
            for k, expected in (
                ("additional_calls", 31),
                ("previous_calls", 34),
                ("carried_calls", 29),
                ("renewed_calls", 2),
                ("repeats", 3),
                ("retry_calls", 1),
            )
        )
        or any(
            not isinstance(value.get(k), str) or not _DIGEST.fullmatch(value[k])
            for k in ("model_binding", "campaign_binding")
        )
    ):
        raise LedgerError("the clause continuation allowance is not a bound seventh grant")
    return value


def _clause_isolation_allowance(grant: dict[str, Any], generation: int) -> dict[str, Any] | None:
    value = grant.get("clause_isolation_allowance")
    if value is None:
        return None
    if (
        generation != 8
        or grant.get("conditional_priority_allowance") is not None
        or grant.get("closure_allowance") is not None
        or grant.get("successor_allowance") is not None
        or grant.get("login_resume_allowance") is not None
        or grant.get("clause_continuation_allowance") is not None
        or not isinstance(value, dict)
        or set(value)
        != {
            "additional_calls",
            "previous_calls",
            "carried_calls",
            "renewed_calls",
            "repeats",
            "retry_calls",
            "model_binding",
            "campaign_binding",
        }
        or grant["previous"]["ledger_chain"]["calls"] != CLAUSE_ISOLATION_PREVIOUS_CALLS
        or any(
            type(value.get(k)) is not int or value[k] != expected
            for k, expected in (
                ("additional_calls", 31),
                ("previous_calls", 36),
                ("carried_calls", 29),
                ("renewed_calls", 2),
                ("repeats", 3),
                ("retry_calls", 1),
            )
        )
        or any(
            not isinstance(value.get(k), str) or not _DIGEST.fullmatch(value[k])
            for k in ("model_binding", "campaign_binding")
        )
    ):
        raise LedgerError("the clause isolation allowance is not a bound eighth grant")
    return value


def _conditional_priority_allowance(
    grant: dict[str, Any], generation: int
) -> dict[str, Any] | None:
    value = grant.get("conditional_priority_allowance")
    if value is None:
        return None
    if (
        generation != 9
        or grant.get("closure_allowance") is not None
        or grant.get("successor_allowance") is not None
        or grant.get("login_resume_allowance") is not None
        or grant.get("clause_continuation_allowance") is not None
        or grant.get("clause_isolation_allowance") is not None
        or not isinstance(value, dict)
        or set(value)
        != {
            "additional_calls",
            "previous_calls",
            "carried_calls",
            "renewed_calls",
            "repeats",
            "retry_calls",
            "model_binding",
            "campaign_binding",
        }
        or grant["previous"]["ledger_chain"]["calls"] != CONDITIONAL_PRIORITY_PREVIOUS_CALLS
        or any(
            type(value.get(k)) is not int or value[k] != expected
            for k, expected in (
                ("additional_calls", 31),
                ("previous_calls", 38),
                ("carried_calls", 29),
                ("renewed_calls", 2),
                ("repeats", 3),
                ("retry_calls", 1),
            )
        )
        or any(
            not isinstance(value.get(k), str) or not _DIGEST.fullmatch(value[k])
            for k in ("model_binding", "campaign_binding")
        )
    ):
        raise LedgerError("the conditional priority allowance is not a bound ninth grant")
    return value


# Every generation-specific allowance key; a grant carries at most one, and only its own.
ALLOWANCE_KEYS = (
    "closure_allowance",
    "successor_allowance",
    "login_resume_allowance",
    "clause_continuation_allowance",
    "clause_isolation_allowance",
    "conditional_priority_allowance",
    "tenth_continuation_allowance",
)


def _tenth_allowance(grant: dict[str, Any], generation: int) -> dict[str, Any] | None:
    """Grant 10's own allowance: the ninth's held retry carried and thirty renewed."""
    value = grant.get("tenth_continuation_allowance")
    if value is None:
        return None
    if (
        generation != 10
        or any(
            grant.get(key) is not None
            for key in ALLOWANCE_KEYS
            if key != "tenth_continuation_allowance"
        )
        or not isinstance(value, dict)
        or set(value)
        != {
            "additional_calls",
            "previous_calls",
            "carried_calls",
            "renewed_calls",
            "repeats",
            "retry_calls",
            "model_binding",
            "campaign_binding",
        }
        or grant["previous"]["ledger_chain"]["calls"] != TENTH_PREVIOUS_CALLS
        or any(
            type(value.get(k)) is not int or value[k] != expected
            for k, expected in (
                ("additional_calls", CLOSURE_CALLS),
                ("previous_calls", TENTH_PREVIOUS_CALLS),
                ("carried_calls", TENTH_CARRIED_CALLS),
                ("renewed_calls", TENTH_RENEWED_CALLS),
                ("repeats", 3),
                ("retry_calls", 1),
            )
        )
        or any(
            not isinstance(value.get(k), str) or not _DIGEST.fullmatch(value[k])
            for k in ("model_binding", "campaign_binding")
        )
    ):
        raise LedgerError("the tenth continuation allowance is not a bound tenth grant")
    return value


def closure_allowance(grant: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """Only the validated active grant chooses a legacy or successor allowance."""
    return (
        (grant or {}).get("tenth_continuation_allowance")
        or (grant or {}).get("conditional_priority_allowance")
        or (grant or {}).get("clause_isolation_allowance")
        or (grant or {}).get("clause_continuation_allowance")
        or (grant or {}).get("login_resume_allowance")
        or (grant or {}).get("successor_allowance")
        or (grant or {}).get("closure_allowance")
    )


def allowance_cap(grant: Mapping[str, Any] | None) -> int:
    """The sealed generation's ceiling, without transferring an older allowance."""
    if not grant or grant.get("phase") != "sealed" or not closure_allowance(grant):
        return MAX_CALLS
    return next(
        (
            cap
            for key, cap in (
                ("tenth_continuation_allowance", TENTH_CAP),
                ("conditional_priority_allowance", CONDITIONAL_PRIORITY_CAP),
                ("clause_isolation_allowance", CLAUSE_ISOLATION_CAP),
                ("clause_continuation_allowance", CLAUSE_CONTINUATION_CAP),
                ("login_resume_allowance", LOGIN_RESUME_CAP),
                ("successor_allowance", SUCCESSOR_CAP),
            )
            if grant.get(key)
        ),
        CLOSURE_CAP,
    )


def result_path(generation: int) -> str:
    """Packet `generation`'s committed result: the original's at 0, continuation k's at k."""
    return CLAUDE_SUMMARY_PATH if generation == 0 else CONTINUATION_SUMMARY_PATHS[generation - 1]


def grant_exists(k: int) -> bool:
    """Whether grant k's file is present at all, a symlink included."""
    return os.path.lexists(CONTINUATION_PATHS[k - 1])


def generation() -> int:
    """The highest grant present, 0 with none: the packet a fresh run would write."""
    return max((k for k in range(1, MAX_GRANTS + 1) if grant_exists(k)), default=0)


def _stray_grant() -> str:
    """A grant-shaped file the naming pattern never writes, or empty.

    Ignored, a misnamed or out-of-bound grant (`-0`, `-02`, `-10`) would leave
    an earlier grant active and select that generation's packet unnoticed.
    """
    folder = os.path.dirname(CONTINUATION_PATHS[0])
    try:
        names = os.listdir(folder)
    except OSError:
        return ""
    canonical = {os.path.basename(path) for path in CONTINUATION_PATHS}
    strays = sorted(n for n in names if _GRANT_SHAPED.fullmatch(n) and n not in canonical)
    return strays[0] if strays else ""


def _segment(previous: Mapping[str, Any]) -> list[Any]:
    return [
        previous["ledger_chain"]["calls"],
        [previous["marks_digest"], previous["inputs_digest"]],
    ]


def follows(
    calls: list[dict[str, Any]], grant: Mapping[str, Any], new_pair: tuple[str, str]
) -> bool:
    """Whether each call was charged under its packet's key, the granted packet's last."""
    start = 0
    for end, pair in grant["segments"]:
        if any([c["marks_digest"], c["inputs_digest"]] != list(pair) for c in calls[start:end]):
            return False
        start = end
    return all((c["marks_digest"], c["inputs_digest"]) == new_pair for c in calls[start:])


def _grant(path: str, failed_path: str) -> dict[str, Any] | None:
    """One grant file, checked against the failed result it continues from."""
    grant = _review_json(path, "continuation grant", cap=32 * 1024, optional=True)
    if grant is _MISSING:
        return None
    if not isinstance(grant, dict) or type(grant.get("v")) is not int or grant["v"] != 1:
        raise LedgerError("the continuation grant has an invalid version")
    phase = grant.get("phase")
    previous, next_packet = grant.get("previous"), grant.get("next")
    if (
        phase not in ("marking", "sealed")
        or not isinstance(previous, dict)
        or not isinstance(next_packet, dict)
        or not isinstance(previous.get("ledger_chain"), dict)
        or not well_formed(previous["ledger_chain"])
        or not all(
            isinstance(previous.get(key), str) and _DIGEST.fullmatch(previous[key])
            for key in ("marks_digest", "inputs_digest")
        )
        or not isinstance(next_packet.get("cases_digest"), str)
        or not _DIGEST.fullmatch(next_packet["cases_digest"])
        or (
            phase == "sealed"
            and not all(
                isinstance(next_packet.get(key), str) and _DIGEST.fullmatch(next_packet[key])
                for key in ("marks_digest", "inputs_digest")
            )
        )
    ):
        raise LedgerError("the continuation grant is malformed")
    summary = _review_json(failed_path, "prior committed result", cap=2 * 1024 * 1024)
    if (
        not isinstance(summary, dict)
        or not (
            (
                summary.get("verdict") == "failed"
                and grant.get("login_resume_allowance") is None
                and grant.get("clause_continuation_allowance") is None
                and grant.get("clause_isolation_allowance") is None
                and grant.get("conditional_priority_allowance") is None
                and grant.get("tenth_continuation_allowance") is None
            )
            or (
                path == CONTINUATION_PATHS[5]
                and grant.get("login_resume_allowance") is not None
                and summary.get("verdict") == "blocked"
                and summary.get("stopped") is True
                and isinstance(summary.get("counts"), dict)
                and type(summary["counts"].get("attempts")) is int
                and summary["counts"]["attempts"] == 2
                and type(summary["counts"].get("unusable_attempts")) is int
                and summary["counts"]["unusable_attempts"] == 2
            )
            or (
                path == CONTINUATION_PATHS[6]
                and grant.get("clause_continuation_allowance") is not None
                and summary.get("verdict") == "failed"
                and summary.get("stopped") is True
                and isinstance(summary.get("counts"), dict)
                and type(summary["counts"].get("attempts")) is int
                and summary["counts"]["attempts"] == 2
                and type(summary["counts"].get("unusable_attempts")) is int
                and summary["counts"]["unusable_attempts"] == 0
            )
            or (
                path == CONTINUATION_PATHS[7]
                and grant.get("clause_isolation_allowance") is not None
                and summary.get("verdict") == "failed"
                and summary.get("stopped") is True
                and isinstance(summary.get("counts"), dict)
                and type(summary["counts"].get("attempts")) is int
                and summary["counts"]["attempts"] == 2
                and type(summary["counts"].get("unusable_attempts")) is int
                and summary["counts"]["unusable_attempts"] == 0
            )
            or (
                path == CONTINUATION_PATHS[8]
                and grant.get("conditional_priority_allowance") is not None
                and summary.get("verdict") == "failed"
                and summary.get("stopped") is True
                and isinstance(summary.get("counts"), dict)
                and type(summary["counts"].get("attempts")) is int
                and summary["counts"]["attempts"] == 2
                and type(summary["counts"].get("unusable_attempts")) is int
                and summary["counts"]["unusable_attempts"] == 0
            )
            or (
                # The ninth measured all thirty and was not stopped (result 9, 2026-10-07).
                path == CONTINUATION_PATHS[9]
                and grant.get("tenth_continuation_allowance") is not None
                and summary.get("verdict") == "failed"
                and summary.get("stopped") is False
                and isinstance(summary.get("counts"), dict)
                and type(summary["counts"].get("attempts")) is int
                and summary["counts"]["attempts"] == 30
                and type(summary["counts"].get("unusable_attempts")) is int
                and summary["counts"]["unusable_attempts"] == 0
            )
        )
        or summary.get("producer") != "claude"
        or any(summary.get(key) != previous.get(key) for key in ("marks_digest", "inputs_digest"))
        or summary.get("ledger_chain") != previous["ledger_chain"]
    ):
        raise LedgerError("the continuation grant disagrees with the failed result")
    return grant


def _review_json(path: str, label: str, *, cap: int, optional: bool = False) -> Any:
    """Read a bounded regular repository artifact, never following a symlink."""
    if os.path.islink(path):
        raise LedgerError(f"the {label} is a symlink")
    flags = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except FileNotFoundError:
        if optional:
            return _MISSING
        raise LedgerError(f"the {label} is missing") from None
    except OSError as error:
        raise LedgerError(f"the {label} cannot be opened") from error
    try:
        with os.fdopen(descriptor, "rb") as handle:
            info = os.fstat(handle.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > cap:
                raise LedgerError(f"the {label} is not a bounded regular file")
            payload = handle.read(cap + 1)
            if len(payload) > cap:
                raise LedgerError(f"the {label} grew beyond its read bound")
            return json.loads(payload)
    except (OSError, ValueError, RecursionError) as error:
        raise LedgerError(f"the {label} cannot be read") from error


def marking_refusal(cases_digest: str, ledger_path: str | None = None) -> str:
    """Why the marker cannot write this fresh case set, or empty."""
    try:
        grant = continuation()
        if grant is None or grant["phase"] != "marking":
            return "there is no marking-phase continuation grant"
        if grant["next"]["cases_digest"] != cases_digest:
            return "this is not the case set named by the continuation grant"
        path = ledger_path or LEDGER_PATH
        prior = grant["previous"]["ledger_chain"]
        if not begins_with(path, prior):
            return "the spend ledger no longer begins with the failed result's chain"
        if len(read(path)["calls"]) != prior["calls"]:
            return "a continuation call has already been charged"
    except LedgerError as error:
        return str(error)
    return ""


def _lock_file(handle: IO[bytes]) -> None:
    if sys.platform == "win32":
        import msvcrt  # noqa: PLC0415 - Windows only

        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
    else:
        import fcntl  # noqa: PLC0415 - POSIX only

        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)


def _unlock_file(handle: IO[bytes]) -> None:
    if sys.platform == "win32":
        import msvcrt  # noqa: PLC0415 - Windows only

        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl  # noqa: PLC0415 - POSIX only

        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@contextlib.contextmanager
def locked(path: str) -> Iterator[None]:
    """An exclusive lock on a sidecar file, held across processes."""
    os.makedirs(os.path.dirname(path) or ".", mode=0o700, exist_ok=True)
    with open(f"{path}.lock", "a+b") as handle:
        _lock_file(handle)
        try:
            yield
        finally:
            _unlock_file(handle)


def _write(path: str, body: Mapping[str, Any]) -> None:
    """Durably, through a temporary file no other writer shares."""
    folder = os.path.dirname(path) or "."
    descriptor, tmp = tempfile.mkstemp(prefix=".spend-", suffix=".tmp", dir=folder)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(body, handle, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


class Ledger:
    """The ledger as one packet sees it: its digests, and the cap it runs under."""

    def __init__(
        self,
        path: str | None,
        *,
        cap: int,
        marks_digest: str,
        inputs_digest: str,
        producer: str,
        cases_digest: str = "",
        model_binding: str = "",
        campaign: Campaign | None = None,
    ) -> None:
        if path is None:
            raise LedgerError("the account's canonical home is unavailable")
        self.path = path
        self.requested_cap = min(cap, TENTH_CAP)
        self.model_binding = model_binding
        self.campaign = campaign
        self.marks_digest = marks_digest
        self.inputs_digest = inputs_digest
        self.producer = producer
        self.cases_digest = cases_digest

    @property
    def cap(self) -> int:
        """Each key keeps its own generation's cap; only the bound tenth key admits 99."""
        try:
            grant = continuation()
        except LedgerError:
            return min(self.requested_cap, MAX_CALLS)
        if grant and grant["phase"] == "sealed":
            for admitted in reversed(grant["authorized_allowances"]):
                if (
                    self.model_binding == admitted["allowance"]["model_binding"]
                    and self.marks_digest == admitted["next"].get("marks_digest")
                    and self.inputs_digest == admitted["next"].get("inputs_digest")
                    and self.cases_digest == admitted["next"].get("cases_digest")
                    and self.producer == "claude"
                    and (
                        admitted["cap"]
                        not in (
                            LOGIN_RESUME_CAP,
                            CLAUSE_CONTINUATION_CAP,
                            CLAUSE_ISOLATION_CAP,
                            CONDITIONAL_PRIORITY_CAP,
                            TENTH_CAP,
                        )
                        or (
                            self.campaign is not None
                            and self.campaign.binding == admitted["allowance"]["campaign_binding"]
                        )
                    )
                ):
                    return min(self.requested_cap, int(admitted["cap"]))
        return min(self.requested_cap, MAX_CALLS)

    def _refuse_other(self, body: Mapping[str, Any]) -> None:
        grant = continuation()
        if grant is not None:
            prior = grant["previous"]["ledger_chain"]
            if not begins_with(self.path, prior):
                raise OtherPacketError("the spend ledger lost the failed result's chain")
            if grant["phase"] != "sealed":
                raise OtherPacketError("the new packet's marks and rubric are not sealed")
            allowance = closure_allowance(grant)
            if allowance and (
                self.producer != "claude" or self.model_binding != allowance["model_binding"]
            ):
                raise OtherPacketError("the model differs from the closure allowance")
            next_packet = grant["next"]
            if (self.marks_digest, self.inputs_digest) != (
                next_packet["marks_digest"],
                next_packet["inputs_digest"],
            ) or self.cases_digest != next_packet["cases_digest"]:
                raise OtherPacketError("the packet differs from the sealed continuation grant")
            if not follows(body["calls"], grant, (self.marks_digest, self.inputs_digest)):
                raise OtherPacketError("the spend ledger is not the authorized old and new packets")
            return
        for call in body["calls"]:
            if (call["marks_digest"], call["inputs_digest"]) != (
                self.marks_digest,
                self.inputs_digest,
            ):
                msg = "the spend ledger holds calls charged under other marks or other cases"
                raise OtherPacketError(msg)

    def check(self) -> str:
        """Empty when this packet may be scored, else why not."""
        try:
            body = read(self.path)
            self._refuse_other(body)
        except LedgerError as error:
            return str(error)
        if len(body["calls"]) >= self.cap:
            return f"the spend ledger already holds {len(body['calls'])} of {self.cap} calls"
        return ""

    def used(self) -> int:
        return len(read(self.path)["calls"])

    def charge(
        self,
        case_id: str,
        *,
        repeat: int = 1,
        retry: bool = False,
        request_binding: str = "",
    ) -> str:
        """Charge one call before it runs, or raise. Returns the charge's id."""
        with locked(self.path):
            body = read(self.path)
            self._refuse_other(body)
            if len(body["calls"]) >= self.cap:
                raise SpendCapError
            grant = continuation()
            allowance = closure_allowance(grant)
            extra: dict[str, Any] = {}
            if allowance:
                if (
                    not self.campaign
                    or self.campaign.binding != allowance["campaign_binding"]
                    or type(repeat) is not int
                    or not 1 <= repeat <= 3
                    or not isinstance(case_id, str)
                    or not _CASE.fullmatch(case_id)
                    or not isinstance(request_binding, str)
                    or not _DIGEST.fullmatch(request_binding)
                ):
                    raise LedgerError("the closure call has no bound campaign exposure")
                slot = f"{case_id}:r{repeat}"
                reserved = self.campaign.reserve(
                    "qualification", slot, request_binding, retry=retry
                )
                extra = {"repeat": repeat, "retry": retry, "campaign_charge": reserved}
            charge_id = uuid.uuid4().hex
            body["calls"].append(
                {
                    "id": charge_id,
                    "at": time.time(),
                    "case": case_id,
                    "producer": self.producer,
                    "status": "charged",
                    "marks_digest": self.marks_digest,
                    "inputs_digest": self.inputs_digest,
                    **extra,
                }
            )
            _write(self.path, body)
        return charge_id

    def settle(self, charge_id: str, status: str) -> None:
        """Record how a charged call ended, re-reading under the lock first."""
        reserved = ""
        with locked(self.path):
            body = read(self.path)
            for call in body["calls"]:
                if call["id"] == charge_id:
                    if call.get("campaign_charge") and call["status"] != "charged":
                        raise LedgerError("the closure transport was already classified")
                    call["status"] = status if status in STATUSES else "failed"
                    reserved = str(call.get("campaign_charge") or "")
            _write(self.path, body)
        if reserved and status != "ok":
            if not self.campaign:
                raise LedgerError("the closure transport lost its campaign")
            self.campaign.settle(reserved, "unusable")

    def finish_exposure(self, charge_id: str, status: str) -> None:
        """Classify parsed/rubric evidence before the next campaign subprocess."""
        body = read(self.path)
        call = next((c for c in body["calls"] if c["id"] == charge_id), None)
        if not call or not call.get("campaign_charge") or not self.campaign:
            raise LedgerError("the closure exposure is not a charged campaign call")
        if call["status"] == "ok":
            self.campaign.settle(call["campaign_charge"], status)

    def record_run(self, records_digest: str) -> None:
        """What a finished run wrote, so a resume can prove its records are that run's."""
        with locked(self.path):
            body = read(self.path)
            body["runs"].append(
                {
                    "at": time.time(),
                    "records_digest": records_digest,
                    "marks_digest": self.marks_digest,
                    "inputs_digest": self.inputs_digest,
                }
            )
            _write(self.path, body)

    def last_run(self) -> dict[str, Any] | None:
        runs = read(self.path)["runs"]
        return dict(runs[-1]) if runs else None


def chain(calls: Any) -> str:
    """A hash chain over charges in order: each link hashes the last with the next charge.

    A charge is its id and the two digests it was charged under, so rewriting a
    call's `marks_digest` in place breaks the chain as surely as replacing the
    call (V3e): with ids alone, a re-marked key and a re-digested ledger agreed.
    """
    link = hashlib.sha256(b"drc-4666").hexdigest()
    for call in calls:
        part = f"{call['id']}|{call['marks_digest']}|{call['inputs_digest']}"
        link = hashlib.sha256(f"{link}:{part}".encode()).hexdigest()
    return link


def chain_of(path: str) -> dict[str, Any]:
    """What a committed result records of the ledger: the first charge, the count, the head."""
    calls = read(path)["calls"]
    return {"first": calls[0]["id"] if calls else "", "calls": len(calls), "head": chain(calls)}


def begins_with(path: str | None, committed: Mapping[str, Any]) -> bool:
    """Whether the ledger still starts with the chain a committed result recorded.

    A deleted or replaced ledger reads as empty or as another run's, and a
    key re-marked into it would score fresh (V3). The committed chain is what
    survives the deletion, in git beside the result.
    """
    if not well_formed(committed):
        return False
    count = committed["calls"]
    try:
        calls = read(path)["calls"]
    except LedgerError:
        return False
    if count == 0:
        # A result that spent nothing covers no charge, so a ledger holding one
        # holds a run that result never saw.
        return not calls
    return (
        len(calls) >= count
        and calls[0]["id"] == committed.get("first")
        and chain(calls[:count]) == committed.get("head")
    )


def well_formed(committed: Mapping[str, Any]) -> bool:
    """Whether a committed chain is one `chain_of` could have written (N4).

    A count that is not a non-negative int was once read as "nothing to check",
    so a chain edited to 0, -1, "1" or 1.0 unfroze the key. A zero count is
    accepted only as the empty chain itself.
    """
    count, first, head = committed.get("calls"), committed.get("first"), committed.get("head")
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        return False
    if not isinstance(first, str) or not isinstance(head, str):
        return False
    if count == 0:
        return first == "" and head == chain([])
    return bool(first)


def committed_chain(summary_path: str = "") -> dict[str, Any] | None:
    """The ledger chain a committed Claude Code result recorded.

    None only when there is no result at all. A result with no chain reads as
    `{}`, which the scorer refuses (V3d): every result this scorer writes
    carries one, so a result without one was edited.
    """
    try:
        with open(summary_path or CLAUDE_SUMMARY_PATH, encoding="utf-8") as handle:
            body = json.load(handle)
    except FileNotFoundError:
        return None
    except (OSError, ValueError, RecursionError):
        # A result that cannot be read cannot vouch that the key is unfrozen.
        return {"first": "", "calls": 1, "head": ""}
    held = body.get("ledger_chain") if isinstance(body, dict) else None
    return dict(held) if isinstance(held, dict) else {}


def has_calls(path: str | None = "") -> bool:
    """Whether any call is charged. An unreadable ledger answers yes: fail closed."""
    try:
        return bool(read(path or LEDGER_PATH)["calls"])
    except LedgerError:
        return True
