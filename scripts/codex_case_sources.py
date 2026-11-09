"""Offline native Codex source admission. No dashboard, observer state or model calls.

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
from typing import Any

import mark_abstention as marker
from codex_case_candidates import MAX_FILES, outside_repository


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
            "reading_maps.py",
            "entry_numbers.py",
            "git_status.py",
            "claude_data.py",
        )
    ]
    paths += [Path(__file__), Path(marker.__file__)]
    for path in paths:
        digest.update(path.name.encode() + b"\0")
        digest.update(
            ast.dump(ast.parse(path.read_bytes()), include_attributes=False).encode() + b"\0"
        )
    return digest.hexdigest()


def _head(path: Path) -> tuple[str, str, float | None]:
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
    if (
        not isinstance(sid, str)
        or len(sid) != 36
        or not path.name.endswith(sid + ".jsonl")
        or payload.get("session_id", sid) != sid
    ):
        raise marker.FreezeError("codex-source-identity-unconfirmed")
    parent = context._codex_parent(row, str(path))
    return sid, parent, context._record_timestamp(row)


def _selection(config: Any, entry: dict[str, Any]) -> tuple[Path, Path, list[Path]]:  # noqa: C901, PLR0912 - independent native membership guards
    root = Path(str(entry.get("sessions_root") or "")).absolute()
    path = Path(str(entry.get("transcript") or "")).absolute()
    if not root.is_dir() or root.is_symlink() or not outside_repository(root):
        raise marker.FreezeError("codex-source-root-invalid")
    native_roots = config.store_roots.get("codex.sessions", ())
    if root.resolve() not in {Path(native).resolve() for native in native_roots}:
        raise marker.FreezeError("codex-source-not-native-store")
    selected = entry.get("children")
    if not isinstance(selected, list) or not all(isinstance(p, str) for p in selected):
        raise marker.FreezeError("codex-children-selection-required")
    children = sorted(Path(p).absolute() for p in selected)
    for source in (path, *children):
        if not source.resolve().is_relative_to(root.resolve()) or source.is_symlink():
            raise marker.FreezeError("codex-source-outside-selection")
    sid, parent, _ = _head(path)
    if sid != entry.get("sid") or parent:
        raise marker.FreezeError("codex-source-other-session")
    # Metadata-only discovery is independent of the owner's selected children.
    paths = sorted(root.rglob("rollout-*.jsonl"))
    if len(paths) > MAX_FILES:
        raise marker.FreezeError("codex-source-discovery-limit")
    heads: dict[str, tuple[Path, str]] = {}
    for candidate in paths:
        identity, parent, at = _head(candidate)
        if at is None:
            raise marker.FreezeError("codex-source-head-untimed")
        if at > float(entry["captured_at"]):
            continue
        if identity in heads:
            raise marker.FreezeError("codex-source-identity-ambiguous")
        heads[identity] = (candidate, parent)
    wanted = {sid}
    while True:
        more = {identity for identity, (_, parent) in heads.items() if parent in wanted}
        if more <= wanted:
            break
        wanted |= more
    discovered = sorted(heads[identity][0].absolute() for identity in wanted - {sid})
    if children != discovered or len(set(children)) != len(children):
        raise marker.FreezeError("codex-children-differ")
    return root, path, children


def _seal(config: Any, path: Path, captured: float) -> dict[str, Any]:
    from compass_runtime import project_context as context

    prefix = context.codex_source_prefix(config, str(path), captured)
    sid, parent, _ = _head(path)
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
        checks, press = context.frozen_codex_checks(
            config, cut, sid, until=captured, child_paths=child_cuts
        )
        _, people = context.frozen_codex_user_messages(config, cut, sid, until=captured)
        _, agents = context.frozen_codex_agent_messages(config, cut, sid, until=captured)
        refusals = _refusals(cut, sid)
    case: dict[str, Any] = {
        "codex_format": marker.FORMAT_CODEX,
        "id": marker._case_id("codex", sid),
        "harness": "codex",
        "sid": sid,
        "origin": "recorded",
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
        "producer_facts": [*people, *agents, *checks],
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
