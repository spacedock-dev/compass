#!/usr/bin/env python3
"""The answer key for "does each drift level mean the same thing every time".

DRC-4692 validates the two level functions of DEC-26 against recorded Claude Code sessions. The
owner marks the level each case should get BEFORE any rule is scored against it, and the marks'
digest is committed first, because a mark written after seeing an output is agreement, not a mark.
This follows `mark_abstention.py` and `score_abstention.py`, and keeps their split:

    levels_cases.py --build SPEC   freeze cases from recorded transcripts, under ~/.compass
    levels_cases.py                mark the unmarked ones, one level per source per case
    levels_cases.py --report       how far through the key you are; scores nothing
    levels_cases.py --read --reading-home DIR [--case ID ...] [--dry-run]
                                   replay the frozen cases through the board's reading producer
    levels_cases.py --score        run both functions against the marks, write the summary

The spec is a local file the owner writes, one entry per case: its kind from the closed set
below, the transcript it is drawn from, an optional `until` (a Unix time; the transcript is cut
there, which is how a session that later passed keeps a failed-check case frozen before the
second turn DRC-4673 gave it), the intent as a separate yardstick, how many later directions stand
unsettled, and an optional stored reading for the analysis source. Nothing is defaulted: an entry
missing the intent or the direction count is refused, because a default there is the author's thumb
on the case.

The cases carry recorded check lines and written paths, so they stay under `~/.compass`, never in
the repository. What is committed is the marks' digest (`docs/drift-levels/marks-digest.json`) and
the scored summary (`docs/drift-levels/results.json`): case ids, kinds, marks, levels, reason
tokens and outcomes, and never a session id, a path, a command, the intent's words, a fact id or
model prose. SECURITY.md's abstention-check section names this second committed half.

Scoring calls no model. Both functions are pure over the frozen facts, so `--score` spends nothing
and can be re-run; it refuses a pass when the marks no longer hash to the committed digest.

`--read` is the one mode that calls a model, and only on the owner's go-ahead: it hands each
chosen case's frozen facts and intent to `reading.produce` over the Codex route, charged on the
reading home's own ledger, and writes what `--attach-readings` takes. `docs/drift-levels/README.md`
says why it replays rather than presses a live board, and what the replay row is.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import time
import uuid
from typing import TYPE_CHECKING, Any

import abstention_ledger
import store_paths

if TYPE_CHECKING:
    from collections.abc import Mapping

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SKILL = os.path.join(_ROOT, "compass", "skills", "compass")


def _runtime() -> tuple[Any, Any, Any]:
    """(config, project_context, levels), reached the way `mark_abstention` reaches `reading`.

    Deferred for the reason given there: `scripts` is on mypy's path and a package to the tests,
    and a top-level runtime import makes this module resolvable under two names.
    """
    if _SKILL not in sys.path:
        sys.path.insert(0, _SKILL)
    from compass_runtime import config, levels, project_context  # noqa: PLC0415

    return config, project_context, levels


HOME = store_paths.store_home()
SUBDIR = "drift-levels"
DIGEST_PATH = os.path.join(_ROOT, "docs", "drift-levels", "marks-digest.json")
RESULTS_PATH = os.path.join(_ROOT, "docs", "drift-levels", "results.json")

# The Codex analysis cohort is a second, separate check: its own packet folder, its own committed
# digest and result, and no Claude case, mark or reading in any of them.
COHORT_CLAUDE = "claude"
COHORT_CODEX = "codex"
CODEX_SUBDIR = "drift-levels-codex"
CODEX_DIGEST_PATH = os.path.join(_ROOT, "docs", "drift-levels", "codex-marks-digest.json")
CODEX_RESULTS_PATH = os.path.join(_ROOT, "docs", "drift-levels", "codex-results.json")
CODEX_MAX_CASES = 12
# The kinds the cohort's matrix is drawn from (docs/drift-levels/README.md, the Codex cohort).
# The spec declares which of them it covers before any output, and the digest binds that choice.
CODEX_KINDS = (
    "admissible-support",
    "unrelated-or-partial-check",
    "stale-pass",
    "failure-timing",
    "missing-citation",
    "legitimate-change",
    "misleading-claim",
    "insufficient-evidence",
    "goal-only",
    "other",
)
REPLAY_ALLOWANCE_MAX = 12

# The case kinds DRC-4692 and its case map name. Closed, because the kind is
# copied into the committed summary and a hand-typed value must not be.
KINDS = (
    "failed-check",
    "check-not-recorded",
    "pass-then-write",
    "pass-older-than-read",
    "own-account-only",
    "intent-names-no-folder",
    "draft-unsaved",
    "work-left-out",
    "later-direction",
    "other",
)

# One key per level, and no key for "the same as last time".
KEYS = {
    "n": "none_or_low",
    "m": "medium",
    "h": "high",
    "e": "extreme",
    "x": "not_enough",
    "d": "no_live_level",
}
LABELS = {
    "none_or_low": "None or low",
    "medium": "Medium",
    "high": "High",
    "extreme": "Extreme",
    "not_enough": "Not enough recorded yet",
    "no_live_level": "No live level (Save your intent to see a live estimate)",
}

MATCH = "match"
CAUTIOUS = "more-cautious"
FAILED = "failed"
VERDICT_PASSED = "passed"
VERDICT_FAILED = "failed"
VERDICT_STALE = "stale"
VERDICT_UNMARKED = "unmarked"

_SCALE = ("none_or_low", "medium", "high", "extreme")
# An analysis has no "no live level": that answers only a draft, on the live side.
ANALYSIS_LEVELS = frozenset(LABELS) - {"no_live_level"}
VERDICT_REFUSED = "refused"
# A Codex cohort that scored what it had, but not every case it fixed before any output.
VERDICT_INCOMPLETE = "incomplete"


def _paths(home: str, cohort: str = COHORT_CLAUDE) -> dict[str, str]:
    base = os.path.join(home, CODEX_SUBDIR if cohort == COHORT_CODEX else SUBDIR)
    return {
        "dir": base,
        "cases": os.path.join(base, "cases.json"),
        "marks": os.path.join(base, "marks.json"),
        "sha": os.path.join(base, "marks.sha256"),
        "readings": os.path.join(base, "readings.json"),
        # What `--read` wrote: the `--attach-readings` spec, and its own
        # record of every case it was asked for, read or refused.
        "replayed": os.path.join(base, "replayed-readings.json"),
        "replay": os.path.join(base, "replay.json"),
    }


def digest(body: Any) -> str:
    """A canonical hash of a JSON body, binding marks to the cases the marker saw."""
    encoded = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def case_id(sid: str, until: float | None, kind: str, harness: str = "claude") -> str:
    """Stable over identity, cut and kind, and nothing readable.

    One session stands for more than one case (one of the frozen sessions is both
    a check with no recorded result and work left out), so the kind and the cut
    are part of it. The harness leads the hash, so one session id can never name a Claude
    case and a Codex case alike; the Claude default is the string every id was made from.
    """
    return hashlib.sha256(f"{harness}|{sid}|{until}|{kind}".encode()).hexdigest()[:16]


def _write(path: str, body: Any) -> None:
    """Atomically and private: these files name sessions."""
    os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(body, handle, indent=2, sort_keys=True)
        handle.write("\n")
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def _load(path: str) -> dict[str, Any]:
    try:
        with open(path, encoding="utf-8") as handle:
            body = json.load(handle)
    except (OSError, ValueError):
        return {}
    return body if isinstance(body, dict) else {}


def _inside(path: str, root: str) -> bool:
    path, root = os.path.realpath(path), os.path.realpath(root)
    return path == root or path.startswith(root + os.sep)


def _number(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None


def _intent_ok(intent: Any) -> bool:
    return (
        isinstance(intent, dict)
        and isinstance(intent.get("saved"), bool)
        and isinstance(intent.get("goal"), str)
        and isinstance(intent.get("lines"), list)
        and all(isinstance(line, str) for line in intent["lines"])
    )


def _count_ok(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _refusal(entry: Any) -> str:
    """Why a spec entry cannot be a case, or empty. Nothing is defaulted."""
    if not isinstance(entry, dict):
        return "not an object"
    transcript = entry.get("transcript")
    until = entry.get("until", False)
    checks = (
        (
            entry.get("harness", "claude") == "claude",
            "a Codex entry belongs in a Codex cohort (--cohort codex)",
        ),
        (entry.get("kind") in KINDS, f"kind must be one of {', '.join(KINDS)}"),
        (
            isinstance(transcript, str) and os.path.isfile(transcript),
            "transcript must name a recorded Claude Code .jsonl file",
        ),
        (
            until is None or _number(until) is not None,
            "until must be a Unix time, or null for the whole transcript",
        ),
        (
            _intent_ok(entry.get("intent")),
            "intent must carry saved (true or false), goal and lines",
        ),
        (
            _count_ok(entry.get("unsettled_directions")),
            "unsettled_directions must be a count, written by hand",
        ),
        (
            "reading" not in entry,
            "a reading is attached after the marks are committed, with --attach-readings",
        ),
    )
    return next((why for holds, why in checks if not holds), "")


_CODEX_SOURCE_KEYS = (
    "harness",
    "sid",
    "sessions_root",
    "transcript",
    "children",
    "captured_at",
    "intent",
    "row",
)


def _codex_refusal(entry: Any) -> str:
    """Why a Codex spec entry cannot be a case, or empty. Nothing is defaulted.

    This only checks what the owner wrote by hand. Identity, descendants, the capture prefix and
    the lifecycle are rebuilt from the recorded sources at freeze time and refused there.
    """
    if not isinstance(entry, dict):
        return "not an object"
    children = entry.get("children")
    checks = (
        (entry.get("harness") == "codex", "harness must be codex in a Codex cohort"),
        (entry.get("kind") in CODEX_KINDS, f"kind must be one of {', '.join(CODEX_KINDS)}"),
        (
            isinstance(entry.get("transcript"), str) and os.path.isfile(entry["transcript"]),
            "transcript must name a recorded Codex rollout file",
        ),
        (isinstance(entry.get("sessions_root"), str), "sessions_root must be written by hand"),
        (
            isinstance(children, list) and all(isinstance(c, str) for c in children),
            "children must list every child rollout, or be empty",
        ),
        (_number(entry.get("captured_at")) is not None, "captured_at must be a Unix time"),
        (
            isinstance(entry.get("intent"), dict) and isinstance(entry.get("row"), dict),
            "intent and row must be recorded objects",
        ),
        (
            _count_ok(entry.get("unsettled_directions")),
            "unsettled_directions must be a count, written by hand",
        ),
        ("until" not in entry, "a Codex case is cut at captured_at, never at until"),
        (
            "reading" not in entry,
            "a reading is attached after the marks are committed, with --attach-readings",
        ),
    )
    return next((why for holds, why in checks if not holds), "")


def _codex_sources() -> Any:
    """`codex_case_sources`, loaded after the runtime path is set, as `_runtime` is."""
    _runtime()
    import codex_case_sources  # noqa: PLC0415

    return codex_case_sources


def _cut(source: str, until: float, into: str) -> str:
    """The transcript as it stood at `until`: every record timed after it dropped.

    A call made before the cut whose result arrived after it then reads as no
    recorded result, which is what the session showed at that moment.
    """
    _config, project_context, _levels = _runtime()
    path = os.path.join(into, "cut.jsonl")
    with (
        open(source, encoding="utf-8", errors="replace") as reader,
        open(path, "w", encoding="utf-8") as writer,
    ):
        for line in reader:
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if not isinstance(record, dict):
                continue
            at = project_context._record_timestamp(record)  # noqa: SLF001 - the scan's own clock
            if at is not None and at <= until:
                writer.write(line if line.endswith("\n") else line + "\n")
    return path


def _freeze(config: Any, entry: Mapping[str, Any], scratch: str) -> dict[str, Any]:
    """Layer 1's published facts and full-scan counts, exactly as the runtime builds them."""
    _config, project_context, _levels = _runtime()
    source = str(entry["transcript"])
    sid = pathlib.Path(source).stem
    until = _number(entry["until"])
    path = _cut(source, until, scratch) if until is not None else source
    rows, scan = project_context.claude_tool_reports(config, path, sid)
    facts = [
        project_context._semantic_fact_from_event(row, row["kind"], "tool_report", "")  # noqa: SLF001
        for row in rows
    ]
    captured = until if until is not None else max((float(r["at"]) for r in rows), default=None)
    cwd = next((str(r["cwd"]) for r in _records(path) if isinstance(r.get("cwd"), str)), "")
    intent = entry["intent"]
    return {
        "id": case_id(sid, until, str(entry["kind"])),
        "kind": entry["kind"],
        "harness": "claude",
        "sid": sid,
        "transcript": source,
        "until": until,
        "captured_at": captured,
        "facts": facts,
        "scan": dict(scan),
        "intent": {
            "saved": intent["saved"],
            "goal": intent["goal"],
            "lines": list(intent["lines"]),
        },
        "unsettled_directions": entry["unsettled_directions"],
        "cwd": cwd,
    }


def _freeze_codex(config: Any, entry: Mapping[str, Any]) -> dict[str, Any]:
    """The approved frozen Codex case, plus the facts and counts the level functions read.

    The sealed source case is rebuilt, never trusted, by `codex_case_sources.freeze_case`. The
    levels fields are then derived from the same bounded prefixes, children included.
    """
    sources = _codex_sources()
    _config_mod, project_context, _levels = _runtime()
    source = {key: entry[key] for key in _CODEX_SOURCE_KEYS if key in entry}
    sealed = sources.freeze_case(config, source)
    _root, path, children = sources._selection(config, source)  # noqa: SLF001 - its own rebuild
    captured = float(sealed["captured_at"])
    with project_context.frozen_codex_sources(
        config, str(path), until=captured, child_paths=[str(p) for p in children]
    ) as (cut, cuts):
        rows, scan = project_context.codex_tool_reports(
            config, cut, str(sealed["sid"]), child_paths=cuts
        )
        meta = next(
            (r.get("payload") for r in _records(cut) if r.get("type") == "session_meta"), None
        )
    cwd = meta.get("cwd") if isinstance(meta, dict) else ""
    facts = [
        project_context._semantic_fact_from_event(row, row["kind"], "tool_report", "")  # noqa: SLF001
        for row in rows
    ]
    return {
        **sealed,
        "id": case_id(str(sealed["sid"]), captured, str(entry["kind"]), "codex"),
        "kind": entry["kind"],
        "until": None,
        "facts": facts,
        "scan": dict(scan),
        "unsettled_directions": entry["unsettled_directions"],
        "cwd": cwd if isinstance(cwd, str) and os.path.isabs(cwd) else "",
    }


def _records(path: str) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    with open(path, encoding="utf-8", errors="replace") as handle:
        for line in handle:
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if isinstance(record, dict):
                found.append(record)
    return found


def _config() -> Any:
    config_mod, _project_context, _levels = _runtime()
    return config_mod.build_runtime_config(
        environ=os.environ,
        platform_name=sys.platform,
        os_name=os.name,
        launcher_path=pathlib.Path(_SKILL, "server.py"),
    )


_FREEZE_ERRORS = (OSError, ValueError, KeyError, TypeError, RuntimeError, AttributeError)


def _matrix_refusal(spec: Mapping[str, Any], entries: list[Any]) -> str:
    """Why a Codex spec's declared matrix cannot stand, or empty.

    The matrix is the owner's statement, before any output, of which kinds the cohort covers.
    Every declared kind needs a case, and every case needs a declared kind.
    """
    matrix = spec.get("matrix")
    if not isinstance(matrix, list) or not matrix or not all(k in CODEX_KINDS for k in matrix):
        return f"the spec must declare a matrix drawn from {', '.join(CODEX_KINDS)}"
    if spec.get("cohort") != COHORT_CODEX:
        return "the spec must name cohort codex"
    if len(entries) > CODEX_MAX_CASES:
        return f"a Codex cohort is at most {CODEX_MAX_CASES} cases"
    kinds = {e.get("kind") for e in entries if isinstance(e, dict)}
    if kinds - set(matrix):
        return "a case has a kind the matrix did not declare"
    if set(matrix) - kinds:
        return "the matrix declares a kind no case covers"
    return ""


def build(  # noqa: C901, PLR0911 - one refusal per way a spec cannot be frozen
    spec_path: str | os.PathLike[str],
    *,
    home: str,
    repo_root: str,
    say: Any,
    cohort: str = COHORT_CLAUDE,
) -> int:
    """Freeze every spec entry into `<home>/drift-levels[-codex]/cases.json`."""
    codex = cohort == COHORT_CODEX
    paths = _paths(home, cohort)
    if _inside(paths["dir"], repo_root):
        say(f"{paths['dir']} is inside the repository. The cases name sessions and stay local.")
        say("Set COMPASS_HOME outside it, or leave it unset for ~/.compass.")
        return 2
    spec = _load(str(spec_path))
    entries = spec.get("cases") if spec.get("v") == 1 else None
    if not isinstance(entries, list) or not entries:
        say(f"No cases in {spec_path}: it wants {{'v': 1, 'cases': [...]}}.")
        return 1
    refused = [(n, _codex_refusal(e) if codex else _refusal(e)) for n, e in enumerate(entries, 1)]
    refused = [(n, why) for n, why in refused if why]
    for number, why in refused:
        say(f"  case {number}: {why}")
    matrix = _matrix_refusal(spec, entries) if codex else ""
    if matrix:
        say(f"  {matrix}")
    if refused or matrix:
        say("Nothing was written.")
        return 1
    config = _config()
    if codex:
        try:
            cases = [_freeze_codex(config, entry) for entry in entries]
        except (_codex_sources().marker.FreezeError, *_FREEZE_ERRORS) as error:
            # Only a freeze token is a closed phrase; another error's text may carry a path.
            marker_error = _codex_sources().marker.FreezeError
            why = str(error) if isinstance(error, marker_error) else type(error).__name__
            say(f"  a source, lifecycle or selection is unconfirmed ({why}). Nothing was written.")
            return 1
    else:
        with tempfile.TemporaryDirectory(dir=_ensure(paths["dir"])) as scratch:
            cases = [_freeze(config, entry, scratch) for entry in entries]
    ids = [case["id"] for case in cases]
    if len(set(ids)) != len(ids):
        say("Two entries are the same case (session, cut and kind). Nothing was written.")
        return 1
    held = _load(paths["marks"]).get("marks") or {}
    orphans = [k for k in held if k not in set(ids)]
    if orphans:
        say(f"{len(orphans)} existing marks name cases this build does not include.")
        say("Move the marks aside first; a build never deletes them.")
        return 1
    body: dict[str, Any] = {"v": 1, "cases": cases}
    if codex:
        body = {
            "v": 1,
            "cohort": COHORT_CODEX,
            "matrix": sorted(set(spec["matrix"])),
            "cases": cases,
        }
    _write(paths["cases"], body)
    kinds = sorted({str(c["kind"]) for c in cases})
    say(f"Built {len(cases)} cases ({', '.join(kinds)}) at {paths['cases']}.")
    say("It stays on this machine and is never committed.")
    return 0


def _ensure(path: str) -> str:
    os.makedirs(path, mode=0o700, exist_ok=True)
    return path


def _clip(value: Any, limit: int) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _saved(case: Mapping[str, Any]) -> bool:
    """Whether the intent was saved. A Codex case freezes a saved revision only."""
    return case.get("harness") == "codex" or (case.get("intent") or {}).get("saved") is True


def _show(case: Mapping[str, Any], position: str, say: Any) -> None:
    """One self-contained screen: the intent, the frozen record, and nothing the rules concluded."""
    captured = _number(case.get("captured_at")) or 0.0
    intent = case.get("intent") or {}
    say("\n" + "=" * 72)
    say(f"  {position}   case {case['id']}   kind: {case['kind']}")
    state = "SAVED" if _saved(case) else "DRAFTED, NEVER SAVED"
    say(f"\n  INTENT ({state})\n    Goal: {_clip(intent.get('goal'), 200)}")
    for number, line in enumerate(intent.get("lines") or [], 1):
        say(f"    {number}. {_clip(line, 200)}")
    if not intent.get("lines"):
        say("    (no expected-outcome line)")
    say(f"  Unsettled later directions: {case.get('unsettled_directions')}")
    say("\n  RECORDED CHECKS AND WRITES (seconds before the cut)")
    for fact in case.get("facts") or []:
        ago = captured - (_number(fact.get("at")) or captured)
        if fact.get("subject") == "check":
            extra = ", passed before a later change" if fact.get("before_last_change") else ""
            extra += (
                ", a command after it may have changed files" if fact.get("changed_after") else ""
            )
            extra += ", work record not fully read" if fact.get("read_incomplete") else ""
            line = _clip(fact.get("summary"), 90)
            say(f"    -{ago:6.0f}s  check  {fact.get('result')}{extra}: {line}")
        else:
            say(f"    -{ago:6.0f}s  wrote  {_clip(fact.get('summary'), 90)}")
    scan = case.get("scan") or {}
    counts = ("passed", "failed", "not_recorded", "background", "written_paths", "outside_paths")
    say("  Full scan: " + ", ".join(f"{k} {scan.get(k, 0)}" for k in counts))
    changed = _number(scan.get("last_changing_command_at"))
    if changed is not None:
        say(f"  Last shell command that may change files: {captured - changed:.0f}s before the cut")


def _ask(ask: Any, prompt: str) -> str | None:
    """One level, no default. None means stop; "skip" skips this case."""
    while True:
        try:
            reply = str(ask(prompt)).strip().lower()
        except (EOFError, KeyboardInterrupt):
            return None
        if reply in KEYS:
            return KEYS[reply]
        if reply in {"s", "skip"}:
            return "skip"
        if reply in {"q", "quit"}:
            return None


_MENU = (
    "    n None or low   m Medium   h High   e Extreme   x Not enough recorded yet\n"
    "    d No live level   s skip   q stop\n    > "
)


def _question(source: str) -> str:
    if source == "live":
        return (
            "\n  What should the LIVE ESTIMATE say here? It reads checks and file paths,\n"
            "  not what the intent says.\n" + _MENU
        )
    return (
        "\n  And what should an ANALYSIS read, taking each line of the intent against\n"
        "  this evidence? (No reading is shown: it is attached after the marks.)\n" + _MENU
    )


def _marks(body: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """The marks that are marks. A Codex cohort marks analysis only, and every case needs one."""
    raw = body.get("marks")
    codex = body.get("cohort") == COHORT_CODEX
    return {
        k: v
        for k, v in (raw.items() if isinstance(raw, dict) else ())
        if isinstance(v, dict)
        and (
            (v.get("live") is None and v.get("analysis") in ANALYSIS_LEVELS)
            if codex
            else v.get("live") in LABELS
            and (v.get("analysis") is None or v.get("analysis") in ANALYSIS_LEVELS)
        )
    }


def _publish_digest(
    paths: Mapping[str, str],
    digest_path: str,
    cases: int,
    marked: int,
    *,
    cases_digest: str,
    extra: Mapping[str, Any] | None = None,
) -> str:
    """Hash the marks as written, beside them and in the committable file."""
    with open(paths["marks"], "rb") as handle:
        sha = hashlib.sha256(handle.read()).hexdigest()
    with open(paths["sha"], "w", encoding="utf-8") as handle:
        handle.write(f"{sha}  marks.json\n")
    body = {
        "v": 1,
        "marks_digest": sha,
        "cases_digest": cases_digest,
        "cases": cases,
        "marked": marked,
        **(extra or {}),
    }
    os.makedirs(os.path.dirname(digest_path), exist_ok=True)
    with open(digest_path, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(body, handle, indent=2, sort_keys=True)
        handle.write("\n")
    return sha


def _scored_marker(paths: Mapping[str, str], cases_digest: str) -> str:
    """Where a score of this case set is remembered, outside the repository (V2)."""
    return os.path.join(paths["dir"], f"scored-{cases_digest}.json")


def _repo_path(path: str, repo_root: str) -> str:
    """`path` as git names it in a `<rev>:<path>` argument: relative, with forward slashes.

    `os.path.relpath` answers with backslashes on Windows, and git reads a
    backslash in `HEAD:docs\\x.json` as part of the name. That reading of the
    windows-latest failures in test_levels_cases is inferred, not observed there.
    """
    return pathlib.PurePath(
        os.path.relpath(os.path.realpath(path), os.path.realpath(repo_root))
    ).as_posix()


def _history_blobs(repo_root: str, relative: str) -> list[dict[str, Any]]:
    """Every version of one file git has ever held, on any ref, deleted ones included."""
    shas = (_git(repo_root, "log", "--all", "--format=%H", "--", relative) or "").split()
    found = []
    for sha in shas:
        blob = _git(repo_root, "show", f"{sha}:{relative}")
        try:
            body = json.loads(blob) if blob is not None else None
        except ValueError:
            body = None
        if isinstance(body, dict):
            found.append(body)
    return found


def _marking_closed(
    paths: Mapping[str, str], repo_root: str, digest_path: str, results_path: str, bound: str
) -> str:
    """Why this case set can no longer be marked, or empty.

    A result seen closes the key however the files that showed it were
    removed: the local marker survives deleting the result and the marks, and
    git history survives deleting the marker. A marks digest already committed
    for this case set closes it too, since the digest is committed once.
    """
    if os.path.exists(results_path):
        return f"{results_path} exists, so a score has been seen"
    if os.path.exists(_scored_marker(paths, bound)):
        return "this case set has been scored on this machine"
    for path, what in ((results_path, "a result"), (digest_path, "a marks digest")):
        for body in _history_blobs(repo_root, _repo_path(path, repo_root)):
            if body.get("cases_digest") == bound or (
                path == results_path and "cases_digest" not in body
            ):
                return f"git history already holds {what} for it"
    return ""


def mark(  # noqa: PLR0911 - one return per way a marking is refused or finished
    *,
    home: str,
    digest_path: str,
    results_path: str,
    repo_root: str,
    ask: Any = input,
    say: Any = print,
    cohort: str = COHORT_CLAUDE,
) -> int:
    """Ask the owner for each unmarked case's level, per source, and write the key.

    Refused once any result exists: a mark written after a result is agreement. A Codex cohort
    asks for the analysis level only: an unsupported Codex live source is outside its claim.
    """
    codex = cohort == COHORT_CODEX
    paths = _paths(home, cohort)
    body = _load(paths["cases"])
    cases = body.get("cases") if isinstance(body.get("cases"), list) else None
    if not cases:
        say(f"No cases at {paths['cases']}. Run --build first.")
        return 1
    if codex and (body.get("cohort") != COHORT_CODEX or _foreign(cases, "codex")):
        say("These are not Codex cases. Nothing was changed.")
        return 1
    saved = _load(paths["marks"])
    entries = _marks(saved)
    bound = digest(body)
    closed = _marking_closed(paths, repo_root, digest_path, results_path, bound)
    if closed:
        say(f"Marking is closed for this case set: {closed}. Nothing was changed.")
        return 1
    if entries and saved.get("cases_digest") != bound:
        say("These marks belong to a different case set. Nothing was changed.")
        return 1
    todo = [c for c in cases if c.get("id") not in entries]
    if not todo:
        say(f"All {len(cases)} cases are marked.")
        return 0
    say(f"{len(todo)} of {len(cases)} left. Say what each level SHOULD read, not what it does.")
    _mark_cases(todo, entries, ask, say, codex=codex)
    if not entries:
        say("Nothing marked.")
        return 0
    held: dict[str, Any] = {"v": 1, "cases_digest": bound, "marks": entries}
    extra: dict[str, Any] | None = None
    if codex:
        held["cohort"] = COHORT_CODEX
        # Fixed with the marks and before any output: which kinds the cohort covers, every case it
        # requires an admissible reading for, and the exact producer inputs each one is read from.
        extra = {
            "cohort": COHORT_CODEX,
            "matrix": body.get("matrix"),
            "required_analysis": sorted(str(c["id"]) for c in cases),
            "inputs": {str(c["id"]): _inputs(c) for c in cases},
        }
    _write(paths["marks"], held)
    sha = _publish_digest(
        paths, digest_path, len(cases), len(entries), cases_digest=bound, extra=extra
    )
    left = len(cases) - len(entries)
    say(f"\nSaved {len(entries)} marks, {left} left. sha256 {sha}")
    say(f"Commit {digest_path} before any score is run.")
    return 0


def _foreign(cases: list[Any], harness: str) -> bool:
    """Whether any case belongs to another harness than the cohort's."""
    return any(not isinstance(c, dict) or c.get("harness") != harness for c in cases)


def _mark_cases(  # noqa: C901 - the Codex branch is one more way through the same loop
    todo: list[dict[str, Any]],
    entries: dict[str, dict[str, Any]],
    ask: Any,
    say: Any,
    *,
    codex: bool = False,
) -> None:
    """One screen per case; stops, keeping what was marked, at the first `q`."""
    for index, case in enumerate(todo, 1):
        _show(case, f"{index}/{len(todo)}", say)
        if codex:
            level = _ask(ask, _question("analysis"))
            if level is None:
                return
            if level in {"skip", "no_live_level"}:
                continue
            entries[str(case["id"])] = {"live": None, "analysis": level}
            continue
        live = _ask(ask, _question("live"))
        if live is None:
            return
        if live == "skip":
            continue
        analysis: str | None = None
        if (case.get("intent") or {}).get("lines"):
            analysis = _ask(ask, _question("analysis"))
            if analysis is None:
                return
            if analysis == "skip":
                continue
            if analysis == "no_live_level":
                say("  No live level answers a draft only; this case's analysis is not marked.")
                continue
        else:
            say("  The intent has no outcome line, so there is no analysis level to mark.")
        entries[str(case["id"])] = {"live": live, "analysis": analysis}


def judge(got: str, marked: str) -> str:
    """Whether a level meets the owner's mark: the same, or more cautious.

    More cautious means it reassures less. A higher drift level is more
    cautious than a lower one, and "Not enough recorded yet" is more cautious
    than "None or low" only: said of a case marked Medium or above, it hides the
    drift the owner saw. "None or low" on a case marked anything else fails.
    "No live level" answers only a draft and is met only by itself.
    """
    if got == marked:
        return MATCH
    if "no_live_level" in (got, marked):
        return FAILED
    if got == "none_or_low":
        return FAILED
    if got == "not_enough":
        return CAUTIOUS if marked == "none_or_low" else FAILED
    if marked == "not_enough":
        return CAUTIOUS
    return CAUTIOUS if _SCALE.index(got) > _SCALE.index(marked) else FAILED


def _git(repo_root: str, *args: str) -> str | None:
    """Git's answer, or None when the repository cannot give one."""
    try:
        done = subprocess.run(  # noqa: S603 - fixed argv, no shell
            ["git", "-C", repo_root, *args],  # noqa: S607 - the operator's git on PATH
            capture_output=True,
            check=False,
        )
    except OSError:
        return None
    return done.stdout.decode("utf-8", "replace") if done.returncode == 0 else None


class Committed:
    """The marks digest as committed, the commit that holds it, and when it was made."""

    def __init__(self, marks_digest: str, commit: str, committed_at: float) -> None:
        self.marks_digest = marks_digest
        self.commit = commit
        self.committed_at = committed_at


def committed_digest(repo_root: str, digest_path: str) -> Committed | str:
    """Read from HEAD, never from the working copy the marker rewrites (T2); why not, if not."""
    relative = _repo_path(digest_path, repo_root)
    blob = _git(repo_root, "show", f"HEAD:{relative}")
    if blob is None:
        return "the marks digest is not committed"
    try:
        with open(digest_path, encoding="utf-8") as handle:
            working = handle.read()
    except OSError:
        working = ""
    # Compared by line: a Windows checkout may hold CRLF where the blob holds LF.
    if working.splitlines() != blob.splitlines():
        return "the working copy of the marks digest differs from the committed one"
    log = (_git(repo_root, "log", "-1", "--format=%H %ct", "--", relative) or "").split()
    try:
        body = json.loads(blob)
    except ValueError:
        return "the committed marks digest is not JSON"
    if len(log) != 2 or not isinstance(body, dict) or not isinstance(body.get("marks_digest"), str):
        return "the committed marks digest cannot be read"
    return Committed(body["marks_digest"], log[0], float(log[1]))


def _marks_sha(paths: Mapping[str, str]) -> str:
    try:
        with open(paths["marks"], "rb") as handle:
            return hashlib.sha256(handle.read()).hexdigest()
    except OSError:
        return ""


def _admit(config: Any, value: Any) -> Any:
    """A reading the store would keep, or None: the store's own validator, not a copy of it."""
    if _SKILL not in sys.path:
        sys.path.insert(0, _SKILL)
    from compass_runtime import annotations  # noqa: PLC0415

    return annotations._assessment(value, config.annotation_text_cap_chars)  # noqa: SLF001


# ------------------------------------------------------- the Codex replay allowance


class ReplayLedgerError(Exception):
    """The replay allowance cannot be read, or refuses the call asked of it."""


def default_allowance_path() -> str | None:
    """The fixed account-level file, or None where the account home cannot be settled."""
    return abstention_ledger.study_path("codex-levels-replay-spend.json")


def approve_replay_allowance(
    path: str | os.PathLike[str] | None, total: int, *, now: float, say: Any = print
) -> int:
    """Fix the total number of replay readings the Codex cohort may ever be charged, once.

    A fixed total approved before any replay, outside the producer qualification's exposures and
    its one retry. It is written exclusively: a second call cannot raise or renew it.
    """
    if path is None:
        say("Refused: the account home is not settled, so no allowance can be fixed.")
        return 1
    if type(total) is not int or not 0 <= total <= REPLAY_ALLOWANCE_MAX:
        say(f"Refused: the allowance is a whole number from 0 to {REPLAY_ALLOWANCE_MAX}.")
        return 1
    target = str(path)
    with abstention_ledger.locked(target):
        if os.path.lexists(target):
            say("Refused: the replay allowance is already fixed; it is never raised or renewed.")
            return 1
        _write(target, {"v": 1, "allowance": total, "approved_at": now, "events": []})
    say(f"Fixed the Codex replay allowance at {total}. Each call still needs its own approval.")
    return 0


class ReplayLedger:
    """What the Codex replays were approved for and charged, in one file of events.

    A charge is recorded before the call is launched and is never removed. A failed, timed-out or
    interrupted call keeps its charge, and no input is ever charged twice, so a rerun cannot
    renew what a failed case spent.
    """

    def __init__(self, path: str | None) -> None:
        self.path = path or ""

    def load(self) -> dict[str, Any]:
        body = _load(self.path) if self.path and not os.path.islink(self.path) else {}
        events = body.get("events")
        allowance = body.get("allowance")
        if (
            body.get("v") != 1
            or type(allowance) is not int
            or not 0 <= allowance <= REPLAY_ALLOWANCE_MAX
            or not isinstance(events, list)
            or not all(isinstance(e, dict) for e in events)
        ):
            msg = "the replay allowance is not fixed, or its file cannot be read"
            raise ReplayLedgerError(msg)
        return body

    def events(self, kind: str) -> list[dict[str, Any]]:
        return [e for e in self.load()["events"] if e.get("kind") == kind]

    def charges(self) -> list[dict[str, Any]]:
        return self.events("charge")

    def remaining(self) -> int:
        return int(self.load()["allowance"]) - len(self.charges())

    def charged_inputs(self) -> set[str]:
        return {str(e.get("inputs")) for e in self.charges()}

    def charge(self, *, case: str, inputs: str, request: str, approval: str, now: float) -> str:
        """Record one approved call before it is launched; refuse past the total or a repeat."""
        with abstention_ledger.locked(self.path):
            body = self.load()
            charges = [e for e in body["events"] if e.get("kind") == "charge"]
            if len(charges) >= body["allowance"]:
                msg = "the fixed replay allowance is spent"
                raise ReplayLedgerError(msg)
            if any(e.get("inputs") == inputs for e in charges):
                msg = "these inputs were charged already; a call is never silently charged again"
                raise ReplayLedgerError(msg)
            if any(e.get("approval") == approval for e in charges):
                msg = "this approval was used already"
                raise ReplayLedgerError(msg)
            event = {
                "id": uuid.uuid4().hex,
                "kind": "charge",
                "case": case,
                "inputs": inputs,
                "request": request,
                "approval": approval,
                "at": now,
            }
            body["events"].append(event)
            _write(self.path, body)
        return str(event["id"])

    def settle(self, charge: str, status: str, *, now: float) -> None:
        """Say how a charged call ended. Nothing here ever gives a charge back."""
        with abstention_ledger.locked(self.path):
            body = self.load()
            if any(
                e.get("kind") == "settlement" and e.get("charge") == charge for e in body["events"]
            ):
                return
            body["events"].append(
                {
                    "id": uuid.uuid4().hex,
                    "kind": "settlement",
                    "charge": charge,
                    "status": status,
                    "at": now,
                }
            )
            _write(self.path, body)


def _producer(case: Mapping[str, Any]) -> str:
    """What read a case: provider and model, plus the parser and prompt it was frozen on."""
    _reading, _policy, reading_route = _read_runtime()
    frozen = case.get("production_reading")
    return digest(
        {
            "provider": READ_PROVIDER,
            "model": reading_route.MODELS[READ_PROVIDER],
            "parser": case.get("parser"),
            "prompt": frozen.get("prompt_digest") if isinstance(frozen, dict) else None,
        }
    )


_BINDING_KEYS = frozenset({"producer", "request", "inputs", "charge"})


def _binding_problem(
    case: Mapping[str, Any] | None,
    binding: Any,
    charges: Mapping[str, Mapping[str, Any]],
    committed_at: float,
) -> str:
    """Why a Codex reading is not bound to its case's inputs, producer and approved charge."""
    if case is None:
        return "not a case in the committed marks"
    if not isinstance(binding, dict) or set(binding) != _BINDING_KEYS:
        return "no binding to its producer, request, inputs and charge"
    charge = charges.get(str(binding["charge"]))
    at = _number((charge or {}).get("at"))
    problems = (
        (binding["inputs"] == _inputs(case), "its inputs differ from the case's"),
        (
            binding["producer"] == _producer(case),
            "its producer is not the one the case was frozen on",
        ),
        (charge is not None, "its charge was never approved"),
        (
            charge is not None
            and charge.get("inputs") == binding["inputs"]
            and charge.get("request") == binding["request"],
            "its charge was approved for another request",
        ),
        (at is not None and at > committed_at, "its charge predates the committed marks digest"),
    )
    return next((why for holds, why in problems if not holds), "")


def _charges_by_id(allowance_path: str | None) -> dict[str, dict[str, Any]]:
    """Every approved charge by id; none, rather than a guess, when the file cannot be read."""
    try:
        return {
            str(e["id"]): e
            for e in ReplayLedger(allowance_path or default_allowance_path()).charges()
        }
    except (ReplayLedgerError, KeyError):
        return {}


def attach_readings(  # noqa: C901 - one refusal per binding
    spec_path: str | os.PathLike[str],
    *,
    home: str,
    repo_root: str,
    digest_path: str,
    now: float,
    say: Any = print,
    cohort: str = COHORT_CLAUDE,
    allowance_path: str | None = None,
) -> int:
    """Add readings after the marks, stamped with the committed digest they came after (T1).

    A Codex reading also carries a binding to the producer, the request, the exact inputs and the
    approved charge it came from, each checked here. A late timestamp alone attaches nothing.
    """
    codex = cohort == COHORT_CODEX
    paths = _paths(home, cohort)
    committed = committed_digest(repo_root, digest_path)
    if isinstance(committed, str):
        say(f"Refused: {committed}. Mark, commit the digest, then attach readings.")
        return 1
    if committed.marks_digest != _marks_sha(paths):
        say("Refused: the local marks no longer hash to the committed digest.")
        return 1
    # Only the committed marks' cases (V4): the marks hash to the committed
    # digest, checked above, so these are exactly the committed ones.
    cases = set(_marks(_load(paths["marks"])))
    raw = _load(str(spec_path))
    readings = raw.get("readings") if raw.get("v") == 1 else None
    given = raw.get("bindings")
    bindings: dict[str, Any] = given if isinstance(given, dict) else {}
    by_id = {str(c.get("id")): c for c in _load(paths["cases"]).get("cases") or []}
    charges = _charges_by_id(allowance_path) if codex else {}
    if not isinstance(readings, dict) or not readings:
        say(f"No readings in {spec_path}: it wants {{'v': 1, 'readings': {{case id: reading}}}}.")
        return 1
    config = _config()
    problems = []
    for key, value in readings.items():
        admitted = _admit(config, value) if key in cases else None
        read_at = _number(value.get("read_at")) if isinstance(value, dict) else None
        if key not in cases:
            problems.append(f"{key}: not a case in the committed marks")
        elif admitted is None:
            problems.append(f"{key}: the annotation store would refuse this reading")
        elif read_at is None or read_at <= committed.committed_at:
            problems.append(f"{key}: made before the marks digest was committed")
        elif codex and (
            why := _binding_problem(
                by_id.get(key), bindings.get(key), charges, committed.committed_at
            )
        ):
            problems.append(f"{key}: binding refused: {why}")
    for problem in problems:
        say(f"  {problem}")
    if problems:
        say("Nothing was attached.")
        return 1
    _write(
        paths["readings"],
        {
            "v": 1,
            "marks_digest": committed.marks_digest,
            "digest_commit": committed.commit,
            "attached_at": now,
            "readings": readings,
            **({"cohort": COHORT_CODEX, "bindings": bindings} if codex else {}),
        },
    )
    say(f"Attached {len(readings)} readings under digest commit {committed.commit[:12]}.")
    return 0


def _reading_for(
    case: Mapping[str, Any],
    attached: Mapping[str, Any],
    committed: Committed,
    config: Any,
    charges: Mapping[str, Mapping[str, Any]] | None = None,
) -> tuple[Any, str]:
    """The reading to score for a case, or a refusal token (T1 item 5), or neither.

    A Codex case is read only through the binding it was attached under, checked again here
    against the case as it now stands, so a changed case cannot borrow an old reading.
    """
    if "reading" in case:
        return None, "reading-in-cases"
    value = (attached.get("readings") or {}).get(str(case["id"]))
    if value is None:
        return None, ""
    if charges is not None and _binding_problem(
        case, (attached.get("bindings") or {}).get(str(case["id"])), charges, committed.committed_at
    ):
        return None, "unbound"
    if (
        attached.get("marks_digest") != committed.marks_digest
        or attached.get("digest_commit") != committed.commit
    ):
        return None, "other-digest"
    read_at = _number(value.get("read_at")) if isinstance(value, dict) else None
    if read_at is None or read_at <= committed.committed_at:
        return None, "predates-marks"
    admitted = _admit(config, value)
    return (admitted, "") if admitted is not None else (None, "malformed")


def _admitted(row: Mapping[str, Any] | None) -> bool:
    """Whether an analysis row came from an admissible reading, scored to a level."""
    return row is not None and row.get("level") is not None


def _level_row(level: Any, marked: str) -> dict[str, Any]:
    return {
        "level": level.level,
        "reasons": list(level.reasons),
        "outcome": judge(level.level, marked),
    }


def _score_case(
    levels: Any, case: Mapping[str, Any], marked: Mapping[str, Any], reading: tuple[Any, str]
) -> dict[str, Any]:
    intent = case.get("intent") or {}
    lines = tuple(str(x) for x in intent.get("lines") or ())
    evidence = levels.Evidence(
        facts=tuple(case.get("facts") or ()),
        scan=case.get("scan") or {},
        unsettled_directions=int(case.get("unsettled_directions") or 0),
        cwd=str(case.get("cwd") or ""),
    )
    codex = case.get("harness") == "codex"
    live = (
        None
        if codex
        else levels.live_level(
            evidence,
            levels.Intent(
                saved=intent.get("saved") is True, goal=str(intent.get("goal") or ""), lines=lines
            ),
        )
    )
    value, refusal = reading
    analysis: dict[str, Any] | None = None
    if refusal:
        analysis = {"level": None, "reasons": [], "outcome": f"refused:{refusal}"}
    elif value is not None and marked.get("analysis"):
        level = levels.analysis_level(value, evidence, outcome_lines=len(lines), lines=lines)
        analysis = _level_row(level, str(marked["analysis"]))
    return {
        "kind": case["kind"] if case.get("kind") in (CODEX_KINDS if codex else KINDS) else "other",
        "marks": {"live": marked["live"], "analysis": marked.get("analysis")},
        "live": None if live is None else _level_row(live, str(marked["live"])),
        "analysis": analysis,
    }


def score(
    *,
    home: str,
    repo_root: str,
    digest_path: str,
    results_path: str,
    now: float,
    say: Any = print,
    cohort: str = COHORT_CLAUDE,
    allowance_path: str | None = None,
) -> int:
    """Both functions against the marks; the summary holds expectations and results only.

    Writes nothing when the marks do not hash to the committed digest, or when any
    case is unmarked (T3, T4): a level written for either can be read, then marked.
    A Codex cohort scores the analysis function only, and passes only when every case it fixed
    before any output holds an admissible reading and every kind of its matrix is covered by one.
    """
    codex = cohort == COHORT_CODEX
    _config_mod, _project_context, levels = _runtime()
    paths = _paths(home, cohort)
    body = _load(paths["cases"])
    cases = body.get("cases") if isinstance(body.get("cases"), list) else []
    if not cases:
        say(f"No cases at {paths['cases']}. Run --build first.")
        return 1
    saved = _load(paths["marks"])
    entries = _marks(saved)
    committed = committed_digest(repo_root, digest_path)
    if isinstance(committed, str):
        say(f"Not scored: {committed}. Nothing was written.")
        return 1
    if committed.marks_digest != _marks_sha(paths) or saved.get("cases_digest") != digest(body):
        say("Not scored: the marks do not hash to the committed digest. Nothing was written.")
        return 1
    unmarked = [c for c in cases if str(c.get("id")) not in entries]
    if unmarked:
        say(f"Not scored: {len(unmarked)} cases are unmarked. Nothing was written.")
        return 1
    if codex and (body.get("cohort") != COHORT_CODEX or _foreign(cases, "codex")):
        say("Not scored: these are not Codex cases. Nothing was written.")
        return 1
    attached = _load(paths["readings"])
    config = _config()
    charges = _charges_by_id(allowance_path) if codex else None
    rows = {
        str(case["id"]): _score_case(
            levels,
            case,
            entries[str(case["id"])],
            _reading_for(case, attached, committed, config, charges),
        )
        for case in cases
    }
    outcomes = [
        row[source]["outcome"]
        for row in rows.values()
        for source in ("live", "analysis")
        if row[source] is not None
    ]
    by_key = {str(c["id"]): c for c in cases}
    uncovered = (
        sorted(
            set(body.get("matrix") or ())
            - {str(by_key[k]["kind"]) for k, r in rows.items() if _admitted(r["analysis"])}
        )
        if codex
        else []
    )
    if any(o.startswith("refused:") for o in outcomes):
        verdict = VERDICT_REFUSED
    elif FAILED in outcomes:
        verdict = VERDICT_FAILED
    elif codex and (uncovered or any(r["analysis"] is None for r in rows.values())):
        verdict = VERDICT_INCOMPLETE
    else:
        verdict = VERDICT_PASSED
    counts = {o: outcomes.count(o) for o in (MATCH, CAUTIOUS, FAILED)}
    counts["refused"] = sum(o.startswith("refused:") for o in outcomes)
    counts["no_reading"] = sum(
        1 for key, row in rows.items() if row["analysis"] is None and entries[key].get("analysis")
    )
    summary = {
        "v": 1,
        "cases_digest": digest(body),
        "scored_at": now,
        "marks_digest": committed.marks_digest,
        "digest_commit": committed.commit,
        "verdict": verdict,
        "counts": counts,
        "cases": rows,
    }
    if codex:
        summary["cohort"] = COHORT_CODEX
        summary["coverage"] = {
            "matrix": sorted(set(body.get("matrix") or ())),
            "uncovered": uncovered,
        }
    os.makedirs(os.path.dirname(results_path), exist_ok=True)
    with open(results_path, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(summary, handle, indent=2, sort_keys=True)
        handle.write("\n")
    _write(
        _scored_marker(paths, digest(body)),
        {"v": 1, "cases_digest": digest(body), "scored_at": now, "digest_commit": committed.commit},
    )
    say(f"Drift levels scored: {verdict}. {counts}")
    return 0 if verdict == VERDICT_PASSED else 1


# ------------------------------------------------------------ replayed readings

# The cases the marking prep named for an analysis reading (2026-09-27): the
# four uncut sessions, one of them frozen as two kinds, so five cases and four
# producer inputs. Case ids only: a committed file never names a session.
DEFAULT_READ = (
    "e41740a407b84be1",
    "5e607f9f716ab27c",
    "a753d332906e61bd",
    "d68d3f6a32182ba0",
    "0dd3ae7c558bf2cf",
)
# The route the owner named: Codex, to OpenAI, which was the board's route for
# a Claude Code session here (`fallback-not-qualified`) until the owner accepted
# the Claude Code producer on 2026-10-02. Pinned, so that acceptance moves nothing.
READ_PROVIDER = "codex"
# When the intent counts as typed: before every record, as DRC-4666's replay
# stamps its own (`mark_abstention.INTENT_AT`). The owner marked each line
# against the whole frozen record, so the window opens before all of it.
REPLAY_INTENT_AT = 1.0
STATUS_READ = "read"
STATUS_REFUSED = "refused"


def reading_config(reading_home: str) -> Any:
    """The runtime config for the home the reading board ran on, whose ledger is charged."""
    config_mod, _project_context, _levels = _runtime()
    return config_mod.build_runtime_config(
        environ={**os.environ, "COMPASS_HOME": reading_home},
        platform_name=sys.platform,
        os_name=os.name,
        launcher_path=pathlib.Path(_SKILL, "server.py"),
        observer_model_enabled=True,
    )


def _read_runtime() -> tuple[Any, Any, Any]:
    """(reading, reading_policy, reading_route), deferred for `_runtime`'s reason."""
    _runtime()
    from compass_runtime import reading, reading_policy, reading_route  # noqa: PLC0415

    return reading, reading_policy, reading_route


def _replay_row(case: Mapping[str, Any]) -> dict[str, Any]:
    """The row a press would read, stopped at the case's own clock.

    A recorded session this old has no observed turn stop or end (the board's
    history holds state snapshots, and `end_kind` reads `finished_at`), so a
    live press withholds `idle-unknown`. The frozen case already fixes the
    moment it stands at, `captured_at`, and the owner marked against the
    record through exactly that moment; it is the stop this replay reads to.

    A Codex case carries the row its own frozen lifecycle confirmed instead.
    """
    if case.get("harness") == "codex":
        return dict(case["row_snapshot"])
    return {
        "harness": "claude",
        "sid": str(case["sid"]),
        "state": "idle",
        "finished_at": float(case["captured_at"]),
    }


def _replay_revision(case: Mapping[str, Any]) -> dict[str, Any]:
    if case.get("harness") == "codex":
        return dict(_marker().case_revision(dict(case)))
    intent = case.get("intent") or {}
    return {
        "n": 1,
        "at": REPLAY_INTENT_AT,
        "goal": str(intent.get("goal") or ""),
        "lines": [str(line) for line in intent.get("lines") or ()],
    }


def _check_pairs(case: Mapping[str, Any], flag: str) -> frozenset[tuple[str, str]]:
    """The (record id, check line) pairs a press carries, from the frozen facts' own flag."""
    pairs = set()
    for fact in case.get("facts") or ():
        branch = fact.get("branch") if isinstance(fact, dict) else None
        record = branch.get("record_id") if isinstance(branch, dict) else None
        if fact.get(flag) is True and isinstance(record, str):
            pairs.add((record, str(fact.get("summary") or "")))
    return frozenset(pairs)


def _marker() -> Any:
    """`mark_abstention`, the owner of the frozen Codex case's shapes, loaded as `_runtime` is."""
    _runtime()
    import mark_abstention  # noqa: PLC0415

    return mark_abstention


def _inputs(case: Mapping[str, Any]) -> str:
    """Everything `produce` reads of a case. Two cases with one digest are one call.

    A Codex case binds more: its recovered messages and checks, the frozen lifecycle row and
    tool output, the sealed source and parser identities and the prompt the production reader
    built, so that no reading can stand for a case whose evidence or prompt has changed.
    """
    if case.get("harness") == "codex":
        sources = case.get("sources") or {}
        frozen = case.get("production_reading") or {}
        return digest(
            {
                "harness": "codex",
                "sid": case.get("sid"),
                "captured_at": case.get("captured_at"),
                "intent": case.get("intent"),
                "producer_facts": case.get("producer_facts"),
                "row": case.get("row_snapshot"),
                "tool_output": case.get("tool_output"),
                "parent": (sources.get("parent") or {}).get("sha256"),
                "children": [c.get("sha256") for c in sources.get("children") or ()],
                "selection": sources.get("selection_digest"),
                "parser": case.get("parser"),
                "prompt": frozen.get("prompt_digest"),
            }
        )
    return digest(
        {
            "sid": case.get("sid"),
            "captured_at": case.get("captured_at"),
            "facts": case.get("facts"),
            "goal": (case.get("intent") or {}).get("goal"),
            "lines": (case.get("intent") or {}).get("lines"),
        }
    )


def _read_refusal(
    case: Mapping[str, Any] | None,
    marked: Mapping[str, Any] | None,
    cohort: str = COHORT_CLAUDE,
) -> str:
    """Why a chosen case cannot be read at all, before any call; empty when it can."""
    intent = (case or {}).get("intent") or {}
    codex = cohort == COHORT_CODEX
    checks = (
        (case is not None, "not a case in cases.json"),
        (marked is not None, "not marked"),
        ((marked or {}).get("analysis") in ANALYSIS_LEVELS, "has no analysis mark"),
        (
            (case or {}).get("harness") == ("codex" if codex else "claude"),
            "is not a Codex case" if codex else "is not a Claude Code case",
        ),
        (_saved(case or {}), "its intent was never saved, so no press reads it"),
        (bool(intent.get("lines")), "its intent has no outcome line"),
        (_number((case or {}).get("captured_at")) is not None, "has no frozen clock"),
    )
    return next((why for holds, why in checks if not holds), "")


def _read_preflight(
    home: str,
    repo_root: str,
    digest_path: str,
    chosen: list[str] | None,
    say: Any,
    cohort: str = COHORT_CLAUDE,
) -> tuple[list[str], dict[str, dict[str, Any]], dict[str, dict[str, Any]]] | None:
    """(chosen, every case, its marks) once the marks bind them; None, having said why, if not.

    No case chosen means the Claude cohort's named five, or every case of a Codex cohort.
    """
    paths = _paths(home, cohort)
    body = _load(paths["cases"])
    committed = committed_digest(repo_root, digest_path)
    saved = _load(paths["marks"])
    why = ""
    if not isinstance(body.get("cases"), list) or not body["cases"]:
        why = f"no cases at {paths['cases']}"
    elif isinstance(committed, str):
        why = committed
    elif committed.marks_digest != _marks_sha(paths):
        why = "the local marks no longer hash to the committed digest"
    elif saved.get("cases_digest") != digest(body):
        # The marks file hashes to the committed digest, so its case digest is
        # the committed one: any change to a case since marking lands here.
        why = "the cases changed since they were marked"
    if why:
        say(f"Refused: {why}. Nothing was read and nothing was charged.")
        return None
    cases = {str(c.get("id")): c for c in body["cases"] if isinstance(c, dict)}
    entries = _marks(saved)
    if chosen is None:
        chosen = list(cases) if cohort == COHORT_CODEX else list(DEFAULT_READ)
    chosen = list(dict.fromkeys(chosen))
    problems = [(key, _read_refusal(cases.get(key), entries.get(key), cohort)) for key in chosen]
    problems = [(key, why) for key, why in problems if why]
    for key, why in problems:
        say(f"  {key}: {why}")
    if problems:
        say("Refused. Nothing was read and nothing was charged.")
        return None
    return chosen, cases, entries


def _budget_refusal(answer: Mapping[str, Any], calls: int, *, granted: bool) -> str:
    if not answer.get("providers", {}).get(READ_PROVIDER):
        return "Codex is not allowed in the reading home; Allow it on the reading board first"
    if not granted:
        # The cases froze only tool-reported facts, and without the grant none
        # of them is sent: the producer would withhold every case as
        # `ledger-empty`. Refused here instead, with the reason that is true.
        return (
            "the reading home holds no grant for tool output to OpenAI, and the cases hold "
            "only tool-reported facts, so there would be nothing to read"
        )
    if answer.get("reason") and answer["reason"] != "daily-cap":
        return f"the reading ledger answers {answer['reason']}"
    used, limit = int(answer.get("used") or 0), int(answer.get("limit") or 0)
    if used + calls > limit:
        return f"the reading ledger holds {used} of {limit}, and this needs {calls} more"
    return ""


class _Spy:
    """The model a dry run hands `produce`: measures the prompt, sends nothing."""

    unavailable_reason = "model-unavailable"

    def __init__(self) -> None:
        self.sizes: list[int] = []
        self.prompts: list[str] = []

    def available(self) -> bool:
        return True

    def __call__(self, prompt: str, *, output_cap_bytes: int) -> tuple[str, str]:
        del output_cap_bytes
        self.sizes.append(len(prompt.encode("utf-8")))
        self.prompts.append(prompt)
        return "", "cancelled"


# The replies a dry run scores per case: each answer token on every question,
# citing nothing, each numbered entry alone, or all of them, and one refusal.
# Small on purpose: it asks whether any reply can move a case's outcome, which
# a uniform reply already answers for the rules `levels.analysis_level` keeps.
SYNTHETIC_TOKENS = ("departure", "consistent", "unverifiable")
SYNTHETIC_REFUSAL = "I can't help with reading this session."


class _Synthetic:
    """A reply a dry run scores through the real producer and scorer; nothing leaves."""

    unavailable_reason = "model-unavailable"

    def __init__(self, questions: list[str], token: str, pattern: str | int) -> None:
        self.questions = questions
        self.token = token
        self.pattern = pattern

    def available(self) -> bool:
        return True

    def __call__(self, prompt: str, *, output_cap_bytes: int) -> tuple[str, str]:
        del output_cap_bytes
        if not self.token:
            return SYNTHETIC_REFUSAL, "ok"
        numbered = _numbered(prompt)
        if self.pattern == "all":
            cites = numbered
        elif isinstance(self.pattern, int):
            cites = [self.pattern]
        else:
            cites = []
        detail = "A synthetic departure." if self.token == SYNTHETIC_TOKENS[0] else ""
        body = {q: {"result": self.token, "cites": cites, "detail": detail} for q in self.questions}
        return json.dumps(body), "ok"


def _numbered(prompt: str) -> list[int]:
    """The entry numbers the prompt's menu lists, which are all a reply may cite."""
    import re  # noqa: PLC0415

    reading, _policy, _route = _read_runtime()
    _head, _sep, menu = prompt.partition(reading.MENU_HEADING)
    return sorted({int(n) for n in re.findall(r"^\[(\d+)\] ", menu, re.MULTILINE)})


def _questions(case: Mapping[str, Any]) -> list[str]:
    """The keys a reply answers: the Goal when the producer asks it, and each outcome line."""
    reading, _policy, _route = _read_runtime()
    intent = case.get("intent") or {}
    frozen = case.get("production_reading")
    if case.get("harness") == "codex" and isinstance(frozen, dict):
        return [str(name) for name in frozen.get("constraints") or ()]
    asked = [reading.CONSTRAINT_GOAL] if reading.asks_goal(str(intent.get("goal") or "")) else []
    return asked + [reading.outcome_line(k) for k in range(1, len(intent.get("lines") or ()) + 1)]


def _produce(
    config: Any, case: Mapping[str, Any], model: Any, tool_output: Any, now: float
) -> tuple[Any, str, bool]:
    """One producer call on the frozen case, as the board's press composes it."""
    reading, reading_policy, reading_route = _read_runtime()
    codex = case.get("harness") == "codex"
    if codex:
        # Exactly as the production capture asked at freeze time (`_production_capture`), and the
        # recovered words are checked against it: the prompt is the one the producer qualification
        # was held to, never a levels-only rewording of it.
        marker = _marker()
        facts = list(case.get("producer_facts") or ())
        extra: dict[str, Any] = {
            "read_agent_words": True,
            "admit_idle": True,
            "person_source_lookup": marker.native_case_person_lookup(dict(case), config=config),
            "final_source_lookup": marker.native_case_final_lookup(dict(case), config=config),
        }
    else:
        facts = list(case.get("facts") or ())
        # Not the idle admission of 2026-10-20: the owner marked these cases under the earlier
        # rule, which withheld an idle session with no recorded finish, and re-scoping the key
        # is the owner's decision, not this replay's.
        extra = {"admit_idle": False}
    try:
        produced: tuple[Any, str, bool] = reading.produce(
            config,
            _replay_row(case),
            [_replay_revision(case)],
            facts,
            now=now,
            stamp_text=f"{reading_route.MODELS[READ_PROVIDER]} · replayed "
            f"{time.strftime('%Y-%m-%d %H:%M', time.localtime(now))}",
            model=model,
            tool_output=tool_output,
            read_lines=True,
            admit_turn_stop=True,
            **extra,
        )
    except reading_policy.RefusedError as error:
        return None, f"ledger:{error.answer['reason']}", False
    return produced


def read_cases(  # noqa: C901, PLR0911, PLR0912, PLR0913 - one keyword per thing bound
    *,
    home: str,
    repo_root: str,
    digest_path: str,
    reading_config: Any,
    case_ids: list[str] | None = None,
    model: Any = None,
    destination: str | None = None,
    dry_run: bool = False,
    clock: Any = time.time,
    say: Any = print,
    cohort: str = COHORT_CLAUDE,
    approve: Any = None,
    allowance_path: str | None = None,
) -> int:
    """Replay each chosen case through `reading.produce`, charged on the reading home's ledger.

    A Codex cohort needs more before the first call: a fixed total allowance on its own ledger,
    room left in it for every call this run makes, and the owner's approval of each call,
    shown with the digest of the exact request. Reading consent, the tool-output grant and the
    rolling budget still apply.

    Everything that can refuse does so before the first call: the committed
    marks, the cases they bind, each case's mark and intent, the route, the
    consent, the tool-output grant and the room left on the ledger. A case the
    producer withholds is recorded as refused with its reason, and nothing
    stands in for it.
    """
    _reading, reading_policy, reading_route = _read_runtime()
    codex = cohort == COHORT_CODEX
    bound = _read_preflight(home, repo_root, digest_path, case_ids, say, cohort)
    if bound is None:
        return 1
    chosen, every, marks = bound
    cases = {key: every[key] for key in chosen}
    ledger = ReplayLedger(
        allowance_path if allowance_path is not None or not codex else default_allowance_path()
    )
    if codex and not dry_run:
        try:
            ledger.load()
        except ReplayLedgerError as error:
            say(f"Refused: {error}. Nothing was read and nothing was charged.")
            return 1
        if approve is None:
            say(
                "Refused: a Codex replay needs the owner's approval of each call, "
                "and none can be given here."
            )
            say("Nothing was read and nothing was charged.")
            return 1
    where = reading_route.destination(READ_PROVIDER) if destination is None else destination
    if where != reading_route.VENDORS[READ_PROVIDER]:
        say(f"Refused: the reading call would reach {where or 'an unnamed host'}, not OpenAI.")
        return 1
    paths = _paths(home, cohort)
    held = dict(_load(paths["replayed"]).get("readings") or {})
    bindings: dict[str, Any] | None = (
        dict(_load(paths["replayed"]).get("bindings") or {}) if codex else None
    )
    record = dict(_load(paths["replay"]).get("cases") or {})
    spent = ledger.charged_inputs() if codex and not dry_run else set()
    plan = _plan(chosen, every, held, record, reading_config, clock, say, spent)
    # Covered only by an Allow given for where these calls go (owner, 2026-10-02).
    answer = reading_policy.status(
        reading_config, now=clock(), provider=READ_PROVIDER, destinations={READ_PROVIDER: where}
    )
    press = _Press(
        where, reading_policy.tool_output_allowed(answer, READ_PROVIDER, where), reading_config
    )
    say(
        f"{len(plan.groups)} call{'s' if len(plan.groups) != 1 else ''} for "
        f"{sum(map(len, plan.groups.values()))} cases; "
        f"ledger {answer.get('used')} of {answer.get('limit')}; "
        f"tool output to {where} {'granted' if press.granted else 'not granted'}."
    )
    refusal = _budget_refusal(answer, len(plan.groups), granted=press.granted)
    if not refusal and codex and not dry_run and len(plan.groups) > ledger.remaining():
        refusal = (
            f"the replay allowance holds {ledger.remaining()} calls, and this needs "
            f"{len(plan.groups)}"
        )
    if refusal:
        say(f"Refused: {refusal}. Nothing was read and nothing was charged.")
        return 1
    if dry_run:
        return _dry_run(press, cases, marks, plan.groups, clock, say)
    files = _Files(paths, held, record, bindings)
    gate = _Gate(ledger, approve) if codex else None
    for key, sibling in plan.reused.items():
        held[key] = held[sibling]
        if bindings is not None and sibling in bindings:
            bindings[key] = bindings[sibling]
        record[key] = {
            "status": STATUS_READ,
            "withheld": "",
            "spent": False,
            "charged": False,
            "call": sibling,
            "at": clock(),
        }
    if plan.reused:
        files.save()
    for keys in plan.groups.values():
        _read_group(press, cases, keys, model, clock, files, say, gate)
    files.save()
    if held:
        say(f"Readings for --attach-readings: {paths['replayed']}")
    return 0


# A call's marker in `replay.json` before its outcome: `pending` is written just
# before the reservation, with the job id the ledger records the charge under;
# `charged` once the reservation has committed. Either one left behind means the
# run stopped mid-call. A re-run never reads a `charged` case again, and reads a
# `pending` one again only when the ledger says its job was never charged.
STATUS_PENDING = "pending"
STATUS_CHARGED = "charged"


class _Plan:
    """The calls a run makes, and the cases it answers from a held sibling instead."""

    def __init__(self) -> None:
        self.groups: dict[str, list[str]] = {}
        self.reused: dict[str, str] = {}


def _in_flight(entry: Any, config: Any, clock: Any) -> bool:
    """Whether a record marks a call that may have been charged and has no outcome."""
    if not isinstance(entry, dict):
        return False
    if entry.get("status") == STATUS_CHARGED:
        return True
    if entry.get("status") != STATUS_PENDING:
        return False
    _reading, reading_policy, _route = _read_runtime()
    landed = reading_policy.charged(
        config, str(entry.get("job") or ""), started_at=entry.get("started_at"), now=clock()
    )
    # None is "cannot say", which the ledger's own callers count as spent.
    return landed is not False


def _plan(
    chosen: list[str],
    cases: Mapping[str, Mapping[str, Any]],
    held: Mapping[str, Any],
    record: Mapping[str, Any],
    config: Any,
    clock: Any,
    say: Any,
    spent: set[str] | None = None,
) -> _Plan:
    """The calls to make: one per distinct producer input that holds no reading yet.

    `spent` is a Codex cohort's own ledger: inputs it has charged are never read again, whatever
    the local record says, because a failed call there is not a call to retry.


    A case already read is kept. A case whose sibling, with identical inputs,
    holds a reading takes that reading, so splitting siblings across two runs
    never pays twice. A case a stopped run charged and left without an outcome
    is not read again. A call that finished and failed is read again, charged
    again, as a fresh press is the retry on the board.
    """
    plan = _Plan()
    by_inputs = {_inputs(cases[key]): key for key in held if key in cases}
    charged = {
        _inputs(cases[k]) for k in record if k in cases and _in_flight(record[k], config, clock)
    }
    for key in chosen:
        inputs = _inputs(cases[key])
        if key in held:
            say(f"  {key}: already read, kept and not read again")
        elif inputs in by_inputs:
            plan.reused[key] = by_inputs[inputs]
            say(f"  {key}: takes {by_inputs[inputs]}'s reading, which read the same inputs")
        elif inputs in charged:
            say(f"  {key}: charged by a run that stopped before its reading; not read again")
        elif inputs in (spent or ()):
            say(f"  {key}: its call was charged already, and a charged call is never charged again")
        else:
            plan.groups.setdefault(inputs, []).append(key)
    return plan


class _Files:
    """Both output files, written together after every change so a stop loses nothing."""

    def __init__(
        self,
        paths: Mapping[str, str],
        held: dict[str, Any],
        record: dict[str, Any],
        bindings: dict[str, Any] | None = None,
    ):
        self.paths = paths
        self.held = held
        self.record = record
        self.bindings = bindings

    def save(self) -> None:
        _write(self.paths["replay"], {"v": 1, "cases": self.record})
        if self.held:
            body: dict[str, Any] = {"v": 1, "readings": self.held}
            if self.bindings is not None:
                body["bindings"] = self.bindings
            _write(self.paths["replayed"], body)


class _Press:
    """What every call of one replay shares: where it goes, the grant, and the reading home."""

    def __init__(self, where: str, granted: bool, config: Any) -> None:
        self.where = where
        self.granted = granted
        self.config = config

    def tool_output(self, case: Mapping[str, Any]) -> Any:
        """As the board's press composes it for a Claude Code session with the grant.

        `read_cases` refuses without one. The cases froze no output tails, so no
        check's output is sent: its line, result and times are.
        """
        reading, _policy, reading_route = _read_runtime()
        if case.get("harness") == "codex":
            tails, changed, incomplete = _marker().case_checks(
                {"v": _marker().FORMAT_CODEX}, dict(case)
            )
            return reading.ToolOutput(
                destination=self.where,
                label=reading_route.LABELS[READ_PROVIDER],
                tails=tails or {},
                changed_after=changed,
                read_incomplete=incomplete,
            )
        return reading.ToolOutput(
            destination=self.where,
            label=reading_route.LABELS[READ_PROVIDER],
            tails={},
            changed_after=_check_pairs(case, "changed_after"),
            read_incomplete=_check_pairs(case, "read_incomplete"),
        )


class _Gate:
    """What a Codex call needs besides the reading home: the owner's approval and the allowance."""

    def __init__(self, ledger: ReplayLedger, approve: Any) -> None:
        self.ledger = ledger
        self.approve = approve


class _Pinned:
    """The model the owner approved a request for: it sends that request or nothing."""

    def __init__(self, model: Any, request: str) -> None:
        self.model = model
        self.request = request
        self.unavailable_reason = getattr(model, "unavailable_reason", "model-unavailable")

    def available(self) -> bool:
        return bool(self.model.available())

    def __call__(self, prompt: str, **kwargs: Any) -> tuple[str, str]:
        if hashlib.sha256(prompt.encode("utf-8")).hexdigest() != self.request:
            return "", "cancelled"
        return self.model(prompt, **kwargs)  # type: ignore[no-any-return]


def _read_group(  # noqa: C901 - the gate adds one stage to each group
    press: _Press,
    cases: Mapping[str, Mapping[str, Any]],
    keys: list[str],
    model: Any,
    clock: Any,
    files: _Files,
    say: Any,
    gate: _Gate | None = None,
) -> None:
    """One producer call for cases that share every input, charged once at the model seam.

    With a `gate`, the call is prepared locally first (which sends nothing), the owner approves
    that one request by its digest, and the charge is recorded on the allowance before launch.
    An interruption after the charge leaves it unsettled and charged.
    """
    reading, reading_policy, _route = _read_runtime()
    charged: list[bool] = []
    job = f"levels-replay:{keys[0]}:{clock():.6f}"
    case = cases[keys[0]]
    inputs, request, approval = _inputs(case), "", ""
    charge: list[str] = []
    if gate is not None:
        spy = _Spy()
        _produce(press.config, case, spy, press.tool_output(case), clock())
        if spy.prompts:
            request = hashlib.sha256(spy.prompts[0].encode("utf-8")).hexdigest()
            approval = uuid.uuid4().hex
            asked = {
                "case": keys[0],
                "cases": list(keys),
                "request_digest": request,
                "inputs": inputs,
                "remaining": gate.ledger.remaining(),
                "provider": READ_PROVIDER,
                "destination": press.where,
            }
            if not gate.approve(asked):
                say(f"  {keys[0]}: not approved; nothing was sent and nothing was charged")
                return

    def mark(status: str, **extra: Any) -> None:
        at = clock()
        for key in keys:
            files.record[key] = {"status": status, "call": keys[0], "at": at, **extra}
        files.save()

    def before_reserve() -> str:
        if gate is not None and request:
            charge.append(
                gate.ledger.charge(
                    case=keys[0], inputs=inputs, request=request, approval=approval, now=clock()
                )
            )
        mark(STATUS_PENDING, job=job, started_at=clock())
        return job

    def on_reserved() -> None:
        charged.append(True)
        mark(STATUS_CHARGED, job=job, charged=True)

    inner = model if model is not None else reading.CodexReadingModel(press.config)
    guarded = reading_policy.GuardedModel(
        press.config,
        _Pinned(inner, request) if request else inner,
        clock,
        provider=READ_PROVIDER,
        destination=press.where,
        on_reserved=on_reserved,
        before_reserve=before_reserve,
    )
    try:
        assessment, why, spent = _produce(
            press.config, case, guarded, press.tool_output(case), clock()
        )
    except ReplayLedgerError:
        assessment, why, spent = None, "ledger:replay-allowance", False
    if assessment is not None and _admit(press.config, assessment) is None:
        assessment, why = None, "store-refused"
    if charge and gate is not None:
        gate.ledger.settle(
            charge[0], "usable" if assessment is not None else "unusable", now=clock()
        )
    for key in keys:
        if assessment is not None:
            files.held[key] = assessment
            if files.bindings is not None and charge:
                files.bindings[key] = {
                    "producer": _producer(case),
                    "request": request,
                    "inputs": inputs,
                    "charge": charge[0],
                }
        files.record[key] = {
            "status": STATUS_READ if assessment is not None else STATUS_REFUSED,
            "withheld": why,
            "spent": spent,
            "charged": bool(charged),
            "call": keys[0],
            "at": clock(),
        }
        say(f"  {key}: {files.record[key]['status']}{f' ({why})' if why else ''}")
    files.save()


def _reachable(
    press: _Press, case: Mapping[str, Any], marked: Mapping[str, Any], clock: Any
) -> tuple[set[str], set[str], int, int]:
    """(levels, outcomes, replies withheld, replies) over the synthetic family, no call made."""
    _config_mod, _project_context, levels = _runtime()
    questions = _questions(case)
    spy = _Spy()
    _produce(press.config, case, spy, press.tool_output(case), clock())
    replies: list[tuple[str, str | int]] = [("", "")]
    if spy.prompts:
        numbered = _numbered(spy.prompts[0])
        patterns: list[str | int] = ["none", *numbered, "all"]
        replies += [(token, pattern) for token in SYNTHETIC_TOKENS for pattern in patterns]
    reached: set[str] = set()
    outcomes: set[str] = set()
    withheld = 0
    for token, pattern in replies:
        model = _Synthetic(questions, token, pattern)
        assessment, _why, _spent = _produce(
            press.config, case, model, press.tool_output(case), clock()
        )
        admitted = _admit(press.config, assessment) if assessment is not None else None
        if admitted is None:
            withheld += 1
            continue
        row = _score_case(levels, case, marked, (admitted, ""))["analysis"]
        reached.add(str(row["level"]))
        outcomes.add(str(row["outcome"]))
    return reached, outcomes, withheld, len(replies)


def _dry_run(
    press: _Press,
    cases: Mapping[str, Mapping[str, Any]],
    marks: Mapping[str, Mapping[str, Any]],
    groups: Mapping[str, list[str]],
    clock: Any,
    say: Any,
) -> int:
    """What would be sent, and what any reply could score: counts, ids and closed tokens only.

    Each chosen case is also scored against a small family of synthetic replies
    through the real producer and the real scorer, so the owner sees before any
    spend which cases a reading cannot move: the evidence alone fixes their
    analysis outcome, and a reading would buy a result known in advance.
    """
    for keys in groups.values():
        spy = _Spy()
        case = cases[keys[0]]
        _assessment, why, _spent = _produce(
            press.config, case, spy, press.tool_output(case), clock()
        )
        facts = len(case.get("facts") or ())
        shown = (
            f"would send {spy.sizes[0]} prompt bytes over {facts} frozen facts"
            if spy.sizes
            else f"would be refused ({why})"
        )
        say(f"  {', '.join(keys)}: {shown}")
    fixed = failing = 0
    for key, case in cases.items():
        reached, outcomes, withheld, total = _reachable(press, case, marks[key], clock)
        flags = []
        if len(outcomes) == 1:
            fixed += 1
            flags.append("fixed by the evidence")
        if outcomes == {FAILED}:
            failing += 1
            flags.append("fails whatever the reply")
        say(
            f"  {key}: analysis reaches {', '.join(sorted(reached)) or 'nothing'}; "
            f"outcomes {', '.join(sorted(outcomes)) or 'none'}; "
            f"{withheld} of {total} replies withheld" + "".join(f" -- {flag}" for flag in flags)
        )
    say(
        f"{fixed} of {len(cases)} cases have an analysis outcome no reply can move; "
        f"{failing} fail whatever the reply."
    )
    say("Dry run: no call was made and nothing was charged or written.")
    return 0


def report(*, home: str, say: Any = print, cohort: str = COHORT_CLAUDE) -> int:
    paths = _paths(home, cohort)
    cases = _load(paths["cases"]).get("cases") or []
    if not cases:
        say("No cases built yet.")
        return 1
    entries = _marks(_load(paths["marks"]))
    say(f"{sum(1 for c in cases if c.get('id') in entries)} of {len(cases)} marked.")
    for source in ("analysis",) if cohort == COHORT_CODEX else ("live", "analysis"):
        spread: dict[str, int] = {}
        for value in entries.values():
            if value.get(source):
                spread[value[source]] = spread.get(value[source], 0) + 1
        say(f"  {source:9} " + ", ".join(f"{LABELS[k]} {n}" for k, n in sorted(spread.items())))
    return 0


def _ask_approval(call: Mapping[str, Any]) -> bool:
    """The owner's yes or no to one call, shown the alias, request digest and allowance left."""
    print(
        f"\n  Replay call: case {call['case']} to {call['destination']}\n"
        f"    request digest {call['request_digest']}\n"
        f"    allowance left {call['remaining']}; this call is charged once and never given back."
    )
    try:
        return input("    Approve this one call? [y/N] ").strip().lower() in {"y", "yes"}
    except (EOFError, KeyboardInterrupt):
        return False


def main(argv: list[str] | None = None) -> int:  # noqa: PLR0911 - one return per mode
    parser = argparse.ArgumentParser(description="Freeze, mark and score drift-level cases.")
    parser.add_argument("--build", metavar="SPEC", help="freeze the cases a local spec names")
    parser.add_argument("--report", action="store_true", help="how far through the key you are")
    parser.add_argument(
        "--attach-readings", metavar="SPEC", help="add readings after the digest is committed"
    )
    parser.add_argument("--score", action="store_true", help="run both functions; calls no model")
    parser.add_argument(
        "--read", action="store_true", help="replay frozen cases through the reading producer"
    )
    parser.add_argument(
        "--reading-home", metavar="DIR", help="with --read: the home whose reading ledger pays"
    )
    parser.add_argument(
        "--case", action="append", metavar="ID", help="with --read: a case id (repeatable)"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="with --read: show what would be sent; no call"
    )
    parser.add_argument(
        "--cohort",
        choices=(COHORT_CLAUDE, COHORT_CODEX),
        default=COHORT_CLAUDE,
        help="codex: the separate analysis-only Codex cohort, with its own files",
    )
    parser.add_argument(
        "--approve-replay-allowance",
        type=int,
        metavar="N",
        help="with --cohort codex: fix the total replay readings to be charged (0-12), once",
    )
    args = parser.parse_args(argv)
    cohort = args.cohort
    codex = cohort == COHORT_CODEX
    digest_path, results_path = (
        (CODEX_DIGEST_PATH, CODEX_RESULTS_PATH) if codex else (DIGEST_PATH, RESULTS_PATH)
    )
    chosen = (
        args.build,
        args.report,
        args.attach_readings,
        args.score,
        args.read,
        args.approve_replay_allowance is not None,
    )
    if sum(map(bool, chosen)) > 1:
        print(
            "Run one of --build, --report, --attach-readings, --read, --score and "
            "--approve-replay-allowance at a time."
        )
        return 2
    if args.approve_replay_allowance is not None:
        if not codex:
            print("--approve-replay-allowance belongs to --cohort codex.")
            return 2
        return approve_replay_allowance(
            default_allowance_path(), args.approve_replay_allowance, now=time.time()
        )
    if args.read:
        if not args.reading_home:
            print("--read needs --reading-home: the home the reading board ran on.")
            return 2
        return read_cases(
            home=HOME,
            repo_root=_ROOT,
            digest_path=digest_path,
            reading_config=reading_config(os.path.expanduser(args.reading_home)),
            case_ids=args.case,
            dry_run=args.dry_run,
            cohort=cohort,
            approve=_ask_approval if codex else None,
        )
    if args.build:
        return build(args.build, home=HOME, repo_root=_ROOT, say=print, cohort=cohort)
    if args.report:
        return report(home=HOME, cohort=cohort)
    if args.attach_readings:
        return attach_readings(
            args.attach_readings,
            home=HOME,
            repo_root=_ROOT,
            digest_path=digest_path,
            now=time.time(),
            cohort=cohort,
        )
    if args.score:
        return score(
            home=HOME,
            repo_root=_ROOT,
            digest_path=digest_path,
            results_path=results_path,
            now=time.time(),
            cohort=cohort,
        )
    return mark(
        home=HOME,
        digest_path=digest_path,
        results_path=results_path,
        repo_root=_ROOT,
        cohort=cohort,
    )


if __name__ == "__main__":
    raise SystemExit(main())
