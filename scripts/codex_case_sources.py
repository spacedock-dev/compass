"""Offline Codex rollout admission. No dashboard, observer state or model calls.

Private packet paths are explicit. A selection grants access, never source integrity:
identity, descendant membership, capture prefix and every derived field are rebuilt.
"""

# Shared offline intake deliberately reuses the marker's private pure helpers and
# loads runtime imports only after the marker initializes its installed module path.
# ruff: noqa: INP001, SLF001, PLC0415
from __future__ import annotations

import ast
import contextlib
import hashlib
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

import mark_abstention as marker
from codex_case_candidates import MAX_FILES, outside_repository

if TYPE_CHECKING:
    from collections.abc import Iterable

PASSING_CHECK_ADVERSARIES = (
    "goal-unrelated",
    "outcome-unrelated",
    "browser-unrelated",
    "stale-before-write",
    "partial-check",
)
KIND_SUPPORTED_DEPARTURE = "supported-departure"
KIND_INCORRECT_EXECUTION = "matching-intent-incorrect-execution"
KIND_MISLEADING_COMPLETION = "misleading-completion"
AUTHORED_CORE_KINDS = (
    KIND_SUPPORTED_DEPARTURE,
    KIND_INCORRECT_EXECUTION,
    KIND_MISLEADING_COMPLETION,
)


def _provenance(entry: dict[str, Any]) -> dict[str, str]:
    origin = entry.get("origin", "recorded")
    if origin == "recorded":
        return {"origin": origin}
    if origin != marker.ORIGIN_SYNTHESISED:
        raise marker.FreezeError("codex-source-origin-invalid")
    kind = entry.get("kind")
    if kind not in (*AUTHORED_CORE_KINDS, *PASSING_CHECK_ADVERSARIES):
        raise marker.FreezeError("codex-authored-kind-ineligible")
    author, verifier = entry.get("authored_by"), entry.get("verified_by")
    if (
        not isinstance(author, str)
        or not isinstance(verifier, str)
        or not author.strip()
        or not verifier.strip()
        or author.strip() == verifier.strip()
    ):
        raise marker.FreezeError("codex-authored-identities-required")
    return {"origin": origin, "kind": kind, "authored_by": author, "verified_by": verifier}


def parser_digest() -> str:
    digest = hashlib.sha256(b"compass-codex-source-ast-v1\0")
    root = Path(marker._SKILL) / "compass_runtime"
    paths = [
        root / name
        for name in (
            *marker._PARSER_FILES,
            "records.py",
            "observer.py",
            "transcripts.py",
            "collectors/codex.py",
            "reader_checks.py",
            "project_scripts.py",
            "ci_read.py",
            "config.py",
            "settings.py",
            "reading_maps.py",
            "entry_numbers.py",
            "git_status.py",
            "claude_data.py",
            "semantic_history.py",
        )
    ]
    paths += [Path(__file__), Path(marker.__file__)]
    for path in paths:
        digest.update(path.name.encode() + b"\0")
        digest.update(
            ast.dump(ast.parse(path.read_bytes()), include_attributes=False).encode() + b"\0"
        )
    return digest.hexdigest()


def _head(path: Path) -> tuple[str, str, float | None, str]:
    from compass_runtime import project_context as context
    from compass_runtime import records

    if path.is_symlink():
        raise marker.FreezeError("codex-source-linked")
    with path.open("rb") as handle:
        raw = handle.readline(65537)
    if len(raw) > 65536:
        raise marker.FreezeError("codex-source-head-too-large")
    row = json.loads(raw)
    if not isinstance(row, dict) or row.get("type") != "session_meta":
        raise marker.FreezeError("codex-source-identity-unconfirmed")
    payload = records.as_dict(row.get("payload"))
    sid = payload.get("id")
    if not isinstance(sid, str) or len(sid) != 36 or not path.name.endswith(sid + ".jsonl"):
        raise marker.FreezeError("codex-source-identity-unconfirmed")
    parent = context._codex_parent(row, str(path))
    # A subagent rollout records its chain root as `session_id` (all 697 of the owner's, measured
    # by metadata on 2026-11-09); a root records its own id. Discovery holds a descendant to the
    # selected root's id.
    session = payload.get("session_id", sid)
    if not isinstance(session, str) or len(session) != 36 or (session != sid and not parent):
        raise marker.FreezeError("codex-source-identity-unconfirmed")
    return sid, parent, context._record_timestamp(row), session


def _selection(config: Any, entry: dict[str, Any]) -> tuple[Path, Path, list[Path]]:  # noqa: C901, PLR0912 - independent native membership guards
    raw_root, raw_path = entry.get("sessions_root"), entry.get("transcript")
    if (
        not isinstance(raw_root, str)
        or not raw_root.strip()
        or not isinstance(raw_path, str)
        or not raw_path.strip()
    ):
        raise marker.FreezeError("codex-source-root-invalid")
    root, path = Path(raw_root).absolute(), Path(raw_path).absolute()
    if not root.is_dir() or root.is_symlink() or not outside_repository(root):
        raise marker.FreezeError("codex-source-root-invalid")
    native_roots = {
        Path(native).resolve() for native in config.store_roots.get("codex.sessions", ())
    }
    resolved_root = root.resolve()
    if entry.get("origin") == marker.ORIGIN_SYNTHESISED:
        if any(
            resolved_root.is_relative_to(native) or native.is_relative_to(resolved_root)
            for native in native_roots
        ):
            raise marker.FreezeError("codex-authored-root-overlaps-native-store")
    elif resolved_root not in native_roots:
        raise marker.FreezeError("codex-source-not-native-store")
    selected = entry.get("children")
    if not isinstance(selected, list) or not all(isinstance(p, str) for p in selected):
        raise marker.FreezeError("codex-children-selection-required")
    children = sorted(Path(p).absolute() for p in selected)
    # Metadata-only discovery is independent of the owner's selected children.
    paths = sorted(root.rglob("rollout-*.jsonl"))
    if len(paths) > MAX_FILES:
        raise marker.FreezeError("codex-source-discovery-limit")
    for source in dict.fromkeys((path, *children, *paths)):
        if (
            not source.resolve().is_relative_to(resolved_root)
            or source.is_symlink()
            or not outside_repository(source)
        ):
            raise marker.FreezeError("codex-source-outside-selection")
    sid, parent, _, _ = _head(path)
    if sid != entry.get("sid") or parent:
        raise marker.FreezeError("codex-source-other-session")
    heads: dict[str, tuple[Path, str]] = {}
    sessions: dict[str, str] = {}
    for candidate in paths:
        identity, parent, at, session = _head(candidate)
        if at is None:
            raise marker.FreezeError("codex-source-head-untimed")
        if at > float(entry["captured_at"]):
            continue
        if identity in heads:
            raise marker.FreezeError("codex-source-identity-ambiguous")
        heads[identity] = (candidate, parent)
        sessions[identity] = session
    wanted = {sid}
    while True:
        more = {identity for identity, (_, parent) in heads.items() if parent in wanted}
        if more <= wanted:
            break
        wanted |= more
    claimed = {identity for identity, session in sessions.items() if session == sid}
    # An orphan or cycle can claim this root without being reached by the parent walk.
    if claimed - {sid} != wanted - {sid}:
        raise marker.FreezeError("codex-source-identity-unconfirmed")
    discovered = sorted(heads[identity][0].absolute() for identity in wanted - {sid})
    if children != discovered or len(set(children)) != len(children):
        raise marker.FreezeError("codex-children-differ")
    return root, path, children


def _seal(config: Any, path: Path, captured: float) -> dict[str, Any]:
    from compass_runtime import project_context as context

    prefix = context.codex_source_prefix(config, str(path), captured)
    sid, parent, _, _ = _head(path)
    return {
        "path": str(path),
        "sid": sid,
        "parent": parent,
        "bytes": len(prefix),
        "sha256": hashlib.sha256(prefix).hexdigest(),
    }


def _refusals(path: str, sid: str) -> list[dict[str, Any]]:
    from compass_runtime import observer, records
    from compass_runtime import project_context as context

    result: list[dict[str, Any]] = []
    with open(path, "rb") as handle:
        for index, raw in enumerate(handle):
            record = json.loads(raw)
            payload = records.as_dict(record.get("payload"))
            if (
                record.get("type") == "response_item"
                and payload.get("type") == "message"
                and payload.get("role") == "user"
                and (
                    not context.codex_person_record(record)
                    or observer.parse_reader_record(record, cap=len(raw)) is None
                )
            ):
                result.append(
                    {
                        "source": marker._source_digest([sid, index]),
                        "reason": "person-authorship-unconfirmed",
                    }
                )
    return result


def _verify_cuts(paths: tuple[str, ...], sources: dict[str, Any]) -> None:
    seals = [sources["parent"], *sources["children"]]
    if len(paths) != len(seals) or any(
        hashlib.sha256(Path(path).read_bytes()).hexdigest() != seal["sha256"]
        for path, seal in zip(paths, seals, strict=True)
    ):
        raise marker.FreezeError("production-source-moved")


def _person_events(config: Any, lines: Iterable[str], sid: str) -> list[dict[str, Any]]:
    from compass_runtime import project_context as context

    people: dict[tuple[float, str], dict[str, Any]] = {}
    for raw in lines:
        record = context._json_dict(raw.encode())
        if record is None or record.get("type") != "response_item":
            continue
        if context.codex_person_record(record):
            event = context._instruction_event(config, record, "codex", sid)
            if event is not None:
                people.setdefault((event["at"], event["title"]), event)
    return list(people.values())


def _person_history(config: Any, cut: str, sid: str, now: float) -> dict[str, Any]:
    from compass_runtime import io as runtime_io
    from compass_runtime import project_context as context
    from compass_runtime import semantic_history

    lines = reversed(
        list(runtime_io.reverse_lines(config, cut, max_bytes=context.SEMANTIC_BACKFILL_MAX_BYTES))
    )
    decoded = (line.decode("utf-8", "replace") for line in lines)
    since = now - context.SEMANTIC_HISTORY_HORIZON_SEC
    people = [event for event in _person_events(config, decoded, sid) if event["at"] >= since]
    history = context._semantic_model(context._dedupe_project_events(people), [], now=now)
    incoming = [
        event
        for fact in history["facts"]
        if (event := semantic_history._event_from_fact(fact, {})) is not None
    ]
    return {"events": semantic_history._redact_history(semantic_history._merge([], incoming))}


def _focused_facts(
    config: Any, cut: str, child_cuts: tuple[str, ...], sid: str, now: float
) -> tuple[list[dict[str, Any]], Any]:
    from compass_runtime import io as runtime_io
    from compass_runtime import project_context as context

    tally = context._codex_tally(config, cut, child_paths=child_cuts)
    if tally is None:
        raise context.FrozenCheckCutoffUnreachableError("codex commands unreadable")
    if (
        tally.named_unread
        or tally.parent_failed
        or tally.scan.get("subagent_transcripts_unread")
        or tally.scan.get("unread_calls")
    ):
        raise context.FrozenCheckCutoffUnreachableError("codex checks incomplete")
    people = _person_events(config, runtime_io.read_tail(config, cut), sid)
    limits = marker.codex_analyze_limits(config)
    checks = tally.entries(sid, cap=limits.analyze_listed_checks)
    # The live timeline reserves check slots before other events. Capping facts
    # after projection could leave a file write that Analyze never kept.
    timeline = context._project_timeline(
        [*people, *checks], ("codex", sid), cap=limits.analyze_record_events
    )
    # Analyze can recover a reader instruction even when checks fill every timeline slot.
    # The sealed parent supplies that history so the qualification needs no observer store.
    semantic = context._merge_semantic_history(
        context._semantic_model(timeline, [], now=now),
        _person_history(config, cut, sid, now),
        now=now,
    )
    return semantic["facts"], context._press(tally)


def freeze_case(config: Any, entry: dict[str, Any]) -> dict[str, Any]:
    from dataclasses import replace

    from compass_runtime import project_context as context
    from compass_runtime import transcripts
    from compass_runtime.collectors import codex

    if (
        not isinstance(entry, dict)
        or entry.get("harness") != "codex"
        or not marker._epoch(entry.get("captured_at"))
    ):
        raise marker.FreezeError("codex-source-spec-invalid")
    captured = float(entry["captured_at"])
    sid = str(entry.get("sid") or "")
    provenance = _provenance(entry)
    root, path, children = _selection(config, entry)
    intent = entry.get("intent")
    if (
        not isinstance(intent, dict)
        or not marker._epoch(intent.get("at"))
        or intent["at"] > captured
        or type(intent.get("n")) is not int
        or intent["n"] < 1
        or not marker.case_lines({"intent": intent})
    ):
        raise marker.FreezeError("codex-saved-intent-required")
    sources: dict[str, Any] = {
        "v": 1,
        "root": str(root),
        "captured_at": captured,
        "parent": _seal(config, path, captured),
        "children": [_seal(config, child, captured) for child in children],
        "intent_digest": marker._source_digest(intent),
    }
    sources["selection_digest"] = marker._source_digest(
        [str(root), str(path), [str(p) for p in children]]
    )
    with context.frozen_codex_sources(
        config, str(path), until=captured, child_paths=[str(p) for p in children]
    ) as (cut, child_cuts):
        _verify_cuts((cut, *child_cuts), sources)
        # Analyze the entire already-bounded prefix. A current tail could lose the
        # task_complete needed to distinguish a late result from a resumed turn.
        info = transcripts.analyze_codex_transcript(
            replace(config, tail_bytes=config.turn_scan_max_bytes), cut
        )
        stop = codex.transcript_turn_end(
            config, info, work_activity=float(info.get("last_turn_ts") or 0), blocked=False
        )
        supplied = entry.get("row")
        if (
            not isinstance(supplied, dict)
            or supplied.get("state") != "idle"
            or supplied.get("finished_at") is not None
            or supplied.get("ended_at") is not None
        ):
            raise marker.FreezeError("codex-lifecycle-unconfirmed")
        if (
            stop is None
            or supplied.get("turn_end_at") != stop
            or context.codex_activity_between(cut, stop, captured)
        ):
            raise marker.FreezeError("codex-lifecycle-unconfirmed")
        if captured < stop + config.reading_settle_sec:
            raise marker.FreezeError("captured-before-settled")
        for child in child_cuts:
            child_info = transcripts.analyze_codex_transcript(
                replace(config, tail_bytes=config.turn_scan_max_bytes), child
            )
            child_stop = codex.transcript_turn_end(
                config,
                child_info,
                work_activity=float(child_info.get("last_turn_ts") or 0),
                blocked=False,
            )
            if (
                child_stop is None
                or context.codex_activity_between(child, child_stop, captured)
                or child_info.get("last_event_ts", 0) > stop
            ):
                raise marker.FreezeError("codex-child-active")
        facts, press = _focused_facts(config, cut, child_cuts, sid, captured)
        refusals = _refusals(cut, sid)
    case: dict[str, Any] = {
        "codex_format": marker.FORMAT_CODEX,
        "id": marker._case_id("codex", sid),
        "harness": "codex",
        "sid": sid,
        **provenance,
        "captured_at": captured,
        "row_snapshot": {
            "harness": "codex",
            "sid": sid,
            "state": "idle",
            "turn_end_at": stop,
            "finished_at": None,
            "ended_at": None,
        },
        "intent": intent,
        "sources": sources,
        "parser": parser_digest(),
        "transcript_bytes": sources["parent"]["bytes"],
        "transcript_cut": "capture",
        "lifecycle_from": "codex-transcript",
        "producer_facts": facts,
        "message_refusals": refusals,
        "unconfirmed": [],
        "tool_output": {
            "tails": dict(press.tails),
            "changed_after": sorted(map(list, press.changed_after)),
            "read_incomplete": sorted(map(list, press.read_incomplete)),
        },
    }
    case["production_reading"] = marker._production_capture(config, case, str(path))
    return case


def source_entry(case: dict[str, Any], transcript: str) -> dict[str, Any]:
    sources = case["sources"]
    if transcript != sources["parent"]["path"]:
        raise marker.FreezeError("codex-source-selection-differs")
    return {
        **_provenance(case),
        "harness": "codex",
        "sid": case["sid"],
        "sessions_root": sources["root"],
        "transcript": transcript,
        "children": [row["path"] for row in sources["children"]],
        "captured_at": case["captured_at"],
        "intent": case["intent"],
        "row": case["row_snapshot"],
    }


@contextlib.contextmanager
def historical_source(config: Any, case: dict[str, Any], transcript: str) -> Any:
    from compass_runtime import project_context as context

    entry = source_entry(case, transcript)
    root, path, children = _selection(config, entry)
    sources = case["sources"]
    captured = float(case["captured_at"])
    if sources.get("captured_at") != captured or sources.get(
        "selection_digest"
    ) != marker._source_digest([str(root), str(path), [str(p) for p in children]]):
        raise marker.FreezeError("codex-source-selection-differs")
    if sources["parent"] != _seal(config, path, captured) or sources["children"] != [
        _seal(config, child, captured) for child in children
    ]:
        raise marker.FreezeError("production-source-differs")
    with context.frozen_codex_sources(
        config, str(path), until=captured, child_paths=[str(p) for p in children]
    ) as (cut, cuts):
        _verify_cuts((cut, *cuts), sources)
        yield cut, sources["parent"]["sha256"]


def content_refusal(config: Any, case: dict[str, Any], transcript: str) -> list[str]:
    if case.get("parser") != parser_digest():
        return ["frozen-on-another-parser"]
    try:
        expected = freeze_case(config, source_entry(case, transcript))
    except (marker.FreezeError, OSError, ValueError, KeyError, TypeError, RuntimeError):
        return ["codex-source-unconfirmed"]
    return [] if expected == case else ["codex-frozen-content-differs"]


def _freeze_packet(spec_path: str) -> int:
    if not outside_repository(Path(marker.CASES_PATH)) or not outside_repository(Path(spec_path)):
        raise marker.FreezeError("codex-packet-must-stay-outside-repository")
    if Path(spec_path).is_symlink():
        raise marker.FreezeError("codex-spec-linked")
    spec = json.loads(
        marker._export_bytes(str(Path(spec_path).resolve()), 1024 * 1024),
        object_pairs_hook=marker._export_object,
    )
    if not isinstance(spec, dict):
        raise marker.FreezeError("codex-spec-invalid")
    entries = spec.get("cases")
    if not isinstance(entries, list) or not entries:
        raise marker.FreezeError("codex-no-cases")
    if Path(marker.CASES_PATH).exists():
        raise marker.FreezeError("codex-packet-already-exists")
    cases = [freeze_case(marker._runtime_config(), entry) for entry in entries]
    if len({case["id"] for case in cases}) != len(cases):
        raise marker.FreezeError("codex-duplicate-case")
    marker._write(marker.CASES_PATH, {"v": marker.FORMAT_CODEX, "cases": cases})
    return len(cases)


def freeze(spec_path: str) -> int:
    """Read only explicit private selections; persist no raw cut or recovered reply."""
    try:
        count = _freeze_packet(spec_path)
    except (marker.FreezeError, OSError, ValueError, KeyError, TypeError, RuntimeError):
        print(
            "codex-source-unconfirmed: source, lifecycle or packet selection is unconfirmed. "
            "Nothing was written."
        )
        return 1
    print(f"Froze {count} Codex cases privately. No model called.")
    return 0
