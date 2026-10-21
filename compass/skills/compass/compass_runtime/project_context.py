"""Read-only observer, gate, and captain-instruction context for one project."""

from __future__ import annotations

import contextlib
import copy
import hashlib
import heapq
import json
import math
import os
import re
import shlex
import shutil
import stat
import subprocess
import time
from collections import deque
from collections.abc import Callable, Iterable, Mapping
from typing import TYPE_CHECKING, Any, NamedTuple

from . import (
    claude_data,
    entry_numbers,
    events,
    observer,
    reading_route,
    records,
    semantic_history,
    spacedock,
    transcripts,
)
from . import io as runtime_io
from . import sessions as runtime_sessions
from . import state as runtime_state

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator, Sequence

    from .config import RuntimeConfig
    from .state import RuntimeState

MAX_PROJECT_EVENTS = 100
MAX_PROJECT_OBSERVERS = 3
MAX_PROJECT_ATTENTION_SESSIONS = 64
MAX_ACTIVE_CHILD_OBSERVERS = 3
MAX_SEMANTIC_LINE = 112
# A reading's bound on one reader message: about nine titles, so a correction's later sentences
# arrive (owner ruling, 2026-10-01). How many go whole is the prompt's to decide, not this cap's:
# `reading.WORDS_SHARE_DIVISOR` gives them half the 16 KiB: seven full-length ASCII messages,
# or two CJK ones at three bytes a character, measured beside a failed check and a write.
READER_WORDS_CAP_CHARS = 1_000
# The fact field holding them, named so `for_page` can strip it at any depth without colliding.
READER_WORDS_FIELD = "reader_words"
# The agent's own messages, read whole by a reading as evidence of what it said, claimed and
# reported (owner ruling, 2026-10-03). The reader's bound, in a field of its own so the ledger
# keeps the two apart and `for_page` strips both:
# docs/design-reading-a-session.md#amended-2026-10-03-owner-the-agents-own-words-are-evidence
AGENT_WORDS_CAP_CHARS = 1_000
AGENT_WORDS_FIELD = "agent_words"
AGENT_WORDS_TOTAL_FIELD = "agent_words_total"
# The title a message's fact id was hashed from, on an event whose published title is not it. Only a
# paste whose tag shares a line with typed words has one, and it still carries the tag.
ID_TITLE_FIELD = "id_title"
# Every server-side-only words field, which no page route may publish.
_SERVER_ONLY_FIELDS = frozenset(
    {
        READER_WORDS_FIELD,
        ID_TITLE_FIELD,
        AGENT_WORDS_FIELD,
        AGENT_WORDS_TOTAL_FIELD,
        records.GOAL_SOURCE_CUT_FIELD,
        "request_source_digest",
        "request_source_stamp",
        "request_words_digest",
    }
)
# The harnesses whose top-level assistant text this module reads as the agent's messages.
# Claude Code only for now; Codex's final answers are a follow-up.
AGENT_MESSAGE_HARNESSES = ("claude",)
_AGENT_SAY = "agent_say"
SEMANTIC_CURRENT_HORIZON_SEC = 15 * 60
SEMANTIC_BURST_EPSILON_SEC = 2
MAX_PRIMARY_ACTIVITY_NODES = 5
MAX_PRIMARY_STEERING_NODES = 3
SEMANTIC_HISTORY_HORIZON_SEC = 24 * 60 * 60
SEMANTIC_BACKFILL_MAX_BYTES = 32 * 1024 * 1024
# The newest-final lookup reads recent source only, never more than the other press-only
# lookups, and refuses an assistant record too large to be a reply that could fit the prompt:
# a whole reply must fit the 4,096-byte agent share, so a megabyte-scale record never could.
FINAL_WORDS_SCAN_MAX_BYTES = SEMANTIC_BACKFILL_MAX_BYTES
FINAL_WORDS_RECORD_MAX_BYTES = 1024 * 1024
FINAL_WORDS_STOP_REASON = "end_turn"
_ASSISTANT_TYPE_RE = re.compile(rb'"type"\s*:\s*"assistant"')
# The most a candidate's whole words may hold in memory: the reading's prompt cap
# (`observer.OBSERVER_MODEL_MAX_PROMPT_BYTES`) counts bytes and a character is at least one,
# so a reply past it could never fit. It is named apart so a candidate that long is recognised
# without being kept. And the most assistant UUIDs one scan tracks for conflicting duplicates.
FINAL_WORDS_MAX_CHARS = 16_384
FINAL_WORDS_UUIDS_MAX = 100_000
WORKFLOW_DISCOVERY_TIMEOUT_SEC = 2.0
WORKFLOW_DISCOVERY_CACHE_SEC = 30.0
WORKFLOW_DISCOVERY_MAX_BYTES = 64 * 1024
WORKFLOW_DISCOVERY_MAX_DIRS = 64
WORKFLOW_DISCOVERY_SOURCE = "spacedock status --discover"

_DIRECTIVE_PREFIX_RE = re.compile(
    r"^(?:please\s+|captain(?:\s+(?:says|asks|adds|clarifies|refines|clarification|refinement|correction))?\s*[:—-]\s*)+",
    re.IGNORECASE,
)
_DIRECTIVE_TAGS = (
    ("corrected", ("correction", "correct this", "fix the")),
    ("reframed", ("reframe", "refinement", "clarification", "change direction")),
    ("answered", ("answer to", "answered")),
    ("generated", ("new acceptance", "add a new", "create a new")),
)
_TASK_DIRECTIVE_RE = re.compile(
    r"^(?:add|append|build|compare|create|design|diagnose|fix|implement|inspect|make|"
    r"prepare|remove|replace|review|revise|run|test|update|verify|write)\b",
    re.IGNORECASE,
)
_AUTHORIZATION_ANSWER_RE = re.compile(
    r"\b(?:approve|authorize)(?:d)?\b[^.\n]*\bpush(?:ing)?\b[^.\n]*\bPR\b",
    re.IGNORECASE,
)
_AUTHORIZATION_RESULT_RE = re.compile(
    r"\bpush(?:ed|ing)\b[^.\n]*\b(?:created|opened|published)\b[^.\n]*\bPR\b",
    re.IGNORECASE,
)
_SEMANTIC_FACT_TYPES = {
    "steer": "user_message",
    _AGENT_SAY: "agent_message",
    "prepared_dispatch": "prepared_dispatch",
    "task_started": "work_birth",
    "task_result": "work_result",
    "outcome": "result",
    "gate": "gate_decision",
    "checkpoint": "result",
    "decision": "decision",
    "test_result": "result",
    "ask_resolution": "decision",
    # One fact type for a check and a write; `subject` tells them apart. The
    # ruling `claude_tool_reports` cites, item 6.
    "check_run": "tool_report",
    "path_written": "tool_report",
    "background_launch": "tool_report",
}
_DISPATCH_BUILD_RE = re.compile(r"^\s*spacedock\s+dispatch\s+build(?:\s+(.*))?$", re.IGNORECASE)
# This is transcript grammar from the dispatch contract, not a location we create or write.
_DISPATCH_DIRECTORY = "/tmp/spacedock-dispatch"  # noqa: S108 — legacy producer path; checked file reads below.
DISPATCH_MAX_BYTES = 64 * 1024
_DISPATCH_FILE_PREFIX = f"{_DISPATCH_DIRECTORY}/spacedock-ensign-"
_DISPATCH_VALUE_OPTIONS = {
    "--checklist-file",
    "--host",
    "--stage",
    "--stamp",
    "--workflow-dir",
}
_CODEX_ENSIGN_TASK_RE = re.compile(r"^spacedock_ensign_([a-z0-9_]+?)(?:_cycle\d+)?$")


def _discovery_result(state: str, reason: str = "") -> dict[str, Any]:
    result: dict[str, Any] = {
        "state": state,
        "source": WORKFLOW_DISCOVERY_SOURCE,
        "workflows": [],
    }
    if reason:
        result["reason"] = reason
    return result


def _parse_discovery_output(
    config: RuntimeConfig,
    state: RuntimeState,
    root: str,
    stdout: object,
) -> dict[str, Any]:
    if not isinstance(stdout, str) or (
        len(stdout.encode("utf-8", "replace")) > WORKFLOW_DISCOVERY_MAX_BYTES
    ):
        return _discovery_result("error", "Spacedock discovery returned invalid output")
    raw_paths = [line.strip() for line in stdout.splitlines() if line.strip()]
    base = os.path.realpath(os.path.join(root, ".spacedock"))
    workflows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw_path in raw_paths[:WORKFLOW_DISCOVERY_MAX_DIRS]:
        if not os.path.isabs(raw_path):
            continue
        candidate = os.path.realpath(raw_path)
        try:
            contained = os.path.commonpath((base, candidate)) == base
        except ValueError:
            contained = False
        name = os.path.basename(candidate)
        if (
            not contained
            or os.path.dirname(candidate) != base
            or not name
            or name in seen
            or not os.path.isdir(candidate)
        ):
            continue
        seen.add(name)
        definition = spacedock.read_workflow(
            config,
            state,
            candidate,
            definition_root=base,
        )
        workflows.append(
            {
                "workflow": name,
                "goal": str((definition or {}).get("goal") or ""),
                "stages": list((definition or {}).get("stages") or []),
                "definition": "read" if definition is not None else "unavailable",
            }
        )
    if raw_paths and not workflows:
        return _discovery_result(
            "error", "Spacedock discovery returned no valid project workflow paths"
        )
    result = _discovery_result("observed" if workflows else "none")
    result["workflows"] = workflows
    return result


def _run_project_workflow_discovery(
    config: RuntimeConfig,
    state: RuntimeState,
    root: str,
    runner: Any,
    binary_resolver: Any = shutil.which,
) -> dict[str, Any]:
    executable = os.environ.get("SPACEDOCK_BIN") or binary_resolver("spacedock")
    if not executable or not os.path.isabs(executable):
        return _discovery_result(
            "unavailable", "Spacedock discovery command requires an absolute path"
        )
    argv = [executable, "status", "--discover"]
    try:
        completed = runner(
            argv,
            cwd=root,
            capture_output=True,
            text=True,
            timeout=WORKFLOW_DISCOVERY_TIMEOUT_SEC,
            check=False,
            shell=False,
            env={"PATH": os.defpath, "HOME": config.home, "LANG": "C.UTF-8"},
        )
    except FileNotFoundError:
        return _discovery_result("unavailable", "Spacedock discovery command unavailable")
    except subprocess.TimeoutExpired:
        return _discovery_result("error", "Spacedock discovery timed out")
    except (OSError, ValueError):
        return _discovery_result("error", "Spacedock discovery could not run")
    if completed.returncode != 0:
        return _discovery_result(
            "error", f"Spacedock discovery exited with status {completed.returncode}"
        )
    return _parse_discovery_output(config, state, root, completed.stdout)


def discover_project_workflows(
    config: RuntimeConfig,
    state: RuntimeState,
    project_root: str,
    *,
    now: float,
    runner: Any = subprocess.run,
    binary_resolver: Any = shutil.which,
    force: bool = False,
) -> dict[str, Any]:
    """Discover commissioned workflows from one verified project root.

    Spacedock owns workflow discovery. Compass invokes its fixed read-only
    command without a shell, then accepts only immediate children of this
    project's ``.spacedock`` directory. The browser receives derived plan
    scalars, never filesystem paths or a way to invoke the command itself.
    """
    if not config.spacedock_enabled:
        return _discovery_result("unavailable", "Spacedock observation is disabled")
    root = os.path.realpath(project_root)
    if not os.path.isabs(project_root) or not os.path.isdir(root):
        return _discovery_result("unavailable", "project root unavailable")
    with state.cache_lock:
        cached = state.spacedock_discovery_cache.get(root)
    if cached and not force and now - cached[0] < WORKFLOW_DISCOVERY_CACHE_SEC:
        return copy.deepcopy(cached[1])

    result = _run_project_workflow_discovery(config, state, root, runner, binary_resolver)

    detached = copy.deepcopy(result)
    with state.cache_lock:
        runtime_state.bounded_put(
            state.spacedock_discovery_cache,
            root,
            (now, detached),
            limit=config.max_cache_entries,
        )
    return copy.deepcopy(detached)


def _transcript_cwd(
    config: RuntimeConfig,
    state: RuntimeState,
    harness: str,
    transcript_path: str,
) -> str:
    if harness == "claude":
        return claude_data.session_cwd(config, state, transcript_path)
    if harness == "codex":
        return str(transcripts.codex_meta(config, state, transcript_path).get("cwd") or "")
    if harness == "pi":
        return str(transcripts.pi_meta(config, state, transcript_path).get("cwd") or "")
    return ""


def _project_workflow_discovery(
    config: RuntimeConfig,
    state: RuntimeState,
    analysis_sessions: Sequence[Mapping[str, Any]],
    project: str,
    *,
    now: float,
    refresh: bool,
    runner: Any = subprocess.run,
    binary_resolver: Any = shutil.which,
) -> dict[str, Any]:
    for session in analysis_sessions:
        harness = str(session.get("harness") or "")
        sid = str(session.get("sid") or "")
        transcript_path = observer.resolve_transcript(config, state, harness, sid)
        if transcript_path is None:
            continue
        cwd = _transcript_cwd(config, state, harness, transcript_path)
        identity = runtime_sessions.project_identity(config, cwd)
        root = runtime_sessions.project_root(cwd)
        recorded_key = str(session.get("project_key") or "")
        recorded_label = str(session.get("project") or "")
        if not root or not identity:
            continue
        # The transcript cwd must agree with the collector's stable identity.
        # A label-only legacy request remains valid only for its own session.
        if recorded_key and recorded_key != identity.get("key"):
            continue
        if project not in {identity.get("key"), recorded_key, recorded_label}:
            continue
        return discover_project_workflows(
            config,
            state,
            root,
            now=now,
            runner=runner,
            binary_resolver=binary_resolver,
            force=refresh,
        )
    return _discovery_result("unavailable", "project root unavailable from observed sessions")


def _semantic_id(prefix: str, *parts: object) -> str:
    payload = "\x1f".join(str(part) for part in parts).encode("utf-8", "replace")
    return f"{prefix}:{hashlib.sha256(payload).hexdigest()[:16]}"


def _transcript_signature(transcript_path: str) -> dict[str, int] | None:
    try:
        info = os.stat(transcript_path)
    except OSError:
        return None
    return {"size": info.st_size, "mtime_ns": info.st_mtime_ns}


def _cached_text(value: Any, cap: int) -> str | None:
    """One re-read sidecar string, bounded and scrubbed, or nothing.

    The isinstance was once the whole check, on the argument that the observer
    had already bounded what it wrote. That holds on the fresh path and not
    here, where the sidecar is re-read under `state_read_cap_bytes` from a file
    any local process could have rewritten: a type check is not a bound. One
    cap for all three rather than a threshold each, because nobody would tune a
    stage name apart from a reason literal and `config.py` grows a field per
    feature as it is.
    """
    return records.safe_text(value, cap) if isinstance(value, str) else None


# Which arm produced a published goal. "unknown" is for a sidecar written
# before the field existed, and is never inferred into one of the other two.
_GOAL_SOURCES = frozenset({"deterministic", "model"})


def _observe_session(
    config: RuntimeConfig,
    state: RuntimeState,
    transcript_path: str,
    identity: tuple[str, str],
    *,
    now: float,
    refresh: bool,
    child_activity_fallback: bool = False,
    model_consent: bool = False,
) -> dict[str, Any] | None:
    harness, sid = identity
    signature = _transcript_signature(transcript_path)
    cached = observer.read_sidecar(config, harness, sid)
    cached_payload = cached if isinstance(cached, dict) else {}
    raw_cached_model = cached_payload.get("model")
    cached_model = raw_cached_model if isinstance(raw_cached_model, dict) else {}
    if not refresh:
        observed_at = cached_payload.get("observed_at")
        goal = cached_payload.get("goal")
        if not isinstance(observed_at, (int, float)) or not isinstance(goal, str):
            return None
        model_metadata = dict(cached_model)
        model_metadata["status"] = (
            "cached" if cached_payload.get("transcript") == signature else "cached-stale"
        )
        # A sidecar written before goal provenance existed carries neither
        # field. "unknown" rather than "deterministic": defaulting to the
        # latter would relabel every already-cached model goal as something a
        # source published, which is the one substitution DRC-4509 forbids.
        cached_source = cached_payload.get("goal_source")
        # Every one of these is re-read from a file any local process could have
        # rewritten, so each is checked on the way out rather than only on the
        # way in. `goal` above was already checked and `goal_source` is checked
        # against a frozen set; these four were not, and a dict here reaches the
        # served payload verbatim. `deterministic_goal` is a goal line, so it
        # carries the same bound a freshly derived one does.
        raw_deterministic = cached_payload.get("deterministic_goal")
        return {
            "goal": goal,
            "deterministic_goal": (
                records.safe_text(raw_deterministic, config.observer_goal_cap_chars)
                if isinstance(raw_deterministic, str)
                else None
            ),
            "goal_source": cached_source if cached_source in _GOAL_SOURCES else "unknown",
            "stage": _cached_text(cached_payload.get("stage"), config.observer_block_cap_chars),
            "block": _cached_text(cached_payload.get("block"), config.observer_block_cap_chars),
            "reason": _cached_text(cached_payload.get("reason"), config.observer_block_cap_chars),
            "model": model_metadata,
            "observed_at": observed_at,
            "snapshot_status": model_metadata["status"],
        }

    caller = observer.CodexGoalModel(
        config,
        child_assignment=child_activity_fallback,
        consent=model_consent,
        session_key=f"{harness}:{sid}",
        resolve_destination=lambda: reading_route.destination(reading_route.CODEX),
        clock=lambda: now,
    )
    model = caller if config.observer_model_enabled and model_consent else None
    result = observer.analyze(
        config,
        state,
        transcript_path,
        now=now,
        window_sec=config.window_hours * 3600,
        model=model,
    )
    if child_activity_fallback and model is not None and result.get("goal") == observer.NO_GOAL:
        result["goal"] = observer.derive_child_assignment(config, transcript_path, model)
        if result["goal"] != observer.NO_GOAL:
            result["reason"] = "derived-from-readable-child-activity"
            # A third writer of `goal`, and a model wrote it: this arm is only
            # reached with a caller in hand.
            result["goal_source"] = "model"
    model_metadata = caller.metadata()
    sidecar = {
        **result,
        "model": model_metadata,
        "transcript": signature,
        "observed_at": now,
    }
    observer.write_sidecar(config, harness, sid, sidecar)
    return {
        **result,
        "model": model_metadata,
        "observed_at": now,
        "snapshot_status": "refreshed",
        **({"notice": caller.notice} if caller.notice is not None else {}),
    }


def _instruction_event(
    config: RuntimeConfig,
    record: Any,
    harness: str,
    sid: str,
) -> dict[str, Any] | None:
    """One timestamped user-role message, excluding known tool/meta records."""
    if not isinstance(record, dict):
        return None
    if harness in observer.DIRECTION_HARNESSES:
        return _direction_event(config, record, harness, sid)
    message = observer.parse_reader_record(record)
    if message is None or message.get("role") != "user":
        return None
    at = records.parse_ts(_reader_stamp(record) or record.get("timestamp") or "")
    text = message["text"].strip()
    if at is None or not text:
        return None
    title = _message_title(config, text, harness)
    if not title:
        return None
    hashed = _unstripped_title(config, record, harness, title)
    event: dict[str, Any] = {
        "at": at,
        "kind": "steer",
        "phase": "user-role instruction",
        "title": title,
        **({ID_TITLE_FIELD: hashed} if hashed else {}),
        READER_WORDS_FIELD: _message_words(config, text, harness),
        "source": message.get("source") or "timestamped non-meta user-role record",
        "harness": harness,
        "sid": sid,
        # An answer is the reader's choice among the agent's options and names no work alone.
        "intent_promotable": message.get("source") != observer.ANSWER_SOURCE
        and _intent_promotable(text, title),
    }
    record_id = record.get("id")
    if isinstance(record_id, str) and record_id:
        event["record_id"] = record_id
        event["turn_id"] = record_id
        event["branch_id"] = record_id
    parent_id = record.get("parentId")
    if isinstance(parent_id, str) and parent_id:
        event["parent_id"] = parent_id
    lower = text.casefold()
    for tag, markers in _DIRECTIVE_TAGS:
        if any(marker in lower for marker in markers):
            event["steering_tag"] = tag
            event["tag_source"] = "explicit user-role wording"
            break
    return event


def _unstripped_title(
    config: RuntimeConfig, record: dict[str, Any], harness: str, title: str
) -> str:
    """The title the message had before its paste tags came off, when that is not `title`, else "".

    A fact id hashes the title (`_semantic_fact_from_event`), so a title the strip changed would
    move the id a stored reading cites. A message with no paste tag costs one failed substring
    test per text and never reaches the second parse. The tag is looked for in a string content
    (the shape recorded in docs/captures/claude/paste-wrapper-shape-2.1.305-macos.jsonl) and in
    the text blocks of a list content, which the strip reads the same way.
    """
    if not _carries_paste_tag(record):
        return ""
    held = observer.parse_reader_record(record, paste_tags=True)
    if held is None:
        return ""
    before = _message_title(config, held["text"].strip(), harness)
    return before if before and before != title else ""


def _carries_paste_tag(record: dict[str, Any]) -> bool:
    """Whether a message's content, or one of its text blocks, names a paste tag."""
    content = records.message_dict(record).get("content")
    if content is None:
        content = records.as_dict(record.get("payload")).get("content")
    if isinstance(content, str):
        return "pasted_content" in content
    if not isinstance(content, list):
        return False
    return any(
        isinstance(block, dict)
        and isinstance(block.get("text"), str)
        and "pasted_content" in block["text"]
        for block in content
    )


def _reader_stamp(record: dict[str, Any]) -> Any:
    """When the reader typed a message the agent took in mid-turn, from the attachment itself.

    The queue records the message when it is absorbed, which can be minutes after it was sent
    (measured: 2 m 44 s on one session). The reader's direction dates from the typing, and the
    attachment carries that time under its own `timestamp`.
    """
    attachment = record.get("attachment")
    if isinstance(attachment, dict) and attachment.get("type") == "queued_command":
        return attachment.get("timestamp")
    return None


def _message_title(config: RuntimeConfig, text: str, harness: str) -> str:
    """A user message's one-line title, or "" when it names nothing."""
    limit = min(MAX_SEMANTIC_LINE, config.observer_goal_cap_chars)
    # A slash command is the reader's direction in the harness's markup, every
    # line of which opens with `<` and so reads as empty to `_semantic_line`
    # (DRC-4764). `records`' note on the command tags is the other half.
    command = transcripts.command_direction(config, text) if harness == "claude" else None
    if command is None:
        return _semantic_line(text, limit)
    return records.safe_text(command, limit)


def _message_words(config: RuntimeConfig, text: str, harness: str) -> str:
    """A user message whole, as a reading reads it: one line, redacted, bounded.

    Never the page's: `for_page` drops it from a published context, and the history store's
    field allowlist does not name it. Why it exists, in its own amendment:
    docs/design-reading-a-session.md#amended-2026-10-01-a-reading-sees-the-readers-whole-message
    """
    command = transcripts.command_direction(config, text) if harness == "claude" else None
    return records.safe_text(" ".join((command or text).split()), READER_WORDS_CAP_CHARS)


def whole_message_words(
    config: RuntimeConfig, record: dict[str, Any], harness: str, cap: int
) -> str:
    """Source words use the same parser and slash-command normalization, without a prompt cap."""
    message = observer.parse_reader_record(record, cap=cap)
    text = str(message["text"]) if message else ""
    command = transcripts.command_direction(config, text) if harness == "claude" else None
    return records.safe_text(" ".join(records.mask_prose(command or text).split()), cap)


def _agent_message_event(
    config: RuntimeConfig,
    record: Any,
    harness: str,
    sid: str,
    *,
    text_cap: int = records.EXTRACT_TEXT_CAP_CHARS,
) -> dict[str, Any] | None:
    """One timestamped top-level assistant text message, as what the agent said.

    `observer.parse_message_record` already refuses sidechain and meta records and yields
    no text for a thinking or a tool_use block. A record Claude Code wrote itself rather
    than the model (`claude_data.SYNTHETIC_MODEL`: a cancellation notice, an error banner)
    is not the agent speaking, so it stays out, by value as `model_reported` tests it.
    """
    if (
        harness not in AGENT_MESSAGE_HARNESSES
        or not isinstance(record, dict)
        or record.get("type") != "assistant"
        or records.message_dict(record).get("model") == claude_data.SYNTHETIC_MODEL
    ):
        return None
    message = observer.parse_message_record(record)
    if message is None or message.get("role") != "assistant":
        return None
    at = records.parse_ts(record.get("timestamp") or "")
    text = message["text"].strip()
    if at is None or not text:
        return None
    title = _semantic_line(text, min(MAX_SEMANTIC_LINE, config.observer_goal_cap_chars))
    if not title:
        return None
    full = observer.parse_message_record(record, cap=text_cap)
    words = records.safe_text(
        " ".join(records.mask_prose(full["text"] if full else text).split()), text_cap
    )
    event: dict[str, Any] = {
        "at": at,
        "kind": _AGENT_SAY,
        "phase": "assistant message",
        "title": title,
        AGENT_WORDS_FIELD: words[:AGENT_WORDS_CAP_CHARS],
        "source": "timestamped top-level assistant text record",
        "harness": harness,
        "sid": sid,
    }
    if full is not None and len(full["text"]) < text_cap:
        event[AGENT_WORDS_TOTAL_FIELD] = len(words)
    # Claude spells a record's identity `uuid`. A new fact type has no stored citation to
    # keep, so it joins the id here: two text blocks in one second opening with the same
    # sentence stay two entries.
    record_id = record.get("uuid")
    if isinstance(record_id, str) and record_id:
        event["record_id"] = record_id
    return event


def _agent_message_lines(
    config: RuntimeConfig, lines: Iterable[str], harness: str, sid: str
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    seen: set[tuple[float, str, str]] = set()
    for raw in lines:
        if not raw or not raw.lstrip().startswith("{"):
            continue
        try:
            record = json.loads(raw)
        except (ValueError, RecursionError):
            continue
        event = _agent_message_event(config, record, harness, sid, text_cap=len(raw))
        if event is None:
            continue
        key = (event["at"], event["title"], str(event.get("record_id") or ""))
        if key in seen:
            continue
        seen.add(key)
        events.append(event)
    return events


def agent_message_events(
    config: RuntimeConfig, transcript_path: str, harness: str, sid: str
) -> list[dict[str, Any]]:
    """The agent's top-level text messages from the bounded transcript tail.

    Live only: `collect` appends them, and `_semantic_history_source_events` never calls
    this, so the history store never sees one (its `_FACT_EVENT_TYPES` naming no
    `agent_message` is the second wall).
    """
    if harness not in AGENT_MESSAGE_HARNESSES:
        return []
    return _agent_message_lines(config, runtime_io.read_tail(config, transcript_path), harness, sid)


# A press stops reading back once this many timestamped records in a row are older than the
# window. One older record is not enough: a resumed transcript can rewrite earlier records after
# newer ones (see the note in `observer`), and stopping there would drop what sits before them.
PRESS_OLDER_RUN = 16
# A press does not read a message whose text is longer than this. Redaction is not linear in the
# worst case (a megabyte of token-like text took seconds), the clock is only asked between records,
# and a message worth reading is a few kilobytes. It counts as an unread region, as a skipped
# oversized line does. The text is measured, not the record: a pasted screenshot makes a user record
# several megabytes of image data around a short question, and parsing that costs milliseconds.
PRESS_TEXT_MAX_CHARS = 256 * 1024
# How many turns' closing agent messages a press keeps beyond the newest messages and the project
# cap. A long session's first turns are what an early Goal rests on, and what the agent said it had
# done is the last message of a turn, not its first. Twelve is about what the prompt's anchor share
# (an eighth of the budget) carries at 130 to 190 bytes a row.
PRESS_ANCHORS = 12


class MessageReach(NamedTuple):
    """How far a press read back, measured from the records it visited and nothing else.

    `reached` is whether the window's start was read: a record older than it, or the file's start,
    with no unread region inside the window. `earliest` is where the contiguous read began: the
    oldest timestamp seen when it reached, else the oldest in-window time before the first thing it
    could not read (None when it read none). `stopped_by` says why the read ended. `lost` is the
    newest message the read saw and did not keep, which is where a whole record would begin after.
    """

    reached: bool
    earliest: float | None
    stopped_by: str
    lost: float | None = None


class PressMessages(NamedTuple):
    events: list[dict[str, Any]]
    reach: MessageReach
    # The message keys of the turn-closing agent messages the read kept past its newest messages, so
    # the project cap can reserve them without a marker on the event, which a page would carry.
    anchors: frozenset[tuple[object, ...]] = frozenset()


class PressWindow(NamedTuple):
    """A press's request to read messages back: the window's start and the file it stamped."""

    start: float
    stamp: tuple[int, int, int, int] | None


def _message_text_chars(record: Mapping[str, Any]) -> int:
    """The characters of text a transcript record carries, which is what a reading would redact."""
    answered = observer.answer_text_chars(record)
    message = record.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if content is None:
        # A mid-turn message holds its words in the attachment, beside any pasted image's bytes.
        attachment = record.get("attachment")
        content = attachment.get("prompt") if isinstance(attachment, dict) else None
    if isinstance(content, str):
        return answered + len(content)
    if not isinstance(content, list):
        return answered
    return answered + sum(
        len(block["text"])
        for block in content
        if isinstance(block, dict) and isinstance(block.get("text"), str)
    )


class _MessageRead:
    """The visitor for one press read. Its fields are the read's whole state.

    `begun` is where the contiguous read of the window began: the oldest in-window time seen before
    any region the read could not take. A record older than the window never lowers it, so one
    replayed record cannot make a partial read look complete, and an unread region freezes it.
    """

    def __init__(self, config: RuntimeConfig, harness: str, sid: str, window_start: float) -> None:
        self.config, self.harness, self.sid = config, harness, sid
        self.window_start = window_start
        self.found: list[dict[str, Any]] = []
        # Turn-closing agent messages found after `found` was full, each with the reader's message
        # that followed it, newest first and bounded: the oldest `PRESS_ANCHORS` stay, which are
        # the earliest turns' evidence. The reader's message rides with it because the prompt
        # finds a turn's close by the reader's message after it, and the history store may not
        # hold that one.
        self.anchors: deque[tuple[dict[str, Any], dict[str, Any] | None]] = deque(
            maxlen=PRESS_ANCHORS
        )
        self.anchored: set[tuple[object, ...]] = set()
        self.keys: set[tuple[object, ...]] = set()
        # The latest reader's message seen after `found` was full, not yet kept with an anchor.
        self.pending: dict[str, Any] | None = None
        # Going back, a reader's message ends one turn's messages and the next agent message found
        # closes the turn before it; the scan's first agent message closes the newest turn.
        self.closing = True
        self.lost: float | None = None
        self.older = 0
        self.seen_older = False
        self.earliest: float | None = None
        self.begun: float | None = None
        self.gap = False
        self._before: float | None = None

    @property
    def at_window(self) -> bool:
        return self.older >= PRESS_OLDER_RUN

    @property
    def full(self) -> bool:
        # One past the cap, as before: a window of exactly the cap's size is whole.
        return len(self.found) > MAX_PROJECT_EVENTS

    def stop(self, skipped: bool = False) -> bool:
        if skipped:
            self.unread(self._before)
        return self.at_window

    def unread(self, begun: float | None) -> None:
        """A region the read could not take. Only one inside the window matters: once a record older
        than the window has been seen, what lies further back is outside it."""
        if not (self.gap or self.seen_older):
            self.gap, self.begun = True, begun

    def visit(self, raw: bytes) -> None:
        self._before = self.begun
        if not (_ASSISTANT_TYPE_RE.search(raw) or _could_be_instruction(raw, self.harness)):
            return
        text = raw.decode("utf-8", "replace")
        try:
            record = json.loads(text)
        except (ValueError, RecursionError):
            return
        at = _record_timestamp(record) if isinstance(record, dict) else None
        if at is None:
            return
        if _message_text_chars(record) > PRESS_TEXT_MAX_CHARS:
            self._seen(at)
            self.unread(self.begun)
            return
        self._seen(at)
        if at < self.window_start:
            self.older += 1
            self.seen_older = True
            return
        self.older = 0
        if not self.gap and (self.begun is None or at < self.begun):
            self.begun = at
        self._take("instruction", _instruction_event(self.config, record, self.harness, self.sid))
        if self.full and self.lost is not None and not self.closing:
            # Neither kept nor the newest loss, so building and redacting its event would only cost.
            return
        said = _agent_message_event(self.config, record, self.harness, self.sid, text_cap=len(text))
        self._take("agent", said)

    def _seen(self, at: float) -> None:
        if self.earliest is None or at < self.earliest:
            self.earliest = at

    def _take(self, kind: str, event: dict[str, Any] | None) -> None:
        if event is None:
            return
        key = (kind, event["at"], event["title"], str(event.get("record_id") or ""))
        if key in self.keys:
            return
        if kind == "instruction":
            self.closing = True
            if not self.full:
                self.keys.add(key)
                self.found.append(event)
                return
            self._lose_pending()
            self.pending = event
            return
        anchor, self.closing = self.closing, False
        if not self.full:
            self.keys.add(key)
            self.found.append(event)
        elif not anchor:
            self._lose(event)
        else:
            self._keep_anchor(key, event)

    def _keep_anchor(self, key: tuple[object, ...], event: dict[str, Any]) -> None:
        """Keep a turn's closing message with the reader's message after it."""
        boundary, self.pending = self.pending, None
        if len(self.anchors) == PRESS_ANCHORS:
            # A newer anchor goes to make room; whatever the read does not keep is lost.
            gone, gone_boundary = self.anchors[0]
            self.anchored.discard(_message_key(gone))
            for lost in (gone, gone_boundary):
                if lost is not None:
                    self._lose(lost)
                    self.keys.discard(_scan_key(lost))
        self.keys.add(key)
        if boundary is not None:
            self.keys.add(_scan_key(boundary))
        self.anchors.append((event, boundary))
        self.anchored.add(_message_key(event))

    def _lose_pending(self) -> None:
        if self.pending is not None:
            self._lose(self.pending)
            self.pending = None

    def finish(self) -> None:
        self._lose_pending()

    def _lose(self, event: Mapping[str, Any]) -> None:
        at = float(event["at"])
        if self.lost is None or at > self.lost:
            self.lost = at


def _scan_key(event: Mapping[str, Any]) -> tuple[object, ...]:
    """The read's own dedupe key, whose kind is the scan's word for it, not the event's."""
    kind = "instruction" if event.get("kind") == "steer" else "agent"
    return (kind, event["at"], event["title"], str(event.get("record_id") or ""))


def press_message_events(
    config: RuntimeConfig,
    transcript_path: str,
    harness: str,
    sid: str,
    window: PressWindow,
) -> PressMessages | None:
    """The session's person and agent messages, read back from the end to the window's start.

    A reader's Analyze press only. The tail reads above cover 400,000 bytes, which a long session
    outgrows before its first turn: measured on a 1.82 MB transcript the tail began four minutes
    after the Goal, so what the agent said it had done was outside it. This reads backward under
    the press bounds (`direction_scan_max_*`) and stops at `PRESS_OLDER_RUN` records older than the
    window. It keeps the newest `MAX_PROJECT_EVENTS` messages, which is all the project cap can
    keep, and goes on reading for the closing agent message of each earlier turn, the oldest
    `PRESS_ANCHORS` of them: stopping at the cap read only the newest messages and never reached the
    first turns an early Goal rests on. What it saw and did not keep is `MessageReach.lost`.
    Enlarging `tail_bytes` instead is a recorded rejection: docs/design-session-record-pages.md,
    "Rejected alternatives".

    Both kinds are emitted although the history store also supplies person messages: coverage
    claims the whole message record was read, and that claim cannot rest on a backfill this read
    did not measure. Nothing is retained after it returns. None means the file moved or could not
    be read, so the caller keeps its tail reads and its tail coverage.
    """
    if harness not in AGENT_MESSAGE_HARNESSES:
        return None
    from . import record_pages  # noqa: PLC0415 - shared reader imports the fact builders

    read = _MessageRead(config, harness, sid, window.start)
    scan = record_pages.scan_source(
        config,
        transcript_path,
        read.visit,
        max_bytes=config.direction_scan_max_bytes,
        deadline=time.monotonic() + config.direction_scan_max_seconds,
        expected_stamp=window.stamp,
        stop=read.stop,
    )
    if scan.state != "ok":
        return None
    # A region skipped after the last visited line never reached `stop`.
    read.stop(scan.skipped)
    read.finish()
    if read.gap:
        stopped_by = "skipped"
    elif read.at_window:
        stopped_by = "window"
    else:
        stopped_by = scan.bound or "start"
    reached = stopped_by in {"window", "start"}
    kept = [event for pair in read.anchors for event in pair if event is not None]
    # Oldest first, and file order among equal times, as the tail reads give them.
    events = sorted([*reversed(kept), *reversed(read.found)], key=lambda event: float(event["at"]))
    return PressMessages(
        events,
        MessageReach(reached, read.earliest if reached else read.begun, stopped_by, read.lost),
        frozenset(read.anchored & {_message_key(event) for event in events}),
    )


def for_page(value: Any) -> Any:
    """A project context with every message's whole words removed, for a page route.

    The reader's `reader_words` and the agent's `agent_words` alike. Walks the whole context
    rather than naming `events` and `semantic.facts`, so a projection that later copies a fact
    cannot publish them by being missed.
    """
    if isinstance(value, dict):
        return {
            key: for_page(item) for key, item in value.items() if key not in _SERVER_ONLY_FIELDS
        }
    if isinstance(value, list):
        return [for_page(item) for item in value]
    return value


def _direction_event(
    config: RuntimeConfig, record: dict[str, Any], harness: str, sid: str
) -> dict[str, Any] | None:
    """One Antigravity direction as a steer event, under the same bounds as a
    user-role message; `transcripts.antigravity_direction` is the only read."""
    direction = transcripts.antigravity_direction(record)
    if direction is None:
        return None
    text = direction.text.strip()
    title = _semantic_line(text, min(MAX_SEMANTIC_LINE, config.observer_goal_cap_chars))
    if not title:
        return None
    event: dict[str, Any] = {
        "at": direction.at,
        "kind": "steer",
        "phase": "user-role instruction",
        "title": title,
        READER_WORDS_FIELD: _message_words(config, text, harness),
        "source": "timestamped explicit user input record",
        "harness": harness,
        "sid": sid,
        "intent_promotable": _intent_promotable(text, title),
    }
    if direction.record_id:
        event["record_id"] = direction.record_id
        event["turn_id"] = direction.record_id
        event["branch_id"] = direction.record_id
    lower = text.casefold()
    for tag, markers in _DIRECTIVE_TAGS:
        if any(marker in lower for marker in markers):
            event["steering_tag"] = tag
            event["tag_source"] = "explicit user-role wording"
            break
    return event


def _intent_promotable(text: str, title: str) -> bool:
    """Reject rows that cannot stand alone as a useful semantic directive."""
    normalized = re.sub(r"[^a-z0-9]+", " ", title.casefold()).strip()
    if normalized in {
        "continue",
        "do it",
        "go ahead",
        "no",
        "ok",
        "okay",
        "why do we need that",
        "why do we need this",
        "yes",
    }:
        return False
    lowered = text.lstrip().casefold()
    stripped_title = title.strip()
    looks_like_non_intent = (
        re.match(r"^[,.;:)}\]]", stripped_title) is not None
        or re.match(
            r"^(?:raise\s+[a-z_][a-z0-9_]*\s*\(|(?:find|ls|cat|sed|rg)\s+(?:~?/|\.\.?/))",
            stripped_title,
            re.IGNORECASE,
        )
        is not None
        or re.match(r"^(?:saved|wrote|written|created)\b.*\s(?:to|at)\s+/", lowered) is not None
    )
    if looks_like_non_intent:
        return False
    if lowered.startswith(
        (
            "command failed",
            "error:",
            "exception:",
            "fatal:",
            "traceback (most recent call last)",
        )
    ):
        return False
    if re.match(
        r"^(?:\.?\.?/|\.venv/|python(?:3)?\s|uv\s+run\s|npm\s|pytest(?:\s|$))",
        lowered,
    ):
        return False
    words = re.findall(r"[a-z0-9]+", normalized)
    return len(words) >= 3 and len(normalized) >= 12


def _semantic_line(text: str, limit: int) -> str:
    """A short directive/task label from real text, without its envelope prose."""
    candidates: list[str] = []
    for raw in text.splitlines():
        line = raw.strip().lstrip("#*- ").strip()
        if not line or line.startswith(("<", "```", "Message Type:", "Task name:", "Sender:")):
            continue
        line = _DIRECTIVE_PREFIX_RE.sub("", line)
        if not line:
            continue
        candidates.append(line)
    if not candidates:
        return ""
    chosen = candidates[0]
    sentence = re.split(r"(?<=[.!?])\s+", chosen, maxsplit=1)[0]
    sentence = re.sub(r"\s+", " ", sentence).strip()
    return records.safe_text(sentence, limit)


def _task_assignment(text: str, artifact: str) -> str:
    """Select the current task directive, not a preceding status sentence."""
    if artifact:
        return ""
    candidates: list[tuple[int, int, str]] = []
    for index, raw in enumerate(text.splitlines()):
        line = raw.strip().lstrip("#*- ").strip()
        if not line or line.startswith(("```", "Message Type:", "Task name:", "Sender:")):
            continue
        task_match = re.match(r"^Task:\s*(.+)$", line, re.IGNORECASE)
        if task_match:
            candidates.append((4, index, task_match.group(1)))
            continue
        if _TASK_DIRECTIVE_RE.match(line):
            priority = 5 if "stage report" in line.casefold() else 3
            candidates.append((priority, index, line))
    if candidates:
        _priority, _index, chosen = max(candidates, key=lambda item: (item[0], -item[1]))
        return _semantic_line(chosen, MAX_SEMANTIC_LINE)
    return _semantic_line(text, MAX_SEMANTIC_LINE)


def _record_timestamp(record: dict[str, Any]) -> float | None:
    message = record.get("message")
    message_ts = message.get("timestamp") if isinstance(message, dict) else None
    return records.parse_ts(record.get("timestamp") or message_ts or _reader_stamp(record) or "")


def _dispatch_identity(command_line: str) -> tuple[str, str, str] | None:
    match = _DISPATCH_BUILD_RE.match(command_line)
    if match is None:
        return None
    try:
        tokens = shlex.split(match.group(1) or "")
    except ValueError:
        return None
    slug = ""
    stage = ""
    workflow_binding = ""
    index = 0
    while index < len(tokens):
        part = tokens[index]
        if part in {"|", "&&", ";"} or part.startswith((">", "1>", "2>")):
            break
        if part in _DISPATCH_VALUE_OPTIONS:
            value = tokens[index + 1] if index + 1 < len(tokens) else ""
            if part == "--stage" and spacedock.SD_STAGE_RE.fullmatch(value):
                stage = value
            elif part == "--workflow-dir":
                workflow_binding = value
            index += 2
            continue
        if part.startswith("-"):
            index += 1
            continue
        if not slug and spacedock.SD_STAGE_RE.fullmatch(part):
            slug = part
        index += 1
    return (workflow_binding, slug, stage) if slug else None


def _subagent_tasks(arguments: dict[str, Any]) -> list[str]:
    tasks: list[str] = []
    task = arguments.get("task")
    if isinstance(task, str) and task.strip():
        tasks.append(task)
    batch = arguments.get("tasks")
    if isinstance(batch, list):
        for item in batch:
            if not isinstance(item, dict):
                continue
            value = item.get("task")
            if isinstance(value, str) and value.strip():
                tasks.append(value)
    return tasks


def _dispatch_directories() -> tuple[str, ...]:
    runtime = os.environ.get("XDG_RUNTIME_DIR", "")
    if runtime and os.path.isabs(runtime):
        return (os.path.join(runtime, "spacedock-dispatch"), _DISPATCH_DIRECTORY)
    return (_DISPATCH_DIRECTORY,)


def _dispatch_artifact(text: str) -> str:
    for directory in _dispatch_directories():
        pattern = re.escape(directory + "/spacedock-ensign-") + r"[A-Za-z0-9][A-Za-z0-9._-]*\.md"
        match = re.search(pattern, text)
        if match is not None:
            return match.group(0)
    return ""


def _dispatch_artifact_identity(artifact: str) -> tuple[str, str] | None:
    directory, name = os.path.split(artifact)
    if (
        directory not in _dispatch_directories()
        or not name.startswith("spacedock-ensign-")
        or not name.endswith(".md")
    ):
        return None
    name = name[len("spacedock-ensign-") : -len(".md")]
    slug, separator, stage = name.rpartition("-")
    if not separator or not spacedock.SD_STAGE_RE.fullmatch(slug):
        return None
    if not spacedock.SD_STAGE_RE.fullmatch(stage):
        return None
    return slug, stage


def _read_dispatch_artifact(artifact: str) -> str:
    if (
        _dispatch_artifact_identity(artifact) is None
        or not hasattr(os, "O_NOFOLLOW")
        or not hasattr(os, "getuid")
    ):
        return ""
    directory = os.path.dirname(artifact)
    try:
        resolved_directory = os.path.realpath(directory)
        if os.path.dirname(os.path.realpath(artifact)) != resolved_directory:
            return ""
        # The directory fd anchors the open even if an entry is replaced between
        # realpath and open. Inspect the opened file, never a pre-open stat.
        with contextlib.ExitStack() as stack:
            directory_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            stack.callback(os.close, directory_fd)
            if os.fstat(directory_fd).st_uid != os.getuid():
                return ""
            descriptor = os.open(
                os.path.basename(artifact),
                os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                dir_fd=directory_fd,
            )
            with os.fdopen(descriptor, "rb") as handle:
                info = os.fstat(handle.fileno())
                if (
                    not stat.S_ISREG(info.st_mode)
                    or info.st_uid != os.getuid()
                    or info.st_mode & 0o022
                    or info.st_size > DISPATCH_MAX_BYTES
                ):
                    return ""
                raw = handle.read(DISPATCH_MAX_BYTES + 1)
                return raw.decode("utf-8", "replace") if len(raw) <= DISPATCH_MAX_BYTES else ""
    except (OSError, ValueError):
        return ""


def _dispatch_file_assignment(artifact: str) -> str:
    """Read the bounded human work title from one exact dispatch artifact."""
    if _dispatch_artifact_identity(artifact) is None:
        return ""
    prefix = "You are working on:"
    for raw in _read_dispatch_artifact(artifact).splitlines()[:40]:
        line = raw.strip()
        if line.startswith(prefix):
            return records.safe_text(line[len(prefix) :].strip(), MAX_SEMANTIC_LINE)
    return ""


def _subagent_specs(arguments: dict[str, Any]) -> list[tuple[str, str, str, str]]:
    specs: list[tuple[str, str, str, str]] = []
    task = arguments.get("task")
    if isinstance(task, str) and task.strip():
        contributor = arguments.get("agent") or arguments.get("name") or ""
        binding = arguments.get("work_item") or arguments.get("task_id") or ""
        specs.append((task, str(contributor), str(binding), _dispatch_artifact(task)))
    batch = arguments.get("tasks")
    if isinstance(batch, list):
        for item in batch:
            if not isinstance(item, dict):
                continue
            value = item.get("task")
            if not isinstance(value, str) or not value.strip():
                continue
            contributor = item.get("agent") or item.get("name") or ""
            binding = item.get("work_item") or item.get("task_id") or ""
            specs.append((value, str(contributor), str(binding), _dispatch_artifact(value)))
    return specs


def _work_records(
    config: RuntimeConfig,
    transcript_path: str,
    *,
    max_bytes: int | None = None,
    follow_links: bool = True,
) -> list[dict[str, Any]]:
    transcript: list[dict[str, Any]] = []
    bounded = list(
        runtime_io.reverse_lines(
            config,
            transcript_path,
            max_bytes=max_bytes or config.turn_scan_max_bytes,
            follow_links=follow_links,
        )
    )
    for raw_bytes in reversed(bounded):
        raw = raw_bytes.decode("utf-8", "replace")
        if not raw or not raw.lstrip().startswith("{"):
            continue
        try:
            record = json.loads(raw)
        except (ValueError, json.JSONDecodeError, RecursionError):
            continue
        if isinstance(record, dict):
            transcript.append(record)
    return transcript


def _result_text(message: dict[str, Any]) -> str:
    content = message.get("content")
    if isinstance(content, str):
        return records.safe_text(content, 16_000)
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for block in content:
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, dict) and isinstance(block.get("text"), str):
            parts.append(block["text"])
    return records.safe_text("\n".join(parts), 16_000)


def _paired_results(transcript: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    results: dict[str, dict[str, Any]] = {}
    for record in transcript:
        message = record.get("message")
        if not isinstance(message, dict) or message.get("role") != "toolResult":
            continue
        call_id = message.get("toolCallId")
        if isinstance(call_id, str):
            results[call_id] = {
                "succeeded": message.get("isError") is not True,
                "is_error": message.get("isError"),
                "text": _result_text(message),
                "at": _record_timestamp(record),
                **_pi_status(message),
            }
    return results


# Pi 0.87.1's bash tool throws on a nonzero exit, a timeout, an abort and a
# missing exit code, and appends exactly one of these lines after any
# truncation notice; the agent loop then sets `isError`. Measured in
# docs/captures/pi/validation-results-0.87.1-macos.jsonl: `isError` was set on
# exactly the runs that carried one, and every nonzero exit carried the first.
_PI_EXITED_RE = re.compile(r"(?:\A|\n\n)Command exited with code ([1-9]\d*)\Z")
_PI_STOPPED_RE = re.compile(
    r"(?:\A|\n\n)(?:Command timed out after \d+ seconds|Command aborted"
    r"|Command terminated without an exit code)\Z"
)


def _pi_status(message: dict[str, Any]) -> dict[str, Any]:
    """The call's status line, and the output tail before it.

    Read from the whole text rather than `_result_text`, which keeps the head:
    Pi's own truncation keeps the tail, and both the summary and the status
    line sit at the end.
    """
    content = message.get("content")
    blocks = content if isinstance(content, list) else [content]
    text = "\n".join(
        block if isinstance(block, str) else str(block.get("text"))
        for block in blocks
        if isinstance(block, str)
        or (isinstance(block, dict) and isinstance(block.get("text"), str))
    )
    status, body = "", text
    if (found := _PI_EXITED_RE.search(text)) is not None:
        status, body = "exited", text[: found.start()]
    elif (found := _PI_STOPPED_RE.search(text)) is not None:
        status, body = "stopped", text[: found.start()]
    return {"status": status, "tail": records.redact_secrets(body)[-TOOL_REPORT_TAIL_CHARS:]}


def _dispatch_count(command: str) -> int:
    return sum(_dispatch_identity(line) is not None for line in command.splitlines())


def _dispatch_events(
    command: str,
    *,
    at: float,
    result: dict[str, Any] | None,
    harness: str,
    sid: str,
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for command_line in command.splitlines():
        identity = _dispatch_identity(command_line)
        if identity is None:
            continue
        workflow_binding, slug, stage = identity
        title = slug + (f" → {stage}" if stage else " dispatched")
        events.append(
            {
                "at": at,
                "kind": "prepared_dispatch",
                "phase": "Spacedock dispatch preparation",
                "title": title,
                "source": "Pi bash tool call"
                + (" and paired result" if result is not None else ""),
                "harness": harness,
                "sid": sid,
                "entity": slug,
                "workflow_binding": workflow_binding,
                "stage": stage,
                "dispatch_artifact": (f"{_DISPATCH_FILE_PREFIX}{slug}-{stage}.md" if stage else ""),
                "dispatch_artifact_prefix": f"{_DISPATCH_FILE_PREFIX}{slug}-",
                "succeeded": result.get("succeeded") if result is not None else None,
            }
        )
    return events


# Counts only; which result a run had is `_ToolReportTally._outcome`'s to say.
_PI_FAILED_COUNT_RE = re.compile(r"\b([1-9]\d*) failed\b|^\u2139 fail ([1-9]\d*)\s*$", re.MULTILINE)
_PI_PASSED_COUNT_RE = re.compile(r"\b([1-9]\d*) passed\b|^\u2139 pass ([1-9]\d*)\s*$", re.MULTILINE)
_PI_READ_ONLY_TOOLS = frozenset({"read", "grep", "find", "ls"})


def _pi_flag(result: Mapping[str, Any]) -> bool | None:
    """What Pi's error flag says about the call, as the 0.87.1 capture shows it.

    A clear flag is an exit of 0 for the whole call. A set flag with the
    exit line is a nonzero exit. Anything else flagged is not an exit: `None`.
    So is a flag that is not set beside Pi's own exit line: a `tool_result`
    extension may clear it on a call that threw, and the capture shows the two
    only agreeing.
    """
    if result.get("status") == "exited":
        return True if result.get("is_error") is True else None
    if result.get("is_error") is False:
        return False
    return None


def _pi_count(pattern: re.Pattern[str], tail: str) -> int:
    found = pattern.search(tail)
    return int(next(group for group in found.groups() if group)) if found else 0


def _checks_word(count: int) -> str:
    return "check" if count == 1 else "checks"


def _pi_check_title(result: str, *, failed: int, passed: int) -> str:
    if result == "failed":
        return (
            f"{failed} validation {_checks_word(failed)} failed" if failed else "Validation failed"
        )
    if result == "passed":
        return (
            f"{passed} validation {_checks_word(passed)} passed" if passed else "Validation passed"
        )
    return "Validation ran, result not recorded"


def _pi_check_runs(
    command: str,
    *,
    call_key: str,
    at: float,
    result: dict[str, Any] | None,
    harness: str,
    sid: str,
) -> list[tuple[str, dict[str, Any], _ShellCall]]:
    """Each check in one Pi bash call, read by
    [DEC-23](docs/design-reading-a-session.md#dec-23-a-claude-code-sessions-record-of-its-checks-may-show-the-work)'s
    rules, as `(check identity, run, call)`.

    Only a runner on the closed list counts, so no other command's output is
    read as a result. Failure is read first, a zero count is "ran, result not
    recorded", and the flag speaks only as `_pi_flag` reads it.
    """
    if result is not None and result.get("is_error") is True and not result.get("status"):
        # Flagged with no status line: refused or blocked, so the call never ran.
        return []
    call = _ShellCall(at, "", {"command": command})
    if call.unbalanced or not call.checks:
        return []
    flag = _pi_flag(result) if result is not None else None
    tail = str(result.get("tail") or "") if result is not None else ""
    all_and = all(joiner == "&&" for joiner in call.joiners()[:-1])
    attributable = call.output_attributable()
    runs = []
    for index in call.checks:
        words, rtk = call.words[index]
        outcome, source = "not-recorded", ""
        if (
            result is not None
            and not call.background(index)
            and not call.unestablished(index)
            and (flag is not None or result.get("status") != "stopped")
        ):
            outcome, source = _ToolReportTally._outcome(  # noqa: SLF001 - one rule, both harnesses
                tail,
                rtk=rtk,
                attributable=attributable,
                flag_result=_flag_result(
                    flag,
                    last=index == len(call.parts) - 1,
                    all_and=all_and,
                    alone=len(call.meaningful) == 1,
                ),
            )
        if outcome == "passed" and flag is None and result and result.get("status") == "exited":
            # The exit line says the call failed, so no output may say it passed.
            outcome, source = "not-recorded", ""
        failed = _pi_count(_PI_FAILED_COUNT_RE, tail) if attributable else 0
        passed = _pi_count(_PI_PASSED_COUNT_RE, tail) if attributable else 0
        run: dict[str, Any] = {
            "at": at,
            "kind": "outcome",
            "phase": "validation result",
            "title": _pi_check_title(outcome, failed=failed, passed=passed),
            "source": "Pi bash tool call"
            + (" and paired result" if result is not None else ", no result recorded yet"),
            "harness": harness,
            "sid": sid,
            "subject": "check",
            "result": outcome,
            "lineage": f"{call_key}:check:{index}",
            "index": index,
        }
        if source:
            run["result_source"] = source
        if outcome == "failed" and failed:
            run["checks_failed"] = failed
        if outcome == "passed" and passed:
            run["checks_passed"] = passed
        result_at = result.get("at") if result is not None else None
        if isinstance(result_at, (int, float)):
            run["result_at"] = float(result_at)
        runs.append((_check_identity(call.directories[index], words), run, call))
    return runs


def _pi_changes(block: dict[str, Any]) -> bool:
    """Whether one Pi tool call may have changed files: any tool but the four
    Pi 0.87.1 ships that only read, or a bash call that is not on the closed
    read-only list.

    Unknown tools count as changes, `powershell` and extension tools included,
    because a pass a write followed is not current, and the cost of guessing
    wrong the other way is a false consistent.
    """
    name = block.get("name")
    if name != "bash":
        return name not in _PI_READ_ONLY_TOOLS
    command = _call_arguments(block).get("command")
    return isinstance(command, str) and _ShellCall(0.0, "", {"command": command}).changes()


def _latest_pi_checks(
    runs: list[tuple[str, dict[str, Any], _ShellCall, int]], changing: list[bool]
) -> list[dict[str, Any]]:
    """The latest run of each check, as Claude Code's record lists them, with
    whether a failure came earlier and whether a change followed.

    One run per check rather than every run: the levels read the latest run of
    a check, and an earlier failure the same check since passed is not a
    failing check.
    """
    by_check: dict[str, list[tuple[dict[str, Any], _ShellCall, int]]] = {}
    for identity, run, call, seq in runs:
        by_check.setdefault(identity, []).append((run, call, seq))
    latest: list[dict[str, Any]] = []
    for history in by_check.values():
        order = max(range(len(history)), key=lambda i: (_evidence_at(history[i][0]), i))
        run, call, seq = history[order]
        index = run.pop("index")
        in_call = any(i > index for i in (*call.fixers, *call.changing_others, *call.substituted))
        edited_later = any(changing[s] for s in range(seq + 1, len(changing)))
        run["earlier_failed"] = any(
            other["result"] == "failed" for i, (other, _c, _s) in enumerate(history) if i != order
        )
        run["changed_after"] = in_call or edited_later
        run["before_last_change"] = run["result"] == "passed" and (
            any(i >= index for i in call.fixers) or edited_later
        )
        for other, _call, _seq in history:
            other.pop("index", None)
        latest.append(run)
    return latest


def _subagent_category(combined: str) -> str:
    if re.match(r"^(?:review|inspect)\b", combined):
        return (
            "Implementation review completed"
            if "implementation" in combined
            else "Technical review completed"
        )
    if re.match(r"^implement\b", combined):
        return "Implementation pass completed"
    if re.match(r"^(?:design|write\b.*\bdesign)\b", combined):
        return "Design result produced"
    if re.match(r"^(?:perform\s+)?(?:independent\s+)?acceptance\b", combined):
        return "Independent acceptance completed"
    return ""


def _subagent_result_counts(text: str, tasks: list[str]) -> tuple[int, int]:
    completed = re.search(r"(?:children|tasks?):\s*(\d+)\s+completed", text, re.IGNORECASE)
    failed = re.search(r"(\d+)\s+failed", text, re.IGNORECASE)
    completed_count = int(completed.group(1)) if completed else len(tasks)
    failed_count = int(failed.group(1)) if failed else 0
    return completed_count, failed_count


def _subagent_has_substantive_review(result: Mapping[str, Any]) -> bool:
    for key in ("review_findings", "findings"):
        findings = result.get(key)
        if isinstance(findings, list) and any(
            isinstance(finding, str) and finding.strip() for finding in findings
        ):
            return True
    text = str(result.get("text", ""))
    match = re.search(r"(?im)^\s*review changed the course\s*:\s*$", text)
    if match is None:
        return False
    return any(
        re.match(r"^\s*[-*]\s+\S", line)
        for line in text[match.end() :].splitlines()
        if line.strip()
    )


def _subagent_result_title(tasks: list[str], result: dict[str, Any]) -> str:
    if _subagent_result_pending(result):
        return ""
    text = str(result.get("text", ""))
    lowered = text.casefold()
    if "acceptance cannot be requested explicitly" in lowered or (
        "cannot supply" in lowered and "reviewer result" in lowered
    ):
        return ""
    combined = " ".join(tasks).casefold()
    if result.get("succeeded") is not True:
        return "Independent acceptance was unavailable" if "acceptance" in combined else ""
    title = _subagent_category(combined)
    if not title:
        return ""
    if re.match(r"^(?:review|inspect)\b", combined):
        return title if _subagent_has_substantive_review(result) else "Review call returned"
    contributors, failures = _subagent_result_counts(text, tasks)
    if contributors > 1:
        title += f" by {contributors} contributors"
    if failures:
        title += f" with {failures} contributor failure"
        if failures != 1:
            title += "s"
    return title


def _subagent_result_pending(result: dict[str, Any]) -> bool:
    text = str(result.get("text", "")).casefold()
    return any(marker in text for marker in ("detached", "running in the background"))


def _subagent_events(
    arguments: dict[str, Any],
    *,
    call_key: str,
    at: float,
    result: dict[str, Any] | None,
    harness: str,
    sid: str,
) -> list[dict[str, Any]]:
    specs = _subagent_specs(arguments)
    tasks = [spec[0] for spec in specs]
    if not specs:
        return []
    rows: list[dict[str, Any]] = []
    for index, (task, contributor, binding, artifact) in enumerate(specs):
        assignment = _task_assignment(task, artifact)
        title = assignment or _semantic_line(task, MAX_SEMANTIC_LINE)
        if not title:
            continue
        rows.append(
            {
                "at": at,
                "kind": "task_started",
                "phase": "ordinary subagent task",
                "title": title,
                "source": "Pi subagent task label",
                "harness": harness,
                "sid": sid,
                "lineage": f"{call_key}:{index}",
                "work_item_binding": binding,
                "contributor_ref": contributor,
                "dispatch_artifact": artifact,
                "assignment": assignment,
                "worker_kind": "ensign" if artifact else "subagent",
                "stage": "started",
            }
        )
    if result is None or _subagent_result_pending(result):
        return rows
    result_title = _subagent_result_title(tasks, result)
    result_at = result.get("at")
    outcome_at = float(result_at) if isinstance(result_at, (int, float)) else at
    text = str(result.get("text", ""))
    completed = re.search(r"(?:children|tasks?):\s*(\d+)\s+completed", text, re.IGNORECASE)
    failed = re.search(r"(\d+)\s+failed", text, re.IGNORECASE)
    complete_count = int(completed.group(1)) if completed else len(tasks)
    failure_count = int(failed.group(1)) if failed else 0
    if len(tasks) == 1 or (complete_count == len(tasks) and failure_count == 0):
        for index, (task, contributor, binding, artifact) in enumerate(specs):
            item_title = result_title or _subagent_result_title([task], result)
            if not item_title and artifact and result.get("succeeded") is True:
                item_title = "Dispatch result returned"
            if not item_title:
                continue
            rows.append(
                {
                    "at": outcome_at,
                    "kind": "task_result",
                    "phase": "ordinary subagent result",
                    "title": item_title,
                    "source": "Pi subagent task label and paired result",
                    "harness": harness,
                    "sid": sid,
                    "lineage": f"{call_key}:{index}",
                    "work_item_binding": binding,
                    "contributor_ref": contributor,
                    "dispatch_artifact": artifact,
                    "assignment": _task_assignment(task, artifact),
                    "worker_kind": "ensign" if artifact else "subagent",
                    "stage": "completed",
                }
            )
    elif result_title:
        rows.append(
            {
                "at": outcome_at,
                "kind": "outcome",
                "phase": "ordinary subagent batch result",
                "title": result_title,
                "source": "Pi subagent batch call and paired result",
                "harness": harness,
                "sid": sid,
                "contributors": len(tasks),
            }
        )
    return rows


def _call_arguments(block: dict[str, Any]) -> dict[str, Any]:
    """A Pi tool call's arguments: the one read `_tool_call_events` and the
    check reader share, so SECURITY.md's count of input reads holds."""
    arguments = block.get("arguments")
    return arguments if isinstance(arguments, dict) else {}


def _tool_call_events(
    block: dict[str, Any],
    *,
    at: float,
    results: dict[str, dict[str, Any]],
    harness: str,
    sid: str,
) -> list[dict[str, Any]]:
    call_id = block.get("id")
    call_key = call_id if isinstance(call_id, str) else ""
    args = _call_arguments(block)
    result = results.get(call_key)
    if block.get("name") == "bash":
        command = args.get("command")
        return _dispatch_events(
            command if isinstance(command, str) else "",
            at=at,
            result=result,
            harness=harness,
            sid=sid,
        )
    if block.get("name") != "subagent":
        return []
    return _subagent_events(
        args,
        call_key=call_key,
        at=at,
        result=result,
        harness=harness,
        sid=sid,
    )


def _tool_support(
    block: dict[str, Any], results: dict[str, dict[str, Any]]
) -> dict[str, int] | None:
    name = block.get("name")
    if name not in {"bash", "subagent"}:
        return None
    support = {"tool_calls": 1, "dispatch_builds": 0, "subagent_calls": 0, "pending_subagents": 0}
    arguments = block.get("arguments")
    args = arguments if isinstance(arguments, dict) else {}
    if name == "bash" and isinstance(args.get("command"), str):
        support["dispatch_builds"] = _dispatch_count(args["command"])
    if name != "subagent" or not _subagent_tasks(args):
        return support
    support["subagent_calls"] = 1
    call_id = block.get("id")
    pair = results.get(call_id) if isinstance(call_id, str) else None
    pending = pair is None or _subagent_result_pending(pair)
    support["pending_subagents"] = int(pending)
    return support


def _assistant_branch_identity(
    record: dict[str, Any], records_by_id: dict[str, dict[str, Any]]
) -> dict[str, str]:
    record_id = record.get("id")
    parent_id = record.get("parentId")
    if not isinstance(record_id, str) or not record_id:
        return {}
    identity = {"record_id": record_id}
    if isinstance(parent_id, str) and parent_id:
        identity["parent_id"] = parent_id
    branch_id = record_id
    cursor = record
    seen: set[str] = {record_id}
    while True:
        ancestor_id = cursor.get("parentId")
        if not isinstance(ancestor_id, str) or not ancestor_id or ancestor_id in seen:
            return identity
        seen.add(ancestor_id)
        ancestor = records_by_id.get(ancestor_id)
        if ancestor is None:
            return identity
        message = ancestor.get("message")
        if isinstance(message, dict) and message.get("role") == "user":
            identity["turn_id"] = ancestor_id
            identity["branch_id"] = branch_id
            return identity
        branch_id = ancestor_id
        cursor = ancestor


def _assistant_tool_calls(
    transcript: list[dict[str, Any]],
) -> Iterator[tuple[float, dict[str, Any], dict[str, str]]]:
    records_by_id = {
        str(record["id"]): record
        for record in transcript
        if isinstance(record.get("id"), str) and record.get("id")
    }
    for record in transcript:
        message = record.get("message")
        if not isinstance(message, dict) or message.get("role") != "assistant":
            continue
        content = message.get("content")
        at = _record_timestamp(record)
        if not isinstance(content, list) or at is None:
            continue
        identity = _assistant_branch_identity(record, records_by_id)
        for block in content:
            if isinstance(block, dict) and block.get("type") == "toolCall":
                yield at, block, identity


def _work_evidence(
    config: RuntimeConfig,
    transcript_path: str,
    harness: str,
    sid: str,
    *,
    max_bytes: int | None = None,
    since: float | None = None,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Demonstrated Pi results plus counts for suppressed supporting telemetry."""
    stats = {
        "tool_calls": 0,
        "dispatch_builds": 0,
        "subagent_calls": 0,
        "pending_subagents": 0,
        "suppressed_tool_calls": 0,
        "collapsed_contributors": 0,
    }
    if harness != "pi":
        return [], stats
    transcript = _work_records(config, transcript_path, max_bytes=max_bytes)
    results = _paired_results(transcript)

    events: list[dict[str, Any]] = []
    calls = list(_assistant_tool_calls(transcript))
    changing = [_pi_changes(block) for _at, block, _identity in calls]
    check_runs: list[tuple[str, dict[str, Any], _ShellCall, int]] = []
    for seq, (at, block, identity) in enumerate(calls):
        support = _tool_support(block, results)
        if support is None:
            continue
        for key, value in support.items():
            stats[key] += value
        found = _tool_call_events(
            block,
            at=at,
            results=results,
            harness=harness,
            sid=sid,
        )
        runs = _pi_bash_check_runs(block, at=at, results=results, harness=harness, sid=sid)
        for check, run, call in runs:
            run.update(identity)
            check_runs.append((check, run, call, seq))
        for event in found:
            event.update(identity)
        found = _with_dispatch_titles(_events_after(found, since))
        events.extend(found)
        if not found and not runs:
            stats["suppressed_tool_calls"] += 1
        for event in found:
            stats["collapsed_contributors"] += max(0, int(event.get("contributors", 1)) - 1)
    # Chosen over the whole bounded read before `since` cuts it, so a run the
    # cut leaves out still supersedes an earlier one.
    events.extend(_events_after(_latest_pi_checks(check_runs, changing), since))
    return events, stats


def _with_dispatch_titles(found: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for event in found:
        artifact = str(event.get("dispatch_artifact") or "")
        assignment = _dispatch_file_assignment(artifact)
        if assignment:
            event["assignment"] = assignment
            event["source"] = (
                str(event.get("source") or "") + " and bounded dispatch artifact title"
            )
    return found


def _pi_bash_check_runs(
    block: dict[str, Any],
    *,
    at: float,
    results: dict[str, dict[str, Any]],
    harness: str,
    sid: str,
) -> list[tuple[str, dict[str, Any], _ShellCall]]:
    command = _call_arguments(block).get("command")
    if block.get("name") != "bash" or not isinstance(command, str):
        return []
    call_id = block.get("id")
    call_key = call_id if isinstance(call_id, str) else ""
    return _pi_check_runs(
        command,
        call_key=call_key,
        at=at,
        result=results.get(call_key),
        harness=harness,
        sid=sid,
    )


def _events_after(events: list[dict[str, Any]], since: float | None) -> list[dict[str, Any]]:
    floor = float(since) if isinstance(since, (int, float)) else float("-inf")
    return [event for event in events if float(event.get("at") or 0) >= floor]


def work_events(
    config: RuntimeConfig,
    transcript_path: str,
    harness: str,
    sid: str,
) -> list[dict[str, Any]]:
    """Demonstrated Pi results; supporting tool and lifecycle facts stay suppressed."""
    return _work_evidence(config, transcript_path, harness, sid)[0]


# The checks a Claude Code session ran and the files it wrote, as the
# transcript recorded them. The ruling `claude_tool_reports` cites owns every
# rule below; the closed runner list and the result patterns are its "The
# closed lists" section, written out, with the owner's rulings and the review's
# clarifications of 2026-09-24, and the parser and wrapper amendment of 2026-09-25.
#
# Called from `collect` only, never from `_semantic_history_source_events`, so
# the history store never sees these facts; `semantic_history._FACT_EVENT_TYPES`
# not naming the type is the second wall (item 6).
_TOOL_REPORT_KINDS = frozenset({"check_run", "path_written", "background_launch"})
TOOL_REPORT_MAX_ENTRIES = 12
TOOL_REPORT_LINE_CHARS = 120
# The existing ledger cap (`reading.LEDGER_SUMMARY_CAP_CHARS`), which item 5 names.
TOOL_REPORT_TAIL_CHARS = 180
TOOL_REPORT_PATH_CHARS = 240
# Shorter pieces of a masked value are not scrubbed from the tail: a two-letter
# piece would wipe ordinary output, and the check line masks it anyway.
_SCRUB_MIN_CHARS = 4
_WRITE_TOOLS = frozenset({"Write", "Edit", "MultiEdit", "NotebookEdit"})
_ASSIGNMENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_PYTHON_RE = re.compile(r"^python(?:\d+(?:\.\d+)?)?$")
_DURATION_RE = re.compile(r"^\d+(?:\.\d+)?[smhd]?$")
_REDIRECT_RE = re.compile(r"^(?:\d*>&\d+|&>.*|\d*>>?.+|<.+)$")
# What a substituted command, and a here-string's stdin word, publish instead
# of their text (the parser's ruling is cited on `_ShellLexer`).
_SUBSTITUTED = "$(…)"
_ARITHMETIC = "$((…))"
_WITHHELD = "…"
# An arithmetic body holding a substitution: read as a change, never parsed.
_UNREAD_BODY = "\0"
_NESTING_CAP = 32
_REDIRECTION_RE = re.compile(
    r"(?:\d+|\{[A-Za-z_][A-Za-z0-9_]*\})?(?P<op>&>>|&>|<<<|<<-|<<|<&|<>|>>|>&|>\||<|>)"
)
_BRACE_EXPANSION_RE = re.compile(r"\{[^{}]*(?:,|\.\.)[^{}]*\}")
_CASE_WORD_RE = re.compile(r"(?:case|esac)(?=[\s;|&()]|$)")
_COMMAND_STARTS = frozenset(" \t\n;(|&")
_ANSI_C_ESCAPES = {
    "a": "\a", "b": "\b", "e": "\x1b", "E": "\x1b", "f": "\f", "n": "\n", "r": "\r",
    "t": "\t", "v": "\v", "\\": "\\", "'": "'", '"': '"', "?": "?",
}  # fmt: skip
_ANSI_C_WIDTHS = {"x": 2, "u": 4, "U": 8}
_HEX_DIGITS = frozenset("0123456789abcdefABCDEF")
_OCTAL_DIGITS = frozenset("01234567")
# The shell `-c` wrappers the owner ruled on 2026-09-25: a closed option set,
# and at most two wrappers deep. Anything else leaves the segment unread.
_SHELLS = frozenset({"bash", "sh", "zsh"})
# `x` is left out: xtrace echoes every word, a masked value included, into the
# output tail the prompt row carries (review, 2026-09-27).
_SHELL_FLAGS_RE = re.compile(r"^-[eulc]+$")
_SHELL_LONG_OPTIONS = frozenset({"--login", "--noprofile", "--norc"})
_SHELL_WRAPPER_DEPTH = 2
_WRAPPER_PAIRS = (["poetry", "run"], ["pipenv", "run"], ["pnpm", "exec"])
_UV_VALUE_OPTIONS = frozenset(
    {"--with", "--with-requirements", "--python", "-p", "--project", "--directory", "--extra",
     "--group", "--package", "--env-file", "--index"}
)  # fmt: skip
# Runners named by their first word, by their first two, and by three.
_CHECK_WORDS = frozenset(
    {
        "pytest", "py.test", "nose2", "tox", "nox", "jest", "vitest", "mocha", "rspec",
        "phpunit", "ctest", "flake8", "pylint", "eslint", "stylelint", "golangci-lint",
        "rubocop", "shellcheck", "mypy", "pyright", "tsc",
    }
)  # fmt: skip
_CHECK_PAIRS = frozenset(
    {
        ("npm", "test"), ("pnpm", "test"), ("yarn", "test"), ("bun", "test"),
        ("deno", "test"), ("go", "test"), ("cargo", "test"), ("cargo", "nextest"),
        ("mvn", "test"), ("gradle", "test"), ("./gradlew", "test"), ("dotnet", "test"),
        ("rake", "test"), ("swift", "test"), ("make", "test"), ("make", "check"),
        ("pnpm", "build"), ("yarn", "build"), ("cargo", "build"), ("go", "build"),
        ("make", "build"), ("mvn", "package"), ("gradle", "build"), ("./gradlew", "build"),
        ("dotnet", "build"), ("swift", "build"), ("vite", "build"), ("ruff", "check"),
        ("cargo", "clippy"), ("cargo", "check"), ("go", "vet"),
    }
)  # fmt: skip
_CHECK_TRIPLES = frozenset(
    {
        ("bundle", "exec", "rspec"), ("npm", "run", "test"), ("pnpm", "run", "test"),
        ("npm", "run", "build"), ("pnpm", "run", "build"), ("bun", "run", "build"),
    }
)  # fmt: skip
# Runners that are checks only with `--check` among their words.
_CHECK_FLAGGED = frozenset({("black",), ("prettier",), ("ruff", "format")})
# A check that rewrites files is a change too, and ages every pass, its own
# included (review, 2026-09-24).
_FIX_FLAGS = frozenset({"--fix", "--write", "--fix-only", "--unsafe-fixes"})
_INTERPRETERS = frozenset({"node", "bash", "sh", "zsh"})
_SHELL_BUILTINS = frozenset({"test", "[", "[["})
_INFO = "\u2139"  # node's summary glyph, written as an escape so review can read it
# Item 2, source (ii): summary lines. A failure anywhere in the tail wins over a
# pass, because a run that printed both failed. Matched per line: node prints
# its pass and fail counts on lines of their own.
_SUMMARY_FAILED = re.compile(
    rf"\b[1-9]\d* failed\b|^FAILED \(|^\s*Tests:.*\b[1-9]\d* failed|^{_INFO} fail [1-9]\d*\s*$"
    r"|^FAIL\b|test result: FAILED|\b[1-9]\d* errors?\b(?! \(\d+ fixed, 0 remaining\))",
    re.MULTILINE,
)
# A pass counts only when nothing else in the tail records a failure (owner,
# 2026-09-24). Node's pass count alone is not a pass: node prints the fail count
# on the line after it, so a tail that kept one and lost the other says nothing
# about failures. Go's `ok  <pkg>` is not a pass either: go passes come from the
# error flag alone. unittest's `OK` must be the whole line.
_SUMMARY_PASSED = re.compile(
    rf"\b\d+ passed\b|^OK\s*$|^\s*Tests:\s.*\b\d+ passed|^{_INFO} fail 0\s*$"
    r"|test result: ok|^Success: no issues found|^All checks passed!",
    re.MULTILINE,
)
# Source (iii): may record a failure, never a pass. Node's cancelled count is
# one: a timed-out test prints `fail 0` beside it and exits 1 (measured on node
# 26, review 2026-09-24).
_FAILURE_MARKER = re.compile(
    r"\u2716|failing tests:|AssertionError|ERR_ASSERTION|^FAILED |^ERROR |--- FAIL:|panicked at"
    rf"|error TS\d*|^{_INFO} cancelled [1-9]\d*\s*$",
    re.MULTILINE,
)
# A pass that ran nothing is not a pass, from the flag or from a summary: it
# reads "ran, result not recorded". go's `[no test files]` counts only when no
# package printed `ok`.
_RAN_NOTHING = re.compile(
    rf"^{_INFO} pass 0\s*$|(?<![\d.])0 passed\b|^Ran 0 tests\b|\[no tests to run\]",
    re.MULTILINE,
)
_NO_TEST_FILES = re.compile(r"\[no test files\]")
_GO_OK = re.compile(r"^ok\s", re.MULTILINE)
# Item 4 as amended on 2026-10-04: failed, passed, written, then no recorded
# result, which carries no verdict and had crowded out every pass (85 in the
# scan, none listed, across the drift replay's 99 cuts). The ruling:
# [DEC-23](docs/design-reading-a-session.md#amended-2026-10-04-no-recorded-result-is-listed-last)
_RESULT_ORDER = {"failed": 0, "passed": 1, "not-recorded": 3}
_WRITE_RANK = 2
# A true error flag is a run that exited nonzero only when Claude Code says so;
# any other flagged result is a call that never ran: a rejection, a cancelled
# parallel call, a sibling error, a hook block or an input error (measured:
# 89% of flagged Bash results open this way; verifier, 2026-09-24).
_EXITED_RE = re.compile(r"\AExit code [1-9]\d*\b")
# Claude Code moved the call to the background itself: no result is recorded.
_MOVED_TO_BACKGROUND_RE = re.compile(
    r"\A(?:Command running in background with ID: "
    r"|Command did not complete within its \d+s timeout and was moved to the background)"
)
# Owner, 2026-09-24: the closed read-only list. A segment that is neither a
# check nor on it is timed, never kept as text; DRC-4692's levels compare the
# time with each check's latest pass. Counted, never listed, never drift.
_READ_ONLY_WORDS = frozenset(
    {"ls", "cat", "head", "tail", "grep", "rg", "find", "wc", "pwd", "echo", "which", "file",
     "stat", "tree", "less"}
)  # fmt: skip
_READ_ONLY_PAIRS = frozenset(
    {"git status", "git log", "git diff", "git show", "git rev-parse", "git merge-base"}
)
# Options that make a read-only command write or run something, per command:
# `find -o` is an OR and stays read-only, `tree -o` writes a file.
_WRITING_OPTIONS = {
    "find": frozenset(
        {"-delete", "-exec", "-execdir", "-ok", "-okdir", "-fprint", "-fprint0", "-fprintf", "-fls"}
    ),
    "tree": frozenset({"-o"}),
    "git diff": frozenset({"--output"}),
    "git log": frozenset({"--output"}),
    "git show": frozenset({"--output"}),
}
# A device that stores nothing, whichever operator writes to it (review W5).
_HARMLESS_DEVICE_RE = re.compile(r"^/dev/(?:null|stdout|stderr|tty|fd/\d+)$")
_CD_OPTION_RE = re.compile(r"^-[LPe@]+$")
# A written redirection's operator, its optional descriptor first, and the
# target word after it.
_WRITE_OPERATORS = frozenset({"&>>", "&>", ">>", ">&", ">|", "<>", ">"})


def _skip_options(words: list[str], takes_value: frozenset[str]) -> list[str]:
    while words and words[0].startswith("-"):
        words = words[2:] if words[0] in takes_value else words[1:]
    return words


def _stripped(words: list[str]) -> tuple[list[str], bool]:
    """Item 3's stripping, and whether `rtk` wrapped the runner (owner, 2026-09-24)."""
    rtk = False
    while words:
        if _ASSIGNMENT_RE.match(words[0]):
            words = words[1:]
        elif words[:2] == ["rtk", "proxy"] or words[0] == "rtk":
            words, rtk = words[2:] if words[1:2] == ["proxy"] else words[1:], True
        elif words[:2] == ["uv", "run"]:
            words = _skip_options(words[2:], _UV_VALUE_OPTIONS)
        elif words[:2] in _WRAPPER_PAIRS:
            words = words[2:]
        elif words[0] in ("npx", "bunx", "time"):
            words = words[1:]
        elif os.path.basename(words[0]) == "env":
            command = _env_command(words[1:])
            if command is None:
                break
            words = command
        elif words[0] == "timeout":
            # `-s KILL` and `-k 5` carry a value; `--signal=KILL` does not.
            words = _skip_options(words[1:], frozenset({"-s", "-k", "--signal", "--kill-after"}))
            words = words[1:] if words and _DURATION_RE.match(words[0]) else words
        else:
            break
    return words, rtk


def _env_command(words: list[str]) -> list[str] | None:
    """The command `env` runs, past assignments, `-i`, `-u NAME` and `--`; None
    for any other option. `-S` re-splits a string and `-C` changes directory,
    so neither is a wrapper (owner, 2026-09-25)."""
    while words:
        word = words[0]
        if _ASSIGNMENT_RE.match(word) or word in ("-i", "--ignore-environment", "-"):
            words = words[1:]
        elif word in ("-u", "--unset"):
            words = words[2:]
        elif word.startswith("--unset=") or (word.startswith("-u") and len(word) > 2):
            words = words[1:]
        elif word == "--":
            return words[1:] or None
        elif word.startswith("-"):
            return None
        else:
            return words
    return None


def _strip_runner_prefix(words: list[str]) -> list[str]:
    return _stripped(words)[0]


class _Unbalanced(Exception):  # noqa: N818 - a parse outcome, not an error the caller reports
    """An unterminated quote, substitution or backtick, a redirection with no
    target, or nesting past the cap: the call is read as not run."""


class _Redirect(NamedTuple):
    # Quoting belongs to the target, never to the operator. Joining them
    # made `> '&1'` indistinguishable from `>&1` (DRC-4725).
    operator: str
    target: str
    kind: str


class _Heredoc(NamedTuple):
    delimiter: str
    strip: bool
    expand: bool
    # The declaring segment's list survives the newline that resets the lexer.
    bodies: list[str]


class _Segment(NamedTuple):
    words: list[str]
    joiner: str
    # Redirections, kept out of `words` because the shell strips them before
    # argv is built: `--password 2>&1 value` reaches the program as a flag and
    # its value side by side, and masking must see them that way.
    redirects: list[_Redirect]
    # The command text of each substitution in the segment, read afterwards
    # with the same rules, since whatever it runs runs whether or not the
    # segment is a check.
    bodies: list[str]
    # Subshells a `(` at command position opened before this segment, and
    # closed after it (DRC-4724).
    opens: int = 0
    closes: int = 0
    # Redirections after a `)`, which the outer shell opens where the group
    # started: each with the index of the segment that opened it (review W3).
    outer: tuple[tuple[_Redirect, int], ...] = ()
    syntax: tuple[str, ...] = ()


class _ShellLexer:
    """One shell line read once, the way the shell reads it, into segments of
    decoded words: what the program receives, which is what masking reads.

    It replaced a token regex, a line-based heredoc strip and `shlex`, whose
    fallback split an unterminated value on spaces and published its tail
    (DRC-4703). Quotes, `$'…'` escapes, `\\`-newline continuations,
    redirections, heredocs (only as an unquoted operator, any delimiter),
    parameter expansions and nested substitutions are read here and nowhere
    else. Anything it cannot read raises `_Unbalanced`.
    [DEC-23](docs/design-reading-a-session.md#amended-2026-09-25-one-parser-reads-the-line-shell-wrappers-and-unbalanced-quoting)
    """

    def __init__(self, text: str) -> None:
        self.text = text
        self.pos = 0
        self.heredocs: list[_Heredoc] = []
        self.redirects: list[_Redirect] = []
        self.bodies: list[str] = []
        self.depth = 0
        # One entry per open parenthesis: the index of the segment a subshell
        # opened at, or None where it opened none.
        self.parens: list[int | None] = []
        self.opens = self.closes = 0
        self.outer: list[tuple[_Redirect, int]] = []
        self.group: int | None = None
        self.syntax: list[str] = []
        self.cases: list[str] = []
        self.literal = False

    def _at(self, offset: int = 0) -> str:
        index = self.pos + offset
        return self.text[index] if index < len(self.text) else ""

    def segments(self) -> list[_Segment]:
        if "\x00" in self.text:
            # No shell passes a NUL in a command line; nothing here can be read.
            raise _Unbalanced
        found: list[_Segment] = []
        words: list[str] = []
        # `--{x,password} value` expands to `--x --password value`, so the
        # word after a withheld brace word may be a named form's value.
        hide_next = False
        while self.pos < len(self.text):
            if not words and self.text.startswith("((", self.pos):
                # An arithmetic command: `<<` in it is a shift, not a heredoc.
                self.pos += 1
                self._skip_group(arithmetic=True)
                words.append(_ARITHMETIC)
                continue
            if self._parenthesis(words, found) or self._skip_space() or self._pattern_alternative():
                continue
            joiner = self._joiner()
            if joiner is None:
                redirect = self._redirection()
                if redirect is None:
                    hide_next = self._add_word(words, hide_next=hide_next)
                else:
                    self._add_redirect(redirect)
                continue
            if words or self.redirects or self.bodies or self.syntax:
                found.append(self._segment(words, joiner))
                # An open before an empty segment waits for the next one.
                self.opens = self.closes = 0
            words, self.redirects, self.bodies, hide_next = [], [], [], False
            self.outer, self.group = [], None
            self.syntax = []
            if joiner == "\n":
                self._skip_bodies(self.heredocs)
                self.heredocs = []
        if words or self.redirects or self.bodies or self.syntax:
            found.append(self._segment(words, ""))
        return found

    def _add_word(self, words: list[str], *, hide_next: bool) -> bool:
        start = self.pos
        word = self._word()
        literal = self.text[start : self.pos] == word
        if not self._syntax_word(word, literal=literal, words=words):
            words.append(_WITHHELD if hide_next else word)
        return word == _WITHHELD

    def _add_redirect(self, redirect: _Redirect) -> None:
        self.redirects.append(redirect)
        if self.group is not None:
            self.outer.append((redirect, self.group))

    def _segment(self, words: list[str], joiner: str) -> _Segment:
        return _Segment(
            words,
            joiner,
            self.redirects,
            self.bodies,
            self.opens,
            self.closes,
            tuple(self.outer),
            tuple(self.syntax),
        )

    def _syntax_word(self, word: str, *, literal: bool, words: list[str]) -> bool:
        if not literal:
            return False
        if not words and word in {"{", "}", "if", "then", "else", "elif", "fi"}:
            self.syntax.append(word)
            return True
        if not words and word == "case":
            self.cases.append("selector")
            self.syntax.append("case")
        elif self.cases and self.cases[-1] == "selector" and word == "in" and len(words) >= 2:
            self.cases[-1] = "pattern"
        elif not words and self.cases and word == "esac":
            self.cases.pop()
            self.syntax.append("esac")
        return False

    def _pattern_alternative(self) -> bool:
        if self.cases and self.cases[-1] == "pattern" and self._at() == "|":
            self.pos += 1
            return True
        return False

    def _parenthesis(self, words: list[str], found: list[_Segment]) -> bool:
        """A subshell's `(` or `)`, consumed and counted on its segment (DRC-4724).

        Only a `(` at command position opens one: `f()` and `a=(1 2)` open
        nothing, and a `)` that matches no `(`, such as a `case` arm's,
        closes nothing.
        """
        char = self._at()
        if char in "()" and char and self.cases and self.cases[-1] == "pattern":
            if char == ")":
                self.cases[-1] = "body"
                # A pattern's close starts its command, not the enclosing
                # subshell's end. Retain the selector as a separate opaque
                # part so it cannot establish that an arm's check ran.
                found.append(self._segment(list(words), ";"))
                words.clear()
                self.redirects, self.bodies, self.syntax, self.outer = [], [], [], []
                self.syntax.append("case-arm")
                self.opens = self.closes = 0
                self.group = None
            self.pos += 1
            return True
        if char == "(":
            prefix = words not in ([], ["time"], ["time", "-p"])
            self.parens.append(None if prefix or self.redirects else len(found))
            self.opens += self.parens[-1] is not None
        elif char == ")":
            opened = self.parens.pop() if self.parens else None
            if opened is not None:
                if words or self.redirects or self.bodies or self.syntax:
                    self.closes += 1
                    self.group = opened
                elif self.opens:
                    self.opens -= 1  # `( )`: nothing ran inside it
                elif found:
                    # `(pytest; )`: the close follows the joiner.
                    found[-1] = found[-1]._replace(closes=found[-1].closes + 1)
        else:
            return False
        self.pos += 1
        return True

    def _skip_space(self) -> bool:
        """Blanks, a backslash-newline, a lone backslash at the very end (bash
        passes no argument for it), and a comment at a word start."""
        char, after = self._at(), self._at(1)
        if char in (" ", "\t") or (char == "\\" and after in ("\n", "")):
            self.pos += 2 if char == "\\" else 1
        elif char == "#":
            end = self.text.find("\n", self.pos)
            self.pos = len(self.text) if end == -1 else end
        else:
            return False
        return True

    def _joiner(self) -> str | None:
        """`&&`, `||`, `;`, `|`, a newline or a background `&`, consumed; None
        when the next thing is a word. `&>` is a redirect, and `|&` pipes."""
        char, after = self._at(), self._at(1)
        if char == "\n":
            self.pos += 1
            return "\n"
        if char == ";":
            # `;;` and `;&` end a case arm; they join like `;`.
            if after in (";", "&") and self.cases:
                self.cases[-1] = "pattern"
            self.pos += 1
            while self._at() and self._at() in ";&":
                self.pos += 1
            return ";"
        if char == "|":
            self.pos += 2 if after in ("|", "&") else 1
            return "||" if after == "|" else "|"
        if char == "&" and after != ">":
            self.pos += 2 if after == "&" else 1
            return "&&" if after == "&" else "&"
        return None

    def _skip_blanks(self) -> None:
        while self._at() in (" ", "\t") and self._at():
            self.pos += 1

    def _target(self, *, literal: bool = False) -> str:
        """The word a redirection or heredoc operator takes; a missing one is a
        syntax error."""
        self._skip_blanks()
        substitution = self._at() in ("<", ">") and self._at(1) == "("
        if self._at() in ("", "\n", ";", "|", "&", "(", ")", "<", ">") and not substitution:
            raise _Unbalanced
        previous, self.literal = self.literal, literal
        try:
            return self._word()
        finally:
            self.literal = previous

    def _redirection(self) -> _Redirect | None:
        """A redirection with its optional descriptor and its target, consumed
        and returned as one token (`2>&1`, `>out`, `<<EOF`, `<<<…`); None when
        the next thing is a word. A descriptor counts only as a whole word:
        `a2>f` is the word `a2` and the redirection `>f`."""
        match = _REDIRECTION_RE.match(self.text, self.pos)
        if match is None or self._process_substitution(match):
            return None
        operator = match.group()
        self.pos = match.end()
        if operator.endswith("<<<"):
            self._target()  # stdin data: never published, though it is still read
            return _Redirect(operator, "…", match.group("op"))
        if operator.endswith(("<<", "<<-")):
            pending = self._heredoc_target(operator.endswith("-"))
            self.heredocs.append(pending)
            return _Redirect(operator, pending.delimiter, match.group("op"))
        return _Redirect(operator, self._target(), match.group("op"))

    def _process_substitution(self, match: re.Match[str]) -> bool:
        """`<(…)` and `>(…)` are words, not redirections."""
        bare = match.group("op") in ("<", ">")
        return bare and self.text[match.end() : match.end() + 1] == "("

    def _heredoc_target(self, strip: bool) -> _Heredoc:
        self._skip_blanks()
        start = self.pos
        delimiter = self._target(literal=True)
        raw = self.text[start : self.pos].replace("\\\n", "")
        return _Heredoc(delimiter, strip, not any(c in raw for c in "'\"\\"), self.bodies)

    def _heredoc(self, pending: list[_Heredoc]) -> None:
        """A heredoc operator inside a substitution, and its delimiter word."""
        self.pos += 2
        strip = self._at() == "-"
        self.pos += strip
        pending.append(self._heredoc_target(strip))

    def _skip_bodies(self, pending: list[_Heredoc], *, nested: bool = False) -> None:
        """Each pending heredoc body in order, a line equal to its delimiter
        closing it; an unclosed one runs to the end, as bash reads it."""
        for here in pending:
            body: list[str] = []
            while self.pos < len(self.text):
                line = self._heredoc_line()
                physical = [line]
                logical = line.lstrip("\t") if here.strip else line
                # Unquoted backslash-newline removal precedes delimiter
                # matching; an escaped backslash keeps the physical newline.
                while (
                    here.expand
                    and (len(logical) - len(logical.rstrip("\\"))) % 2
                    and self.pos < len(self.text)
                ):
                    line = self._heredoc_line()
                    physical.append(line)
                    logical = logical[:-1] + (line.lstrip("\t") if here.strip else line)
                if logical == here.delimiter:
                    break
                body.extend(physical)
            if here.expand:
                expanded = self._heredoc_expansions("\n".join(body))
                if not nested:
                    here.bodies.extend(expanded)

    def _heredoc_line(self) -> str:
        end = self.text.find("\n", self.pos)
        line = self.text[self.pos : len(self.text) if end == -1 else end]
        self.pos = len(self.text) if end == -1 else end + 1
        return line

    def _word(self) -> str:
        out: list[str] = []
        # The word with every quoted or expanded part blanked, for the one
        # rule that reads unquoted text alone: brace expansion.
        bare: list[str] = []
        start = self.pos
        while self.pos < len(self.text):
            char, after = self._at(), self._at(1)
            if char in " \t\n;()|&" or (char in "<>" and after != "("):
                break
            part = self._expansion(char, after)
            if part is None:
                part = char
                self.pos += 1
                bare.append(char)
            else:
                bare.append("_")
            out.append(part)
        if self.pos == start:
            self.pos += 1
        if not self.literal and _BRACE_EXPANSION_RE.search("".join(bare)):
            # `{--password=,x}value` becomes `--password=value` and `xvalue`,
            # and `AKIA{…,}` a whole key: the words are unknown, so withheld.
            return _WITHHELD
        return "".join(out)

    def _expansion(self, char: str, after: str) -> str | None:
        """A quoted, escaped or substituted part of a word, decoded and
        consumed; None for a plain character."""
        if char == "\\":
            self.pos += 2
            return after if after != "\n" else ""
        if char == "'" or (char == "$" and after == "'"):
            return self._single_quoted(ansi=char == "$")
        if char == '"' or (char == "$" and after == '"'):
            self.pos += 1 if char == '"' else 2
            return self._double_quoted()
        if not self.literal and char == "$" and after == "{":
            return self._braced()
        if not self.literal and ((char in "$<>" and after == "(") or char == "`"):
            return self._substitution()
        return None

    def _single_quoted(self, *, ansi: bool) -> str:
        if ansi:
            self.pos += 2
            return self._ansi_c()
        end = self.text.find("'", self.pos + 1)
        if end == -1:
            raise _Unbalanced
        part, self.pos = self.text[self.pos + 1 : end], end + 1
        return part

    def _substitution(self) -> str:
        """`$(…)`, `$((…))`, `<(…)`, `>(…)` or a backtick run, from its opening
        mark: its body is kept for reading, and the word shows `$(…)`."""
        if self._at() == "`":
            self.pos += 1
            start = self.pos
            self._skip_backticks()
            body = re.sub(r"\\([\\`$])", r"\1", self.text[start : self.pos - 1])
            self.bodies.append(body)
            return _SUBSTITUTED
        arithmetic = self.text.startswith("$((", self.pos)
        self.pos += 2
        start = self.pos
        # The containing body is parsed below. Collecting its nested bodies
        # here as well makes later effect/masking reads grow exponentially.
        previous, self.bodies = self.bodies, []
        try:
            self._skip_group(arithmetic=arithmetic)
            nested = self.bodies
        finally:
            self.bodies = previous
        body = self.text[start : self.pos - 1]
        if not arithmetic:
            self.bodies.append(body)
            return _SUBSTITUTED
        # Arithmetic effects stay unknown, while its actual executable
        # substitutions still supply private named values to tail masking.
        self.bodies.extend(nested)
        if "$(" in body or "`" in body:
            self.bodies.append(_UNREAD_BODY)
        return _ARITHMETIC

    def _double_quoted(self) -> str:
        out: list[str] = []
        while True:
            char, after = self._at(), self._at(1)
            if not char:
                raise _Unbalanced
            if char == '"':
                self.pos += 1
                return "".join(out)
            if char == "\\" and after in ('"', "\\", "$", "`", "\n"):
                out.append("" if after == "\n" else after)
                self.pos += 2
            elif not self.literal and char == "$" and after == "{":
                out.append(self._braced())
            elif not self.literal and ((char == "$" and after == "(") or char == "`"):
                out.append(self._substitution())
            else:
                out.append(char)
                self.pos += 1

    def _ansi_c(self) -> str:
        """A `$'…'` string decoded with bash's escapes, so `\\x41KIA…` reaches
        shape redaction as the key it is. A decoded NUL ends the string, as it
        ends the C string the program receives."""
        out: list[str] = []
        ended = False
        while True:
            char = self._at()
            if not char:
                raise _Unbalanced
            if char == "'":
                self.pos += 1
                return "".join(out)
            if char == "\\":
                piece = self._ansi_escape()
            else:
                piece = char
                self.pos += 1
            ended = ended or piece == "\x00"
            if not ended:
                out.append(piece)

    def _ansi_escape(self) -> str:
        after = self._at(1)
        if not after:
            raise _Unbalanced
        if after in _ANSI_C_ESCAPES:
            self.pos += 2
            return _ANSI_C_ESCAPES[after]
        if after in _ANSI_C_WIDTHS:
            digits = self._run(self.pos + 2, _HEX_DIGITS, _ANSI_C_WIDTHS[after])
            self.pos += 2 + len(digits)
            if not digits:
                return "\\" + after
            code = int(digits, 16)
            return chr(code) if code <= 0x10FFFF and not 0xD800 <= code <= 0xDFFF else ""
        if after in _OCTAL_DIGITS:
            digits = self._run(self.pos + 1, _OCTAL_DIGITS, 3)
            self.pos += 1 + len(digits)
            return chr(int(digits, 8) & 0xFF)
        if after == "c" and self._at(2):
            self.pos += 3
            return chr(ord(self.text[self.pos - 1]) & 0x1F)
        self.pos += 2
        return "\\" + after

    def _run(self, start: int, allowed: frozenset[str], width: int) -> str:
        end = start
        while end < len(self.text) and end - start < width and self.text[end] in allowed:
            end += 1
        return self.text[start:end]

    def _nest(self) -> None:
        # Measured: 400 nested `"$(` overflowed Python's stack at four frames a
        # level. Deeper than any command a person or an agent writes.
        self.depth += 1
        if self.depth > _NESTING_CAP:
            raise _Unbalanced

    def _braced(self) -> str:
        """`${…}`, kept as written, read atomically: a quoted `}` or a `)` in it
        closes nothing, and a substitution in it is still read."""
        self._nest()
        start, depth = self.pos, 1
        self.pos += 2
        while depth:
            char, after = self._at(), self._at(1)
            if not char:
                raise _Unbalanced
            if (char == "$" and after == "(") or char == "`":
                self._substitution()
            elif char == "$" and after == "{":
                self._braced()
            elif not self._skip_quoted(char):
                depth += {"{": 1, "}": -1}.get(char, 0)
                self.pos += 1
        self.depth -= 1
        return self.text[start : self.pos]

    def _skip_backticks(self) -> None:
        while True:
            char = self._at()
            if not char:
                raise _Unbalanced
            self.pos += 2 if char == "\\" else 1
            if char == "`":
                return

    def _skip_group(self, *, arithmetic: bool = False) -> None:
        """A `$(…)`, `<(…)`, `>(…)` or arithmetic body, to its matching
        parenthesis, with quotes, parameter expansions, comments, heredocs and
        `case` patterns read as the shell reads them: a commit message written
        through `$(cat <<'EOF' … EOF)` holds apostrophes, and a `case` arm's
        `)` closes nothing."""
        self._nest()
        depth, previous, cases = 1, "(", 0
        pending: list[_Heredoc] = []
        while depth:
            char, after = self._at(), self._at(1)
            if not char:
                raise _Unbalanced
            if char == "$" and after == "{":
                self._braced()
            elif arithmetic and ((char == "$" and after == "(") or char == "`"):
                self._substitution()
            # Arithmetic executes nested commands between single quote
            # characters before rejecting the resulting expression.
            elif (not arithmetic or char != "'") and self._skip_quoted(char):
                pass
            elif arithmetic:
                depth += {"(": 1, ")": -1}.get(char, 0)
                self.pos += 1
            elif previous in _COMMAND_STARTS and (word := _CASE_WORD_RE.match(self.text, self.pos)):
                cases += 1 if word.group() == "case" else -min(cases, 1)
                self.pos = word.end()
            else:
                self._skip_group_char(char, after, previous, pending)
                if char in "()" and not cases:
                    depth += 1 if char == "(" else -1
            previous = char
        self.depth -= 1

    def _skip_group_char(
        self, char: str, after: str, previous: str, pending: list[_Heredoc]
    ) -> None:
        if char == "#" and previous in _COMMAND_STARTS:
            end = self.text.find("\n", self.pos)
            self.pos = len(self.text) if end == -1 else end
        elif self.text.startswith("<<<", self.pos):
            self.pos += 3
        elif char == "<" and after == "<":
            self._heredoc(pending)
        elif char == "\n":
            self.pos += 1
            self._skip_bodies(pending, nested=True)
            pending.clear()
        else:
            self.pos += 1

    def _heredoc_expansions(self, body: str) -> list[str]:
        """Only substitutions execute here; quotes and literal lines are data.

        Retain the depth bound across a heredoc inside a substitution. The
        containing substitution is read later on its own, so nested bodies
        validate here without also being added to its parent's effect list.
        """
        logical = re.sub(r"(?<!\\)((?:\\\\)*)\\\n", r"\1", body)
        lexer = _ShellLexer(logical)
        lexer.depth = self.depth
        while lexer.pos < len(lexer.text):
            char, after = lexer._at(), lexer._at(1)
            if char == "\\" and after in ("$", "`", "\\"):
                lexer.pos += 2
            elif (char == "$" and after == "(") or char == "`":
                lexer._substitution()
            else:
                lexer.pos += 1
        return lexer.bodies

    def _skip_quoted(self, char: str) -> bool:
        """An escape, a quoted string or a backtick run inside a group, skipped."""
        if char == "\\":
            self.pos += 2
        elif char == "'":
            end = self.text.find("'", self.pos + 1)
            if end == -1:
                raise _Unbalanced
            self.pos = end + 1
        elif char == '"':
            self.pos += 1
            self._double_quoted()
        elif char == "`":
            self.pos += 1
            self._skip_backticks()
        else:
            return False
        return True


def _backgrounds(joiners: list[str]) -> list[bool]:
    """`&` sends the whole and-or list before it to the background, back to the
    previous `;`, newline or `&` (verifier, 2026-09-24)."""
    found, ended = [], False
    for joiner in reversed(joiners):
        if joiner in ("", ";", "\n", "&"):
            ended = joiner == "&"
        found.append(ended)
    return found[::-1]


def _shell_wrapper_line(words: list[str]) -> tuple[str, int] | None:
    """The command string of `bash -c '…'`, `sh -c`, `zsh -c` or `bash -lc`
    under the closed option set, and its word index; otherwise None. Words
    after it are `$0` and positional arguments, neither matched nor published."""
    if not words or os.path.basename(words[0]) not in _SHELLS:
        return None
    rest = words[1:]
    while rest:
        if rest[0] in _SHELL_LONG_OPTIONS:
            rest = rest[1:]
        elif rest[:2] == ["-o", "pipefail"]:
            rest = rest[2:]
        elif _SHELL_FLAGS_RE.match(rest[0]):
            if "c" in rest[0]:
                return (rest[1], len(words) - len(rest) + 1) if len(rest) > 1 else None
            rest = rest[1:]
        else:
            return None
    return None


class _Part(NamedTuple):
    """One segment of a call after wrappers are spliced: what every rule reads."""

    words: list[str]
    rtk: bool
    joiner: str
    redirects: list[_Redirect]
    # A substitution in it runs something that is not read-only.
    hides_change: bool
    background: bool
    # Background launches this part ends: its own `&`, and an inner one a
    # wrapper's splice would otherwise overwrite.
    launches: int
    # Subshells and wrappers entered at this part and left after it: a `cd`
    # inside either does not carry past it (DRC-4724).
    opens: int
    closes: int
    # A group's or a wrapper's own redirections, each with the index of the
    # part whose starting directory the outer shell opens it in (review W3).
    # They are in `redirects` as well, for every other rule.
    outer: tuple[tuple[_Redirect, int], ...] = ()
    # The segment's words before any stripping, assignments included, and a
    # wrapper's own words on its first inner part: what masking may hide.
    raw: tuple[str, ...] = ()
    syntax: tuple[str, ...] = ()
    # Named values in executed substitutions can be echoed into the same tail.
    hidden_values: tuple[str, ...] = ()


def _body_facts(body: str) -> tuple[bool, tuple[str, ...]]:
    """A substitution's effects and masked values, under the same segment rules.

    The text stays private: only its named values reach the call's tail scrub.
    """
    if body == _UNREAD_BODY:
        return False, ()
    try:
        parts = _call_parts(body)
    except _Unbalanced:
        return False, ()
    reads = all(
        not part.hides_change
        and not _writes_a_file(part.redirects)
        and (
            not part.words
            or part.words[0] == "cd"
            or (not _is_check(part.words) and _reads_only(part.redirects, part.words))
        )
        for part in parts
    )
    masked = tuple(
        value
        for part in parts
        for value in (*records.masked_values(list(part.raw)), *part.hidden_values)
    )
    return reads, masked


def _call_parts(text: str, depth: int = 0) -> list[_Part]:
    """The call's segments, each shell `-c` wrapper replaced by its inner
    segments (owner, 2026-09-25).

    Splice, not wrap: the last inner segment takes the wrapper's joiner, so
    every existing attribution rule applies unchanged and only ever withholds.
    Background is decided per level before splicing, since an inner `;` must
    not end an outer list that `&` sent to the background. The wrapper's own
    redirections apply to every inner segment, since they redirect the shell.
    """
    segments = _ShellLexer(text).segments()
    parts: list[_Part] = []
    first_part: list[int] = []
    for segment, background in zip(
        segments, _backgrounds([s.joiner for s in segments]), strict=True
    ):
        first_part.append(len(parts))
        outer = tuple((redirect, first_part[at]) for redirect, at in segment.outer)
        words, rtk = _stripped(segment.words)
        bodies = [_body_facts(body) for body in segment.bodies]
        hides = not all(reads for reads, _values in bodies)
        hidden_values = tuple(value for _reads, values in bodies for value in values)
        inner = _shell_wrapper_line(words) if depth < _SHELL_WRAPPER_DEPTH else None
        try:
            spliced = _call_parts(inner[0], depth + 1) if inner is not None else []
        except _Unbalanced:
            # The inner shell fails and the rest of the call runs: only this
            # segment is unread, and it stays a change (review, 2026-09-27).
            spliced = []
        launches = int(segment.joiner == "&")
        if not spliced:
            parts.append(
                _Part(words, rtk, segment.joiner, segment.redirects, hides, background,
                      launches, segment.opens, segment.closes, outer, tuple(segment.words),
                      segment.syntax, hidden_values)
            )  # fmt: skip
            continue
        last, offset = len(spliced) - 1, len(parts)
        # The wrapper's own redirections open where the wrapper started.
        wrapper = tuple((r, offset) for r in _without(segment.redirects, segment.outer))
        # Its script is parsed into inner words below. Treating that entire
        # script as one assignment also masks ordinary runner/summary words.
        script = len(segment.words) - len(words) + inner[1] if inner else 0
        outer_words = [*segment.words[:script], *segment.words[script + 1 :]]
        parts.extend(
            part._replace(
                outer=(*((r, at + offset) for r, at in part.outer), *outer, *wrapper),
                raw=(*outer_words, *part.raw) if index == 0 else part.raw,
                hidden_values=(*hidden_values, *part.hidden_values)
                if index == 0
                else part.hidden_values,
                syntax=(*segment.syntax, *part.syntax) if index == 0 else part.syntax,
                rtk=part.rtk or rtk,
                joiner=segment.joiner if index == last else part.joiner,
                redirects=[*part.redirects, *segment.redirects],
                hides_change=part.hides_change or hides,
                background=part.background or background,
                launches=part.launches + (launches if index == last else 0),
                opens=part.opens + (index == 0) * (1 + segment.opens),
                closes=part.closes + (index == last) * (1 + segment.closes),
            )
            for index, part in enumerate(spliced)
        )
    return parts


def _without(redirects: list[_Redirect], outer: Iterable[tuple[_Redirect, int]]) -> list[_Redirect]:
    """`redirects` with one occurrence of each outer redirection taken out."""
    left = list(redirects)
    for redirect, _at in outer:
        left.remove(redirect)
    return left


def _names_a_test_file(word: str) -> bool:
    """`test` or `tests` as a whole word of a file name, split on `_`, `-` and `.`.

    Owner, 2026-09-24: `run_tests.py` and `test.sh` count, and `runtests.py` and
    `fetch_latest_creds.py` do not.
    """
    name = os.path.basename(word).lower()
    return bool(set(re.split(r"[_.-]", name)) & {"test", "tests"}) and ("/" in word or "." in name)


def _runner_words(words: list[str]) -> list[str]:
    """The words with an interpreter or runner path shed to its name."""
    name = os.path.basename(words[0])
    if "/" in words[0] and (
        _PYTHON_RE.match(name) or name in _INTERPRETERS or name in _CHECK_WORDS
    ):
        return [name, *words[1:]]
    return words


def _is_named_runner(words: list[str]) -> bool:
    if _PYTHON_RE.match(words[0]):
        return words[1:3] in (["-m", "pytest"], ["-m", "unittest"])
    if (
        words[0] in _CHECK_WORDS
        or tuple(words[:2]) in _CHECK_PAIRS
        or tuple(words[:3]) in _CHECK_TRIPLES
    ):
        return True
    flagged = tuple(words[:1]) in _CHECK_FLAGGED or tuple(words[:2]) in _CHECK_FLAGGED
    return flagged and "--check" in words


def _is_test_program(words: list[str]) -> bool:
    """A program file whose name has `test` or `tests` as a word, run directly or
    by an interpreter; and `node --test`."""
    first = words[0]
    if first == "node" and "--test" in words:
        return True
    if _PYTHON_RE.match(first) or first in _INTERPRETERS:
        return len(words) > 1 and not words[1].startswith("-") and _names_a_test_file(words[1])
    return _names_a_test_file(first)


def _is_check(words: list[str]) -> bool:
    """Whether a stripped segment's runner is on the ruling's closed list."""
    if not words or words[0] in _SHELL_BUILTINS:
        return False
    words = _runner_words(words)
    return _is_named_runner(words) or _is_test_program(words)


def _harmless_redirect(redirect: _Redirect) -> bool:
    if redirect.kind == ">&" and (redirect.target.isdigit() or redirect.target == "-"):
        return True
    return redirect.kind in _WRITE_OPERATORS and bool(
        _HARMLESS_DEVICE_RE.fullmatch(redirect.target)
    )


def _writes_a_file(redirects: list[_Redirect]) -> bool:
    """A `>` into anything but `/dev/null` or another descriptor."""
    return any(r.kind in _WRITE_OPERATORS and not _harmless_redirect(r) for r in redirects)


def _file_targets(redirects: list[_Redirect]) -> list[str]:
    """The target word of each redirection into a file, as written.

    `>&-` and `>&2` name a descriptor, not a file.
    """
    return [r.target for r in redirects if r.kind in _WRITE_OPERATORS and not _harmless_redirect(r)]


def _placeable(target: str) -> bool:
    """Whether a redirection's target is a path as written: an expansion, a
    substitution, `~` or a withheld word is decided by the shell at run time."""
    return (
        bool(target)
        and not target.startswith("~")
        and not any(mark in target for mark in ("$", "`", _WITHHELD))
    )


def _reads_only(redirects: list[_Redirect], words: list[str]) -> bool:
    """Whether one segment is on the closed read-only list.

    A redirect into a file writes something the list does not name (review,
    2026-09-24); a substitution is read on its own, by `_body_facts`.
    """
    if _writes_a_file(redirects):
        return False
    if words[0] == "date":
        # Both GNU and BSD accept a positional clock-setting operand. Keep
        # the portable display forms closed rather than just excluding -s.
        args = [w for w in words[1:] if w not in {"-u", "--utc", "--universal"}]
        return not args or (len(args) == 1 and args[0].startswith("+"))
    if words[:2] == ["gh", "api"]:
        return _gh_api_reads_only(words[2:])
    writing = _WRITING_OPTIONS.get(words[0]) or _WRITING_OPTIONS.get(" ".join(words[:2]))
    if writing and writing & {w.split("=", 1)[0] for w in words[1:]}:
        return False
    return " ".join(words[:2]) in _READ_ONLY_PAIRS or words[0] in _READ_ONLY_WORDS


def _gh_api_reads_only(args: list[str]) -> bool:
    """A REST GET without body/field flags, headers, caching or unknown options.

    gh changes its default method to POST when fields are supplied. Cache
    writes locally; a header may override the HTTP method at the endpoint.
    """
    value_options = {"-X", "--method", "-q", "--jq", "-t", "--template", "--hostname"}
    boolean_options = {
        "--paginate",
        "--slurp",
        "--silent",
        "--include",
        "-i",
        "--verbose",
        "--allow-escape-sequences",
    }
    endpoints: list[str] = []
    index = 0
    while index < len(args):
        word = args[index]
        index += 1
        option, sep, value = word.partition("=")
        if not sep and word[:2] in {"-X", "-q", "-t"} and len(word) > 2:
            option, value = word[:2], word[2:]
        if option in value_options:
            if not value:
                if index == len(args):
                    return False
                value = args[index]
                index += 1
            if option in {"-X", "--method"} and value != "GET":
                return False
        elif word in boolean_options:
            continue
        elif word.startswith("-"):
            return False
        else:
            endpoints.append(word)
    return len(endpoints) == 1 and endpoints[0].lstrip("/") != "graphql"


def _evidence_at(run: dict[str, Any]) -> float:
    """A run's result time, or its call time where no result arrived."""
    result_at = run.get("result_at")
    return float(result_at if result_at is not None else run["at"])


def _changed_directory(current: str, known: bool, args: list[str]) -> tuple[str, bool]:
    """Where a `cd` with these arguments leaves the shell, and whether that is
    known as a path. `-L`, `-P`, `-e`, `-@` and `--` are options."""
    while args and _CD_OPTION_RE.match(args[0]):
        args = args[1:]
    if args[:1] == ["--"]:
        args = args[1:]
    if not args or args[0] == "-":
        return current, False
    target = os.path.normpath(os.path.join(current or "/", args[0]))
    if args[0].startswith("-") or not _placeable(args[0]):
        return target, False
    return target, known or os.path.isabs(args[0])


def _conditional_directory(
    state: tuple[str, bool, bool], conditions: list[tuple[str, bool, bool]], syntax: tuple[str, ...]
) -> tuple[str, bool, bool]:
    current, known, cdpath = state
    for word in syntax:
        if word in {"if", "case"}:
            conditions.append((current, known, cdpath))
            known = False
        elif word in {"else", "elif", "case-arm"} and conditions:
            current, _known, cdpath = conditions[-1]
            known = False
        elif word in {"fi", "esac"} and conditions:
            conditions.pop()
            known = False
    return current, known, cdpath


def _pipe_filter(part: _Part) -> bool:
    """Only stdin transforms: file operands or an input redirect can print
    an unrelated check summary even though the command is read-only."""
    if any("<" in redirect.kind for redirect in part.redirects) or not part.words:
        return False
    command, *args = part.words
    if command in {"tail", "head"}:
        return (
            re.fullmatch(
                r"(?:(?:-\d+|-[nc](?:\s+)?\d+|--(?:lines|bytes)(?:=|\s+)\d+)\s*)*(?:-)?",
                " ".join(args),
            )
            is not None
        )
    if command != "grep":
        return False
    while args and re.fullmatch(r"-[EFGivwxonqschHab]+|--line-buffered|--color=\w+", args[0]):
        args = args[1:]
    if args[:1] == ["--"]:
        args = args[1:]
    return len(args) == 1 or (len(args) == 2 and args[1] == "-")


def _check_identity(directory: str, words: list[str], *, unplaced: str = "") -> str:
    """Item 4's "same check": the directory it ran in and its stripped segment,
    without redirects (review, 2026-09-24: the directory is part of it)."""
    identity = directory + "\0" + " ".join(word for word in words if not _REDIRECT_RE.match(word))
    # Unknown placement must not erase a failure at a known path, or claim
    # a later unknown run was the same check (DRC-4727/4728).
    return identity + "\0unplaced\0" + unplaced if unplaced else identity


def _check_coverage(
    directory: str, words: list[str], worker: str, raw: tuple[str, ...]
) -> dict[str, Any] | None:
    """Closed explicit Python selectors, hashed before any replay checkpoint.

    Only a matching interpreter, runner, directory and worker may cover a
    narrower selector. Filtering options and implicit discovery prove nothing.
    """
    if not directory or len(words) < 4 or words[1] != "-m":
        return None
    runner = words[2]
    original = next((i for i in range(len(raw) - 1) if raw[i : i + 2] == ("-m", runner)), None)
    if original is None:
        return None
    execution = "\0".join(raw[: original + 2])
    if not _PYTHON_RE.fullmatch(words[0]) or runner not in {"unittest", "pytest"}:
        return None
    selectors = [word for word in words[3:] if word not in {"-v", "-q", "--verbose", "--quiet"}]
    if not selectors or any(word.startswith("-") for word in selectors):
        return None
    pattern = (
        r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*"
        if runner == "unittest"
        else (r"(?:[\w.-]+/)*[\w.-]+\.py(?:::[A-Za-z_]\w*)*")
    )
    if any(re.fullmatch(pattern, word) is None for word in selectors):
        return None

    def digest(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8", "replace")).hexdigest()

    ancestors = []
    for word in selectors:
        segments = word.split("." if runner == "unittest" else "::")
        joiner = "." if runner == "unittest" else "::"
        ancestors.append(
            tuple(digest(joiner.join(segments[:k])) for k in range(1, len(segments) + 1))
        )
    return {
        "scope": digest(f"{directory}\0{execution}\0{worker}"),
        "selectors": tuple(digest(word) for word in selectors),
        "ancestors": tuple(ancestors),
    }


def _covers_check(passed: dict[str, Any], failed: dict[str, Any]) -> bool:
    cover, old = passed.get("coverage"), failed.get("coverage")
    return bool(
        isinstance(cover, dict)
        and isinstance(old, dict)
        and cover["scope"] == old["scope"]
        and _evidence_at(passed) > _evidence_at(failed)
        and all(set(cover["selectors"]) & set(ancestors) for ancestors in old["ancestors"])
    )


class _Result(NamedTuple):
    """A call's `tool_result` block, and the time of the record that holds it."""

    block: dict[str, Any]
    at: float | None


def _tool_result_blocks(
    transcript: list[dict[str, Any]], *, sidechain: bool = False
) -> dict[str, _Result]:
    """Each call's result, by call id. `sidechain` reads a subagent's own
    transcript, where every record is one; a parent's reads none of them."""
    results: dict[str, _Result] = {}
    for record in transcript:
        if record.get("type") != "user" or (record.get("isSidechain") is True) is not sidechain:
            continue
        content = records.message_dict(record).get("content")
        at = _record_timestamp(record)
        for block in content if isinstance(content, list) else ():
            if isinstance(block, dict) and block.get("type") == "tool_result":
                call_id = block.get("tool_use_id")
                if isinstance(call_id, str) and call_id:
                    results[call_id] = _Result(block, at)
    return results


def _claude_tool_uses(
    transcript: list[dict[str, Any]], *, sidechain: bool = False
) -> Iterator[tuple[float, str, str, str, dict[str, Any], str]]:
    """`(at, cwd, call id, tool name, input, worker)` for one transcript's own
    calls: the root session's, or with `sidechain` a subagent's, whose worker
    is `SUBAGENT_WORKER`. A sidechain record inside a parent's own file is
    read by neither (none in 300 parent transcripts measured, 2026-09-28)."""
    worker = SUBAGENT_WORKER if sidechain else ""
    for record in transcript:
        if (
            record.get("type") != "assistant"
            or (record.get("isSidechain") is True) is not sidechain
        ):
            continue
        content = records.message_dict(record).get("content")
        at = _record_timestamp(record)
        if not isinstance(content, list) or at is None:
            continue
        cwd = record.get("cwd")
        for block in content:
            if not isinstance(block, dict) or block.get("type") != "tool_use":
                continue
            call_id, name, tool_input = block.get("id"), block.get("name"), block.get("input")
            if isinstance(call_id, str) and isinstance(name, str) and isinstance(tool_input, dict):
                yield at, cwd if isinstance(cwd, str) else "", call_id, name, tool_input, worker


def _tool_result_text(block: dict[str, Any]) -> str:
    content = block.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            str(part.get("text"))
            for part in content
            if isinstance(part, dict) and isinstance(part.get("text"), str)
        )
    return ""


def _ran_nothing(tail: str) -> bool:
    return bool(_RAN_NOTHING.search(tail)) or (
        bool(_NO_TEST_FILES.search(tail)) and not _GO_OK.search(tail)
    )


def _tail_result(tail: str) -> tuple[str, str] | None:
    """Sources (ii) and (iii), failure first; a pass needs no failure beside it."""
    if _SUMMARY_FAILED.search(tail):
        return "failed", "summary"
    if _FAILURE_MARKER.search(tail):
        return "failed", "marker"
    if _SUMMARY_PASSED.search(tail) and not _ran_nothing(tail):
        return "passed", "summary"
    return None


def _flag_result(flag: object, *, last: bool, all_and: bool, alone: bool) -> str:
    """What the call's error flag says about one check in it (review and
    verifier, 2026-09-24).

    The flag is the whole call's status. A pass through `&&` alone passes every
    check, and a pass otherwise speaks for the last segment. A failure speaks
    only for a call of one segment, after `cd`, assignments and wrappers are
    stripped, since any other stage may be the one that failed.
    """
    if not isinstance(flag, bool):
        return ""
    if flag:
        return "failed" if alone else ""
    return "passed" if last or all_and else ""


def _check_line(words: list[str]) -> str:
    """The runner form and the rest of its own segment, masked, redacted, clipped.

    Its own segment only, never the rest of the shell line (owner, 2026-09-24).
    Each word is masked before the words are joined and re-quoted.
    """
    masked = records.mask_words(words)
    line = " ".join(shlex.quote(word) if re.search(r"\s", word) else word for word in masked)
    bounded = records.redact_clip(line, TOOL_REPORT_LINE_CHARS)
    return records.safe_text(bounded, len(bounded))


def _scrubbed_tail(text: str, values: Iterable[str]) -> str:
    """The output tail with every value the call masked removed first:
    an echoed command repeats it, and the tail reaches the prompt row
    (review, 2026-09-27). Redaction then runs over the whole window, and the
    cut comes last (item 5)."""
    # Filename/path characters stay inside the word. A password `test` must
    # not change `test_a.py`, `test-file.py` or `src/test` into a redacted name.
    boundary = r"[\w./:@+\-]"
    spellings = {
        spelling
        for value in values
        for piece in (value, *value.split())
        if len(piece) >= _SCRUB_MIN_CHARS
        for spelling in (
            piece,
            shlex.quote(piece),
            "'" + piece.replace("'", "'\\''") + "'",
            piece.replace("'", "'\\''"),
            piece.replace("'", "'\"'\"'"),
        )
    }
    for spelling in sorted(spellings, key=len, reverse=True):
        text = re.sub(
            rf"(?<!{boundary}){re.escape(spelling)}(?!{boundary})", records.SECRET_MARKER, text
        )
        text = re.sub(
            rf"(?<!{boundary})(-[pP]){re.escape(spelling)}(?!{boundary})",
            lambda match: match[1] + records.SECRET_MARKER,
            text,
        )
        text = re.sub(
            rf"((?:[A-Za-z][A-Za-z0-9+.-]*://)?[^\s:/@'\"]+:){re.escape(spelling)}(@)",
            lambda match: match[1] + records.SECRET_MARKER + match[2],
            text,
        )
    return records.redact_secrets(text)[-TOOL_REPORT_TAIL_CHARS:]


def _written_path(raw: object, cwd: str, session_dir: str = "") -> str | None:
    """A written path relative to the session's directory, or None outside it.

    A relative `raw` is placed where the tool ran it, the record's own `cwd`;
    the result is read from the directory the session began in, because a `cd`
    moves every later record's `cwd` and the documented path is the session's
    ([DEC-23](docs/design-reading-a-session.md#dec-23-a-claude-code-sessions-record-of-its-checks-may-show-the-work)
    item 5, DRC-4884). Reading it from `cwd` published a bare filename for a
    session that had changed folder, and gave two subagents' `src/main.py` one
    identity (DRC-4755). Without a session directory it reads from `cwd`.
    """
    base = os.path.normpath(session_dir or cwd) if session_dir or cwd else ""
    if (
        not isinstance(raw, str)
        or not raw.strip()
        or not base
        or (not os.path.isabs(raw) and not cwd)
    ):
        return None
    target = os.path.normpath(raw if os.path.isabs(raw) else os.path.join(cwd, raw))
    try:
        relative = os.path.relpath(target, base)
    except ValueError:
        return None
    if relative == os.curdir or relative.split(os.sep)[0] == os.pardir:
        return None
    return relative.replace(os.sep, "/")


def _is_fixer(words: list[str]) -> bool:
    """A formatter or fixer run: a change that ages every pass (verifier,
    2026-09-24), whether or not it is also a check."""
    if not words:
        return False
    words = _runner_words(words)
    flags = {word.split("=", 1)[0] for word in words[1:]}
    if _FIX_FLAGS & flags:
        return True
    if words[0] == "black" or words[:2] == ["ruff", "format"]:
        return "--check" not in flags
    return words[0] == "prettier" and "-w" in flags


class _ShellCall:
    """One Bash call, split into segments, with the facts every rule reads."""

    def __init__(
        self, at: float, cwd: str, tool_input: dict[str, Any], *, moved: bool = False
    ) -> None:
        command = tool_input.get("command")
        self.at = at
        self.all_background = tool_input.get("run_in_background") is True or moved
        # Unbalanced quoting is a syntax error, so the call is not run: nothing
        # of it is listed or published, and it still counts as a change, since
        # bash runs the complete lines before it (owner, 2026-09-25).
        self.unbalanced = False
        try:
            self.parts = _call_parts(command if isinstance(command, str) else "")
        except Exception:  # noqa: BLE001 - any parser fault fails closed, as unbalanced does
            self.unbalanced, self.parts = True, []
        self.words: list[tuple[list[str], bool]] = [(p.words, p.rtk) for p in self.parts]
        self.printing_directories: set[int] = set()
        self.directories, self.placed = self._directories(cwd)
        self.meaningful = [
            i for i, (words, _rtk) in enumerate(self.words) if words and words[0] != "cd"
        ]
        self.checks = [i for i in self.meaningful if _is_check(self.words[i][0])]
        # A check's own redirection into a file is a recorded write by the call
        # (DRC-4709), each target read from the directory its segment ran in,
        # or the group's or wrapper's start for their own (review W3).
        self.redirect_writes = [
            (i, target, at)
            for i in self.checks
            for redirects, at in (
                (_without(self.parts[i].redirects, self.parts[i].outer), i),
                *(([r], at) for r, at in self.parts[i].outer),
            )
            for target in _file_targets(redirects)
        ]
        # Every value masking hides anywhere in the call, as the tail scrub
        # reads them (review W1).
        self.masked_values = {
            value
            for part in self.parts
            for value in (*records.masked_values(list(part.raw)), *part.hidden_values)
        }
        self.masked = {
            piece
            for value in self.masked_values
            for piece in (value, *value.split())
            if len(piece) >= _SCRUB_MIN_CHARS
        }
        self.fixers = [i for i in self.meaningful if _is_fixer(self.words[i][0])]
        self.changing_others = [
            i for i in self.meaningful if i not in self.checks and not self._reads_only(i)
        ]
        # A changing substitution runs even in a check's own arguments or an
        # assignment-only segment (review, 2026-09-27; DRC-4724).
        self.substituted = [i for i, part in enumerate(self.parts) if part.hides_change]
        # `> build/output` alone truncates the file: no words, but a write.
        self.substituted += [
            i
            for i, part in enumerate(self.parts)
            if not part.words and _writes_a_file(part.redirects)
        ]

    def _reads_only(self, index: int) -> bool:
        part = self.parts[index]
        return not part.hides_change and _reads_only(part.redirects, part.words)

    def _directories(self, cwd: str) -> tuple[list[str], list[bool]]:
        """The directory each segment runs in, following the call's `cd`s, and
        whether it is known as a path.

        A `cd` the shell resolves at run time (`~`, `$VAR`, a substitution, no
        argument, `-`) and `pushd` or `popd` leave it unknown until a literal
        absolute `cd`, or the close of the group, places it again (review W2).
        The directory string still names the check, as it always did.
        """
        current, known, cdpath = cwd, bool(cwd), False
        found: list[str] = []
        placed: list[bool] = []
        entered: list[tuple[str, bool, bool]] = []
        conditions: list[tuple[str, bool, bool]] = []
        detached: tuple[str, bool, bool] | None = None
        for index, part in enumerate(self.parts):
            if detached is not None and not part.background:
                current, known, cdpath = detached
                detached = None
            if part.background and detached is None:
                detached = current, known, cdpath
            entered.extend([(current, known, cdpath)] * part.opens)
            current, known, cdpath = _conditional_directory(
                (current, known, cdpath), conditions, part.syntax
            )
            found.append(current)
            placed.append(known)
            words = part.words
            assigned = next((word[7:] for word in part.raw if word.startswith("CDPATH=")), None)
            if assigned is not None and (not words or words[:1] == ["export"]):
                cdpath = bool(assigned)
            piped = part.joiner == "|" or (index > 0 and self.parts[index - 1].joiner == "|")
            if words[:1] == ["cd"] and not piped:
                lookup = cdpath if assigned is None else bool(assigned)
                if "-" in words[1:] or (lookup and words[1:] and not os.path.isabs(words[-1])):
                    self.printing_directories.add(index)
                if lookup and words[1:] and not os.path.isabs(words[-1]):
                    known = False
                current, known = _changed_directory(current, known, words[1:])
            elif words[:1] in (["pushd"], ["popd"]):
                known = False
            for _ in range(part.closes):
                current, known, cdpath = entered.pop()
        return found, placed

    def written_path(self, target: str, at: int, cwd: str, session_dir: str = "") -> str | None:
        """A check's redirect target relative to the session's directory, or
        None where it is not published: outside it, decided by the shell,
        under an unknown directory, or holding a value the line masks."""
        if (
            not _placeable(target)
            or records.mask_words([target]) != [target]
            or any(value in target for value in self.masked)
            or (not os.path.isabs(target) and not self.placed[at])
        ):
            return None
        return _written_path(os.path.join(self.directories[at] or "/", target), cwd, session_dir)

    def joiners(self) -> list[str]:
        return [part.joiner for part in self.parts]

    def output_attributable(self) -> bool:
        """A read-only command may print its own summary; only pipe filters
        preserve the check's output provenance (DRC-4733)."""
        if len(self.checks) != 1 or self.changing_others or self.substituted:
            return False
        check = self.checks[0]
        return all(
            i == check
            or (i < check and not words)
            or (
                i < check
                and words[0] == "cd"
                and i not in self.printing_directories
                and all(_placeable(word) for word in words[1:])
            )
            or (
                i > check
                and all(part.joiner == "|" for part in self.parts[check:i])
                and _pipe_filter(self.parts[i])
                and self._reads_only(i)
            )
            for i, (words, _rtk) in enumerate(self.words)
        )

    def background(self, index: int) -> bool:
        return self.all_background or self.parts[index].background

    def unestablished(self, index: int) -> bool:
        """Whether a `||` before the segment leaves its execution unknown."""
        return "||" in self.joiners()[:index]

    def changes(self) -> bool:
        """Whether any segment may change files without a recorded write."""
        return bool(self.unbalanced or self.fixers or self.changing_others or self.substituted)

    def launches(self) -> int:
        """Background launches: the call, or each `&`-ended list in it."""
        return 1 if self.all_background else sum(part.launches for part in self.parts)


class _ToolReportTally:
    """The full scan of one transcript's calls, and the entries chosen from it."""

    def __init__(self, results: dict[str, _Result], session_dir: str) -> None:
        self.results = results
        # Where a written path is read from: not a record's `cwd`, which a `cd` moves.
        self.session_dir = session_dir
        self.runs: dict[str, list[dict[str, Any]]] = {}
        self.launches: dict[str, dict[str, Any]] = {}
        self.last_turn_floor = 0.0
        self.completed_launch_calls: dict[str, float] = {}
        self._hash_identities = False
        self._last_added_runs: list[tuple[str, dict[str, Any]]] = []
        # Replay asks for entries after nearby calls. A new check changes one
        # identity; a write or changing command can age every pass, so it
        # invalidates the whole private, bounded candidate cache.
        self._entry_cache: dict[str, dict[str, Any]] = {}
        self.writes: dict[str, dict[str, Any]] = {}
        # (time, call id) of every recorded write and fixer run. A pass is aged
        # by one from another call at or after its own time, since recorded
        # time cannot order two calls that share it (DRC-4709); its own call is
        # ordered by segment instead (`fixes`, `changes_later_in_call`), which
        # is what keeps `black . && pytest` current.
        self.write_calls: list[tuple[float, str]] = []
        # Order of the shell calls that ran, and which of them may change files,
        # for the press alone (`changed_after`); layer 1's fields are untouched.
        self.shell_seq = 0
        self.changing_seqs: list[int] = []
        # The reads-from horizon (`_tally_of`): a pass called before it may
        # lack a complete read of later work; no change is established by it.
        self.reads_from: float | None = None
        self.named_unread = False
        self.parent_failed = False
        self.orphan_unread = False
        self.scan: dict[str, Any] = {
            "last_changing_command_at": None,
            **dict.fromkeys(
                (
                    "shell_calls", "check_runs", "distinct_checks", "other_commands",
                    "read_only_commands", "background", "unknown_flags", "written_paths",
                    "outside_paths", "write_attempts", "not_run", "failed", "passed",
                    "not_recorded",
                    "listed", "more", "subagent_transcripts", "subagent_transcripts_unread",
                ),
                0,
            ),
        }  # fmt: skip

    def add(
        self,
        at: float,
        cwd: str,
        call_id: str,
        name: str,
        tool_input: dict[str, Any],
        worker: str = "",
    ) -> None:
        # The merged call carries stream identity for launch pairing, while
        # published checks retain their existing generic worker label.
        stream = worker
        worker = SUBAGENT_WORKER if worker else ""
        self._last_added_runs.clear()
        changes_before = (len(self.write_calls), len(self.changing_seqs))
        if name in _WRITE_TOOLS:
            self._add_write(at, cwd, call_id, name, tool_input, worker)
        elif name == "Bash":
            self._add_shell(at, cwd, call_id, tool_input, worker, stream)
        elif name in {"Agent", "Task", "Monitor"} and tool_input.get("run_in_background") is True:
            found = self.results.get(_launch_record_id(call_id, stream or "parent"))
            if found is None or found.block.get("is_error") is not True:
                self._add_launch(at, call_id, name, 1, worker, stream)
        if changes_before != (len(self.write_calls), len(self.changing_seqs)):
            self._entry_cache.clear()

    def _add_launch(
        self, at: float, call_id: str, tool: str, count: int, worker: str, stream: str
    ) -> None:
        call_id = _launch_record_id(call_id, stream)
        completed = self.completed_launch_calls.get(call_id)
        if count != 1 or (completed is not None and completed < at):
            completed = None
        self.launches[call_id] = {
            "kind": "background_launch",
            "subject": "launch",
            "at": at,
            "record_id": call_id,
            "title": f"Background {tool} work launched",
            "source": f"Claude {tool} call",
            "count": count,
            "completed_at": completed,
            "last_activity_at": completed or at,
            "activity_seen": False,
            **({"worker_kind": worker} if worker else {}),
        }

    def _add_write(
        self,
        at: float,
        cwd: str,
        call_id: str,
        name: str,
        tool_input: dict[str, Any],
        worker: str,
    ) -> None:
        found = self.results.get(call_id)
        if found is None or found.block.get("is_error") is True:
            # Not established as written (review, 2026-09-24): an attempt.
            self.scan["write_attempts"] += 1
            return
        # A written file ages every earlier pass wherever it is. Only the path is
        # read: never `content`, `old_string`, `new_string` or `edits`.
        self._record_write(
            at,
            call_id,
            name,
            _written_path(
                tool_input.get("file_path") or tool_input.get("notebook_path"),
                cwd,
                self.session_dir,
            ),
            worker,
        )

    def _record_write(
        self, at: float, call_id: str, tool: str, path: str | None, worker: str
    ) -> None:
        self.write_calls.append((at, call_id))
        if path is None:
            self.scan["outside_paths"] += 1
            return
        previous = self.writes.get(path)
        self.writes[path] = {
            "at": at,
            "record_id": call_id,
            "tool": tool,
            "worker": worker,
            # The first write of this path, which is where its fixed position sits: the entry is the
            # latest write, so its own time moves each time the file is written again.
            "first_at": min(previous["first_at"], at) if previous else at,
        }

    def _add_shell(
        self,
        at: float,
        cwd: str,
        call_id: str,
        tool_input: dict[str, Any],
        worker: str,
        stream: str,
    ) -> None:
        found = self.results.get(call_id)
        result = found.block if found is not None else None
        text = _tool_result_text(result) if result is not None else ""
        launch_found = self.results.get(_launch_record_id(call_id, stream or "parent"))
        launch_result = launch_found.block if launch_found is not None else None
        launch_text = _tool_result_text(launch_result) if launch_result is not None else ""
        launch_call = _ShellCall(
            at, cwd, tool_input, moved=bool(_MOVED_TO_BACKGROUND_RE.match(launch_text))
        )
        launched = not (
            launch_result is not None
            and launch_result.get("is_error") is True
            and not _EXITED_RE.match(launch_text)
        )
        if launched and not launch_call.unbalanced and (count := launch_call.launches()):
            self.scan["background"] += count
            self._add_launch(at, call_id, "Bash", count, worker, stream)
        if result is not None and result.get("is_error") is True and not _EXITED_RE.match(text):
            # V3: the call never ran, so it is no run and supersedes nothing.
            self.scan["not_run"] += 1
            return
        call = (
            launch_call
            if launch_found is found
            else _ShellCall(at, cwd, tool_input, moved=bool(_MOVED_TO_BACKGROUND_RE.match(text)))
        )
        self.shell_seq += 1
        if call.changes():
            self.changing_seqs.append(self.shell_seq)
            self.scan["last_changing_command_at"] = at
        if call.unbalanced:
            self.scan["not_run"] += 1
            return
        self.scan["shell_calls"] += 1
        if call.fixers:
            self.write_calls.append((at, call_id))
        for _index, target, start in call.redirect_writes:
            # Owner, 2026-09-27: published only inside the working directory;
            # a target outside it, or one the shell decides, counts as outside.
            self._record_write(
                at, call_id, "Bash", call.written_path(target, start, cwd, self.session_dir), worker
            )
        foreground = [i for i in call.meaningful if not call.background(i)]
        if foreground and not [i for i in call.checks if i in foreground]:
            self.scan["other_commands"] += 1
            self.scan["read_only_commands"] += not call.changes()
        self._add_runs(call, call_id, result, text, found.at if found is not None else None, worker)

    def _add_runs(
        self,
        call: _ShellCall,
        call_id: str,
        result: dict[str, Any] | None,
        text: str,
        result_at: float | None,
        worker: str,
    ) -> None:
        flag = result.get("is_error") if result is not None else None
        # Redaction runs over the whole read window before the tail is cut (item 5).
        tail = records.redact_secrets(text)[-TOOL_REPORT_TAIL_CHARS:]
        all_and = all(joiner == "&&" for joiner in call.joiners()[:-1])
        # V8: output speaks for a check only when it is the call's one check,
        # background ones counted, and nothing else in the call may print.
        attributable = call.output_attributable()
        for index in call.checks:
            words, rtk = call.words[index]
            background = call.background(index)
            if background:
                outcome, source = "not-recorded", ""
            else:
                self.scan["check_runs"] += 1
                if result is None or call.unestablished(index):
                    outcome, source = "not-recorded", ""
                else:
                    outcome, source = self._outcome(
                        tail,
                        rtk=rtk,
                        attributable=attributable,
                        flag_result=_flag_result(
                            flag,
                            last=index == len(call.parts) - 1,
                            all_and=all_and,
                            alone=len(call.meaningful) == 1,
                        ),
                    )
                self.scan["unknown_flags"] += (
                    result is not None and not isinstance(flag, bool) and outcome == "not-recorded"
                )
            identity = _check_identity(
                call.directories[index],
                words,
                unplaced=f"{worker}:{call_id}:{index}" if not call.placed[index] else "",
            )
            if self._hash_identities:
                identity = hashlib.sha256(identity.encode("utf-8", "replace")).hexdigest()
            self._entry_cache.clear()
            self.runs.setdefault(identity, []).append(
                {
                    "at": call.at,
                    "record_id": call_id,
                    "title": _check_line(words),
                    "segment": index,
                    "result": outcome,
                    "result_source": source,
                    "recorded": result is not None,
                    # When the result arrived (DRC-4702): it decides the window
                    # and which run is latest, never a change comparison.
                    "result_at": result_at if result is not None and not background else None,
                    "background": background,
                    # Held for the press only (`claude_check_tails`); never
                    # copied onto the published entry.
                    "tail": _scrubbed_tail(text, call.masked_values) if result is not None else "",
                    "seq": self.shell_seq,
                    "worker": worker,
                    "coverage": _check_coverage(
                        call.directories[index], words, worker, call.parts[index].raw
                    )
                    if call.placed[index]
                    else None,
                    "changes_later_in_call": any(
                        i > index
                        for i in (
                            *call.fixers,
                            *call.changing_others,
                            *call.substituted,
                            *(j for j, _target, _at in call.redirect_writes),
                        )
                    ),
                    # V7: a fixer at or after this check in the call ages its pass,
                    # and so does a later check's redirect into a file (review W6).
                    "fixes": any(i >= index for i in call.fixers)
                    or any(j > index for j, _target, _at in call.redirect_writes),
                }
            )
            self._last_added_runs.append((identity, self.runs[identity][-1]))

    @staticmethod
    def _outcome(tail: str, *, rtk: bool, attributable: bool, flag_result: str) -> tuple[str, str]:
        """By item 2's order, as the review rounds narrowed it: a result that
        cannot be attributed reads "ran, result not recorded"."""
        failed_summary = bool(_SUMMARY_FAILED.search(tail))
        failure_text = failed_summary or bool(_FAILURE_MARKER.search(tail))
        if rtk:
            # rtk may rewrite output, so its runs read the flag alone (owner),
            # and failure text beside a passing flag withholds it (V5).
            if flag_result == "passed" and failure_text:
                return "not-recorded", ""
            return (flag_result, "flag") if flag_result else ("not-recorded", "")
        if flag_result == "passed":
            # V4: only a failure summary overrides a passing flag; a marker, or
            # a run of nothing, only withholds it.
            if failed_summary:
                return ("failed", "summary") if attributable else ("not-recorded", "")
            if failure_text or _ran_nothing(tail):
                return "not-recorded", ""
        if flag_result:
            return flag_result, "flag"
        from_tail = _tail_result(tail) if attributable else None
        return from_tail if from_tail is not None else ("not-recorded", "")

    @staticmethod
    def _latest(history: list[dict[str, Any]]) -> int:
        """The index of the run whose evidence is newest: its result's time, or
        its call's with none, and call order between equals (DRC-4702)."""
        return max(
            range(len(history)),
            key=lambda i: (_evidence_at(history[i]), i),
        )

    def _check_entry(self, history: list[dict[str, Any]]) -> dict[str, Any]:
        index = self._latest(history)
        latest = history[index]
        # The page renders no word for `worker_kind`, so the source line names
        # the subagent (owner, 2026-09-28).
        who = "Claude subagent" if latest["worker"] else "Claude"
        if latest["background"]:
            source = f"{who} Bash call run in the background, no result recorded"
        elif latest["recorded"]:
            source = f"{who} Bash call and paired result"
        else:
            source = f"{who} Bash call, no result recorded yet"
        entry: dict[str, Any] = {
            "kind": "check_run",
            "subject": "check",
            "at": latest["at"],
            "record_id": latest["record_id"],
            "title": latest["title"],
            "result": latest["result"],
            "earlier_failed": any(
                run["result"] == "failed" for i, run in enumerate(history) if i != index
            ),
            "before_last_change": (
                latest["fixes"]
                or any(
                    at >= latest["at"] and call_id != latest["record_id"]
                    for at, call_id in self.write_calls
                )
            ),
            # Whether a command that may change files followed this run, in its
            # own call or a later one, in command order: the press's
            # `changed_after`, published so the live level can block on it
            # (DRC-4692). Timestamps cannot order two segments of one call.
            "changed_after": self._changed_after(latest),
            "read_incomplete": self._read_incomplete(latest),
            "source": source,
            "rank": _RESULT_ORDER[latest["result"]],
        }
        if latest["result"] == "not-recorded" and entry["earlier_failed"]:
            # Its only recorded result is a failure: ranked with the failures,
            # or twelve writes would push the failure out of the listing.
            entry["rank"] = _RESULT_ORDER["failed"]
        if latest["result_source"]:
            entry["result_source"] = latest["result_source"]
        if latest["result_at"] is not None:
            entry["result_at"] = latest["result_at"]
        if latest["worker"]:
            entry["worker_kind"] = latest["worker"]
        return entry

    def _histories(self) -> list[tuple[str, list[dict[str, Any]]]]:
        histories = {
            identity: list(history)
            for identity, history in self.runs.items()
            if not all(run["background"] for run in history)
        }
        latest = {
            identity: history[self._latest(history)] for identity, history in histories.items()
        }
        passes = [(identity, run) for identity, run in latest.items() if run["result"] == "passed"]
        for identity, run in latest.items():
            if run["result"] != "failed":
                continue
            covering = [(key, passed) for key, passed in passes if _covers_check(passed, run)]
            if covering:
                key, _passed = max(covering, key=lambda pair: _evidence_at(pair[1]))
                histories[key].extend(histories.pop(identity))
        return list(histories.items())

    def entries(self, sid: str, index: Any = None) -> list[dict[str, Any]]:
        histories = self._histories()
        candidates = self._ranked(histories)
        for entry in candidates:
            if entry["subject"] == "check":
                self.scan[str(entry["result"]).replace("-", "_")] += 1
        listed = candidates[:TOOL_REPORT_MAX_ENTRIES]
        self.scan.update(
            distinct_checks=len(histories),
            written_paths=len(self.writes),
            listed=len(listed),
            more=sum(row["subject"] != "launch" for row in candidates[TOOL_REPORT_MAX_ENTRIES:]),
            background_unpaired=sum(
                row["count"] for row in self.launches.values() if row["completed_at"] is None
            ),
            background_more=sum(
                row["subject"] == "launch" for row in candidates[TOOL_REPORT_MAX_ENTRIES:]
            ),
        )
        # A fixed position for every check, file and launch the transcript holds, counted whether
        # or not the listing keeps it: evicting one leaves a gap and moves no number after it. A
        # failed check a later pass covers, and one that has only run in the background, leave the
        # candidates but keep their place, or the entries after them would move when it happened.
        counted = {row["_key"]: row["_first_at"] for row in candidates}
        for identity, runs in self.runs.items():
            counted.setdefault(f"check:{identity}", min(run["at"] for run in runs))
        positions = (
            entry_numbers.tool_positions(index, counted.items()) if index is not None else {}
        )
        return [
            {
                **{k: v for k, v in row.items() if k not in {"rank", "_key", "_first_at"}},
                "harness": "claude",
                "sid": sid,
                **(
                    {"ordinal": position[0], "ordinal_sub": position[1]}
                    if (position := positions.get(row["_key"])) is not None
                    else {}
                ),
            }
            for row in listed
        ]

    @staticmethod
    def _write_entry(path: str, write: dict[str, Any]) -> dict[str, Any]:
        return {
            "kind": "path_written",
            "subject": "write",
            "at": write["at"],
            "record_id": write["record_id"],
            "title": records.safe_text(path, TOOL_REPORT_PATH_CHARS),
            "source": f"Claude {'subagent ' if write['worker'] else ''}{write['tool']} call",
            "rank": _WRITE_RANK,
            "_key": f"write:{path}",
            "_first_at": write["first_at"],
            **({"worker_kind": write["worker"]} if write["worker"] else {}),
        }

    def _ranked(self, histories: list[tuple[str, list[dict[str, Any]]]]) -> list[dict[str, Any]]:
        """Every check's entry and every written path, in the order item 4 keeps them."""
        candidates: list[dict[str, Any]] = []
        for identity, history in histories:
            entry = self._entry_cache.get(identity)
            if entry is None:
                entry = self._check_entry(history)
                self._entry_cache[identity] = entry
            # Its own first run, not the merged history's: a failed run another pass covers joins
            # that pass's history, and the covered run's earlier time must not move the pass's
            # position.
            candidates.append(
                {
                    **entry,
                    "_key": f"check:{identity}",
                    "_first_at": min(run["at"] for run in self.runs[identity]),
                }
            )
        candidates.extend(self._write_entry(path, write) for path, write in self.writes.items())
        candidates.extend(
            {**launch, "rank": 4, "_key": f"launch:{call_id}", "_first_at": launch["at"]}
            for call_id, launch in self.launches.items()
        )
        # Item 4, amended 2026-10-04: failed, then passed, then written paths,
        # then no recorded result, newest first within each. The page shows the
        # kept ones in time order (orchestrator, 2026-09-24).
        candidates.sort(key=lambda row: (row["rank"], -float(row["at"])))
        return candidates

    def passes_and_writes(self) -> tuple[tuple[str, str, float], ...]:
        """(record id, title, time) of every latest passing check and written path.

        For the press alone, like the tails. The reading compares (record id,
        title) with the facts its prompt carried: one call can hold several
        checks and writes under one record id, so the id alone would read a
        sibling as carried. A pass the listing's cap left
        out, or one that arrived after the facts were published, is part of
        the record it did not read, and "not shown by the record" cannot stand
        on it. A check's time is its result's where one arrived. The ruling:
        [DEC-17](docs/design-reading-a-session.md#amended-2026-10-04-owner-what-the-agent-claims-is-its-own-constraint)
        """
        return tuple(
            sorted(
                (
                    str(row["record_id"]),
                    str(row["title"]),
                    float(row.get("result_at") or row["at"]),
                )
                for row in self._ranked(self._histories())
                if row["subject"] == "write" or row.get("result") == "passed"
            )
        )

    def tails(self) -> dict[str, str]:
        """Each check's latest foreground run's redacted output tail, by call id."""
        latest = (history[self._latest(history)] for history in self.runs.values())
        return {
            run["record_id"]: run["tail"] for run in latest if not run["background"] and run["tail"]
        }

    def _changed_after(self, run: dict[str, Any]) -> bool:
        return bool(run["changes_later_in_call"]) or any(
            seq > run["seq"] for seq in self.changing_seqs
        )

    def _read_incomplete(self, run: dict[str, Any]) -> bool:
        return run["result"] == "passed" and (
            self.named_unread
            or self.parent_failed
            or self.orphan_unread
            or (self.reads_from is not None and run["at"] < self.reads_from)
        )

    def read_incomplete(self) -> frozenset[tuple[str, str]]:
        """Latest passes the bounded scan or missing named child cannot vouch for."""
        latest = (history[self._latest(history)] for history in self.runs.values())
        return frozenset(
            (run["record_id"], run["title"]) for run in latest if self._read_incomplete(run)
        )

    def changed_after(self) -> frozenset[tuple[str, str]]:
        """(call id, check line) for each latest run a later command may have changed.

        In command order: a changing segment after the check in its own call,
        or any later call that ran and may change files. A change before the
        check, or a read-only command after it, does not count.
        """
        latest = (history[self._latest(history)] for history in self.runs.values())
        return frozenset(
            (run["record_id"], run["title"]) for run in latest if self._changed_after(run)
        )


class PressChecks(NamedTuple):
    """What a press reads of a session's checks beyond the published facts."""

    tails: dict[str, str]
    changed_after: frozenset[tuple[str, str]]
    read_incomplete: frozenset[tuple[str, str]] = frozenset()
    # (record id, title, time) of each latest pass and each write
    # (`_ToolReportTally.passes_and_writes`): the same titles the facts carry.
    passes_and_writes: tuple[tuple[str, str, float], ...] = ()


def claude_check_press(
    config: RuntimeConfig, transcript_path: str, *, max_bytes: int | None = None
) -> PressChecks:
    """The output tails, later-command flags and incomplete-read flags a press
    may carry, keyed by the call's record id and check line, and the record
    id and time of each pass and write.

    Read again at the press rather than published: the owner ruled that the
    model sees each check's redacted tail (DRC-4677, Q1), and it stays off the
    fact, the page and history, so only a reading the reader allowed tool
    output for ever holds it. The same scan and bounds as
    `claude_tool_reports`, so both belong to the run that fact lists.
    """
    tally = _claude_tally(config, transcript_path, max_bytes=max_bytes)
    return _press(tally)


def _press(tally: _ToolReportTally) -> PressChecks:
    return PressChecks(
        tally.tails(), tally.changed_after(), tally.read_incomplete(), tally.passes_and_writes()
    )


def claude_check_tails(
    config: RuntimeConfig, transcript_path: str, *, max_bytes: int | None = None
) -> dict[str, str]:
    """The output tails `claude_check_press` reads, alone."""
    return claude_check_press(config, transcript_path, max_bytes=max_bytes).tails


def press_checks(config: RuntimeConfig, state: RuntimeState, harness: str, sid: str) -> PressChecks:
    """`claude_check_press` for one session, found as `collect` finds it; empty elsewhere."""
    transcript_path = (
        observer.resolve_transcript(config, state, harness, sid) if harness == "claude" else None
    )
    if not transcript_path:
        return PressChecks({}, frozenset())
    return claude_check_press(config, transcript_path)


# A subagent's own transcript sits under its parent's session directory, flat
# for a Task or Agent call and one level deeper for a workflow's run, as the
# collector lists them (`collectors.claude.SUBAGENT_GLOBS`). Only a plain
# `agent-<hex>` file is a subagent: compaction (`agent-acompact-*`), an aside
# question and a prompt suggestion fork the parent's context and replay its
# calls under the parent's own ids, measured 2026-09-28 in 15 of 16 aside
# questions and 21 of 39 compactions that held a call. `_subagent_transcripts`
# cites the ruling.
_SUBAGENT_GLOBS = (
    ("subagents", "agent-*.jsonl"),
    ("subagents", "workflows", "*", "agent-*.jsonl"),
)
_SUBAGENT_FILE_RE = re.compile(r"agent-[0-9a-f]+\.jsonl")
SUBAGENT_WORKER = "subagent"


def _admitted_subagent_path(transcript_path: str, path: str) -> bool:
    session_dir = transcript_path[: -len(".jsonl")]
    try:
        relative = os.path.relpath(path, session_dir)
    except ValueError:
        return False
    parts = relative.split(os.sep)
    shape = (len(parts) == 2 and parts[0] == "subagents") or (
        len(parts) == 4 and parts[:2] == ["subagents", "workflows"]
    )
    return bool(
        transcript_path.endswith(".jsonl")
        and shape
        and _SUBAGENT_FILE_RE.fullmatch(os.path.basename(path))
        and not os.path.islink(path)
        and os.path.realpath(path) == os.path.join(os.path.realpath(session_dir), relative)
    )


def _subagent_transcripts(transcript_path: str) -> list[str]:
    """Every owned, plain-hex child; copied-context forks and links are refused.

    [DEC-23](docs/design-reading-a-session.md#amended-2026-09-28-a-subagents-checks-and-writes-are-the-parents)
    """
    if not transcript_path.endswith(".jsonl"):
        return []
    session_dir = transcript_path[: -len(".jsonl")]
    if not os.path.isdir(session_dir):
        return []
    return [
        path
        for pattern in _SUBAGENT_GLOBS
        for path in runtime_io.glob_under(session_dir, *pattern)
        if _admitted_subagent_path(transcript_path, path)
    ]


def _admitted_subagent_paths(transcript_path: str, supplied: Sequence[str] | None) -> list[str]:
    return (
        _subagent_transcripts(transcript_path)
        if supplied is None
        else [path for path in supplied if _admitted_subagent_path(transcript_path, path)]
    )


def _oldest_at(records_: list[dict[str, Any]]) -> float | None:
    """The first stamped record's time: where a bounded read begins."""
    return next((at for r in records_ if (at := _record_timestamp(r)) is not None), None)


def _later(a: float | None, b: float | None) -> float | None:
    return b if a is None else a if b is None else max(a, b)


def _scan_budget(config: RuntimeConfig, max_bytes: int | None = None) -> runtime_io.ReadBudget:
    limit = config.turn_scan_max_bytes
    return runtime_io.ReadBudget(limit if max_bytes is None else min(limit, max(0, max_bytes)))


def _scan_records(read: runtime_io.TranscriptRead) -> list[dict[str, Any]]:
    return [record for raw in read.lines if (record := _json_dict(raw)) is not None]


def _agent_result_ids(parent: list[dict[str, Any]]) -> tuple[set[str], set[str]]:
    """Pair known Agent results; keep valid orphan results private for clipped reads."""
    calls = {
        call_id
        for _at, _cwd, call_id, name, _tool_input, _worker in _claude_tool_uses(parent)
        if name in {"Agent", "Task"}
    }
    named: set[str] = set()
    orphan: set[str] = set()
    for record in parent:
        if record.get("type") != "user" or record.get("isSidechain") is True:
            continue
        result = record.get("toolUseResult")
        if not isinstance(result, dict) or not isinstance(result.get("agentId"), str):
            continue
        agent_id = result["agentId"]
        if re.fullmatch(r"[0-9a-f]+", agent_id) is None:
            continue
        content = records.message_dict(record).get("content")
        result_ids = (
            {
                block["tool_use_id"]
                for block in content
                if isinstance(block, dict)
                and block.get("type") == "tool_result"
                and isinstance(block.get("tool_use_id"), str)
                and block["tool_use_id"]
            }
            if isinstance(content, list)
            else set()
        )
        if result_ids & calls:
            named.add(agent_id)
        elif result_ids:
            orphan.add(agent_id)
    return named, orphan


def _named_agent_ids(parent: list[dict[str, Any]]) -> set[str]:
    """Only a paired parent Agent/legacy Task result may name missing work."""
    return _agent_result_ids(parent)[0]


def _child_id(path: str) -> str:
    return os.path.basename(path)[len("agent-") : -len(".jsonl")]


def _session_directory(
    config: RuntimeConfig, transcript_path: str, parent: list[dict[str, Any]]
) -> str:
    """The directory the session began in: the transcript head's, since a clipped
    read starts after any `cd`; the first record read stands in when the head
    carries none."""
    return claude_data.head_cwd(config, transcript_path) or next(
        (record["cwd"] for record in parent if isinstance(record.get("cwd"), str)), ""
    )


class _CheckScan(NamedTuple):
    parent: list[dict[str, Any]]
    children: list[list[dict[str, Any]]]
    unread: int
    horizon: float | None
    named_unread: bool
    parent_failed: bool
    orphan_unread: bool
    budget: runtime_io.ReadBudget
    source_reads: tuple[tuple[str, runtime_io.TranscriptRead | None], ...]
    session_dir: str = ""


def _live_check_scan(
    config: RuntimeConfig,
    transcript_path: str,
    *,
    max_bytes: int | None = None,
    child_paths: Sequence[str] | None = None,
) -> _CheckScan:
    """Parent-first actual bytes; metadata sorts children without spending B."""
    budget = _scan_budget(config, max_bytes)
    parent_read = runtime_io.scan_reverse_lines(config, transcript_path, budget)
    parent = _scan_records(parent_read)
    horizon = None if parent_read.complete else _oldest_at(parent) or _mtime(transcript_path)
    session_dir = transcript_path[: -len(".jsonl")]
    paths = _admitted_subagent_paths(transcript_path, child_paths)
    paths.sort(key=lambda path: (-(_mtime(path) or 0), os.path.relpath(path, session_dir)))
    children: list[list[dict[str, Any]]] = []
    source_reads: list[tuple[str, runtime_io.TranscriptRead | None]] = [
        (transcript_path, parent_read)
    ]
    unread_ids: set[str] = set()
    read_ids: set[str] = set()
    complete_ids: set[str] = set()
    unread = 0
    for path in paths:
        mtime = _mtime(path)
        read = (
            runtime_io.scan_reverse_lines(config, path, budget, follow_links=False)
            if budget.remaining
            else None
        )
        source_reads.append((path, read))
        got = _scan_records(read) if read is not None else []
        if got:
            children.append(got)
            read_ids.add(_child_id(path))
            if read is not None and read.complete:
                complete_ids.add(_child_id(path))
            if read is not None and not read.complete:
                horizon = _later(horizon, _oldest_at(got) or mtime)
        else:
            unread += 1
            unread_ids.add(_child_id(path))
            horizon = _later(horizon, mtime)
    named, orphan = _agent_result_ids(parent)
    missing = named - read_ids
    unread += len(missing - unread_ids)
    # A clipped parent may keep a result but lose its earlier Agent call. It
    # cannot prove a named missing child, yet neither can its pass prove that
    # unread delegated work did not change files.
    orphan_unread = not parent_read.complete and bool(orphan - complete_ids)
    return _CheckScan(
        parent,
        children,
        unread,
        horizon,
        bool(missing),
        parent_read.failed,
        orphan_unread,
        budget,
        tuple(source_reads),
        _session_directory(config, transcript_path, parent),
    )


def _tally_of(
    parent: list[dict[str, Any]],
    subagents: list[list[dict[str, Any]]],
    unread: int,
    reads_from: float | None = None,
    *,
    session_dir: str,
    named_unread: bool = False,
    parent_failed: bool = False,
    orphan_unread: bool = False,
) -> _ToolReportTally:
    """One tally over a parent's calls and its subagents', in call time order.

    Each transcript keeps its own order and the streams are merged by call
    time, the parent's first at a tie, so a session with no subagent reads
    exactly as it did. Call time, not result time, orders them, because every
    change comparison is by call time (the 2026-09-27 amendment's item 4); the
    result time still picks a check's latest run, across both.

    `reads_from` is the latest of where a cut read begins and the newest time
    an unread child can hold. A pass before it is incomplete rather than
    dropped, since dropping calls would drop an older failure too. A named
    unavailable child makes every held pass incomplete without inventing a
    timestamp. A measured failure remains a failure.
    """
    tally = _ToolReportTally(_merged_check_results(parent, subagents), session_dir)
    tally.reads_from = reads_from
    tally.scan["last_user_at"] = _last_person_at(parent)
    tally.named_unread = named_unread
    tally.parent_failed = parent_failed
    tally.orphan_unread = orphan_unread
    tally.completed_launch_calls = _stream_completed_background_calls(parent, subagents)
    for call in _merged_check_calls(parent, subagents):
        tally.add(*call)
    tally.last_turn_floor = _delegated_last_turn_floor(parent)
    _pair_background_launches(tally, parent, subagents)
    tally.scan["background_unpaired"] = sum(
        row["count"] for row in tally.launches.values() if row["completed_at"] is None
    )
    tally.scan.update(subagent_transcripts=len(subagents), subagent_transcripts_unread=unread)
    if reads_from is not None:
        tally.scan["reads_from"] = reads_from
    return tally


def _merged_check_results(
    parent: list[dict[str, Any]], subagents: list[list[dict[str, Any]]]
) -> dict[str, _Result]:
    """Keep check collisions parent-first; launch result aliases stay stream-owned."""
    results = _tool_result_blocks(parent)
    results.update(
        {_launch_record_id(key, "parent"): found for key, found in list(results.items())}
    )
    for index, records_ in enumerate(subagents):
        for call_id, found in _tool_result_blocks(records_, sidechain=True).items():
            results.setdefault(call_id, found)
            results[_launch_record_id(call_id, f"{SUBAGENT_WORKER}:{index}")] = found
    return results


def _child_check_calls(
    child: list[dict[str, Any]], stream: str
) -> Iterator[tuple[float, str, str, str, dict[str, Any], str]]:
    for call in _claude_tool_uses(child, sidechain=True):
        yield (*call[:-1], stream)


def _merged_check_calls(
    parent: list[dict[str, Any]], subagents: list[list[dict[str, Any]]]
) -> Iterator[tuple[float, str, str, str, dict[str, Any], str]]:
    """Parent first at equal call times, matching the published work record."""
    streams = [
        _claude_tool_uses(parent),
        *(
            _child_check_calls(child, f"{SUBAGENT_WORKER}:{index}")
            for index, child in enumerate(subagents)
        ),
    ]
    return heapq.merge(*streams, key=lambda row: row[0])


def _claude_tally(
    config: RuntimeConfig,
    transcript_path: str,
    *,
    max_bytes: int | None = None,
    child_paths: Sequence[str] | None = None,
) -> _ToolReportTally:
    scan = _live_check_scan(config, transcript_path, max_bytes=max_bytes, child_paths=child_paths)
    return _tally_of(
        scan.parent,
        scan.children,
        scan.unread,
        scan.horizon,
        named_unread=scan.named_unread,
        parent_failed=scan.parent_failed,
        orphan_unread=scan.orphan_unread,
        session_dir=scan.session_dir,
    )


def _mtime(path: str) -> float | None:
    try:
        return os.stat(path).st_mtime
    except OSError:
        return None


class _WindowNotRequested:
    __slots__ = ()


_WINDOW_NOT_REQUESTED = _WindowNotRequested()


def _last_person_at(parent: list[dict[str, Any]]) -> float | None:
    """Parent-only human boundary, excluding tool results and injected messages."""
    times = []
    for record in parent:
        message = observer.parse_message_record(record)
        if message is not None and message.get("role") == "user":
            text = str(message.get("text") or "")
            if text and not records.injected_prompt(text, "claude"):
                at = _record_timestamp(record)
                if at is not None:
                    times.append(at)
    return max(times, default=None)


def _delegated_last_turn_floor(parent: list[dict[str, Any]]) -> float:
    stops = sorted(
        _record_timestamp(record) or 0
        for record in parent
        if record.get("type") == "system" and record.get("subtype") == "stop_hook_summary"
    )
    directions = []
    for record in parent:
        message = observer.parse_message_record(record)
        if message is not None and message.get("role") == "user":
            text = str(message.get("text") or "")
            if not records.injected_prompt(text, "claude"):
                directions.append(_record_timestamp(record) or 0)
    return max([*directions, stops[-2] if len(stops) > 1 else 0])


def _notification_field(text: str, field: str) -> str:
    found = re.search(rf"<{field}>([^<>]*)</{field}>", text)
    return found.group(1).strip() if found else ""


def _result_metadata(
    parent: list[dict[str, Any]], *, sidechain: bool = False
) -> dict[str, dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}
    for record in parent:
        if record.get("type") != "user" or (record.get("isSidechain") is True) is not sidechain:
            continue
        metadata = record.get("toolUseResult")
        content = records.message_dict(record).get("content")
        if not isinstance(metadata, dict) or not isinstance(content, list):
            continue
        for block in content:
            call_id = block.get("tool_use_id") if isinstance(block, dict) else None
            if isinstance(call_id, str):
                found[call_id] = metadata
    return found


def _launch_task_calls(
    metadata: dict[str, dict[str, Any]],
) -> dict[str, str]:
    found: dict[str, str] = {}
    for call_id, result in metadata.items():
        task_id = result.get("backgroundTaskId") or result.get("agentId")
        if isinstance(task_id, str):
            found[task_id] = call_id
    return found


def _task_output_completions(
    parent: list[dict[str, Any]],
    task_calls: dict[str, str],
    metadata: dict[str, dict[str, Any]],
    *,
    sidechain: bool = False,
) -> dict[str, float]:
    found: dict[str, float] = {}
    results = _tool_result_blocks(parent, sidechain=sidechain)
    for at, _cwd, call_id, name, tool_input, _worker in _claude_tool_uses(
        parent, sidechain=sidechain
    ):
        if name != "TaskOutput":
            continue
        result = results.get(call_id)
        task_id = tool_input.get("task_id")
        task = metadata.get(call_id, {}).get("task")
        paired = task_calls.get(task_id) if isinstance(task_id, str) else None
        if (
            paired
            and result is not None
            and result.block.get("is_error") is not True
            and isinstance(task, dict)
            and task.get("status") in {"completed", "failed", "killed"}
        ):
            found[paired] = result.at or at
    return found


def _notification_completions(
    parent: list[dict[str, Any]],
    task_calls: dict[str, str],
    *,
    sidechain: bool = False,
) -> dict[str, float]:
    found: dict[str, float] = {}
    for record in parent:
        if record.get("type") != "user" or (record.get("isSidechain") is True) is not sidechain:
            continue
        at = _record_timestamp(record)
        text = _tool_result_text(records.message_dict(record))
        if at is None or not text.lstrip().startswith("<task-notification>"):
            continue
        call_id = _notification_field(text, "tool-use-id") or task_calls.get(
            _notification_field(text, "task-id"),
            "",
        )
        status = _notification_field(text, "status")
        terminal = status in {"completed", "failed", "killed"} or (
            not status and "<result>" in text and "</result>" in text
        )
        if call_id and terminal:
            found[call_id] = at
    return found


def _completed_background_calls(
    parent: list[dict[str, Any]], *, sidechain: bool = False
) -> dict[str, float]:
    metadata = _result_metadata(parent, sidechain=sidechain)
    task_calls = _launch_task_calls(metadata)
    return {
        **_task_output_completions(parent, task_calls, metadata, sidechain=sidechain),
        **_notification_completions(parent, task_calls, sidechain=sidechain),
    }


def _launch_record_id(call_id: str, stream: str) -> str:
    """A private launch key: identical raw tool ids in children cannot collide."""
    return f"{stream}/{call_id}" if stream else call_id


def _stream_completed_background_calls(
    parent: list[dict[str, Any]],
    subagents: list[list[dict[str, Any]]],
) -> dict[str, float]:
    found = _completed_background_calls(parent)
    for index, child in enumerate(subagents):
        found.update(
            {
                _launch_record_id(call_id, f"{SUBAGENT_WORKER}:{index}"): at
                for call_id, at in _completed_background_calls(child, sidechain=True).items()
            }
        )
    return found


def _pair_child_activity(
    tally: _ToolReportTally,
    subagents: list[list[dict[str, Any]]],
    task_calls: dict[str, str],
) -> None:
    for child in subagents:
        task_ids = {row.get("agentId") for row in child if isinstance(row.get("agentId"), str)}
        activity = max((_record_timestamp(row) or 0 for row in child), default=0)
        for task_id in task_ids:
            call_id = task_calls.get(str(task_id))
            if call_id in tally.launches and activity >= tally.launches[call_id]["at"]:
                tally.launches[call_id]["last_activity_at"] = activity
                tally.launches[call_id]["activity_seen"] = True


def _pair_background_launches(
    tally: _ToolReportTally,
    parent: list[dict[str, Any]],
    subagents: list[list[dict[str, Any]]],
) -> None:
    metadata = _result_metadata(parent)
    task_calls = _launch_task_calls(metadata)
    _pair_child_activity(tally, subagents, task_calls)
    for launch in tally.launches.values():
        if launch["completed_at"] is not None:
            launch["last_activity_at"] = max(launch["last_activity_at"], launch["completed_at"])


def delegated_work_published(
    config: RuntimeConfig,
    transcript_path: str | None,
    *,
    own_activity: float,
    now: float,
    state: RuntimeState | None = None,
    child_paths: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Counts and times only; a command-line launch cannot identify another session.

    [DEC-23](docs/design-reading-a-session.md#amended-2026-10-04-owner-delegated-launches)
    """
    launches: list[dict[str, Any]] = []
    partial = False
    last_turn_floor = 0.0
    if transcript_path:
        stamps: list[tuple[str, int, int]] = []
        paths = _admitted_subagent_paths(transcript_path, child_paths)
        for path in [transcript_path, *paths]:
            try:
                stat_result = os.stat(path)
                stamps.append((path, stat_result.st_size, stat_result.st_mtime_ns))
            except OSError:
                stamps.append((path, -1, -1))
        stamp = tuple(stamps)
        hit = None
        if state is not None:
            with state.cache_lock:
                hit = state.delegated_work_cache.get(transcript_path)
        if hit is not None and hit[0] == stamp:
            launches, partial, last_turn_floor = hit[1:]
        else:
            tally = _claude_tally(config, transcript_path, child_paths=paths)
            launches = list(tally.launches.values())
            partial = tally.reads_from is not None or tally.parent_failed
            last_turn_floor = tally.last_turn_floor
            if state is not None:
                with state.cache_lock:
                    runtime_state.bounded_put(
                        state.delegated_work_cache,
                        transcript_path,
                        (stamp, launches, partial, last_turn_floor),
                        limit=config.max_cache_entries,
                    )
    unpaired = [
        row for row in launches if row["completed_at"] is None and not row.get("worker_kind")
    ]
    latest = max((row["at"] for row in launches), default=None)
    activity = max((row["last_activity_at"] for row in unpaired), default=None)
    last_turn_launch = any(row["at"] >= last_turn_floor for row in unpaired)
    quiet = max(activity, own_activity) if activity is not None and last_turn_launch else None
    return {
        "delegated_launches": sum(row["count"] for row in launches)
        if transcript_path and (launches or not partial)
        else None,
        "delegated_unpaired": sum(row["count"] for row in unpaired)
        if transcript_path and (launches or not partial)
        else None,
        "delegated_latest_launch_at": latest,
        "delegated_last_activity_at": activity,
        "delegated_quiet_since": quiet if quiet is not None and now - quiet >= 30 * 60 else None,
        "delegated_visibility": (
            "not-recorded"
            if transcript_path is None
            else "partial"
            if partial
            else "unattributed"
            if any(not row["activity_seen"] for row in unpaired)
            else "linked"
            if unpaired
            else "recorded"
        ),
    }


def claude_tool_reports(
    config: RuntimeConfig,
    transcript_path: str,
    sid: str,
    *,
    max_bytes: int | None = None,
    window_start: float | _WindowNotRequested | None = _WINDOW_NOT_REQUESTED,
    index_provider: Callable[[], Any] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """The listed checks and written paths, and the full-scan counts behind them,
    a subagent's included and labelled.

    Claude Code only, and published into the observed record only:
    [DEC-23](docs/design-reading-a-session.md#dec-23-a-claude-code-sessions-record-of-its-checks-may-show-the-work)
    """
    tally = _claude_tally(config, transcript_path, max_bytes=max_bytes)
    # Asked for after the tally has read. A message written meanwhile is later than every entry the
    # tally read, so it cannot belong to the position of one of them.
    entries = tally.entries(sid, index_provider() if index_provider is not None else None)
    if not isinstance(window_start, _WindowNotRequested):
        tally.scan["window_start"] = window_start
        tally.scan["window_written_paths"] = sum(
            write["at"] > 0 and (window_start is None or write["at"] >= window_start)
            for write in tally.writes.values()
        )
    return entries, tally.scan


def _json_dict(raw: bytes) -> dict[str, Any] | None:
    try:
        record = json.loads(raw)
    except (ValueError, RecursionError):
        return None
    return record if isinstance(record, dict) else None


class FrozenCheckCutoffUnreachableError(RuntimeError):
    """The parent's first future stamp or EOF is outside the check budget."""


def _frozen_check_scan(config: RuntimeConfig, transcript_path: str, until: float) -> _CheckScan:
    """One bounded forward pass finds each moment's cutoff and its evidence."""
    budget = _scan_budget(config)

    def future(raw: bytes) -> bool:
        record = _json_dict(raw)
        return record is not None and (at := _record_timestamp(record)) is not None and at > until

    parent_read = runtime_io.scan_stood_lines(transcript_path, budget, future)
    if not parent_read.cutoff_reached:
        raise FrozenCheckCutoffUnreachableError(
            "parent check cutoff unreachable within byte budget"
        )
    parent = _scan_records(parent_read)
    session_dir = transcript_path[: -len(".jsonl")]
    paths = sorted(
        _subagent_transcripts(transcript_path),
        key=lambda path: os.path.relpath(path, session_dir),
    )
    children: list[list[dict[str, Any]]] = []
    source_reads: list[tuple[str, runtime_io.TranscriptRead | None]] = [
        (transcript_path, parent_read)
    ]
    read_ids: set[str] = set()
    unread_ids: set[str] = set()
    unread = 0
    horizon: float | None = None
    for path in paths:
        read = (
            runtime_io.scan_stood_lines(path, budget, future, follow_links=False)
            if budget.remaining
            else None
        )
        source_reads.append((path, read))
        if read is not None and read.cutoff_reached:
            got = _scan_records(read)
            if got:
                children.append(got)
                read_ids.add(_child_id(path))
                continue
            if read.byte_end and not read.lines:
                # Its first stamped record is later than the frozen moment.
                continue
        unread += 1
        unread_ids.add(_child_id(path))
        mtime = _mtime(path)
        horizon = _later(horizon, until if mtime is None else min(mtime, until))
    missing = _named_agent_ids(parent) - read_ids
    unread += len(missing - unread_ids)
    return _CheckScan(
        parent,
        children,
        unread,
        horizon,
        bool(missing),
        parent_read.failed,
        False,
        budget,
        tuple(source_reads),
        _session_directory(config, transcript_path, parent),
    )


def frozen_claude_checks(
    config: RuntimeConfig, transcript_path: str, sid: str, *, until: float
) -> tuple[list[dict[str, Any]], PressChecks]:
    """The check facts and press reads as the transcript stood at `until`.

    For the abstention packet (DRC-4666). The latest run, `earlier_failed` and
    `before_last_change` are computed over the whole transcript, so filtering
    today's facts to those dated at or before `until` would keep a pass a later
    run overturned. The transcript is append-only, so its prefix up to the
    first record stamped after `until` is what a press at that moment read.
    The bounded forward lookup spends from the same check budget as its
    children; an unreachable parent cutoff refuses the frozen read.
    """
    scan = _frozen_check_scan(config, transcript_path, until)
    tally = _tally_of(
        scan.parent,
        scan.children,
        scan.unread,
        scan.horizon,
        named_unread=scan.named_unread,
        parent_failed=scan.parent_failed,
        session_dir=scan.session_dir,
    )
    facts = [
        _semantic_fact_from_event(row, str(row["kind"]), _SEMANTIC_FACT_TYPES[row["kind"]], "")
        for row in tally.entries(sid)
    ]
    return facts, _press(tally)


def _user_message_facts(
    config: RuntimeConfig, lines: Iterable[str], sid: str, until: float
) -> list[dict[str, Any]]:
    """`instruction_events` over these lines, cut at `until`, as `collect` publishes them."""
    facts: list[dict[str, Any]] = []
    seen: set[tuple[float, str]] = set()
    for raw in lines:
        if not raw or not raw.lstrip().startswith("{"):
            continue
        try:
            record = json.loads(raw)
        except (ValueError, RecursionError):
            continue
        event = _instruction_event(config, record, "claude", sid)
        if event is None or float(event["at"]) > until:
            continue
        key = (event["at"], event["title"])
        if key in seen:
            continue
        seen.add(key)
        facts.append(_semantic_fact_from_event(event, "steer", _SEMANTIC_FACT_TYPES["steer"], ""))
    return facts


TRANSCRIPT_USER_CACHE_ENTRIES = 8
TRANSCRIPT_USER_FACTS_MAX = 4096


def transcript_stamp(path: str) -> tuple[int, int, int, int] | None:
    """Identity of the regular file whose facts a press is about to collect."""
    try:
        value = os.stat(path)
    except OSError:
        return None
    return (
        (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns)
        if stat.S_ISREG(value.st_mode)
        else None
    )


def transcript_tail_coverage(
    config: RuntimeConfig, path: str, *, expected_stamp: tuple[int, int, int, int] | None = None
) -> dict[str, Any]:
    """Press-only size and time measurements, with unknowns when the file moves."""
    unknown = {"tail_truncated": None, "tail_start": None}
    try:
        before = os.stat(path)
        if not stat.S_ISREG(before.st_mode):
            return unknown
        if expected_stamp is not None and expected_stamp != (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
        ):
            return unknown
        lines = runtime_io.read_tail(config, path)
        times = [
            at
            for line in lines
            if (record := _json_dict(line.encode("utf-8"))) is not None
            and (at := _record_timestamp(record)) is not None
        ]
        after = os.stat(path)
        if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
        ):
            return unknown
    except OSError:
        return unknown
    return {
        "tail_truncated": before.st_size > config.tail_bytes,
        "tail_start": min(times) if times else None,
    }


def _masked_window_words(config: RuntimeConfig, text: str, harness: str) -> str:
    """Mask raw person words without letting a cue consume native closing tags."""
    command = transcripts.command_direction(config, text) if harness == "claude" else None
    if command is None:
        return records.mask_prose(text)
    # Keep raw line breaks for split credentials: rendering first would fold
    # them before masking. Whitespace separates the original field delimiters
    # from their values; it adds no closing tag to a genuinely cut record.
    framed = records.mask_prose(text.replace("</command-", " </command-"))
    return transcripts.command_direction(config, framed) or ""


def transcript_window_words(
    config: RuntimeConfig,
    path: str,
    harness: str,
    sid: str,
    wanted: Sequence[Mapping[str, Any]],
    *,
    expected_stamp: tuple[int, int, int, int] | None = None,
) -> list[dict[str, Any]]:
    """Verify already-listed in-window person sources under the backfill byte bound.

    The producer passes its filtered ledger, so this never widens the citable
    list or sends words from before its window or after its stop. Recent source
    records are scanned without caching or publishing raw words. Conflicting
    raw sources invalidate an identity even when masking would make them equal.
    """
    if harness not in {"claude", "codex"}:
        return []
    identities = {
        (entry.get("id"), entry.get("at"))
        for entry in wanted
        if entry.get("type") == "user_message" and entry.get("author") == "person"
    }
    before = transcript_stamp(path)
    if (
        not identities
        or before is None
        or (expected_stamp is not None and before != expected_stamp)
    ):
        return []
    found: dict[tuple[Any, Any], tuple[str, dict[str, Any]]] = {}
    ambiguous: set[tuple[Any, Any]] = set()
    try:
        for raw in runtime_io.reverse_lines(
            config, path, end_pos=before[2], max_bytes=SEMANTIC_BACKFILL_MAX_BYTES
        ):
            record = _json_dict(raw)
            event = _instruction_event(config, record, harness, sid)
            if event is None:
                continue
            fact = _semantic_fact_from_event(event, "steer", "user_message", "")
            key = (fact["fact_id"], fact["at"])
            if key not in identities:
                continue
            message = observer.parse_reader_record(record, cap=len(raw))
            if message is None:
                continue
            text = message["text"]
            # The eligibility parser has already redacted values. Compare a
            # bounded raw-content fingerprint before accepting this identity;
            # equal redacted words cannot vouch for equal source records.
            content = (
                records.as_dict(record.get("payload")).get("content")
                if record is not None and record.get("type") == "response_item"
                else observer.reader_source_content(record)
                or records.message_dict(record).get("content")
            )
            signature = hashlib.sha256(
                json.dumps(content, sort_keys=True, ensure_ascii=False).encode("utf-8", "replace")
            ).hexdigest()
            masked = _masked_window_words(config, text, harness)
            previous = found.get(key)
            if previous is not None and previous[0] != signature:
                ambiguous.add(key)
            fact[READER_WORDS_FIELD] = records.safe_text(
                " ".join(masked.split()), READER_WORDS_CAP_CHARS
            )
            found[key] = (signature, fact)
    except OSError:
        return []
    if transcript_stamp(path) != before:
        return []
    return [fact for key, (_, fact) in found.items() if key not in ambiguous]


def _final_signature(record: dict[str, Any]) -> bytes:
    """A pre-mask fingerprint of every field that decides whether a reply is final.

    Stop reason, model, time, session and the child markers ride with the content, so two
    records sharing a UUID but differing in any of them conflict, and equal masked words
    cannot hide it. Sixteen bytes of the digest, because one is held per assistant UUID.
    """
    message = records.message_dict(record)
    shape = {
        "type": record.get("type"),
        "role": message.get("role"),
        "content": message.get("content"),
        "stop": message.get("stop_reason"),
        "model": message.get("model"),
        "at": record.get("timestamp"),
        "sid": record.get("sessionId"),
        "side": record.get("isSidechain"),
        "meta": record.get("isMeta"),
        "child": record.get("agentId"),
    }
    return hashlib.sha256(
        json.dumps(shape, sort_keys=True, ensure_ascii=False, default=str).encode(
            "utf-8", "replace"
        )
    ).digest()[:16]


def _agent_whole_words(record: dict[str, Any], size: int) -> str | None:
    """A reply's text whole, as `_agent_message_event` reads it: one line, masked, unclipped.

    The same masking and spacing as the 1,000-character excerpt, so the excerpt is the
    start of these words. `size` is the record's own byte length, a bound its text cannot
    pass. None where the words are longer than `FINAL_WORDS_MAX_CHARS`, which no prompt
    could carry, so a reply that long is never copied.
    """
    full = observer.parse_message_record(record, cap=size)
    if full is None or len(full["text"]) > FINAL_WORDS_MAX_CHARS:
        return None
    words = records.safe_text(
        " ".join(records.mask_prose(full["text"]).split()), FINAL_WORDS_MAX_CHARS + 1
    )
    return words if len(words) <= FINAL_WORDS_MAX_CHARS else None


def _final_status(record: dict[str, Any], sid: str, uuid: Any) -> str:
    """`final` for a recorded end of turn, `nonfinal` for another recorded stop, else `refused`.

    Only the record's own `message.stop_reason` says a turn ended: text with no tool block, a
    quiet session and a newer timestamp are each how a mid-turn message looks.
    """
    if (
        not isinstance(uuid, str)
        or not uuid
        or record.get("sessionId") != sid
        or record.get("isSidechain")
        or record.get("isMeta")
        or record.get("agentId")
    ):
        return "refused"
    stop = records.message_dict(record).get("stop_reason")
    if stop == FINAL_WORDS_STOP_REASON:
        return "final"
    return "nonfinal" if isinstance(stop, str) and stop else "refused"


def _final_source_sid(path: str, harness: str, sid: str) -> str:
    """Bind a shortened Claude key to its complete native transcript identity."""
    stem = os.path.basename(path).removesuffix(".jsonl")
    if (
        harness == "claude"
        and path.endswith(".jsonl")
        and re.fullmatch(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", stem)
        and events.normalize_session_id(harness, stem) == sid
    ):
        return stem
    return sid


def transcript_newest_final_words(  # noqa: C901, PLR0911, PLR0912, PLR0915 - one bounded scan and its source guards
    config: RuntimeConfig,
    path: str,
    harness: str,
    sid: str,
    wanted: Sequence[Mapping[str, Any]],
    *,
    expected_stamp: tuple[int, int, int, int] | None = None,
) -> dict[str, Any]:
    """The newest selected recorded final reply, whole, as private press-only words.

    `wanted` is the selection the model is about to receive, so a record outside it is never
    restored. A reply qualifies only on its own recorded `end_turn`, and only when it is the
    unique newest such reply among the selected rows with no newer selected row the source
    cannot prove non-final. The expected stamp is the source version the press read its facts
    from; the file must match it before the scan and still after. The scan is memory-only,
    newest first, and only a complete file within `FINAL_WORDS_SCAN_MAX_BYTES` qualifies;
    nothing is cached or kept. A tail cannot prove an earlier duplicate is absent.

    The result names no path, session or source fingerprint: only an outcome token, the
    row's own identity and, on success, the words. Why whole words and why only this one:
    docs/design-reading-a-session.md#amended-2026-10-05-owner-the-newest-recorded-final-reply-is-read-whole
    """
    rows = {
        (str(entry.get("id")), entry.get("at")): entry
        for entry in wanted
        if entry.get("type") == "agent_message" and entry.get("author") == "agent"
    }
    if harness not in AGENT_MESSAGE_HARNESSES or not rows:
        return {"outcome": "none"}
    before = transcript_stamp(path)
    if before is None or expected_stamp is None or before != expected_stamp:
        return {"outcome": "source-moved"}
    if before[2] > FINAL_WORDS_SCAN_MAX_BYTES:
        return {"outcome": "scan-limit"}
    source_sid = _final_source_sid(path, harness, sid)
    # Words are None for a candidate too long for any prompt: still a final, never a copy.
    found: dict[tuple[str, Any], tuple[str, str, str | None]] = {}
    signatures: dict[str, bytes] = {}
    conflicted: set[str] = set()
    scanned_bytes = 0
    try:
        for raw in runtime_io.reverse_lines(
            config, path, end_pos=before[2], max_bytes=FINAL_WORDS_SCAN_MAX_BYTES
        ):
            # Every complete line contributes its bytes plus one separator; the final
            # unterminated (or empty trailing) line contributes the extra one. The walker
            # can stop silently on a short read or I/O error, so exhaustiveness is checked.
            scanned_bytes += len(raw) + 1
            # JSON escapes can encode the assistant type or its key. Parse those
            # candidates within the same record bound; literal-only tool artifacts
            # still skip decoding. Representation cannot hide a parent or duplicate.
            escaped = b"\\u" in raw
            if b'"assistant"' not in raw and not escaped:
                continue
            if len(raw) > FINAL_WORDS_RECORD_MAX_BYTES:
                # An escaped oversized shape may be an assistant record, but proving
                # that would exceed the bound. Refuse it without decoding any words.
                if escaped or _ASSISTANT_TYPE_RE.search(raw):
                    return {"outcome": "oversized"}
                continue
            record = _json_dict(raw)
            if record is None or record.get("type") != "assistant":
                continue
            # Normalization cannot merge distinct native parents sharing a display key.
            # A complete scan must agree with the file identity, including unselected replies.
            if (
                source_sid != sid
                and not record.get("isSidechain")
                and not record.get("isMeta")
                and not record.get("agentId")
                and record.get("sessionId") != source_sid
            ):
                return {"outcome": "unproven"}
            uuid = record.get("uuid")
            signature = _final_signature(record)
            if isinstance(uuid, str) and uuid:
                previous = signatures.get(uuid)
                if previous is not None:
                    if previous != signature:
                        conflicted.add(uuid)
                    # Compare every duplicate for source conflicts, but recover its
                    # identity and words only once during this memory-only scan.
                    continue
                signatures[uuid] = signature
                if len(signatures) > FINAL_WORDS_UUIDS_MAX:
                    return {"outcome": "scan-limit"}
            # Identity needs only the existing bounded title/time/UUID; full words
            # are measured separately and rejected before their expensive prose mask.
            event = _agent_message_event(config, record, harness, sid)
            if event is None:
                continue
            fact = _semantic_fact_from_event(event, _AGENT_SAY, "agent_message", "")
            key = (str(fact["fact_id"]), fact["at"])
            if key not in rows:
                continue
            status = _final_status(record, source_sid, uuid)
            if key in found and found[key][0] != status:
                status = "refused"
            found[key] = (
                status,
                str(uuid or ""),
                _agent_whole_words(record, len(raw)) if status == "final" else "",
            )
    except OSError:
        return {"outcome": "source-moved"}
    if transcript_stamp(path) != before:
        return {"outcome": "source-moved"}
    if scanned_bytes != before[2] + 1:
        return {"outcome": "unproven"}
    finals = {
        key: found[key]
        for key in rows
        if key in found and found[key][0] == "final" and found[key][1] not in conflicted
    }
    if not finals:
        if any(
            key not in found or found[key][0] == "refused" or found[key][1] in conflicted
            for key in rows
        ):
            return {"outcome": "unproven"}
        return {"outcome": "not-final"}
    top = max(float(at) for _, at in finals)
    newest = [key for key in finals if float(key[1]) == top]
    if len(newest) != 1:
        return {"outcome": "ambiguous"}
    for key, row in rows.items():
        proven = found.get(key)
        if (
            (proven is None or proven[0] == "refused" or proven[1] in conflicted)
            and isinstance(row.get("at"), int | float)
            and float(row["at"]) >= top
        ):
            return {"outcome": "unproven"}
    fact_id, at = newest[0]
    words = finals[newest[0]][2]
    if words is None:
        return {"outcome": "too-long", "fact_id": fact_id, "at": at}
    if not words:
        return {"outcome": "not-final"}
    return {"outcome": "whole", "fact_id": fact_id, "at": at, "words": words}


def transcript_user_facts(
    config: RuntimeConfig,
    state: RuntimeState,
    path: str,
    harness: str,
    sid: str,
    *,
    goal_choices: bool = False,
    coverage: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Press-only user words from bounded newest and opening reads, never the ledger.

    The opening read restores adopted prompts that left the tail; the newest
    read restores recent choices and line sources. They share one clock, skip
    incomplete boundary records and report any unread gap through `coverage`.
    Cache only redacted, capped words and give each caller
    its own copy.
    The uncached goal-menu arm additionally masks named forms before folding raw
    separators; it never changes the default Analyze words or their cache.
    """
    if coverage is not None:
        coverage.update(state="unavailable", bound=None)
    source_version = transcript_stamp(path) if harness in {"claude", "codex"} else None
    if source_version is None:
        return []
    key = (path, harness, sid)
    try:
        with state.cache_lock:
            cached = state.transcript_user_cache.get(key)
            if (
                not goal_choices
                and coverage is None
                and cached is not None
                and cached[0] == source_version
            ):
                return copy.deepcopy(cached[1])
        facts = _read_user_sources(
            config, path, harness, sid, source_version, goal_choices, coverage
        )
        if facts is None:
            return []
        after = os.stat(path)
        if (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns) != source_version:
            return _failed_user_read(coverage)
        for fact in facts:
            fact["request_source_stamp"] = source_version
    except OSError:
        return _failed_user_read(coverage)
    if not goal_choices:
        with state.cache_lock:
            runtime_state.bounded_put(
                state.transcript_user_cache,
                key,
                (source_version, facts),
                limit=TRANSCRIPT_USER_CACHE_ENTRIES,
            )
    return copy.deepcopy(facts)


def _failed_user_read(coverage: dict[str, Any] | None) -> list[dict[str, Any]]:
    if coverage is not None:
        coverage.update(state="unavailable", bound=None)
    return []


def _read_user_sources(
    config: RuntimeConfig,
    path: str,
    harness: str,
    sid: str,
    source_version: tuple[int, int, int, int],
    goal_choices: bool,
    coverage: dict[str, Any] | None,
) -> list[dict[str, Any]] | None:
    """Share one clock across newest and opening coverage; never scan overlapping records."""
    from . import record_pages  # noqa: PLC0415 - shared reader imports the fact builders

    deadline = time.monotonic() + config.direction_scan_max_seconds
    scans: list[record_pages.SourceScan] = []

    def read(visit: Callable[[bytes], None]) -> None:
        tail = record_pages.scan_source(
            config,
            path,
            visit,
            max_bytes=config.direction_scan_max_bytes,
            deadline=deadline,
            expected_stamp=source_version,
        )
        scans.append(tail)
        if tail.state == "ok" and not tail.reached_start:
            scans.append(
                record_pages.scan_source(
                    config,
                    path,
                    visit,
                    max_bytes=SEMANTIC_BACKFILL_MAX_BYTES,
                    deadline=deadline,
                    end=min(SEMANTIC_BACKFILL_MAX_BYTES - 1, tail.start),
                    expected_stamp=source_version,
                )
            )

    facts = _transcript_user_scan(config, b"", harness, sid, goal_choices=goal_choices, read=read)
    if any(scan.state != "ok" for scan in scans):
        if coverage is not None:
            coverage.update(state="unavailable", bound=None)
        return None
    complete = scans[0].reached_start or (
        len(scans) == 2 and scans[1].reached_start and scans[0].start < SEMANTIC_BACKFILL_MAX_BYTES
    )
    if coverage is not None:
        coverage.update(
            state="ok",
            bound=None
            if complete and not any(scan.skipped for scan in scans)
            else "time"
            if any(scan.bound == "time" for scan in scans)
            else "bytes",
            scanned_bytes=sum(scan.scanned_bytes for scan in scans),
        )
    return facts


def _instruction_facts(
    config: RuntimeConfig, raw: bytes, harness: str, sid: str
) -> Iterable[tuple[dict[str, Any], dict[str, Any], bytes]]:
    """The same bounded records used by the words and their private source proof."""
    for line in raw.splitlines():
        if not _could_be_instruction(line, harness):
            continue
        try:
            record = json.loads(line)
        except (ValueError, RecursionError):
            continue
        event = _instruction_event(config, record, harness, sid)
        if event is not None:
            yield record, _semantic_fact_from_event(event, "steer", "user_message", ""), line


def _remember_request(
    fact: dict[str, Any],
    *,
    full: bool,
    seen: set[str],
    times: dict[str, set[str]],
    ambiguous: set[str],
) -> bool:
    """Check ambiguity after the fact cap while keeping proof memory bounded."""
    fact_id, at = str(fact["fact_id"]), str(fact.get("at"))
    previous = times.get(at, set())
    ambiguous.update(previous)
    if full and fact_id not in seen:
        return False
    if previous or fact_id in seen:
        ambiguous.add(fact_id)
    seen.add(fact_id)
    times.setdefault(at, set()).add(fact_id)
    return True


def _complete_request_digest(source: DirectionText) -> str:
    """Only a complete, redacted request can prove these exact words were asked."""
    if source.cut or not source.text.strip():
        return ""
    masked = records.mask_prose(source.text)
    normalised = records.safe_text(masked, len(masked) + 1)
    return hashlib.sha256(
        json.dumps(normalised, ensure_ascii=True, separators=(",", ":")).encode()
    ).hexdigest()


def _user_source_slot(facts: list[dict[str, Any]], fact: dict[str, Any]) -> dict[str, Any] | None:
    """Reserve the oldest source as well as the newest facts when the fact allowance fills."""
    ordered = sorted([*facts, fact], key=lambda item: float(item["at"]))
    retained = ordered[:1] + (
        ordered[-(TRANSCRIPT_USER_FACTS_MAX - 1) :] if TRANSCRIPT_USER_FACTS_MAX > 1 else []
    )
    if fact not in retained:
        return None
    evicted = next(item for item in facts if item not in retained)
    facts.remove(evicted)
    return evicted


def _forget_user_source(
    evicted: dict[str, Any],
    request_seen: set[str],
    request_ambiguous: set[str],
    goal_sources: dict[str, tuple[DirectionText, bytes]],
    seen: set[tuple[str, str]],
    request_times: dict[str, set[str]],
) -> None:
    old_id = str(evicted["fact_id"])
    request_seen.discard(old_id)
    request_ambiguous.discard(old_id)
    goal_sources.pop(old_id, None)
    seen.difference_update({key for key in seen if key[0] == old_id})
    old_time = str(evicted.get("at"))
    request_times.get(old_time, set()).discard(old_id)
    if not request_times.get(old_time):
        request_times.pop(old_time, None)


def _admit_user_source(
    facts: list[dict[str, Any]],
    fact: dict[str, Any],
    request_seen: set[str],
    request_ambiguous: set[str],
    goal_sources: dict[str, tuple[DirectionText, bytes]],
    seen: set[tuple[str, str]],
    request_times: dict[str, set[str]],
) -> bool:
    fact_id = str(fact["fact_id"])
    previous = request_times.get(str(fact.get("at")), set())
    collision = bool(previous)
    # A same-time record can disprove a retained request even when it earns no
    # returned slot. Record that before eviction removes the earlier identity.
    request_ambiguous.update(previous)
    if fact_id not in request_seen and len(facts) >= TRANSCRIPT_USER_FACTS_MAX:
        evicted = _user_source_slot(facts, fact)
        if evicted is None:
            return False
        _forget_user_source(
            evicted, request_seen, request_ambiguous, goal_sources, seen, request_times
        )
    if collision:
        request_ambiguous.add(fact_id)
    return True


def _transcript_user_scan(
    config: RuntimeConfig,
    raw: bytes,
    harness: str,
    sid: str,
    *,
    goal_choices: bool = False,
    read: Callable[[Callable[[bytes], None]], None] | None = None,
) -> list[dict[str, Any]]:
    facts: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    goal_sources: dict[str, tuple[DirectionText, bytes]] = {}
    ambiguous: set[str] = set()
    request_seen: set[str] = set()
    request_times: dict[str, set[str]] = {}
    request_ambiguous: set[str] = set()

    def consume(line: bytes) -> None:
        item = next(iter(_instruction_facts(config, line, harness, sid)), None)
        if item is None:
            return
        record, fact, line = item
        fact_id = str(fact["fact_id"])
        if not _admit_user_source(
            facts, fact, request_seen, request_ambiguous, goal_sources, seen, request_times
        ):
            return
        if not _remember_request(
            fact,
            full=len(facts) >= TRANSCRIPT_USER_FACTS_MAX,
            seen=request_seen,
            times=request_times,
            ambiguous=request_ambiguous,
        ):
            return
        fact["request_source_digest"] = hashlib.sha256(line).hexdigest()
        source_words = _direction_words(config, record, harness)
        fact["request_words_digest"] = _complete_request_digest(source_words)
        if goal_choices:
            fact_id = str(fact["fact_id"])
            # The returned list stays bounded, but a later conflicting source
            # inside the byte budget must still invalidate an offered identity.
            previous = goal_sources.get(fact_id)
            source = (source_words, _direction_signature(record, harness))
            if previous is not None and previous != source:
                ambiguous.add(fact_id)
            goal_sources[fact_id] = source
            # This uncached menu-only arm sees raw separators before masking;
            # the default Analyze words and its cache remain unchanged.
            fact[READER_WORDS_FIELD] = records.safe_text(
                " ".join(records.mask_prose(source_words.text).split()), READER_WORDS_CAP_CHARS
            )
            fact[records.GOAL_SOURCE_CUT_FIELD] = source_words.cut
        key = (str(fact["fact_id"]), str(fact.get(READER_WORDS_FIELD) or ""))
        if key in seen:
            return
        seen.add(key)
        if len(facts) < TRANSCRIPT_USER_FACTS_MAX:
            facts.append(fact)

    _feed_user_scan(raw, consume, read)
    return _checked_user_facts(facts, goal_choices, request_ambiguous, ambiguous)


def _feed_user_scan(
    raw: bytes,
    consume: Callable[[bytes], None],
    read: Callable[[Callable[[bytes], None]], None] | None,
) -> None:
    if read is None:
        for line in raw.splitlines():
            consume(line)
    else:
        read(consume)


def _checked_user_facts(
    facts: list[dict[str, Any]],
    goal_choices: bool,
    request_ambiguous: set[str],
    ambiguous: set[str],
) -> list[dict[str, Any]]:
    if goal_choices:
        facts.sort(key=lambda fact: -float(fact["at"]))
    else:
        facts.sort(key=lambda fact: float(fact["at"]))
    # Keep an empty, verified source match for an ambiguous identity, so a
    # menu caller cannot fall back to its already-folded published words.
    for fact in facts:
        if str(fact["fact_id"]) in request_ambiguous:
            fact["request_source_digest"] = ""
    return [
        {**fact, READER_WORDS_FIELD: ""} if str(fact["fact_id"]) in ambiguous else fact
        for fact in facts
    ]


def frozen_claude_user_messages(
    config: RuntimeConfig, transcript_path: str, sid: str, *, until: float, size: int | None = None
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """The user-message facts a Claude Code transcript held at `until`: all, and the board's tail.

    For the abstention scorer's score-time check (DRC-4711), beside
    `frozen_claude_checks`. Measured 2026-09-27 on a scratch board over three
    recorded sessions: a user message is the only non-check fact such a case
    carries, and this reproduced the board's ledger rows for it. The first
    list reads the whole file; the second reads the bounded tail `collect`
    reads (`io.read_tail`), ending at `size`, the file's length when the case
    was frozen. The board read a file no larger than that, so its tail reached
    at least as far back; ending at today's length instead lets a session that
    ran on past `tail_bytes` leave that tail holding no message (review N3).
    """
    with open(transcript_path, encoding="utf-8", errors="replace") as handle:
        whole = _user_message_facts(config, handle, sid, until)
    lines = runtime_io.read_tail(config, transcript_path, end=size)
    tail = _user_message_facts(config, lines, sid, until)
    return whole, tail


def frozen_claude_agent_messages(
    config: RuntimeConfig, transcript_path: str, sid: str, *, until: float, size: int | None = None
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """The agent-message facts a Claude Code transcript held at `until`: all, and the board's tail.

    `frozen_claude_user_messages`' twin, so an offline replay builds the ledger the board
    builds now that the agent's messages are evidence (owner ruling, 2026-10-03). The same
    two reads, each cut at `until`; the tail ends at `size` for the same reason.
    """

    def facts(lines: Iterable[str]) -> list[dict[str, Any]]:
        return [
            _semantic_fact_from_event(event, _AGENT_SAY, _SEMANTIC_FACT_TYPES[_AGENT_SAY], "")
            for event in _agent_message_lines(config, lines, "claude", sid)
            if float(event["at"]) <= until
        ]

    with open(transcript_path, encoding="utf-8", errors="replace") as handle:
        whole = facts(handle)
    return whole, facts(runtime_io.read_tail(config, transcript_path, end=size))


def claude_activity_between(transcript_path: str, after: float, until: float) -> bool:
    """Whether a user/assistant message was recorded after `after` and through `until`.

    Administrative records such as trailing turn_duration do not resume work.
    Tool results remain messages (Claude serializes them in user records).
    """
    with open(transcript_path, "rb") as handle:
        for raw in handle:
            try:
                record = json.loads(raw)
            except (ValueError, RecursionError):
                continue
            if not isinstance(record, dict) or record.get("type") not in {"user", "assistant"}:
                continue
            at = _record_timestamp(record)
            if at is not None and after < at <= until:
                return True
    return False


def _window_start(value: Any) -> float | None:
    return (
        float(value)
        if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
        else None
    )


def _assessment_window_start(session: Mapping[str, Any]) -> float | None:
    """The stored reading's cutoff, not the newest intent revision's cutoff."""
    assessment = session.get("annotation_assessment")
    if not isinstance(assessment, dict):
        return None
    opened = _window_start(assessment.get("window_start"))
    if opened is not None:
        return opened
    fallback = (
        assessment.get("goal_source_at")
        if assessment.get("goal_source") in {"latest-prompt", "first-prompt", "chosen-prompt"}
        else assessment.get("revision_read_at")
    )
    return _window_start(fallback)


def _index_provider(
    config: RuntimeConfig, state: RuntimeState, transcript_path: str, harness: str, sid: str
) -> Callable[[], entry_numbers.MessageIndex | None]:
    """The session's message index, asked for when its entries are counted rather than when read."""

    def provide() -> entry_numbers.MessageIndex | None:
        return entry_numbers.message_index(config, state, transcript_path, harness, sid)

    return provide


def _session_work_evidence(
    config: RuntimeConfig,
    transcript_path: str,
    session: Mapping[str, Any],
    events: list[dict[str, Any]],
    tool_report_scans: list[dict[str, Any]],
    index_provider: Callable[[], Any] | None = None,
) -> dict[str, int]:
    """Pi's demonstrated results and Claude Code's checks, appended for `collect`.

    Not for the history source: `_semantic_history_source_events` calls
    `_work_evidence` alone, which is what keeps the checks out of the store.
    """
    harness, sid = str(session.get("harness") or ""), str(session.get("sid") or "")
    identity = {"harness": harness, "sid": sid}
    rows, support = _work_evidence(config, transcript_path, harness, sid)
    events.extend(rows)
    if harness == "claude":
        report_rows, scan = claude_tool_reports(
            config,
            transcript_path,
            sid,
            window_start=_assessment_window_start(session),
            index_provider=index_provider,
        )
        events.extend(report_rows)
        tool_report_scans.append({**identity, **scan})
    return support


def instruction_events(
    config: RuntimeConfig,
    transcript_path: str,
    harness: str,
    sid: str,
    *,
    max_bytes: int | None = None,
    since: float | None = None,
) -> list[dict[str, Any]]:
    """Timestamped non-meta user-role messages from the bounded transcript tail."""
    events: list[dict[str, Any]] = []
    seen: set[tuple[float, str]] = set()
    # A directions file was checked link-free by its resolver; do not follow
    # one swapped in since.
    follow = harness not in observer.DIRECTION_HARNESSES
    source = (
        [
            line.decode("utf-8", "replace")
            for line in reversed(
                list(
                    runtime_io.reverse_lines(
                        config, transcript_path, max_bytes=max_bytes, follow_links=follow
                    )
                )
            )
        ]
        if max_bytes is not None
        else runtime_io.read_tail(config, transcript_path, follow_links=follow)
    )
    for raw in source:
        if not raw or not raw.lstrip().startswith("{"):
            continue
        try:
            record = json.loads(raw)
        except (ValueError, json.JSONDecodeError, RecursionError):
            continue
        event = _instruction_event(config, record, harness, sid)
        if event is None:
            continue
        if since is not None and float(event.get("at") or 0) < since:
            continue
        key = (event["at"], event["title"])
        if key in seen:
            continue
        seen.add(key)
        events.append(event)
    return events


# Whole scans a direction lookup tries before it answers `changed`. Three is two retries after the
# first, which at the measured 0.2 to 1.4 s a scan keeps the worst case near the 2 s per-scan clock
# times three.
DIRECTION_SCAN_ATTEMPTS = 3


class DirectionText(NamedTuple):
    """A direction's text for review, and whether the record reader cut it short.

    `cut` covers what the text's own length cannot show: a slash command whose
    arguments lost their closing tag renders shorter than the cap it was cut at.
    """

    text: str
    cut: bool = False


class DirectionLookup(NamedTuple):
    """Private source coverage; only the refusal token and reviewed words leave it."""

    words: DirectionText
    reason: str = "not_found"
    scanned_bytes: int = 0
    at: float | None = None
    fact: dict[str, Any] | None = None


def _could_be_instruction(raw: bytes, harness: str) -> bool:
    if b"\\u" in raw:
        return True
    if harness == "claude":
        return (
            bool(re.search(rb'"type"\s*:\s*"user"', raw))
            and (b'"tool_result"' not in raw or b'"text"' in raw or b'"answers"' in raw)
        ) or (b'"queued_command"' in raw and b'"human"' in raw)
    if harness == "codex":
        return bool(re.search(rb'"role"\s*:\s*"user"', raw))
    return True


def direction_text(
    config: RuntimeConfig, state: RuntimeState, harness: str, sid: str, fact_id: str
) -> DirectionText:
    """The source words of one direction, verified by its published fact id."""
    return direction_lookup(config, state, harness, sid, fact_id).words


def direction_lookup(
    config: RuntimeConfig, state: RuntimeState, harness: str, sid: str, fact_id: str
) -> DirectionLookup:
    """Open one fact through the same stateless scan as a batch."""
    return direction_lookups(config, state, harness, sid, [fact_id])[0]


def _direction_result(
    match: tuple[bytes, DirectionText, dict[str, Any]] | None,
    ambiguous: bool,
    stable: bool,
    bounded: bool,
    scanned: int,
    *,
    changed: bool = False,
) -> DirectionLookup:
    if changed:
        return DirectionLookup(DirectionText(""), "changed", scanned)
    if not stable or ambiguous:
        return DirectionLookup(DirectionText(""), "not_found", scanned)
    if match is not None:
        _, words, fact = match
        return DirectionLookup(words, "", scanned, float(fact["at"]), fact)
    return DirectionLookup(DirectionText(""), "out_of_reach" if bounded else "not_found", scanned)


def _direction_scan_once(
    config: RuntimeConfig,
    path: str,
    harness: str,
    stamp: tuple[int, int, int, int],
    visit: Callable[[bytes], None],
) -> tuple[int, bool, bool, bool] | None:
    """One whole scan: bytes scanned, whether coverage is bounded, stable, and moved.

    `moved` is true only when the file changed under the scan, the one outcome a retry can fix.
    None is a source that could not be read at all.
    """
    from . import record_pages  # noqa: PLC0415 - shared reader imports the fact builders

    if harness in record_pages.HARNESSES:
        scan = record_pages.scan_source(
            config,
            path,
            visit,
            max_bytes=config.direction_scan_max_bytes,
            deadline=time.monotonic() + config.direction_scan_max_seconds,
            expected_stamp=stamp,
        )
        return (
            scan.scanned_bytes,
            not scan.reached_start or scan.skipped,
            scan.state == "ok",
            scan.state == "stale",
        )
    try:
        for line in runtime_io.read_tail(
            config, path, follow_links=harness not in observer.DIRECTION_HARNESSES
        ):
            visit(line.encode())
    except OSError:
        return None
    return 0, False, True, False


def _direction_visitor(
    config: RuntimeConfig,
    harness: str,
    sid: str,
    wanted: set[str],
    matches: dict[str, tuple[bytes, DirectionText, dict[str, Any]]],
    ambiguous: set[str],
) -> Callable[[bytes], None]:
    def visit(raw: bytes) -> None:
        for record, fact, _ in _instruction_facts(config, raw, harness, sid):
            fact_id = str(fact["fact_id"])
            if fact_id not in wanted:
                continue
            signature = _direction_signature(record, harness)
            previous = matches.get(fact_id)
            if previous is not None and previous[0] != signature:
                ambiguous.add(fact_id)
            elif previous is None:
                matches[fact_id] = (signature, _direction_words(config, record, harness), fact)

    return visit


def direction_lookups(
    config: RuntimeConfig, state: RuntimeState, harness: str, sid: str, fact_ids: list[str]
) -> list[DirectionLookup]:
    """Verify every requested identity in one scan, retaining request order.

    docs/design-reading-a-session.md#long-session-direction-and-prompt-reads
    owns the bounded ambiguity guarantee and the unsearched-source limit.
    """
    path = observer.resolve_transcript(config, state, harness, sid) or observer.resolve_directions(
        config, state, harness, sid
    )
    wanted = set(fact_ids)
    matches: dict[str, tuple[bytes, DirectionText, dict[str, Any]]] = {}
    ambiguous: set[str] = set()

    visit = _direction_visitor(config, harness, sid, wanted, matches, ambiguous)

    # A working session appends to its record every few seconds, and a press that lands while
    # the agent writes would otherwise be refused at random. Each attempt is a whole scan of an
    # unchanged file, so the ruling that an append refuses the read holds; only the number of
    # tries is new. Measured 2026-10-14: the page's Keep failed five times in five on a live
    # session because the tool result was written 0.5 s into a 1.4 s scan.
    for _ in range(DIRECTION_SCAN_ATTEMPTS):
        stamp = transcript_stamp(path) if path else None
        if not path or stamp is None:
            return [DirectionLookup(DirectionText("")) for _ in fact_ids]
        matches.clear()
        ambiguous.clear()
        outcome = _direction_scan_once(config, path, harness, stamp, visit)
        if outcome is None:
            return [DirectionLookup(DirectionText("")) for _ in fact_ids]
        scanned, bounded, stable, moved = outcome
        if stable and transcript_stamp(path) != stamp:
            stable, moved = False, True
        if not moved:
            break
    return [
        _direction_result(
            matches.get(fact_id),
            fact_id in ambiguous,
            stable,
            bounded,
            scanned,
            changed=moved,
        )
        for fact_id in fact_ids
    ]


def _direction_signature(record: Any, harness: str) -> bytes:
    if harness in {"claude", "codex"}:
        message = records.as_dict(
            records.as_dict(record).get("payload" if harness == "codex" else "message")
        )
        source = observer.reader_source_content(record) if harness == "claude" else None
        return records.record_fingerprint(source if source is not None else message.get("content"))
    return records.record_fingerprint(record)


def _direction_words(config: RuntimeConfig, record: Any, harness: str) -> DirectionText:
    if harness in observer.DIRECTION_HARNESSES:
        direction = transcripts.antigravity_direction(record)
        return DirectionText(direction.text if direction and not direction.truncated else "")
    message = observer.parse_reader_record(record)
    if not message:
        return DirectionText("")
    text = str(message["text"])
    command = transcripts.command_direction(config, text) if harness == "claude" else None
    return (
        DirectionText(command, transcripts.command_cut(text))
        if command
        else DirectionText(text, len(text) >= records.EXTRACT_TEXT_CAP_CHARS)
    )


def _codex_dispatch_artifact(task_name: str) -> tuple[str, str, str, str] | None:
    match = _CODEX_ENSIGN_TASK_RE.fullmatch(task_name)
    if match is None:
        return None
    stem = match.group(1).replace("_", "-")
    artifact = next(
        (
            candidate
            for directory in _dispatch_directories()
            if _read_dispatch_artifact(candidate := f"{directory}/spacedock-ensign-{stem}.md")
        ),
        "",
    )
    identity = _dispatch_artifact_identity(artifact)
    if identity is None or not os.path.isfile(artifact):
        return None
    entity, stage = identity
    assignment = _dispatch_file_assignment(artifact)
    workflow = ""
    for raw in _read_dispatch_artifact(artifact).splitlines()[:80]:
        if "--workflow-dir" not in raw:
            continue
        try:
            parts = shlex.split(raw.strip())
        except ValueError:
            continue
        if "--workflow-dir" in parts:
            index = parts.index("--workflow-dir") + 1
            if index < len(parts):
                workflow = parts[index]
                break
    if not assignment or not workflow:
        return None
    return artifact, workflow, entity, stage


def codex_dispatch_events(
    config: RuntimeConfig,
    transcript_path: str,
    harness: str,
    sid: str,
    *,
    since: float,
    max_bytes: int = SEMANTIC_BACKFILL_MAX_BYTES,
) -> list[dict[str, Any]]:
    """Exact Codex spawn calls bound to readable Spacedock dispatch artifacts."""
    if harness != "codex":
        return []
    events: list[dict[str, Any]] = []
    bounded = list(runtime_io.reverse_lines(config, transcript_path, max_bytes=max_bytes))
    for raw_bytes in reversed(bounded):
        try:
            record = records.as_dict(json.loads(raw_bytes.decode("utf-8", "replace")))
        except (ValueError, json.JSONDecodeError, RecursionError):
            continue
        at = _record_timestamp(record)
        payload = records.as_dict(record.get("payload"))
        if (
            at is None
            or at < since
            or record.get("type") != "response_item"
            or payload.get("type") != "function_call"
            or payload.get("name") != "spawn_agent"
        ):
            continue
        arguments = payload.get("arguments")
        try:
            args = records.as_dict(json.loads(arguments)) if isinstance(arguments, str) else {}
        except (ValueError, json.JSONDecodeError, RecursionError):
            continue
        task_name = args.get("task_name")
        metadata = _codex_dispatch_artifact(task_name) if isinstance(task_name, str) else None
        if metadata is None:
            continue
        artifact, workflow, entity, stage = metadata
        event = {
            "at": at,
            "kind": "prepared_dispatch",
            "phase": "Spacedock dispatch",
            "title": _dispatch_file_assignment(artifact),
            "source": "Codex spawn_agent call and structured Spacedock dispatch artifact",
            "harness": harness,
            "sid": sid,
            "entity": entity,
            "workflow_binding": workflow,
            "stage": stage,
            "dispatch_artifact": artifact,
        }
        call_id = payload.get("call_id") or payload.get("id")
        if isinstance(call_id, str) and call_id:
            event["record_id"] = call_id
        metadata_passthrough = records.as_dict(
            payload.get("internal_chat_message_metadata_passthrough")
        )
        turn_id = metadata_passthrough.get("turn_id")
        if isinstance(turn_id, str) and turn_id:
            event["turn_id"] = turn_id
            event["branch_id"] = turn_id
        events.append(event)
    return events


def _semantic_history_source_events(
    config: RuntimeConfig,
    transcript_path: str,
    harness: str,
    sid: str,
    *,
    since: float,
    max_bytes: int,
) -> list[dict[str, Any]]:
    events = instruction_events(
        config,
        transcript_path,
        harness,
        sid,
        max_bytes=max_bytes,
        since=since,
    )
    work_rows, _support = _work_evidence(
        config,
        transcript_path,
        harness,
        sid,
        max_bytes=max_bytes,
        since=since,
    )
    events.extend(work_rows)
    events.extend(
        codex_dispatch_events(
            config,
            transcript_path,
            harness,
            sid,
            since=since,
            max_bytes=max_bytes,
        )
    )
    return events


def _incremental_history_events(
    config: RuntimeConfig,
    state: RuntimeState,
    project: str,
    transcript_path: str,
    harness: str,
    sid: str,
    *,
    now: float,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    signature = _transcript_signature(transcript_path)
    if signature is None:
        return [], None
    source_identity = f"{harness}:{sid}"
    scan_bytes, prior_coverage = semantic_history.backfill_plan(
        config,
        state,
        project,
        source_identity,
        signature,
        full_max_bytes=SEMANTIC_BACKFILL_MAX_BYTES,
    )
    if not scan_bytes:
        return [], None
    source_events = _semantic_history_source_events(
        config,
        transcript_path,
        harness,
        sid,
        since=now - SEMANTIC_HISTORY_HORIZON_SEC,
        max_bytes=scan_bytes,
    )
    # An empty forgiving reader is not proof that a scan ran. Keep the prior
    # marker, if any, rather than minting empty coverage after a failed read.
    if not source_events or _transcript_signature(transcript_path) != signature:
        return source_events, None
    return source_events, {**signature, "prior_coverage": prior_coverage}


def _dedupe_project_events(
    events: list[dict[str, Any]], *, limit: int | None = None
) -> list[dict[str, Any]]:
    deduped: dict[tuple[object, ...], dict[str, Any]] = {}
    for event in events:
        key = (
            event.get("kind"),
            event.get("at"),
            event.get("title"),
            event.get("workflow_binding") or event.get("workflow"),
            event.get("entity"),
            event.get("lineage"),
            event.get("work_item_binding"),
            event.get("record_id"),
        )
        deduped.setdefault(key, event)
    ordered = sorted(deduped.values(), key=lambda event: float(event["at"]), reverse=True)
    return ordered[:limit] if limit is not None else ordered


def _project_timeline(
    events: list[dict[str, Any]],
    focus: tuple[str, str] | None,
    anchored: frozenset[tuple[object, ...]] = frozenset(),
) -> list[dict[str, Any]]:
    # The agent's messages are reserved last in each scope. A long session says far more than
    # its reader types or its checks record, and a cap filled newest first would let that
    # evict the checks and the reader's messages a reading rests on.
    said = [event for event in events if event.get("kind") == _AGENT_SAY]
    rest = [event for event in events if event.get("kind") != _AGENT_SAY]
    own_anchor: list[dict[str, Any]] = []
    if focus is None:
        groups: tuple[list[dict[str, Any]], ...] = (rest, said)
    else:
        own_checks: list[dict[str, Any]] = []
        own_other: list[dict[str, Any]] = []
        surrounding: list[dict[str, Any]] = []
        for event in rest:
            if (event.get("harness"), event.get("sid")) != focus:
                surrounding.append(event)
            elif event.get("subject") == "check":
                own_checks.append(event)
            else:
                own_other.append(event)
        own_said = [event for event in said if (event.get("harness"), event.get("sid")) == focus]
        their_said = [event for event in said if (event.get("harness"), event.get("sid")) != focus]
        # A press's turn-closing messages come after the reader's own and before the rest of the
        # agent's, oldest first: they are what the newest-first cap would drop for a long session.
        own_anchor = sorted(
            (event for event in own_said if _message_key(event) in anchored),
            key=lambda event: float(event["at"]),
        )
        held = {id(event) for event in own_anchor}
        own_said = [event for event in own_said if id(event) not in held]
        # A later semantic focus filter cannot restore a check removed by the
        # project cap. Reserve its own evidence before the busy neighbours' rows.
        groups = (own_checks, own_other, own_anchor, own_said, surrounding, their_said)
    selected: list[dict[str, Any]] = []
    for group in groups:
        room = MAX_PROJECT_EVENTS - len(selected)
        if group is own_anchor:
            group = group[:room]  # noqa: PLW2901 - the earliest turns are the ones short of evidence
        selected.extend(_dedupe_project_events(group, limit=room))
        if len(selected) == MAX_PROJECT_EVENTS:
            break
    return sorted(selected, key=lambda event: float(event["at"]), reverse=True)


def _merge_support_counts(target: dict[str, int], incoming: Mapping[str, int]) -> None:
    for key in target:
        target[key] += incoming[key]


def _timeline_counts(timeline: list[dict[str, Any]]) -> tuple[int, int, int]:
    return (
        sum(1 for event in timeline if event["kind"] == "gate"),
        sum(1 for event in timeline if event["kind"] == "steer"),
        sum(
            1
            for event in timeline
            if event["kind"]
            in {"prepared_dispatch", "task_started", "task_result", "outcome", *_TOOL_REPORT_KINDS}
        ),
    )


def _in_context(session: Mapping[str, Any]) -> bool:
    """Whether a row is inside the window the project context reads.

    `active` is the collector's window reading, but a hook's idle overlay
    overwrites it with False to mean "no turn running" (`events.reduce_overlays`),
    and the page's pulse and notify logic depend on that. A row the hooks stopped
    is still in the window: it is exactly the row a reader opens to see what the
    turn did, and reading it as out of the window dropped every check and file
    about three seconds after the stop (DRC-4705).
    """
    return session.get("active") is True or (
        session.get("acquisition") == "event" and session.get("state") == "idle"
    )


def _context_sessions(
    sessions: Sequence[Mapping[str, Any]], project: str, focus: tuple[str, str] | None
) -> tuple[list[Mapping[str, Any]], list[Mapping[str, Any]], str, int]:
    selected = [
        session
        for session in sessions
        if (
            str(session.get("project_key") or session.get("project") or "") == project
            or str(session.get("project") or "") == project
        )
        and _in_context(session)
    ]
    selected.sort(key=lambda item: float(item.get("last_activity") or 0), reverse=True)
    if focus is None:
        return (
            selected[:MAX_PROJECT_OBSERVERS],
            selected[MAX_PROJECT_OBSERVERS:],
            "selected project",
            0,
        )
    analysis = [
        session
        for session in selected
        if (str(session.get("harness") or ""), str(session.get("sid") or "")) == focus
    ]
    return analysis, [], "focused session", len(selected) - len(analysis)


def _history_identity(
    sessions: Sequence[Mapping[str, Any]], project: str
) -> tuple[str, tuple[str, ...]]:
    matching = [
        row
        for row in sessions
        if project
        in {str(row.get("project_key") or row.get("project") or ""), str(row.get("project") or "")}
    ]
    keys = {str(row.get("project_key") or row.get("project") or "") for row in matching}
    if len(keys) != 1:
        return project, ()
    key = keys.pop()
    labels = {str(row.get("project") or "") for row in matching} - {key, ""}
    # A reused display label cannot join distinct repositories' evidence.
    aliases = tuple(
        sorted(
            label
            for label in labels
            if all(
                str(row.get("project_key") or row.get("project") or "") == key
                for row in sessions
                if row.get("project") == label
            )
        )
    )
    return key, aliases


def _history_project(
    config: RuntimeConfig, state: RuntimeState, sessions: Sequence[Mapping[str, Any]], project: str
) -> str:
    key, aliases = _history_identity(sessions, project)
    semantic_history.reconcile_project(config, state, key, aliases)
    return key


def _analysis_context_sessions(
    sessions: Sequence[Mapping[str, Any]], project: str, focus: tuple[str, str] | None
) -> tuple[list[Mapping[str, Any]], list[Mapping[str, Any]], str, int]:
    analysis, omitted, _, _ = _context_sessions(sessions, project, None)
    focused, _, scope, surrounding_active = _context_sessions(sessions, project, focus)
    if focus is None:
        return analysis, omitted, scope, surrounding_active
    known = {
        (str(session.get("harness") or ""), str(session.get("sid") or "")) for session in analysis
    }
    return (
        [
            *analysis,
            *(
                session
                for session in focused
                if (str(session.get("harness") or ""), str(session.get("sid") or "")) not in known
            ),
        ],
        [],
        scope,
        surrounding_active,
    )


def _attention_context_sessions(
    sessions: Sequence[Mapping[str, Any]], project: str
) -> tuple[list[Mapping[str, Any]], dict[str, Any]]:
    selected = [
        session
        for session in sessions
        if (
            str(session.get("project_key") or session.get("project") or "") == project
            or str(session.get("project") or "") == project
        )
        and _in_context(session)
    ]
    selected.sort(key=lambda item: float(item.get("last_activity") or 0), reverse=True)
    scanned = selected[:MAX_PROJECT_ATTENTION_SESSIONS]
    omitted = max(0, len(selected) - len(scanned))
    return scanned, {
        "state": "incomplete" if omitted else "complete",
        "scanned": len(scanned),
        "total": len(selected),
        "omitted": omitted,
        "source": "bounded active-session final-output scan",
    }


def _gate_event(
    config: RuntimeConfig,
    current: dict[str, str],
    slug: str,
    entity_id: str,
    entity_title: str,
    workflow: str,
    workflow_binding: str,
    _harness: str,
    _sid: str,
) -> dict[str, Any] | None:
    current = {
        key: records.safe_text(value, config.observer_block_cap_chars)
        for key, value in current.items()
    }
    at = records.parse_ts(current.get("at", ""))
    decision = current.get("decision", "")
    if at is None or not decision:
        return None
    stage = current.get("stage", "unknown stage")
    application_state = current.get("application_state", "")
    phase = "gate decision" + (f" · application {application_state}" if application_state else "")
    reason = records.safe_text(current.get("reason", ""), config.observer_block_cap_chars)
    detail = workflow
    if reason:
        detail += f" · {reason}"
    workflow_entity = records.safe_text(entity_id, 128)[:10] if entity_id else slug
    return {
        "at": at,
        "kind": "gate",
        "phase": phase,
        "title": f"{slug} · {stage} · {decision}",
        "detail": detail,
        "source": "Spacedock entity gate frontmatter",
        "scope": "project",
        "workflow": workflow,
        "workflow_binding": workflow_binding,
        "entity": workflow_entity,
        "entity_slug": slug,
        "entity_title": records.safe_text(entity_title, config.observer_block_cap_chars),
        "stage": stage,
        "decision": decision,
        "by": current.get("by", ""),
        "application_state": application_state,
        "target_stage": current.get("target_stage", ""),
    }


def _gate_field(body: str, block: str, current: dict[str, str], gate_stage: str) -> str:
    if body.startswith("stage:") and block == "gate":
        gate_stage = body[len("stage:") :].strip().strip("\"'")
        current["stage"] = gate_stage
    elif block == "resolution":
        for key in ("at", "decision", "by", "reason"):
            if body.startswith(key + ":"):
                current[key] = body[len(key) + 1 :].strip().strip("\"'")
                break
    elif block == "application" and body.startswith("state:"):
        current["application_state"] = body[len("state:") :].strip().strip("\"'")
    elif block == "application" and body.startswith("target-stage:"):
        current["target_stage"] = body[len("target-stage:") :].strip().strip("\"'")
    return gate_stage


def gate_events(
    config: RuntimeConfig,
    lines: list[str],
    slug: str,
    workflow: str,
    harness: str,
    sid: str,
    *,
    workflow_binding: str | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """All timestamped gate decisions and the untimestamped briefing count."""
    events: list[dict[str, Any]] = []
    current: dict[str, str] = {}
    block = ""
    gate_stage = ""
    briefings = 0
    entity_id = next(
        (raw[len("id:") :].strip().strip("\"'") for raw in lines if raw.startswith("id:")),
        "",
    )
    entity_title = next(
        (raw[len("title:") :].strip().strip("\"'") for raw in lines if raw.startswith("title:")),
        "",
    )

    def flush() -> None:
        event = _gate_event(
            config,
            current,
            slug,
            entity_id,
            entity_title,
            workflow,
            workflow_binding or workflow,
            harness,
            sid,
        )
        if event is not None:
            events.append(event)

    for raw in lines:
        body = raw.strip()
        if body.startswith("- id: gate:"):
            flush()
            current = {}
            gate_stage = ""
            block = "gate"
        elif body.startswith("- id: gate-attempt:"):
            flush()
            current = {"stage": gate_stage} if gate_stage else {}
            block = "attempt"
        elif body == "briefing:":
            briefings += 1
            block = "briefing"
        elif body == "resolution:":
            block = "resolution"
        elif body == "application:":
            block = "application"
        else:
            gate_stage = _gate_field(body, block, current, gate_stage)
    flush()
    return events, briefings


def _gate_context(
    config: RuntimeConfig,
    state: RuntimeState,
    transcript_path: str,
    harness: str,
    sid: str,
) -> tuple[list[dict[str, Any]], int]:
    events: list[dict[str, Any]] = []
    briefings = 0
    boot = spacedock.transcript_boot(config, state, transcript_path)
    for workflow_dir in spacedock.workflow_dirs(config, boot):
        workflow = spacedock.read_workflow(config, state, workflow_dir)
        entity_dir = spacedock.boot_entity_dir(boot, workflow_dir)
        if workflow is None or not entity_dir:
            continue
        for slug, path, info in spacedock.entity_files(config, entity_dir):
            try:
                lines = spacedock.read_frontmatter(
                    config, path, config.spacedock_entity_bytes, info
                )
            except spacedock.SdMismatchError:
                continue
            found, prepared = gate_events(
                config,
                lines,
                slug,
                str(workflow["name"]),
                harness,
                sid,
                workflow_binding=str(workflow_dir),
            )
            events.extend(found)
            briefings += prepared
    return events, briefings


def _project_peer_gate_context(
    config: RuntimeConfig,
    state: RuntimeState,
    sessions: Sequence[Mapping[str, Any]],
    project: str,
    focus: tuple[str, str] | None,
) -> tuple[list[dict[str, Any]], int]:
    """Read only project state from peers; their transcript facts stay excluded."""
    if focus is None:
        return [], 0
    events: list[dict[str, Any]] = []
    briefings = 0
    for session in sessions:
        harness = str(session.get("harness") or "")
        sid = str(session.get("sid") or "")
        session_project = str(session.get("project_key") or session.get("project") or "")
        if not _in_context(session) or session_project != project or (harness, sid) == focus:
            continue
        transcript_path = observer.resolve_transcript(config, state, harness, sid)
        if transcript_path is None:
            continue
        found, prepared = _gate_context(config, state, transcript_path, harness, sid)
        events.extend(found)
        briefings += prepared
    return events, briefings


def _prepared_dispatches(events: list[dict[str, Any]]) -> list[tuple[str, str, str, str, str]]:
    prepared: list[tuple[str, str, str, str, str]] = []
    for event in events:
        if event.get("kind") != "prepared_dispatch":
            continue
        artifact = str(event.get("dispatch_artifact") or "")
        prefix = str(event.get("dispatch_artifact_prefix") or "")
        workflow = str(event.get("workflow_binding") or "")
        entity = str(event.get("entity") or "")
        stage = str(event.get("stage") or "")
        if workflow and entity and (artifact or prefix):
            prepared.append((artifact, prefix, workflow, entity, stage))
    return prepared


def _artifact_bindings(
    artifact: str, prepared: list[tuple[str, str, str, str, str]]
) -> set[tuple[str, str, str]]:
    bindings: set[tuple[str, str, str]] = set()
    for exact, prefix, workflow, entity, prepared_stage in prepared:
        if exact and artifact == exact:
            bindings.add((workflow, entity, prepared_stage))
            continue
        if not artifact.startswith(prefix) or not artifact.endswith(".md"):
            continue
        stage = artifact[len(prefix) : -len(".md")]
        if stage and spacedock.SD_STAGE_RE.fullmatch(stage):
            bindings.add((workflow, entity, stage))
    return bindings


def _exact_gate_aliases(
    events: list[dict[str, Any]],
) -> tuple[dict[tuple[str, str], tuple[str, str]], dict[str, set[tuple[str, str]]]]:
    by_workflow: dict[tuple[str, str], tuple[str, str]] = {}
    by_entity: dict[str, set[tuple[str, str]]] = {}
    for event in events:
        if event.get("kind") != "gate":
            continue
        workflow = str(event.get("workflow_binding") or "")
        entity = str(event.get("entity") or "")
        if not workflow or not entity:
            continue
        canonical = (workflow, entity)
        for alias in {entity, str(event.get("entity_slug") or "")} - {""}:
            by_workflow[(workflow, alias)] = canonical
            by_entity.setdefault(alias, set()).add(canonical)
    return by_workflow, by_entity


def _bind_exact_gate_alias(
    event: dict[str, Any],
    by_workflow: dict[tuple[str, str], tuple[str, str]],
    by_entity: dict[str, set[tuple[str, str]]],
) -> None:
    if event.get("kind") == "gate":
        return
    workflow = str(event.get("workflow_binding") or "")
    entity = str(event.get("entity") or "")
    canonical = by_workflow.get((workflow, entity)) if workflow and entity else None
    if canonical is None and not workflow and entity:
        candidates = by_entity.get(entity, set())
        canonical = next(iter(candidates)) if len(candidates) == 1 else None
    if canonical is None:
        return
    event["workflow_binding"], event["entity"] = canonical
    event["source"] = str(event.get("source") or "") + " and exact gate entity alias"


def _bind_dispatch_artifacts(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Bind a consumed dispatch file only to its exact prepared artifact."""
    prepared = _prepared_dispatches(events)
    gate_aliases, gate_entities = _exact_gate_aliases(events)

    normalized: list[dict[str, Any]] = []
    for source_event in events:
        event = dict(source_event)
        artifact = str(event.get("dispatch_artifact") or "")
        identity = _dispatch_artifact_identity(artifact)
        if event.get("kind") in {"task_started", "task_result"} and identity is not None:
            entity, stage = identity
            event.update(
                {
                    "entity": entity,
                    "stage": stage,
                    "title": (
                        f"{entity} · {stage} result returned"
                        if event.get("kind") == "task_result"
                        else f"{entity} · {stage} dispatched"
                    ),
                    "source": str(event.get("source") or "")
                    + " and structured dispatch artifact path",
                }
            )
        bindings = _artifact_bindings(artifact, prepared)
        if event.get("kind") in {"task_started", "task_result"} and len(bindings) == 1:
            workflow, entity, stage = next(iter(bindings))
            event.update(
                {
                    "workflow_binding": workflow,
                    "entity": entity,
                    "stage": stage,
                    "title": (
                        f"{entity} · {stage} result returned"
                        if event.get("kind") == "task_result"
                        else f"{entity} · {stage} dispatched"
                    ),
                    "source": str(event.get("source") or "") + " and exact prepared-dispatch match",
                }
            )
        _bind_exact_gate_alias(event, gate_aliases, gate_entities)
        normalized.append(event)
    return normalized


def _focused_persisted_facts(
    history: Mapping[str, Any], focus: tuple[str, str]
) -> list[dict[str, Any]]:
    wanted = {"harness": focus[0], "sid": focus[1]}
    facts: list[dict[str, Any]] = []
    for row in history.get("events", []):
        if not isinstance(row, Mapping):
            continue
        fact = row.get("fact")
        if not isinstance(fact, dict):
            continue
        if fact.get("source_session") == wanted or fact.get("parent_session") == wanted:
            facts.append(fact)
    return facts


def _allow_exact_gate_evidence(
    allowed: set[str],
    evidence: Mapping[str, Any],
    gate_aliases: dict[tuple[str, str], tuple[str, str]],
    gate_entities: dict[str, set[tuple[str, str]]],
) -> None:
    work_item_id = str(evidence.get("work_item_id") or "")
    if work_item_id:
        allowed.add(work_item_id)
    workflow = str(evidence.get("workflow_binding") or "")
    entity = str(evidence.get("workflow_entity") or evidence.get("entity") or "")
    if not entity:
        return
    alias_event = {"kind": "task_started", "workflow_binding": workflow, "entity": entity}
    _bind_exact_gate_alias(alias_event, gate_aliases, gate_entities)
    canonical_work_item, _kind, _label, _binding = _semantic_work_identity(
        alias_event, "task_started"
    )
    if canonical_work_item:
        allowed.add(canonical_work_item)


def _focused_gate_events(
    evidence_events: list[dict[str, Any]],
    gate_events: list[dict[str, Any]],
    child_assignments: list[dict[str, Any]],
    persisted_history: Mapping[str, Any],
    focus: tuple[str, str],
) -> tuple[list[dict[str, Any]], set[str]]:
    normalized = _bind_dispatch_artifacts([*evidence_events, *gate_events])
    gate_aliases, gate_entities = _exact_gate_aliases(normalized)
    allowed = {
        work_item_id
        for event in normalized
        if event.get("kind") != "gate"
        for work_item_id, _kind, _label, _binding in [
            _semantic_work_identity(event, str(event.get("kind") or ""))
        ]
        if work_item_id
    }
    for evidence in child_assignments:
        _allow_exact_gate_evidence(allowed, evidence, gate_aliases, gate_entities)
    for evidence in _focused_persisted_facts(persisted_history, focus):
        _allow_exact_gate_evidence(allowed, evidence, gate_aliases, gate_entities)
    kept: list[dict[str, Any]] = []
    for event in normalized:
        if event.get("kind") != "gate":
            continue
        work_item_id, _kind, _label, _binding = _semantic_work_identity(event, "gate")
        if work_item_id in allowed:
            kept.append(event)
    return kept, allowed


def _scope_gate_events(
    events: list[dict[str, Any]],
    history_events: list[dict[str, Any]],
    gate_events: list[dict[str, Any]],
    focus: tuple[str, str] | None,
    child_assignments: list[dict[str, Any]],
    persisted_history: Mapping[str, Any],
) -> set[str]:
    allowed: set[str] = set()
    if focus is not None:
        gate_events, allowed = _focused_gate_events(
            [*events, *history_events],
            gate_events,
            child_assignments,
            persisted_history,
            focus,
        )
    events.extend(gate_events)
    history_events.extend(gate_events)
    return allowed


def _semantic_work_identity(
    source_event: dict[str, Any], raw_kind: str
) -> tuple[str, str, str, str]:
    binding = str(source_event.get("work_item_binding") or "")
    if raw_kind in {"task_started", "task_result"} and source_event.get("entity"):
        workflow_binding = str(source_event.get("workflow_binding") or "")
        artifact = str(source_event.get("dispatch_artifact") or "")
        work_item_id = (
            semantic_history.workflow_work_item_id(workflow_binding, str(source_event["entity"]))
            if workflow_binding
            else _semantic_id("workflow-item-artifact", artifact)
        )
        label = str(source_event["entity"])
        if source_event.get("stage"):
            label += f" · {source_event['stage']}"
        return work_item_id, "workflow_item", label, binding
    if raw_kind in {"prepared_dispatch", "gate"} and source_event.get("entity"):
        workflow_binding = str(source_event.get("workflow_binding") or "unbound-workflow")
        return (
            semantic_history.workflow_work_item_id(workflow_binding, str(source_event["entity"])),
            "workflow_item",
            str(
                source_event.get("entity_title")
                or source_event.get("entity_slug")
                or source_event["entity"]
            ),
            binding,
        )
    if raw_kind not in {"task_started", "task_result"} or not source_event.get("lineage"):
        return "", "unknown", "", binding
    work_item_id = (
        _semantic_id("work-item", "bound", binding)
        if binding
        else _semantic_id("work-item", "one-off", source_event["lineage"])
    )
    return (
        work_item_id,
        "unknown" if binding else "one_off",
        str(source_event.get("title") or "one-off work"),
        binding,
    )


_STEER_ACTOR_CLAIMS = {
    observer.MID_TURN_SOURCE: "queued-command attachment with a human origin",
    observer.ANSWER_SOURCE: "question tool result holding the reader's answers",
}


def _semantic_actor_claim(source_event: dict[str, Any], raw_kind: str) -> str:
    if raw_kind == "steer":
        # Said by source: the two records that carry the reader's words with no user turn are not
        # the "user-role record" the ordinary claim names, and a reader of the fact should not
        # have to infer which shape stands behind it.
        return _STEER_ACTOR_CLAIMS.get(
            str(source_event.get("source") or ""), "timestamped non-meta user-role record"
        )
    if raw_kind == _AGENT_SAY:
        return "timestamped top-level assistant text record"
    if raw_kind in {"prepared_dispatch", "task_started", "task_result", "outcome"}:
        return "session assistant/tool exchange"
    if raw_kind == "gate":
        return str(source_event.get("by") or "decision author unavailable")
    return ""


def _semantic_fact_from_event(
    source_event: dict[str, Any], raw_kind: str, fact_type: str, work_item_id: str
) -> dict[str, Any]:
    # `record_id` joined the hash on 2026-09-12 (DRC-4544 item 2), and only
    # when present. `_dedupe_project_events` already keys on it, so two events
    # differing in nothing else both survive as facts, and without it here
    # they shared one `fact_id`: the reading ledger then emitted two rows under
    # one citation handle and the page's `Map` kept whichever came last.
    # Appended conditionally so a fact with no record behind it keeps the id
    # it had. The ids of record-bearing facts moved once: a citation stored
    # before this to such a fact no longer resolves and the page demotes it to
    # UNCITED, and `semantic_history` dedupes on the id so those events are
    # recorded a second time. Accepted rather than migrated, per decisions.md;
    # no schema bump.
    #
    # The same one-time move, accepted the same way, on 2026-10-03: the title is
    # hashed as `safe_text` left it, and the `cued` redaction shape added that
    # day masks values it did not before, so a fact whose title held one (a
    # `DB_PASSWORD=…` in a prompt) gets a new id. The hash input is unchanged.
    #
    # Not moved by DRC-4920's paste-wrapper strip: a paste whose tag shares a line with typed
    # words had a title that carried the tag, the strip took it off, and every reading stored
    # before it cited an id that no longer existed (DRC-4935). `ID_TITLE_FIELD` holds the title
    # as it was hashed, so those ids stay what they were while the published title is clean.
    record_id = source_event.get("record_id")
    fact_id = _semantic_id(
        "fact",
        raw_kind,
        source_event.get("harness"),
        source_event.get("sid"),
        source_event.get("at"),
        source_event.get("workflow_binding"),
        source_event.get("entity"),
        source_event.get("lineage"),
        source_event.get(ID_TITLE_FIELD) or source_event.get("title"),
        *((record_id,) if record_id not in (None, "") else ()),
    )
    fact: dict[str, Any] = {
        "fact_id": fact_id,
        "at": source_event.get("at"),
        "type": fact_type,
        "source_kind": raw_kind,
        "summary": source_event.get("title"),
        "scope": "project" if raw_kind == "gate" else "session",
        "actor_claim": _semantic_actor_claim(source_event, raw_kind),
        "work_item_id": work_item_id or None,
        "evidence": {"source": source_event.get("source"), "confidence": "exact"},
    }
    for key in (
        "stage",
        "decision",
        "by",
        "application_state",
        "target_stage",
        "assignment",
        "worker_kind",
        "subject",
        "result",
        "result_source",
        "earlier_failed",
        "before_last_change",
        "changed_after",
        "read_incomplete",
        "result_at",
        "count",
        "completed_at",
        "last_activity_at",
        "ordinal",
        "ordinal_sub",
        READER_WORDS_FIELD,
        AGENT_WORDS_FIELD,
        AGENT_WORDS_TOTAL_FIELD,
    ):
        if source_event.get(key) not in (None, ""):
            fact[key] = source_event[key]
    if raw_kind == "steer":
        fact["intent_promoted"] = source_event.get("intent_promotable") is True
    if raw_kind == "gate" and source_event.get("entity"):
        fact["workflow_entity"] = source_event["entity"]
    harness = records.safe_text(source_event.get("harness"), 32)
    sid = records.safe_text(source_event.get("sid"), 128)
    if raw_kind != "gate" and harness and sid:
        fact["source_session"] = {"harness": harness, "sid": sid}
    branch = {
        key: source_event[key]
        for key in ("record_id", "parent_id", "turn_id", "branch_id")
        if source_event.get(key) not in (None, "")
    }
    if branch:
        fact["branch"] = {
            "harness": source_event.get("harness"),
            "sid": source_event.get("sid"),
            **branch,
        }
    lineage = str(source_event.get("lineage") or "")
    if lineage:
        call_key = lineage.rsplit(":", 1)[0]
        fact["batch_id"] = _semantic_id(
            "batch", source_event.get("harness"), source_event.get("sid"), call_key
        )
    return fact


def _semantic_intent(fact: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    projection_id = _semantic_id("intent", fact["fact_id"])
    projection = {
        "projection_id": projection_id,
        "at": fact["at"],
        "kind": "operator_intent",
        "summary": fact["summary"],
        "derived_from": fact["fact_id"],
        "confidence": "derived-deterministic",
    }
    relation = {
        "from": projection_id,
        "to": fact["fact_id"],
        "type": "derived_from",
        "confidence": "exact",
        "provenance": "bounded semantic-line extraction",
    }
    return projection, relation


def _append_semantic_intent(
    fact: dict[str, Any],
    intent_summaries: set[str],
    intent_projections: list[dict[str, Any]],
    relations: list[dict[str, Any]],
) -> None:
    projection, relation = _semantic_intent(fact)
    summary_key = str(projection["summary"]).casefold().strip()
    if summary_key in intent_summaries:
        return
    intent_summaries.add(summary_key)
    intent_projections.append(projection)
    relations.append(relation)


def _semantic_source_binding(
    source_event: dict[str, Any], work_item_kind: str, binding: str
) -> dict[str, str]:
    if binding:
        return {"source": "explicit task binding", "value": binding}
    if source_event.get("dispatch_artifact"):
        return {
            "source": "structured Spacedock dispatch artifact",
            "value": str(source_event["dispatch_artifact"]),
        }
    if work_item_kind != "workflow_item":
        return {"source": "Pi subagent call", "value": str(source_event.get("lineage") or "")}
    value = (
        str(source_event.get("workflow_binding") or "unbound-workflow")
        + ":"
        + str(source_event.get("entity") or "")
    )
    return {"source": "Spacedock entity slug", "value": value}


def _semantic_work_label(
    work_item: dict[str, Any],
    source_event: dict[str, Any],
    raw_kind: str,
    work_item_label: str,
    has_entity_title: bool,
) -> bool:
    if raw_kind == "gate" and source_event.get("entity_title"):
        work_item["label"] = work_item_label
        return True
    if (
        raw_kind in {"task_started", "task_result"}
        and source_event.get("dispatch_artifact")
        and not has_entity_title
    ):
        work_item["label"] = work_item_label
    return has_entity_title


def _semantic_work_item(
    work_items: dict[str, dict[str, Any]],
    titled_work_items: set[str],
    work_item_id: str,
    work_item_kind: str,
    work_item_label: str,
    source_event: dict[str, Any],
    raw_kind: str,
) -> dict[str, Any]:
    work_item = work_items.setdefault(
        work_item_id,
        {
            "work_item_id": work_item_id,
            "label": work_item_label,
            "kind": work_item_kind,
            "source_bindings": [],
            "contributor_refs": [],
        },
    )
    if _semantic_work_label(
        work_item,
        source_event,
        raw_kind,
        work_item_label,
        work_item_id in titled_work_items,
    ):
        titled_work_items.add(work_item_id)
    return work_item


def _semantic_work_relation(
    source_event: dict[str, Any], raw_kind: str, fact_id: str, work_item_id: str
) -> dict[str, Any] | None:
    relation_type = {
        "prepared_dispatch": "binds_to",
        "task_started": "binds_to",
        "task_result": "progresses",
        "gate": "decides",
    }.get(raw_kind)
    if relation_type is None:
        return None
    return {
        "from": fact_id,
        "to": work_item_id,
        "type": relation_type,
        "confidence": "structural" if raw_kind in {"prepared_dispatch", "gate"} else "exact",
        "provenance": source_event.get("source"),
    }


def _semantic_topology_relations(
    source_event: dict[str, Any], raw_kind: str, fact_id: str, work_item_id: str
) -> list[dict[str, Any]]:
    """Return graph topology only when the source records the endpoint relation."""
    harness = str(source_event.get("harness") or "")
    sid = str(source_event.get("sid") or "")
    if not harness or not sid:
        return []
    fo_id = f"fo:{harness}:{sid}"
    task_id = f"task:{work_item_id}"
    if raw_kind == "prepared_dispatch":
        relation_type, source_id, target_id = "dispatches_to", fo_id, task_id
    elif raw_kind == "task_result":
        relation_type, source_id, target_id = "returns_to", task_id, fo_id
    else:
        return []
    return [
        {
            "from": source_id,
            "to": target_id,
            "type": relation_type,
            "confidence": "structural" if raw_kind == "prepared_dispatch" else "exact",
            "provenance": source_event.get("source"),
            "evidence_ref": fact_id,
        }
    ]


# What an observer snapshot may claim about its own authorship. Read from the
# row's `goal_source` rather than assumed: the deterministic arm is the default
# and stamping every snapshot model-derived put a false claim in a durable store
# (DRC-4533). "unknown" is a sidecar written before the field existed, and it
# claims neither rather than defaulting to the one that is wrong more often.
_OBSERVER_ACTOR_CLAIMS = {
    "model": "model-derived observer snapshot",
    "deterministic": "deterministically derived observer snapshot",
}
_OBSERVER_ACTOR_CLAIM_UNKNOWN = "observer snapshot, derivation not recorded"


def _observer_actor_claim(goal_source: object) -> str:
    """What this snapshot may say about who derived it."""
    if isinstance(goal_source, str):
        return _OBSERVER_ACTOR_CLAIMS.get(goal_source, _OBSERVER_ACTOR_CLAIM_UNKNOWN)
    return _OBSERVER_ACTOR_CLAIM_UNKNOWN


def _semantic_observer_facts(observers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    facts: list[dict[str, Any]] = []
    for observer_row in observers:
        observed_at = observer_row.get("observed_at")
        goal = observer_row.get("goal")
        if not isinstance(observed_at, (int, float)) or not isinstance(goal, str):
            continue
        fact: dict[str, Any] = {
            "fact_id": _semantic_id(
                "observer",
                observer_row.get("harness"),
                observer_row.get("sid"),
                observed_at,
                goal,
            ),
            "at": observed_at,
            "type": "observer_snapshot",
            "summary": goal,
            "scope": "session",
            "actor_claim": _observer_actor_claim(observer_row.get("goal_source")),
            "work_item_id": None,
            "evidence": {
                "source": observer_row.get("source"),
                "confidence": "derived",
                "snapshot_status": observer_row.get("snapshot_status"),
            },
        }
        harness = records.safe_text(observer_row.get("harness"), 32)
        sid = records.safe_text(observer_row.get("sid"), 128)
        if harness and sid:
            fact["source_session"] = {"harness": harness, "sid": sid}
        facts.append(fact)
    return facts


def _semantic_trail_heads(
    fact_by_work_item: dict[str, list[dict[str, Any]]], facts: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    heads: list[dict[str, Any]] = []
    for work_item_id, item_facts in fact_by_work_item.items():
        newest = max(item_facts, key=lambda fact: float(fact.get("at") or 0))
        state_facts = [
            fact
            for fact in item_facts
            if fact.get("type") in {"stage_transition", "prepared_dispatch"} and fact.get("stage")
        ]
        state_fact = (
            max(state_facts, key=lambda fact: float(fact.get("at") or 0)) if state_facts else None
        )
        dispatches = [
            fact
            for fact in item_facts
            if fact.get("type") == "prepared_dispatch"
            and fact.get("source_kind") == "prepared_dispatch"
        ]
        status = {
            "prepared_dispatch": "prepared",
            "work_birth": "requested",
            "work_result": "outcome",
            "result": "returned",
            "gate_decision": "decision",
        }.get(str(newest.get("type")), "latest")
        head = {
            "work_item_id": work_item_id,
            "status": status,
            "latest_meaningful_event": newest["fact_id"],
            "dispatch_count": len(dispatches),
        }
        if state_fact is not None:
            head["stage"] = state_fact["stage"]
            head["state_fact"] = state_fact["fact_id"]
            if state_fact.get("type") == "stage_transition" and float(
                state_fact.get("at") or 0
            ) >= float(newest.get("at") or 0):
                head["status"] = "current stage"
        heads.append(head)
    at_by_id = {fact["fact_id"]: float(fact.get("at") or 0) for fact in facts}
    return sorted(
        heads,
        key=lambda head: at_by_id.get(str(head["latest_meaningful_event"]), 0),
        reverse=True,
    )


def _semantic_assignments(
    fact_by_work_item: dict[str, list[dict[str, Any]]],
    work_items: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    assignments: list[dict[str, Any]] = []
    for work_item_id, item_facts in fact_by_work_item.items():
        births = [fact for fact in item_facts if fact.get("type") == "work_birth"]
        if not births:
            continue
        birth = max(births, key=lambda fact: float(fact.get("at") or 0))
        latest = max(item_facts, key=lambda fact: float(fact.get("at") or 0))
        completed = latest.get("type") == "work_result"
        work_item = work_items[work_item_id]
        assignments.append(
            {
                "projection_id": _semantic_id("assignment", work_item_id, birth["fact_id"]),
                "work_item_id": work_item_id,
                "assignment_fact": birth["fact_id"],
                "state_fact": latest["fact_id"],
                "at": latest.get("at"),
                "state": "completed" if completed else "awaiting_result",
                "worker_kind": birth.get("worker_kind") or "subagent",
                "assignment": birth.get("assignment") or work_item.get("label"),
                "contributor_refs": list(work_item.get("contributor_refs") or []),
            }
        )
    return sorted(assignments, key=lambda row: float(row.get("at") or 0), reverse=True)


def _activity_nodes(representatives: list[dict[str, Any]]) -> list[dict[str, Any]]:
    clusters: list[list[dict[str, Any]]] = []
    for representative in sorted(representatives, key=lambda row: float(row.get("at") or 0)):
        if not clusters:
            clusters.append([representative])
            continue
        cluster = clusters[-1]
        first = cluster[0]
        same_batch = bool(representative.get("batch_id")) and representative.get(
            "batch_id"
        ) == first.get("batch_id")
        near = (
            float(representative.get("at") or 0) - float(first.get("at") or 0)
            <= SEMANTIC_BURST_EPSILON_SEC
        )
        if not (same_batch or near):
            cluster = []
            clusters.append(cluster)
        cluster.append(representative)

    nodes: list[dict[str, Any]] = []
    for cluster in clusters:
        cluster.sort(key=lambda row: float(row.get("at") or 0), reverse=True)
        work_item_ids = [
            work_item_id for member in cluster for work_item_id in member["work_item_ids"]
        ]
        if len(cluster) == 1:
            node = dict(cluster[0])
            node["kind"] = "work"
        else:
            node = {
                "kind": "burst",
                "at": cluster[0].get("at"),
                "count": len(cluster),
                "work_item_ids": work_item_ids,
                "latest_event": cluster[0].get("latest_event"),
                "retry_count": sum(int(member.get("retry_count") or 0) for member in cluster),
            }
        nodes.append(node)
    return sorted(nodes, key=lambda row: float(row.get("at") or 0), reverse=True)[
        :MAX_PRIMARY_ACTIVITY_NODES
    ]


def _semantic_activity_projection(
    work_items: dict[str, dict[str, Any]],
    trail_heads: list[dict[str, Any]],
    facts: list[dict[str, Any]],
    *,
    now: float | None = None,
) -> dict[str, Any]:
    """Bound the primary graph without turning old requests into current state."""
    if not facts:
        return {"nodes": [], "historical_unresolved": 0}
    fact_by_id = {str(fact["fact_id"]): fact for fact in facts}
    reference_at = (
        float(now)
        if isinstance(now, (int, float))
        else max((float(fact.get("at") or 0) for fact in facts), default=0)
    )
    current_after = reference_at - SEMANTIC_CURRENT_HORIZON_SEC

    def label_key(work_item_id: str) -> str:
        label = str(work_items.get(work_item_id, {}).get("label") or "")
        return re.sub(r"[^a-z0-9]+", " ", label.casefold()).strip()

    current: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for head in trail_heads:
        latest = fact_by_id.get(str(head.get("latest_meaningful_event")))
        if latest is None or float(latest.get("at") or 0) < current_after:
            continue
        if head.get("status") not in {"prepared", "requested", "outcome", "decision"}:
            continue
        current.append((head, latest))

    # An exact repeated assignment is one work lane with retry history, not a
    # new primary node each time the orchestrator redispatches it.
    grouped: dict[str, list[tuple[dict[str, Any], dict[str, Any]]]] = {}
    for head, latest in current:
        key = label_key(str(head["work_item_id"])) or str(head["work_item_id"])
        grouped.setdefault(key, []).append((head, latest))
    representatives: list[dict[str, Any]] = []
    for members in grouped.values():
        members.sort(key=lambda pair: float(pair[1].get("at") or 0), reverse=True)
        head, latest = members[0]
        representatives.append(
            {
                "at": latest.get("at"),
                "batch_id": latest.get("batch_id"),
                "status": head.get("status"),
                "work_item_ids": [str(pair[0]["work_item_id"]) for pair in members],
                "latest_event": latest["fact_id"],
                "retry_count": len(members) - 1,
            }
        )
    nodes = _activity_nodes(representatives)

    represented_keys = {
        label_key(work_item_id) for node in nodes for work_item_id in node.get("work_item_ids", [])
    }
    historical_keys = {
        label_key(str(head["work_item_id"]))
        for head in trail_heads
        if head.get("status") == "requested"
        and label_key(str(head["work_item_id"])) not in represented_keys
    }
    represented_ids = {
        work_item_id for node in nodes for work_item_id in node.get("work_item_ids", [])
    }
    historical_dispatches = sum(
        head.get("status") == "requested" and str(head["work_item_id"]) not in represented_ids
        for head in trail_heads
    )
    return {
        "nodes": nodes,
        "historical_unresolved": len(historical_keys),
        "historical_dispatches": historical_dispatches,
        "current_after": current_after,
    }


def _recent_steering_nodes(
    intents: list[dict[str, Any]], paired_intent_ids: set[str] | None = None
) -> list[dict[str, Any]]:
    low_signal = re.compile(
        r"^(?:how far are we\b|is this a raw subagent\b|oh\b.*\b(?:i see|got it)\b|"
        r"ok(?:ay)?\b|thanks?\b)",
        flags=re.IGNORECASE,
    )
    directive = re.compile(
        r"^(?:also\b|before\b|do not\b|don't\b|let's\b|no,?\s+that\b|redispatch\b|"
        r"use\b|we\b.*\b(?:orient|resume|continue)\b)|"
        r"\b(?:must|should|do|keep|make|redispatch|remove|replace|revise|show|update)\b",
        flags=re.IGNORECASE,
    )
    paired = paired_intent_ids or set()
    candidates = [
        intent
        for intent in intents
        if (
            str(intent.get("projection_id") or "") in paired
            or (
                not str(intent.get("summary") or "").strip().endswith("?")
                and not low_signal.match(str(intent.get("summary") or "").strip())
                and directive.search(str(intent.get("summary") or "").strip())
            )
        )
    ]
    selected: list[dict[str, Any]] = []
    selected_tokens: list[tuple[float, list[str]]] = []
    for candidate in sorted(candidates, key=lambda row: float(row.get("at") or 0), reverse=True):
        summary = str(candidate.get("summary") or "").casefold().strip()
        at = float(candidate.get("at") or 0)
        tokens = [
            token
            for token in re.findall(r"[a-z0-9]+", summary)
            if token
            not in {
                "a",
                "again",
                "an",
                "can",
                "could",
                "let",
                "please",
                "the",
                "this",
                "us",
                "would",
                "you",
            }
        ]
        duplicate = any(
            prior_at - at <= SEMANTIC_CURRENT_HORIZON_SEC
            and tokens
            and prior_tokens
            and tokens[0] == prior_tokens[0]
            and (
                len(set(tokens) & set(prior_tokens)) / min(len(set(tokens)), len(set(prior_tokens)))
            )
            >= 0.8
            for prior_at, prior_tokens in selected_tokens
        )
        if duplicate:
            continue
        selected_tokens.append((at, tokens))
        selected.append(candidate)
    return selected[:MAX_PRIMARY_STEERING_NODES]


def _structural_steering_episodes(
    intents: list[dict[str, Any]],
    facts: list[dict[str, Any]],
    relations: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    facts_by_id = {str(fact["fact_id"]): fact for fact in facts}
    reaction_types = {"work_birth", "work_result", "gate_decision", "result", "decision"}
    reactions = [fact for fact in facts if fact.get("type") in reaction_types]
    episodes: list[dict[str, Any]] = []
    for intent in intents:
        source_fact = facts_by_id.get(str(intent.get("derived_from") or ""))
        source_branch = source_fact.get("branch") if source_fact else None
        if not isinstance(source_branch, dict):
            continue
        source_record = source_branch.get("record_id")
        source_harness = source_branch.get("harness")
        source_sid = source_branch.get("sid")
        if not source_record or not source_harness or not source_sid:
            continue
        candidates = []
        for reaction in reactions:
            reaction_branch = reaction.get("branch")
            if not isinstance(reaction_branch, dict):
                continue
            if (
                reaction_branch.get("turn_id") == source_record
                and reaction_branch.get("harness") == source_harness
                and reaction_branch.get("sid") == source_sid
                and reaction_branch.get("branch_id")
            ):
                candidates.append(reaction)
        if not candidates:
            continue
        reaction = min(
            candidates,
            key=lambda fact: (float(fact.get("at") or 0), str(fact.get("fact_id") or "")),
        )
        episode_id = _semantic_id(
            "episode", intent["projection_id"], reaction["fact_id"], "structural"
        )
        episodes.append(
            {
                "episode_id": episode_id,
                "intent_id": intent["projection_id"],
                "adaptation_fact": reaction["fact_id"],
                "confidence": "structural",
                "provenance": "assistant branch descends from the user turn",
            }
        )
        relations.append(
            {
                "from": intent["projection_id"],
                "to": reaction["fact_id"],
                "type": "elicits",
                "confidence": "structural",
                "provenance": "assistant branch descends from the user turn",
            }
        )
    return sorted(
        episodes,
        key=lambda episode: float(facts_by_id[str(episode["adaptation_fact"])].get("at") or 0),
        reverse=True,
    )


def _semantic_model(
    events: list[dict[str, Any]],
    observers: list[dict[str, Any]],
    *,
    now: float | None = None,
) -> dict[str, Any]:
    """Immutable source facts, explicit relations, and replaceable projections."""
    ordered = sorted(
        _bind_dispatch_artifacts(events), key=lambda event: float(event.get("at") or 0)
    )
    facts: list[dict[str, Any]] = []
    work_items: dict[str, dict[str, Any]] = {}
    titled_work_items: set[str] = set()
    contributors: dict[str, dict[str, Any]] = {}
    relations: list[dict[str, Any]] = []
    intent_projections: list[dict[str, Any]] = []
    intent_summaries: set[str] = set()
    fact_by_work_item: dict[str, list[dict[str, Any]]] = {}
    for source_event in ordered:
        raw_kind = str(source_event.get("kind") or "")
        fact_type = _SEMANTIC_FACT_TYPES.get(raw_kind)
        if fact_type is None:
            continue
        work_item_id, work_item_kind, work_item_label, binding = _semantic_work_identity(
            source_event, raw_kind
        )
        fact = _semantic_fact_from_event(source_event, raw_kind, fact_type, work_item_id)
        fact_id = str(fact["fact_id"])
        facts.append(fact)
        if raw_kind == "steer" and fact.get("intent_promoted") is True:
            _append_semantic_intent(fact, intent_summaries, intent_projections, relations)
        if not work_item_id:
            continue
        work_item = _semantic_work_item(
            work_items,
            titled_work_items,
            work_item_id,
            work_item_kind,
            work_item_label,
            source_event,
            raw_kind,
        )
        source_binding = _semantic_source_binding(source_event, work_item_kind, binding)
        if source_binding not in work_item["source_bindings"]:
            work_item["source_bindings"].append(source_binding)
        fact_by_work_item.setdefault(work_item_id, []).append(fact)
        work_relation = _semantic_work_relation(source_event, raw_kind, fact_id, work_item_id)
        if work_relation is not None:
            relations.append(work_relation)
        relations.extend(
            _semantic_topology_relations(source_event, raw_kind, fact_id, work_item_id)
        )
        contributor_ref = str(source_event.get("contributor_ref") or "")
        if contributor_ref:
            contributor_id = _semantic_id("contributor", contributor_ref)
            contributors.setdefault(
                contributor_id,
                {
                    "contributor_id": contributor_id,
                    "source_label": contributor_ref,
                    "identity_status": "unverified source label",
                },
            )
            if contributor_id not in work_item["contributor_refs"]:
                work_item["contributor_refs"].append(contributor_id)
            relations.append(
                {
                    "from": contributor_id,
                    "to": work_item_id,
                    "type": "contributes_to",
                    "confidence": "source-labeled",
                    "provenance": source_event.get("source"),
                }
            )

    facts.extend(_semantic_observer_facts(observers))
    facts.sort(key=lambda fact: float(fact.get("at") or 0), reverse=True)
    trail_heads = _semantic_trail_heads(fact_by_work_item, facts)
    assignments = _semantic_assignments(fact_by_work_item, work_items)
    steering_episodes = _structural_steering_episodes(intent_projections, facts, relations)
    paired_intent_ids = {str(episode["intent_id"]) for episode in steering_episodes}
    activity = _semantic_activity_projection(work_items, trail_heads, facts, now=now)
    activity["steering"] = _recent_steering_nodes(intent_projections, paired_intent_ids)
    return {
        "facts": facts,
        "work_items": list(work_items.values()),
        "contributors": list(contributors.values()),
        "relations": relations,
        "projections": {
            "operator_intents": intent_projections,
            "trail_heads": trail_heads,
            "assignments": assignments,
            "activity": activity,
            "steering_episodes": steering_episodes,
            "candidate_goal_shifts": [],
        },
    }


def _history_sources(
    semantic: dict[str, Any], history: dict[str, Any]
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    facts = list(semantic.get("facts") or [])
    work_items = list(semantic.get("work_items") or [])
    facts_by_id = {str(fact.get("fact_id")): fact for fact in facts}
    work_by_id = {
        str(item.get("work_item_id")): item for item in work_items if item.get("work_item_id")
    }
    for event in history.get("events", []):
        if not isinstance(event, dict):
            continue
        fact = event.get("fact")
        item = event.get("work_item")
        if isinstance(fact, dict) and fact.get("fact_id"):
            facts_by_id.setdefault(str(fact["fact_id"]), fact)
        if isinstance(item, dict) and item.get("work_item_id"):
            work_by_id.setdefault(str(item["work_item_id"]), item)
    return facts_by_id, work_by_id


def _history_intents(
    history: dict[str, Any],
    facts_by_id: dict[str, dict[str, Any]],
    projections: dict[str, Any],
    relations: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    intents = list(projections.get("operator_intents") or [])
    intent_ids = {str(intent.get("derived_from")) for intent in intents}
    for event in history.get("events", []):
        if not isinstance(event, dict):
            continue
        fact = facts_by_id.get(str(event.get("source_ref") or ""))
        if (
            fact is None
            or fact.get("intent_promoted") is not True
            or str(fact.get("fact_id")) in intent_ids
        ):
            continue
        intent, relation = _semantic_intent(fact)
        intents.append(intent)
        relations.append(relation)
        intent_ids.add(str(fact["fact_id"]))
    return intents


def _history_activity_nodes(
    history: dict[str, Any], current_event_ids: set[str]
) -> list[dict[str, Any]]:
    consequential = {
        "assignment",
        "checkpoint",
        "gate_decision",
        "result",
        "final_output",
        "stage_transition",
    }
    nodes: list[dict[str, Any]] = []
    for event in history.get("events", []):
        if not isinstance(event, dict):
            continue
        if (
            event.get("event_type") not in consequential
            or not event.get("work_binding")
            or str(event.get("source_ref") or "") in current_event_ids
        ):
            continue
        nodes.append(
            {
                "kind": "work",
                "at": event.get("at"),
                "status": (
                    "prepared"
                    if event.get("event_type") == "assignment"
                    else "decision"
                    if event.get("event_type") == "gate_decision"
                    else "outcome"
                ),
                "work_item_ids": [event["work_binding"]],
                "latest_event": event.get("source_ref"),
                "history_event_type": event.get("event_type"),
            }
        )
    return nodes[:MAX_PRIMARY_ACTIVITY_NODES]


def _materialize_history_topology(
    facts: list[dict[str, Any]],
    relations: list[dict[str, Any]],
    relation_keys: set[tuple[Any, ...]],
) -> None:
    for fact in facts:
        work_item_id = str(fact.get("work_item_id") or "")
        source_kind = str(fact.get("source_kind") or "")
        branch = fact.get("branch")
        if not work_item_id or not isinstance(branch, dict):
            continue
        evidence = fact.get("evidence")
        source_event = {
            "harness": branch.get("harness"),
            "sid": branch.get("sid"),
            "source": evidence.get("source") if isinstance(evidence, dict) else None,
        }
        topology = _semantic_topology_relations(
            source_event, source_kind, str(fact.get("fact_id") or ""), work_item_id
        )
        for relation in topology:
            key = _semantic_relation_key(relation)
            if key not in relation_keys:
                relations.append(relation)
                relation_keys.add(key)


def _semantic_relation_key(relation: Mapping[str, Any]) -> tuple[Any, ...]:
    key: tuple[Any, ...] = (
        relation.get("from"),
        relation.get("to"),
        relation.get("type"),
    )
    if relation.get("type") in {"dispatches_to", "returns_to"}:
        return (*key, relation.get("evidence_ref"))
    return key


def _merge_semantic_history(
    semantic: dict[str, Any], history: dict[str, Any], *, now: float
) -> dict[str, Any]:
    """Let persisted meaning outlive the bounded source tail without becoming authority."""
    facts_by_id, work_by_id = _history_sources(semantic, history)
    facts = sorted(facts_by_id.values(), key=lambda fact: float(fact.get("at") or 0), reverse=True)
    projections = semantic.get("projections")
    if not isinstance(projections, dict):
        projections = {}
        semantic["projections"] = projections
    relations = list(semantic.get("relations") or [])
    relation_keys = {_semantic_relation_key(row) for row in relations if isinstance(row, dict)}
    _materialize_history_topology(facts, relations, relation_keys)
    for event in history.get("events", []):
        if not isinstance(event, dict):
            continue
        for relation in event.get("relations", []):
            if not isinstance(relation, dict):
                continue
            key = _semantic_relation_key(relation)
            if key in relation_keys:
                continue
            relations.append(relation)
            relation_keys.add(key)
    intents = _history_intents(history, facts_by_id, projections, relations)
    fact_by_work_item: dict[str, list[dict[str, Any]]] = {}
    for fact in facts:
        work_item_id = str(fact.get("work_item_id") or "")
        if work_item_id:
            fact_by_work_item.setdefault(work_item_id, []).append(fact)
    trails = _semantic_trail_heads(fact_by_work_item, facts)
    assignments = _semantic_assignments(fact_by_work_item, work_by_id)
    episodes = _structural_steering_episodes(intents, facts, relations)
    paired = {str(episode["intent_id"]) for episode in episodes}
    activity = _semantic_activity_projection(work_by_id, trails, facts, now=now)
    current_event_ids = {str(node.get("latest_event") or "") for node in activity.get("nodes", [])}
    activity["history_nodes"] = _history_activity_nodes(history, current_event_ids)
    activity["steering"] = _recent_steering_nodes(intents, paired)
    semantic["facts"] = facts
    semantic["work_items"] = list(work_by_id.values())
    semantic["relations"] = relations
    projections["operator_intents"] = sorted(
        intents, key=lambda intent: float(intent.get("at") or 0), reverse=True
    )
    projections["trail_heads"] = trails
    projections["assignments"] = assignments
    projections["activity"] = activity
    projections["steering_episodes"] = episodes
    semantic["history"] = {
        "event_count": len(history.get("events", [])),
        "window_sec": history.get("window_sec", semantic_history.HISTORY_WINDOW_SEC),
        "cursors": history.get("cursors", {}),
        "persisted": history.get("persisted") is True,
        "events": [
            {
                key: event.get(key)
                for key in (
                    "event_id",
                    "event_type",
                    "at",
                    "source_identity",
                    "source_ref",
                    "work_binding",
                    "summary",
                )
            }
            for event in history.get("events", [])
            if isinstance(event, dict)
        ],
    }
    return semantic


def _focused_semantic_history(
    history: dict[str, Any],
    focus: tuple[str, str],
    allowed_gate_work_items: set[str],
) -> dict[str, Any]:
    """Project facts cross session boundaries; transcript facts do not."""
    focused_events: list[dict[str, Any]] = []
    wanted = {"harness": focus[0], "sid": focus[1]}
    for event in history.get("events", []):
        if not isinstance(event, dict):
            continue
        fact = event.get("fact")
        if not isinstance(fact, dict):
            continue
        if (
            fact.get("type") == "gate_decision"
            and fact.get("work_item_id") not in allowed_gate_work_items
        ):
            continue
        if fact.get("scope") in {"project", "workflow"}:
            focused_events.append(event)
            continue
        if fact.get("source_session") == wanted or fact.get("parent_session") == wanted:
            focused_events.append(event)
    return {**history, "events": focused_events}


def _focused_graph_scope(
    focus: tuple[str, str], child_assignments: list[dict[str, Any]]
) -> tuple[set[tuple[str, str]], set[str]]:
    wanted = {"harness": focus[0], "sid": focus[1]}
    allowed_sessions = {(focus[0], focus[1])}
    allowed_work_items: set[str] = set()
    for assignment in child_assignments:
        if not isinstance(assignment, dict) or assignment.get("parent_session") != wanted:
            continue
        observer_sid = records.safe_text(assignment.get("observer_sid"), 128)
        if observer_sid:
            allowed_sessions.add((focus[0], observer_sid))
        work_item_id = records.safe_text(assignment.get("work_item_id"), 256)
        if work_item_id:
            allowed_work_items.add(work_item_id)
    return allowed_sessions, allowed_work_items


def _fact_session_identity(fact: Mapping[str, Any], key: str) -> tuple[str, str]:
    value = fact.get(key)
    if not isinstance(value, dict):
        return "", ""
    return str(value.get("harness") or ""), str(value.get("sid") or "")


def _focused_graph_facts(
    semantic: Mapping[str, Any],
    allowed_sessions: set[tuple[str, str]],
    allowed_work_items: set[str],
) -> list[dict[str, Any]]:
    session_facts: list[dict[str, Any]] = []
    for fact in semantic.get("facts", []):
        if not isinstance(fact, dict):
            continue
        if (
            _fact_session_identity(fact, "source_session") not in allowed_sessions
            and _fact_session_identity(fact, "parent_session") not in allowed_sessions
        ):
            continue
        session_facts.append(copy.deepcopy(fact))
        work_item_id = str(fact.get("work_item_id") or "")
        if work_item_id:
            allowed_work_items.add(work_item_id)
    project_facts = [
        copy.deepcopy(fact)
        for fact in semantic.get("facts", [])
        if isinstance(fact, dict)
        and fact.get("scope") in {"project", "workflow"}
        and str(fact.get("work_item_id") or "") in allowed_work_items
    ]
    facts_by_id = {
        str(fact["fact_id"]): fact
        for fact in [*session_facts, *project_facts]
        if fact.get("fact_id")
    }
    return sorted(facts_by_id.values(), key=lambda fact: float(fact.get("at") or 0), reverse=True)


def _focused_semantic_graph(
    semantic: dict[str, Any],
    focus: tuple[str, str],
    child_assignments: list[dict[str, Any]],
    *,
    now: float,
) -> dict[str, Any]:
    """Filter the project graph by exact provenance instead of rebuilding it."""
    allowed_sessions, allowed_work_items = _focused_graph_scope(focus, child_assignments)
    facts = _focused_graph_facts(semantic, allowed_sessions, allowed_work_items)
    facts_by_id = {str(fact["fact_id"]): fact for fact in facts}
    work_items = {
        str(item["work_item_id"]): copy.deepcopy(item)
        for item in semantic.get("work_items", [])
        if isinstance(item, dict) and str(item.get("work_item_id") or "") in allowed_work_items
    }
    contributor_ids = {
        str(contributor_id)
        for item in work_items.values()
        for contributor_id in item.get("contributor_refs", [])
        if contributor_id
    }
    contributors = [
        copy.deepcopy(contributor)
        for contributor in semantic.get("contributors", [])
        if isinstance(contributor, dict)
        and str(contributor.get("contributor_id") or "") in contributor_ids
    ]
    original_projections = semantic.get("projections")
    if not isinstance(original_projections, dict):
        original_projections = {}
    intents = [
        copy.deepcopy(intent)
        for intent in original_projections.get("operator_intents", [])
        if isinstance(intent, dict) and str(intent.get("derived_from") or "") in facts_by_id
    ]
    projection_ids = {
        str(intent.get("projection_id") or "") for intent in intents if intent.get("projection_id")
    }
    node_ids = set(facts_by_id) | set(work_items) | contributor_ids | projection_ids
    relations = [
        copy.deepcopy(relation)
        for relation in semantic.get("relations", [])
        if isinstance(relation, dict)
        and (
            str(relation.get("evidence_ref") or "") in facts_by_id
            or (
                str(relation.get("from") or "") in node_ids
                and str(relation.get("to") or "") in node_ids
            )
        )
    ]
    fact_by_work_item: dict[str, list[dict[str, Any]]] = {}
    for fact in facts:
        work_item_id = str(fact.get("work_item_id") or "")
        if work_item_id and work_item_id in work_items:
            fact_by_work_item.setdefault(work_item_id, []).append(fact)
    trails = _semantic_trail_heads(fact_by_work_item, facts)
    assignments = _semantic_assignments(fact_by_work_item, work_items)
    episodes = _structural_steering_episodes(intents, facts, relations)
    paired = {str(episode["intent_id"]) for episode in episodes}
    activity = _semantic_activity_projection(work_items, trails, facts, now=now)
    activity["steering"] = _recent_steering_nodes(intents, paired)
    history = semantic.get("history")
    if not isinstance(history, dict):
        history = {}
    history_events = [
        copy.deepcopy(event)
        for event in history.get("events", [])
        if isinstance(event, dict) and str(event.get("source_ref") or "") in facts_by_id
    ]
    return {
        **copy.deepcopy(semantic),
        "facts": facts,
        "work_items": list(work_items.values()),
        "contributors": contributors,
        "relations": relations,
        "projections": {
            **copy.deepcopy(original_projections),
            "operator_intents": intents,
            "trail_heads": trails,
            "assignments": assignments,
            "activity": activity,
            "steering_episodes": episodes,
        },
        "history": {**copy.deepcopy(history), "events": history_events},
    }


def _semantic_for_focus(
    semantic: dict[str, Any],
    focus: tuple[str, str] | None,
    child_assignments: list[dict[str, Any]],
    *,
    now: float,
) -> dict[str, Any]:
    if focus is None:
        return semantic
    return _focused_semantic_graph(semantic, focus, child_assignments, now=now)


def _authorization_resolved(request: Mapping[str, Any], facts: list[dict[str, Any]]) -> bool:
    source = request.get("source_session")
    request_at = float(request.get("at") or 0)
    for fact in facts:
        if float(fact.get("at") or 0) <= request_at or fact.get("source_session") != source:
            continue
        evidence = fact.get("evidence")
        if not isinstance(evidence, dict) or evidence.get("confidence") != "exact":
            continue
        text = str(fact.get("detail") or fact.get("summary") or "")
        if fact.get("type") == "user_message" and _AUTHORIZATION_ANSWER_RE.search(text):
            return True
        if fact.get("type") == "result" and _AUTHORIZATION_RESULT_RE.search(text):
            return True
    return False


def _command_attention_projection(semantic: Mapping[str, Any]) -> list[dict[str, Any]]:
    facts = [fact for fact in semantic.get("facts", []) if isinstance(fact, dict)]
    labels = {
        str(item.get("work_item_id") or ""): str(item.get("label") or "")
        for item in semantic.get("work_items", [])
        if isinstance(item, dict)
    }
    projected: list[dict[str, Any]] = []
    for fact in facts:
        request = fact.get("authorization_request")
        if not isinstance(request, dict) or request.get("status") != "open":
            continue
        if _authorization_resolved(fact, facts):
            continue
        work_item_id = str(fact.get("work_item_id") or "")
        label = labels.get(work_item_id) or "Codex session result"
        projected.append(
            {
                "projection_id": _semantic_id("command-attention", fact.get("fact_id")),
                "at": fact.get("at"),
                "owner": "CAPTAIN",
                "kind": str(request.get("kind") or "authorization"),
                "label": label,
                "question": str(request.get("question") or ""),
                "work_item_id": work_item_id or None,
                "source_fact": fact.get("fact_id"),
                "evidence": copy.deepcopy(fact.get("evidence") or {}),
            }
        )
    return sorted(projected, key=lambda item: float(item.get("at") or 0), reverse=True)


def _with_command_attention(
    semantic: dict[str, Any], coverage: Mapping[str, Any]
) -> dict[str, Any]:
    projections = semantic.get("projections")
    if not isinstance(projections, dict):
        projections = {}
        semantic["projections"] = projections
    projections["command_attention"] = _command_attention_projection(semantic)
    projections["command_attention_coverage"] = dict(coverage)
    return semantic


def _child_workflow(child: Mapping[str, Any]) -> dict[str, Any]:
    workflow_entity = child.get("workflow_entity")
    workflow_stage = child.get("workflow_stage")
    workflow_binding = child.get("workflow_binding")
    if not isinstance(workflow_entity, str) or not isinstance(workflow_stage, str):
        return {}
    bound = isinstance(workflow_binding, str) and bool(workflow_binding)
    return {
        "workflow_entity": workflow_entity,
        "workflow_stage": workflow_stage,
        **({"workflow_binding": workflow_binding} if bound else {}),
        **(
            {
                "work_item_id": semantic_history.workflow_work_item_id(
                    str(workflow_binding), workflow_entity
                )
            }
            if bound
            else {}
        ),
    }


def _active_child_assignments(
    config: RuntimeConfig,
    state: RuntimeState,
    session: Mapping[str, Any],
    *,
    now: float,
    refresh: bool,
    model_consent: bool = False,
    notices: list[Any] | None = None,
) -> list[dict[str, Any]]:
    """The focused session's active children and what each is doing.

    A child's goal call records the goal notice before the parent's call can,
    so every notice a child records is appended to `notices` whatever its
    assignment came to: dropped here, the parent finds none due and the reader
    is never told what left the machine.
    """
    hierarchy = session.get("subagent_hierarchy")
    if not isinstance(hierarchy, list):
        return []
    assignments: list[dict[str, Any]] = []
    parent_harness = records.safe_text(session.get("harness"), 32)
    parent_sid = records.safe_text(session.get("sid"), 128)
    parent_session = (
        {"harness": parent_harness, "sid": parent_sid} if parent_harness and parent_sid else None
    )
    for raw_child in hierarchy[:MAX_ACTIVE_CHILD_OBSERVERS]:
        if not isinstance(raw_child, dict):
            continue
        child = records.as_dict(raw_child)
        row: dict[str, Any] = {
            "name": records.safe_text(child.get("name") or "subagent", 70),
            "depth": child.get("depth"),
            "parent_name": child.get("parent_name"),
            "observer_sid": child.get("observer_sid"),
            **({"parent_session": parent_session} if parent_session else {}),
        }
        row.update(_child_workflow(child))
        exact = child.get("assignment")
        if isinstance(exact, str) and exact:
            assignments.append(
                {
                    **row,
                    "assignment": exact,
                    "confidence": "exact",
                    "source": child.get("assignment_status") or "exact parent dispatch",
                }
            )
            continue
        child_sid = child.get("observer_sid")
        if not isinstance(child_sid, str) or not child_sid:
            assignments.append({**row, "assignment": None, "confidence": "unavailable"})
            continue
        transcript_path = observer.resolve_transcript(config, state, "codex", child_sid)
        if transcript_path is None:
            assignments.append({**row, "assignment": None, "confidence": "unavailable"})
            continue
        observed = _observe_session(
            config,
            state,
            transcript_path,
            ("codex", child_sid),
            now=now,
            refresh=refresh,
            child_activity_fallback=True,
            model_consent=model_consent,
        )
        if observed is None:
            assignments.append({**row, "assignment": None, "confidence": "unavailable"})
            continue
        if notices is not None and observed.get("notice") is not None:
            notices.append(observed["notice"])
        goal = observed.get("goal")
        if not isinstance(goal, str) or not goal or goal == observer.NO_GOAL:
            assignments.append({**row, "assignment": None, "confidence": "unavailable"})
            continue
        assignments.append(
            {
                **row,
                "assignment": goal,
                "confidence": "derived",
                "source": (
                    "bounded child observer snapshot"
                    if observed.get("snapshot_status") == "refreshed"
                    else "cached child observer snapshot"
                ),
                "observed_at": observed.get("observed_at"),
                "snapshot_status": observed.get("snapshot_status"),
            }
        )
    return assignments


def _collect_without_transcript(
    config: RuntimeConfig,
    state: RuntimeState,
    project: str,
    identity: dict[str, str],
    *,
    now: float,
    sinks: tuple[
        list[dict[str, Any]],
        list[dict[str, Any]],
        dict[str, dict[str, Any]],
        list[dict[str, Any]],
    ],
) -> None:
    """A session `resolve_transcript` does not hand a whole transcript for.

    A directions-only harness contributes its directions and their history and
    nothing else its transcript holds: no observer snapshot, no work, no gate
    or boot scan, since each of those reads work or tool output. Any other
    session is named unavailable, with whether its harness has a reader at all.
    """
    events, history_events, history_source_scans, unavailable = sinks
    harness, sid = identity["harness"], identity["sid"]
    path = observer.resolve_directions(config, state, harness, sid)
    if path is None:
        known = harness in (*observer.TRANSCRIPT_HARNESSES, *observer.DIRECTION_HARNESSES)
        reason = observer.TRANSCRIPT_NOT_FOUND if known else observer.READER_UNAVAILABLE
        unavailable.append({**identity, "reason": reason})
        return
    events.extend(instruction_events(config, path, harness, sid))
    rows, signature = _incremental_history_events(
        config, state, project, path, harness, sid, now=now
    )
    history_events.extend(rows)
    if signature is not None:
        history_source_scans[f"{harness}:{sid}"] = signature


def _usable_reach(window: PressWindow | None, now: float) -> bool:
    """A window start a press may read back to: finite, after zero, and not in the future."""
    return window is not None and math.isfinite(window.start) and 0 < window.start <= now


def _session_messages(
    config: RuntimeConfig,
    events: list[dict[str, Any]],
    transcript_path: str,
    identity: tuple[str, str],
    window: PressWindow | None,
    now: float,
) -> PressMessages | None:
    """Append one session's person and agent messages, from the press's read where it has one.

    Returns that read, or None when the tail reads supplied them: ordinary collection, a harness
    without agent messages, no usable window, or a file the read could not hold still.
    """
    harness, sid = identity
    pressed = (
        press_message_events(config, transcript_path, harness, sid, window)
        if window is not None and _usable_reach(window, now)
        else None
    )
    if pressed is None:
        events.extend(instruction_events(config, transcript_path, harness, sid))
        events.extend(agent_message_events(config, transcript_path, harness, sid))
        return None
    events.extend(pressed.events)
    return pressed


_MESSAGE_KINDS = frozenset({"steer", _AGENT_SAY})


def _message_key(event: Mapping[str, Any]) -> tuple[object, ...]:
    return (event.get("kind"), event.get("at"), event.get("title"), event.get("record_id"))


def _message_reach_source(
    reached: PressMessages | None, timeline: list[dict[str, Any]], focus: tuple[str, str] | None
) -> dict[str, Any]:
    kept = _kept_message_reach(reached, timeline, focus)
    return {} if kept is None else {"message_reach": kept}


def _kept_message_reach(
    reached: PressMessages | None, timeline: list[dict[str, Any]], focus: tuple[str, str] | None
) -> dict[str, Any] | None:
    """What a press's message read amounts to once the project cap has been applied.

    The scan alone would say the window was covered while `MAX_PROJECT_EVENTS` dropped its oldest
    messages, so this reads the timeline. Same keys as `transcript_tail_coverage`: a figure that
    read what was scanned rather than what was kept would be a fact about the read, not the record.
    """
    if reached is None or focus is None:
        return None
    kept = [
        event
        for event in timeline
        if (event.get("harness"), event.get("sid")) == focus and event.get("kind") in _MESSAGE_KINDS
    ]
    kept_keys = {_message_key(event) for event in kept}
    dropped = [
        event
        for event in reached.events
        if event.get("kind") in _MESSAGE_KINDS and _message_key(event) not in kept_keys
    ]
    lost_at = [float(event["at"]) for event in dropped]
    if reached.reach.lost is not None:
        lost_at.append(reached.reach.lost)
    if lost_at:
        # The record is whole only after the newest message the read or the cap lost. The cap keeps
        # a session's own reader messages ahead of the agent's, so the oldest message kept is
        # usually the Goal's own prompt at the window start, and reporting that would call a
        # partial record complete. Kept turn-closing messages older than this are extra evidence,
        # not a contiguous record, so they never move the start.
        lost = max(lost_at)
        later = (float(event["at"]) for event in kept if float(event["at"]) > lost)
        start = min(later, default=lost)
        if not reached.reach.reached and reached.reach.earliest is not None:
            # A byte or clock stop, or a region the scan could not read, puts the whole record's
            # start where the contiguous read began if that is later than what the cap left.
            start = max(start, reached.reach.earliest)
        return {"tail_truncated": True, "tail_start": start}
    return {"tail_truncated": not reached.reach.reached, "tail_start": reached.reach.earliest}


def collect(  # noqa: PLR0913, PLR0915 - the press's window rides beside the focus it belongs to
    config: RuntimeConfig,
    state: RuntimeState,
    sessions: Sequence[Mapping[str, Any]],
    project: str,
    *,
    now: float,
    refresh: bool = False,
    focus: tuple[str, str] | None = None,
    model_consent: bool = False,
    message_reach: PressWindow | None = None,
) -> dict[str, Any]:
    """Observer results and a real project event log for exact-label sessions.

    `message_reach` is a reader's Analyze press only: the focused Claude session's messages are
    read back to its window start instead of from the 400,000-byte tail, and the result's
    `sources.message_reach` says how far that got once the project cap has been applied.
    """
    analysis_sessions, omitted, scope, surrounding_active = _analysis_context_sessions(
        sessions, project, focus
    )
    attention_sessions, attention_coverage = _attention_context_sessions(sessions, project)
    history_project = _history_project(config, state, sessions, project)
    workflow_discovery = _project_workflow_discovery(
        config,
        state,
        analysis_sessions,
        project,
        now=now,
        refresh=refresh,
    )
    observers: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    history_events: list[dict[str, Any]] = []
    gate_events: list[dict[str, Any]] = []
    history_source_scans: dict[str, dict[str, Any]] = {}
    tool_report_scans: list[dict[str, Any]] = []
    unavailable: list[dict[str, str]] = []
    briefings = 0
    child_assignments: list[dict[str, Any]] = []
    child_notices: list[Any] = []
    support_totals = {
        "tool_calls": 0,
        "dispatch_builds": 0,
        "subagent_calls": 0,
        "pending_subagents": 0,
        "suppressed_tool_calls": 0,
        "collapsed_contributors": 0,
    }
    reached: PressMessages | None = None
    omitted_rows = [
        {
            "harness": str(session.get("harness") or ""),
            "sid": str(session.get("sid") or ""),
            "reason": f"bounded to {MAX_PROJECT_OBSERVERS} newest active sessions",
        }
        for session in omitted
    ]
    for session in analysis_sessions:
        harness, sid = str(session.get("harness") or ""), str(session.get("sid") or "")
        identity = {"harness": harness, "sid": sid}
        is_focused = focus is not None and (harness, sid) == focus
        if is_focused and harness == "codex":
            child_assignments = _active_child_assignments(
                config,
                state,
                session,
                now=now,
                refresh=refresh,
                model_consent=model_consent,
                notices=child_notices,
            )
        if (
            harness in observer.DIRECTION_HARNESSES
            or (transcript_path := observer.resolve_transcript(config, state, harness, sid)) is None
        ):
            _collect_without_transcript(
                config,
                state,
                history_project,
                identity,
                now=now,
                sinks=(events, history_events, history_source_scans, unavailable),
            )
            continue
        result = _observe_session(
            config,
            state,
            transcript_path,
            (harness, sid),
            now=now,
            refresh=refresh and is_focused,
            model_consent=model_consent,
        )
        if result is not None:
            observers.append(
                {
                    **identity,
                    **result,
                    "source": "cached observer snapshot"
                    if str(result.get("snapshot_status", "")).startswith("cached")
                    else "bounded transcript and entity state",
                }
            )
        reached = (
            _session_messages(
                config,
                events,
                transcript_path,
                (harness, sid),
                message_reach if is_focused else None,
                now,
            )
            or reached
        )
        # Fixed positions are published for the focused session only: its message index is one pass
        # over its whole transcript, and no other session's page asks for it.
        work_support = _session_work_evidence(
            config,
            transcript_path,
            session,
            events,
            tool_report_scans,
            _index_provider(config, state, transcript_path, harness, sid) if is_focused else None,
        )
        backfill_rows, signature = _incremental_history_events(
            config, state, history_project, transcript_path, harness, sid, now=now
        )
        history_events.extend(backfill_rows)
        source_identity = f"{harness}:{sid}"
        if signature is not None:
            history_source_scans[source_identity] = signature
        _merge_support_counts(support_totals, work_support)
        gate_rows, prepared = _gate_context(config, state, transcript_path, harness, sid)
        gate_events.extend(gate_rows)
        briefings += prepared

    project_gate_rows, prepared = _project_peer_gate_context(config, state, sessions, project, None)
    gate_events.extend(project_gate_rows)
    briefings += prepared
    _scope_gate_events(
        events,
        history_events,
        gate_events,
        None,
        child_assignments,
        semantic_history.read(config, state, history_project),
    )

    timeline = _project_timeline(events, focus, reached.anchors if reached else frozenset())
    history_timeline = _dedupe_project_events(history_events)
    gate_count, steer_count, work_count = _timeline_counts(timeline)
    semantic = _semantic_model(timeline, observers, now=now)
    history_semantic = _semantic_model(history_timeline, observers, now=now)
    history = semantic_history.update(
        config,
        state,
        history_project,
        history_semantic,
        attention_sessions,
        child_assignments,
        now=now,
        source_scans=history_source_scans,
    )
    semantic = _with_command_attention(
        _semantic_for_focus(
            _merge_semantic_history(semantic, history, now=now),
            focus,
            child_assignments,
            now=now,
        ),
        attention_coverage,
    )
    return {
        "observer_model": {
            "enabled": config.observer_model_enabled and not config.model_calls_disabled,
            # Children are observed before the parent, so a child's call is the
            # one that records the notice when both are due.
            **next(
                (
                    {"notice": notice}
                    for notice in (
                        *child_notices,
                        *(row["notice"] for row in observers if "notice" in row),
                    )
                ),
                {},
            ),
            "max_prompt_bytes": observer.OBSERVER_MODEL_MAX_PROMPT_BYTES,
            "disclosure": (
                "A focused refresh sends redacted transcript excerpts and workflow stage through "
                f"Codex to {reading_route.destination('codex') or 'an unnamed destination'} "
                "for a goal summary. Each prompt is capped "
                "at 16 KiB, with a 60-second timeout "
                "and one call in flight per session. A focused refresh can include up to three "
                "active child sessions. Pause model calls or --no-observer-model stops these calls."
            ),
        },
        "project": project,
        "focus": {
            "harness": focus[0],
            "sid": focus[1],
            "observed": any(
                row.get("harness") == focus[0] and row.get("sid") == focus[1] for row in observers
            ),
        }
        if focus
        else None,
        "observers": observers,
        "events": timeline,
        "semantic": semantic,
        "workflow_discovery": workflow_discovery,
        "child_assignments": child_assignments,
        "sources": {
            "scope": scope,
            "surrounding_active": surrounding_active,
            "observer": {
                "live": len(observers),
                "unavailable": unavailable,
                "omitted": omitted_rows,
            },
            "gate": {
                "live": gate_count,
                "untimestamped_prepare": briefings,
                "status_history": "unavailable",
            },
            "steer": {
                "live": steer_count,
                "unavailable": unavailable,
                "omitted": omitted_rows,
            },
            "work": {
                "live": work_count,
                "support": support_totals,
                # Per session, never on a row: every sentence the page writes
                # about checks reads these full-scan counts, as item 4 of the
                # ruling `claude_tool_reports` cites requires.
                "tool_reports": tool_report_scans,
                "unavailable": unavailable,
                "omitted": omitted_rows,
            },
            # Only a press that read back carries it, so no page payload gains a key.
            **_message_reach_source(reached, timeline, focus),
        },
    }
