"""Antigravity CLI (``agy``) collection.

Antigravity keeps one SQLite store per conversation under the Gemini home,
plus a workspace cache and CLI logs. Conversation content is never decoded:
discovery and state come from store mtime and from protobuf metadata fields,
which is why this collector still reports on a build without ``sqlite3``.

Split from ``gemini.py`` when Gemini CLI was retired. The two shared a
registry row while both were Google's current surface; see
``docs/design-harness-registry.md``.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
from typing import TYPE_CHECKING, Any

from compass_runtime import claude_data, records, sessions, transcripts, turns
from compass_runtime import config as runtime_config
from compass_runtime import io as runtime_io
from compass_runtime import quota as runtime_quota

if TYPE_CHECKING:
    from collections.abc import Iterator

    from compass_runtime.config import RuntimeConfig
    from compass_runtime.sessions import Session
    from compass_runtime.state import RuntimeState


def _root(config: RuntimeConfig) -> str:
    return runtime_config.primary_store(config, "antigravity.root")


def _conversations_dir(config: RuntimeConfig) -> str:
    return os.path.join(_root(config), "conversations")


def _log_dir(config: RuntimeConfig) -> str:
    return os.path.join(_root(config), "log")


def _last_conversations_path(config: RuntimeConfig) -> str:
    return os.path.join(_root(config), "cache", "last_conversations.json")


def _log_head_lines_from(
    config: runtime_config.RuntimeConfig,
    path: str,
) -> list[str]:
    try:
        return (
            runtime_io.read_prefix_bytes(
                path,
                max_bytes=config.antigravity_log_head_bytes,
            )
            .decode("utf-8", "replace")
            .splitlines()
        )
    except OSError:
        return []


def _log_head_lines(config: RuntimeConfig, path: str) -> list[str]:
    """Read the bounded identity-bearing beginning of an Antigravity CLI log."""
    return _log_head_lines_from(config, path)


def _log_lines(config: RuntimeConfig, path: str) -> list[str]:
    """Read the beginning and bounded tail of an Antigravity CLI log.

    Workspace and conversation identity are written near the beginning,
    while the latest user prompt is near the tail. Long-running logs can
    exceed ``tail_bytes``, so reading only one side loses one of those.
    """
    return _log_head_lines_from(config, path) + runtime_io.read_tail(config, path)


def _session_metadata(
    config: RuntimeConfig,
    now: float,
    window_hours: float,
    show_all: bool,
) -> dict[str, dict[str, Any]]:
    """Best-effort conversation metadata from Antigravity's public-facing
    CLI logs and last-conversation cache.

    Conversation payloads are protobuf blobs inside per-session SQLite
    stores. The logs already expose the stable boundaries needed here:
    workspace, conversation id, and human prompt. Broken or rotated files are
    skipped so one incomplete Antigravity run cannot break the dashboard.
    """
    found: dict[str, dict[str, Any]] = {}
    cached_cwds: dict[str, str] = {}
    try:
        with open(_last_conversations_path(config), encoding="utf-8") as source:
            recent = json.load(source)
        if isinstance(recent, dict):
            for workspace, sid in recent.items():
                if (
                    isinstance(workspace, str)
                    and isinstance(sid, str)
                    and sessions.project_from_cwd(config, workspace)
                ):
                    found.setdefault(sid, {})["cwd"] = workspace
                    cached_cwds[sid] = workspace
    except (OSError, ValueError, TypeError, RecursionError):
        pass

    all_logs = runtime_io.glob_under(_log_dir(config), "cli-*.log")
    try:
        all_logs.sort(key=os.path.getmtime)
    except OSError:
        all_logs.sort()
    logs = all_logs
    if not show_all:
        recent_logs: list[str] = []
        for path in logs:
            try:
                if sessions.is_fresh(config, now, os.path.getmtime(path), window_hours * 3600):
                    recent_logs.append(path)
            except OSError:
                continue
        logs = recent_logs

    workspace_re = re.compile(r"workspaceDirs=\[(.*?)\]\s+appDataDir=")
    session_re = re.compile(r"(?:Created|Streaming) conversation ([0-9a-fA-F-]{36})")
    forward_re = re.compile(r"Forwarding user message to conversation ([0-9a-fA-F-]{36})")
    prompt_marker = "HandleUserInput called with text: "
    workspace_primaries: dict[str, str] = {}
    events: list[tuple[str, str | None, str | None]] = []

    for path in logs:
        workspace = None
        pending_prompt = None
        for line in _log_lines(config, path):
            match = workspace_re.search(line)
            if match:
                workspace = match.group(1).strip() or None
                continue
            match = session_re.search(line)
            if match:
                sid = match.group(1)
                if workspace and sid in cached_cwds:
                    workspace_primaries[workspace] = cached_cwds[sid]
                events.append((sid, workspace, None))
                continue
            if prompt_marker in line:
                raw = line.split(prompt_marker, 1)[1].strip()
                try:
                    decoded = json.loads(raw)
                    pending_prompt = decoded if isinstance(decoded, str) else raw
                except (ValueError, TypeError, RecursionError):
                    pending_prompt = raw.strip('"')
                pending_prompt = records.safe_text(pending_prompt, 2000)
                continue
            match = forward_re.search(line)
            if match:
                sid = match.group(1)
                if workspace and sid in cached_cwds:
                    workspace_primaries[workspace] = cached_cwds[sid]
                prompt = None
                if pending_prompt:
                    prompt = pending_prompt
                    pending_prompt = None
                events.append((sid, workspace, prompt))

    # last_conversations.json names only the newest session for a workspace.
    # That anchor session can be quiet while a sibling using the same
    # multi-folder context remains active. Recover only its identity from
    # bounded stale-log heads; stale prompts and session events stay excluded.
    missing_contexts = {
        workspace
        for _, workspace, _ in events
        if workspace and workspace not in workspace_primaries
    }
    if missing_contexts and cached_cwds and not show_all:
        recent_paths = set(logs)
        for path in reversed(all_logs):
            if path in recent_paths:
                continue
            workspace = None
            for line in _log_head_lines(config, path):
                match = workspace_re.search(line)
                if match:
                    workspace = match.group(1).strip() or None
                    continue
                match = session_re.search(line) or forward_re.search(line)
                if not match:
                    continue
                sid = match.group(1)
                if workspace is not None and workspace in missing_contexts and sid in cached_cwds:
                    workspace_primaries[workspace] = cached_cwds[sid]
                    missing_contexts.remove(workspace)
            if not missing_contexts:
                break

    for sid, workspace, prompt in events:
        session = found.setdefault(sid, {})
        if workspace:
            session["cwd"] = workspace_primaries.get(workspace, workspace)
        if prompt:
            session["last_prompt"] = prompt
    return found


def _wal_has_data(path: str) -> bool:
    """Whether an Antigravity WAL has content beyond an empty sidecar."""
    with contextlib.suppress(OSError):
        return os.path.getsize(path + "-wal") > 0
    return False


def _store_mtime(config: RuntimeConfig, path: str, now: float) -> float:
    """Newest plausible durable activity marker for a conversation store."""
    mtimes: list[float] = []
    with contextlib.suppress(OSError):
        mtimes.append(os.path.getmtime(path))
    if _wal_has_data(path):
        with contextlib.suppress(OSError):
            mtimes.append(os.path.getmtime(path + "-wal"))
    return sessions.newest_plausible(config, now, mtimes)


def protobuf_fields(payload: Any) -> Iterator[tuple[int, int, Any]]:
    """Yield ``(field_number, wire_type, value)`` from a protobuf message.

    Antigravity persists step metadata as protobuf without shipping Python
    descriptors. This bounded wire reader extracts only the stable scalar and
    length-delimited envelope fields needed by the dashboard. Malformed
    messages raise ``ValueError`` and non-buffer payloads raise ``TypeError``;
    callers skip both.
    """
    if not isinstance(payload, (bytes, bytearray, memoryview)):
        raise TypeError("protobuf payload must be bytes-like")
    payload = bytes(payload)
    offset = 0

    def read_varint(position: int) -> tuple[int, int]:
        value = 0
        for shift in range(0, 70, 7):
            if position >= len(payload):
                raise ValueError("truncated protobuf varint")
            byte = payload[position]
            position += 1
            value |= (byte & 0x7F) << shift
            if byte < 0x80:
                return value, position
        raise ValueError("oversized protobuf varint")

    value: Any  # varint int or a length-delimited/fixed-width bytes slice
    while offset < len(payload):
        key, offset = read_varint(offset)
        number, wire_type = key >> 3, key & 7
        if not number:
            raise ValueError("invalid protobuf field")
        if wire_type == 0:
            value, offset = read_varint(offset)
        elif wire_type == 1:
            if offset + 8 > len(payload):
                raise ValueError("truncated protobuf fixed64")
            value = payload[offset : offset + 8]
            offset += 8
        elif wire_type == 2:
            size, offset = read_varint(offset)
            end = offset + size
            if end > len(payload):
                raise ValueError("truncated protobuf bytes")
            value = payload[offset:end]
            offset = end
        elif wire_type == 5:
            if offset + 4 > len(payload):
                raise ValueError("truncated protobuf fixed32")
            value = payload[offset : offset + 4]
            offset += 4
        else:
            raise ValueError(f"unsupported protobuf wire type {wire_type}")
        yield number, wire_type, value


def protobuf_first(payload: Any, number: int, wire_type: int) -> Any:
    try:
        for field, wire, value in protobuf_fields(payload):
            if field == number and wire == wire_type:
                return value
    except (ValueError, TypeError):
        pass
    return None


def protobuf_timestamp(payload: Any) -> float:
    seconds = protobuf_first(payload, 1, 0)
    nanos = protobuf_first(payload, 2, 0) or 0
    if not seconds:
        return 0
    return float(seconds + nanos / 1_000_000_000)


def _step_info(metadata: Any) -> dict[str, Any]:
    """Timestamp, output usage, and tool labels from a step metadata blob."""
    started = protobuf_first(metadata, 1, 2)
    usage = protobuf_first(metadata, 9, 2)
    summary = protobuf_first(metadata, 30, 2)
    action = protobuf_first(metadata, 31, 2)
    output_tokens = protobuf_first(usage, 3, 0) if usage else 0

    def text(value: Any) -> str:
        if not value:
            return ""
        return records.safe_text(value.decode("utf-8", "replace"), 140)

    return {
        "epoch": protobuf_timestamp(started) if started else 0,
        "output_tokens": output_tokens or 0,
        "tool_summary": text(summary),
        "tool_action": text(action),
    }


def _step_activity(
    config: RuntimeConfig,
    state: RuntimeState,
    path: str,
    now: float,
    gaps: set[str] | None = None,
) -> dict[str, Any]:
    """Read live rate, turn boundaries, and current action from a store.

    Prefer a plain ``mode=ro`` connection: it sees committed WAL frames, so
    activity from a live Antigravity writer is current. Some stores refuse
    plain read-only opens (e.g. WAL recovery is needed but the reader cannot
    create shm/journal files); for those, fall back to ``immutable=1``, which
    never contends with the writer but may lag until checkpoint. A transient
    or incompatible store simply returns an empty activity snapshot.
    """
    result: dict[str, Any] = {
        "rate_per_min": 0,
        "turns": None,
        "last_tool_action": "",
    }
    if not runtime_io.sqlite_available():
        if gaps is not None:
            gaps.update((sessions.UNREAD_HISTORY, sessions.UNREAD_TOKENS))
        return result
    query = "SELECT step_type, metadata FROM steps ORDER BY idx DESC LIMIT ?"
    rows = None
    read_error: BaseException | None = None
    for uri in (
        runtime_io.sqlite_ro_uri(path),
        runtime_io.sqlite_ro_uri(path, immutable=True),
    ):
        try:
            con = runtime_io.sqlite_module.connect(uri, uri=True, timeout=0.2)
        except runtime_io.sqlite_module.Error as exc:
            read_error = exc
            continue
        try:
            rows = con.execute(query, (config.sql_message_limit,)).fetchall()
            break
        except runtime_io.sqlite_module.Error as exc:
            read_error = exc
            continue
        finally:
            con.close()
    if rows is None:
        if read_error:
            runtime_io.record_store_error(state, path, read_error)
        # Both rungs of the ladder are spent, so the empty snapshot below is
        # about to be published as a real reading: rate zero and no turn, which
        # the page cannot tell from a session that has genuinely done nothing.
        # The two readings the snapshot loses are named separately because the
        # reader compares them against different things on the row.
        if gaps is not None:
            gaps.update((sessions.UNREAD_HISTORY, sessions.UNREAD_TOKENS))
        return result

    events = []
    usage_events = []
    last_prompt = 0
    latest_action = (0, "")
    for step_type, metadata in reversed(rows):
        info = _step_info(metadata)
        epoch = info["epoch"]
        if not epoch:
            continue
        is_prompt = step_type == 14
        events.append((epoch, is_prompt))
        if is_prompt:
            last_prompt = epoch
            latest_action = (0, "")
        if step_type == 15 and info["output_tokens"]:
            usage_events.append((epoch, info["output_tokens"]))
        action = info["tool_action"] or info["tool_summary"]
        if action and epoch >= last_prompt:
            latest_action = (epoch, action)

    recent = sum(
        tokens
        for epoch, tokens in usage_events
        if sessions.is_fresh(config, now, epoch, config.rate_window_sec)
    )
    result["rate_per_min"] = round(recent / (config.rate_window_sec / 60))
    result["turns"] = turns.turns_from_events(events) if events else None
    result["last_tool_action"] = latest_action[1]
    return result


# Antigravity records the model, but not as a column: no table in a conversation
# store has one, which is why a `PRAGMA table_info` survey once concluded the
# harness does not report it. The value is inside the protobuf blob in
# `gen_metadata.data`, at top-level field 1 then nested field 21, as the product
# display name ("Gemini 3.6 Flash (High)"). Nested field 19 carries a model id
# too and is never preferred: it is an internal alias ("gemini-pro-default"
# where 21 says "Gemini 3.1 Pro (High)"), so publishing it would need an
# alias-to-name table, which is a guess.
#
# Field 21 was the terminal field of every blob observed — an observed
# serialization property, not a documented one — so the read is a 64-byte tail
# slice, not a blob decode.
#
# The slice comes from `Connection.blobopen`, not from `substr(data,-64)`, and
# the difference is the privacy argument rather than a micro-optimisation.
# `substr()` is a scalar function over a *value*: SQLite materialises the whole
# row — every byte of the verbatim system-prompt text that sits before the name
# — and then discards all but 64 of them. Incremental blob I/O never builds that
# value at all. Measured on a 50 MB row: +50 MB peak RSS for `substr`, +9 MB for
# `blobopen` (which caps at the page cache). Only 64 bytes ever reach Python
# either way; the row is what differs.
#
# What this does NOT bound is the traversal. SQLite reaches the tail of an
# overflow-page chain by walking it, so page reads still scale with the row —
# measured 0.28 ms on a 783 KB row, per inspected store per refresh, and real
# stores reach that size because `ORDER BY idx DESC LIMIT 1` selects the newest
# generation, which is the largest row in the store. That cost belongs to the
# harness's row shape, not to this query, and no read of this column can avoid
# it. Do not re-derive it as a bound this read does not claim.
#
# The safety argument is unchanged. The parse is accepted only when the field
# runs exactly to the end of the tail, so if a future Antigravity build appends
# a field after 21 the check fails and the session reports no model rather than
# a wrong one.
#
# The window stays at 64 bytes for privacy, not for speed: a 700-byte tail on
# the same row holds verbatim system-prompt text, and pulling conversation
# content into process memory buys nothing. 64 bytes admits any name up to 61
# characters; a longer one falls to "no model reported", which is the correct
# reading of a blob we could not validate, not a bug to widen the window for.
_MODEL_ROW_QUERY = "SELECT rowid FROM gen_metadata ORDER BY idx DESC LIMIT 1"
_MODEL_TAIL_BYTES = 64
_MODEL_FIELD_TAG = b"\xaa\x01"  # field 21, wire type 2


def _model_tail(con: Any) -> tuple[bool, bytes | None]:
    """Read outcome and last ``_MODEL_TAIL_BYTES`` of the newest generation.

    Rides the caller's already-open connection and fails on its own terms: a
    store on a schema without ``gen_metadata``, one with no generations yet, and
    one whose newest row holds no readable blob all withdraw the model and
    nothing else. Only a successful empty query returns ``(True, None)``;
    conflating it with a failed read would badge every unanswered session.
    The caller's parent-identity read is untouched.
    """
    try:
        row = con.execute(_MODEL_ROW_QUERY).fetchone()
        if not row:
            return True, None
        blob = con.blobopen("gen_metadata", "data", row[0], readonly=True)
    except runtime_io.sqlite_module.Error:
        return False, None
    try:
        blob.seek(max(0, len(blob) - _MODEL_TAIL_BYTES))
        return True, blob.read(_MODEL_TAIL_BYTES)
    except (runtime_io.sqlite_module.Error, OSError, ValueError):
        return False, None
    finally:
        blob.close()


def _model_from_tail(tail: Any) -> str | None:
    """Validated model display name from the tail bytes of a ``gen_metadata`` blob."""
    if not isinstance(tail, (bytes, bytearray, memoryview)):
        return None
    data = bytes(tail)
    for offset in range(len(data) - 2):
        if data[offset : offset + 2] != _MODEL_FIELD_TAG:
            continue
        # A one-byte length is all a 64-byte window can hold, and the field must
        # run to the last byte of the blob. Both together are the check.
        if offset + 3 + data[offset + 2] != len(data):
            continue
        try:
            name = data[offset + 3 :].decode("utf-8")
        except UnicodeDecodeError:
            continue
        return records.safe_text(name, sessions.MODEL_CAP_CHARS).strip() or None
    return None


def _session_info(
    _config: RuntimeConfig,
    state: RuntimeState,
    path: str,
    sid: str,
) -> dict[str, Any]:
    """Extract parent conversation ID, subagent label, and model from a store."""
    info: dict[str, Any] = {
        "parent_id": None,
        "subagent_label": None,
        "model": None,
        "model_unread": True,
    }
    if not runtime_io.sqlite_available():
        return info
    query = "SELECT data FROM trajectory_metadata_blob WHERE id='main'"

    def read_store(uri: str) -> tuple[bool, Any, Any, BaseException | None]:
        try:
            con = runtime_io.sqlite_module.connect(uri, uri=True, timeout=0.2)
        except runtime_io.sqlite_module.Error as exc:
            return False, None, None, exc
        try:
            row = con.execute(query).fetchone()
            # The model rides this connection rather than opening a second one,
            # and it fails on its own: a store on a schema without
            # `gen_metadata` still reports its parent.
            model_read = _model_tail(con)
        except runtime_io.sqlite_module.Error as exc:
            return False, None, None, exc
        else:
            return True, row, model_read, None
        finally:
            con.close()

    readable, row, model_read, read_error = read_store(runtime_io.sqlite_ro_uri(path))
    if not readable and _wal_has_data(path):
        if read_error:
            runtime_io.record_store_error(state, path, read_error)
        return info
    if not readable:
        readable, row, model_read, fallback_error = read_store(
            runtime_io.sqlite_ro_uri(path, immutable=True)
        )
        if _wal_has_data(path):
            if read_error:
                runtime_io.record_store_error(state, path, read_error)
            return info
        if not readable:
            if fallback_error:
                runtime_io.record_store_error(state, path, fallback_error)
            return info
    # A store with no generations yet reads fine and reports no model; that is a
    # session that never got a reply, not a store error. Set it before the
    # identity row is examined, so a missing `main` row withdraws only the
    # parent it feeds.
    model_readable, tail = model_read
    info["model"] = _model_from_tail(tail)
    info["model_unread"] = not model_readable or (tail is not None and info["model"] is None)
    if not row or not row[0]:
        return info
    data = row[0]

    def text(value: Any) -> str | None:
        if not isinstance(value, (bytes, bytearray, memoryview)):
            return None
        with contextlib.suppress(UnicodeDecodeError):
            return bytes(value).decode("utf-8") or None
        return None

    p5 = text(protobuf_first(data, 5, 2))
    p6 = text(protobuf_first(data, 6, 2))
    parent_id = p5 or (p6 if p6 != sid else None)
    if parent_id:
        info["parent_id"] = parent_id
        f8 = protobuf_first(data, 8, 2)
        labels = (
            text(protobuf_first(f8, 2, 2)),
            text(protobuf_first(f8, 1, 2)),
        )
        info["subagent_label"] = next(
            (
                cleaned
                for label in labels
                if label
                for cleaned in (records.safe_text(label, 70).strip(),)
                if cleaned
            ),
            None,
        )
    return info


def collect(
    config: RuntimeConfig,
    state: RuntimeState,
    now: float,
    window_hours: float,
    show_all: bool,
) -> list[Session]:
    metadata = _session_metadata(config, now, window_hours, show_all)
    dbs = runtime_io.glob_under(_conversations_dir(config), "*.db")

    agents_by_parent: dict[str, list[tuple[str, str, float]]] = {}
    subagent_sids: set[str] = set()
    db_mtimes: dict[str, float] = {}
    db_paths: dict[str, str] = {}

    for db in dbs:
        sid = os.path.basename(db)[: -len(".db")]
        mtime = _store_mtime(config, db, now)
        if not mtime:
            continue
        db_mtimes[sid] = mtime
        db_paths[sid] = db

    pending = [
        sid
        for sid, mtime in db_mtimes.items()
        if show_all or sessions.is_fresh(config, now, mtime, window_hours * 3600)
    ]
    inspected: set[str] = set()
    # Every store that reaches a card is inspected here — the freshness filter
    # above admits it, and a subagent pushes its parent on at the bottom of this
    # loop — so one model per inspected store covers every card and every
    # subagent with no read the collector was not already doing. A sid missing
    # from this map was never inspected, which is the same "not read" its None is.
    models: dict[str, str | None] = {}
    unread_models: set[str] = set()
    while pending:
        sid = pending.pop()
        if sid in inspected:
            continue
        inspected.add(sid)
        info = _session_info(config, state, db_paths[sid], sid)
        models[sid] = info.get("model")
        if info.get("model_unread"):
            unread_models.add(sid)
        parent = info.get("parent_id")
        if parent and parent != sid:
            subagent_sids.add(sid)
            label = info.get("subagent_label") or ("subagent " + sid[:8])
            agents_by_parent.setdefault(parent, []).append((sid, label, db_mtimes[sid]))
            if parent in db_paths:
                pending.append(parent)

    def descendants(parent_sid: str) -> list[tuple[str, str, float]]:
        agents: list[tuple[str, str, float]] = []
        pending_agents = list(agents_by_parent.get(parent_sid, []))
        seen: set[str] = set()
        while pending_agents:
            agent_sid, label, mtime = pending_agents.pop()
            if agent_sid in seen or agent_sid == parent_sid:
                continue
            seen.add(agent_sid)
            agents.append((agent_sid, label, mtime))
            pending_agents.extend(agents_by_parent.get(agent_sid, []))
        return agents

    out: list[dict[str, Any]] = []
    for db in dbs:
        sid = os.path.basename(db)[: -len(".db")]
        if sid in subagent_sids:
            continue
        session_mtime = db_mtimes.get(sid)
        if not session_mtime:
            continue
        agents = sorted(descendants(sid), key=lambda a: -a[2])
        activity_sources = (session_mtime, *(mtime for _, _, mtime in agents))
        last_activity = sessions.newest_plausible(config, now, activity_sources)
        active = sessions.is_fresh(config, now, last_activity, window_hours * 3600)
        if not (active or show_all):
            continue
        gaps: set[str] = set()
        if sid in unread_models:
            gaps.add(sessions.UNREAD_MODEL)
        activity: dict[str, Any] = (
            _step_activity(config, state, db, now, gaps)
            if active
            else {"rate_per_min": 0, "turns": None, "last_tool_action": ""}
        )
        if active:
            activity["rate_per_min"] += sum(
                _step_activity(config, state, db_paths[agent_sid], now)["rate_per_min"]
                for agent_sid, _, agent_mtime in agents
                if sessions.is_fresh(config, now, agent_mtime, config.rate_window_sec)
            )
        # Each subagent owns a store, so its model is measured on its own terms
        # and published as read — never compared here, never withheld because a
        # neighbour's reading is missing. The page decides where a child's model
        # is worth showing, and it needs both readings to decide.
        subagents: list[dict[str, Any]] = [
            {
                "name": label,
                "model": models.get(agent_sid),
                "started_at": None,
                "active": None,
                "parent": None,
            }
            for agent_sid, label, agent_mtime in agents
            if sessions.is_fresh(config, now, agent_mtime, config.working_threshold_sec)
        ]
        session_state, state_detail = "idle", "awaiting your message"
        if sessions.is_fresh(config, now, last_activity, config.working_threshold_sec):
            session_state = "working"
            state_detail = (
                sessions.working_detail(None, subagents)
                if subagents
                else activity["last_tool_action"] or sessions.working_detail(None, [])
            )

        meta = metadata.get(sid) or {}
        prompt = str(meta.get("last_prompt") or "").strip()
        if not prompt:
            # 1.2.11 no longer logs the prompt marker (0 of 7 local logs), so the
            # newest typed direction in the brain transcript stands in. Only
            # `USER_INPUT` is read there (DRC-4689).
            brain = transcripts.antigravity_transcript(_root(config), sid)
            if brain is not None:
                prompt = transcripts.antigravity_newest_direction(config, brain).strip()
        cwd = str(meta.get("cwd") or "").strip()
        project = sessions.project_from_cwd(config, cwd) or "antigravity"
        session = sessions.base_session("antigravity", sid, project)
        sessions.apply_project_identity(config, session, cwd)
        # The `/goal` the person typed, from the whole-field transcript so a long condition keeps
        # its middle. Behind `active`, as the other transcript reads are: a stale row reads none.
        full = transcripts.antigravity_transcript(_root(config), sid, full=True) if active else None
        session.update(
            {
                "session_goal": (
                    claude_data.session_goal(config, state, full, "antigravity") if full else None
                ),
                # `provider` stays None: the only vendor-adjacent fields in the
                # blob are per-generation booleans (`used_claude=false`) and an
                # opaque `MODEL_PLACEHOLDER_*` enum. Reading "google" off the
                # string "Gemini" is inference, which this field forbids.
                "model": models.get(sid),
                "title": records.redact_clip(prompt.split("\n")[0], records.PROMPT_TITLE_CAP_CHARS)
                or None,
                "last_prompt": records.redact_clip(prompt, records.LAST_PROMPT_CAP_CHARS),
                "state": session_state,
                "state_detail": state_detail,
                "active": active,
                "last_activity": last_activity,
                "rate_per_min": activity["rate_per_min"],
                "turn": turns.turn_progress(activity["turns"], session_state, now, config),
                "subagents": subagents,
                # This row's own store only. A subagent store that would not read
                # costs the parent a slice of its rate and nothing else, and
                # attributing a child's unread store to the parent's row would
                # say the wrong thing about which source went dark.
                "source_gaps": sorted(gaps),
            }
        )
        out.append(session)
    return out


def discover(config: RuntimeConfig, _state: RuntimeState) -> bool:
    """Whether Antigravity has written at least one conversation store."""
    return runtime_io.any_glob_under(_conversations_dir(config), "*.db")


def usage(
    config: RuntimeConfig,
    state: RuntimeState,
    now: float,
    window_hours: float,
) -> list[dict[str, Any]]:
    """Quota the CLI pushed to its status-line command, read back from memory.

    Antigravity keeps no quota on disk and its stored credential is not usable
    as a bearer token, so neither the Codex nor the Claude approach applies.
    What it does do is publish a `quota` object to a user-configured status-line
    command on every state change, which the user forwards to `/api/usage` with
    the same script the Claude hooks use. This reads what arrived.

    No network and no disk, so `--diagnose` stays clean by construction.
    """
    return runtime_quota.receipt_entries(config, state, now, window_hours)
