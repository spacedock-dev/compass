"""Claude transcript facts and agent classification shared below the collector.

Spacedock, notifications and the Claude collector all read these, so they sit
below all three rather than inside any one of them.
"""

from __future__ import annotations

import glob
import hashlib
import json
import os
import re
from typing import TYPE_CHECKING, Any, cast

from compass_runtime import config as runtime_config
from compass_runtime import io as runtime_io
from compass_runtime import records, transcripts
from compass_runtime import sessions as runtime_sessions
from compass_runtime import state as runtime_state

if TYPE_CHECKING:
    from collections.abc import Mapping

    from compass_runtime.config import RuntimeConfig
    from compass_runtime.state import RuntimeState

# Tools that mean Claude is blocked on the human, not just running long.
INPUT_TOOLS = {"AskUserQuestion", "ExitPlanMode"}


def transcript_started_at(
    config: RuntimeConfig, path: str, *, state: RuntimeState | None = None
) -> float | None:
    """Timestamp on the first record inside the bounded head that carries one.

    The first record is not it. Claude Code 2.1.259 opens a top-level transcript
    with untimestamped control records -- `agent-setting`, `mode`,
    `permission-mode` -- putting the first usable stamp at index 3 on seven of
    the eight freshest transcripts measured here, and index 0 on all four legacy
    `agent-*.jsonl` files. Reading line 1 alone therefore worked for the layout
    DRC-4223 was written against and returned None for every teammate
    dispatched into its own pane.

    The scan reuses the head budget `agent_identity` already reads over the same
    files, so a wider read costs no extra syscall. `st_birthtime` is the obvious
    alternative and DRC-4223 rejected it: macOS/BSD only, absent on the Ubuntu
    leg of `platform-tests`.

    With ``state`` the answer is memoised beside the two other head reads over
    these same files, and keyed on the file's own ``(mtime, size)`` the way
    ``session_title`` and the Codex readers are. A start stamp is immutable only
    once a file HAS one: a teammate parked on a permission prompt has a head
    with no timestamp in it, and the moment it takes its first turn the file
    grows one. Keying on the path alone therefore had to refuse to remember a
    null answer, which left the case the memo was ADDED for — a quiet agent
    retained on the roster — paying the bounded head read and the one-line
    fallback on every collection. Keying on the file makes remembering a null
    safe, so the whole answer is cached and every retained element costs one
    read once. Without ``state`` the read is unmemoised, so a caller outside a
    runtime keeps working.
    """
    key = None
    if state is not None:
        try:
            stat = os.stat(path)
        except OSError:
            return None
        key = (stat.st_mtime_ns, stat.st_size)
        with state.cache_lock:
            hit = state.agent_start_cache.get(path)
        if hit is not None and hit[0] == key:
            return hit[1]

    def remember(value: float | None) -> float | None:
        if state is not None and key is not None:
            with state.cache_lock:
                runtime_state.bounded_put(
                    state.agent_start_cache, path, (key, value), limit=config.max_cache_entries
                )
        return value

    try:
        size = os.path.getsize(path)
        data = runtime_io.read_prefix_bytes(path, max_bytes=config.claude_agent_scan_bytes)
    except OSError:
        return None
    lines = data.split(b"\n")
    if size > len(data) and data and not data.endswith(b"\n"):
        lines.pop()  # the byte prefix ended inside a JSON record
    for line in lines[: config.claude_agent_scan_lines]:
        if not line:
            continue
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if not isinstance(record, dict):
            continue
        stamp = records.parse_ts(record.get("timestamp") or "")
        if stamp is not None:
            return remember(stamp)
    # A first record wider than the head budget is popped as partial above, and
    # the old one-line read had a cap ten times larger. Falling back to it keeps
    # this change purely widening: no transcript that reported a start before
    # can lose it here. Its result is remembered too, null included: a stampless
    # transcript is the recurring cost, and it is the one the memo used to miss.
    return remember(
        records.parse_ts(runtime_io.read_first_json(config, path).get("timestamp") or "")
    )


def input_summary(block: Mapping[str, Any], *, limit: int) -> str:
    """What an input tool is actually asking, in one bounded line, or "".

    Summarised at parse time rather than kept raw, so the question is the only
    thing that survives the read. `ExitPlanMode` carries a whole plan, which can
    run to thousands of words and has no business sitting in a session row or in
    the caches one is built from.

    The two shapes are Claude Code's, read off 160 real records rather than a
    page: `AskUserQuestion` carries `questions`, a list of objects with a
    `question`, and `ExitPlanMode` carries `plan`. Both are treated as untrusted,
    because a transcript is a file on disk that Compass does not write.

    A plan is reduced to its first line, which is the plan's own title in
    practice. Anything longer is a document, and a row is not where a document
    goes.
    """
    payload = records.as_dict(block.get("input"))
    if block.get("name") == "ExitPlanMode":
        # Split before scrubbing, not after: `safe_text` turns a newline into a
        # space, so a plan scrubbed first has no line to take the first of.
        # The first *usable* line rather than the first line, because a plan can
        # open with a blank, a fence or a bullet, and none of those name it.
        for raw_line in str(payload.get("plan") or "").split("\n"):
            line = records.safe_text(raw_line, limit).strip().lstrip("#*->` ").strip()
            if line:
                return line[:limit]
        return ""
    questions = [
        text
        for item in records.as_list(payload.get("questions"))
        if (text := records.safe_text(records.as_dict(item).get("question"), limit).strip())
    ]
    if not questions:
        return ""
    extra = len(questions) - 1
    return f"{questions[0]} (+{extra} more)"[:limit] if extra else questions[0][:limit]


# Claude's own sentinel for an assistant record it generated locally, without
# the request ever reaching the API: a cancellation notice, an error banner, a
# tool-limit message. It is not a model, and it is common — one top-level
# transcript in five carries it as its newest assistant record, and many carry
# nothing else.
SYNTHETIC_MODEL = "<synthetic>"


def model_reported(value: Any) -> str | None:
    """The model an assistant record names, or None when it names none.

    `SYNTHETIC_MODEL` is rejected **by value**, never by the `isApiErrorMessage`
    flag that sits beside it on the same record. That flag is falsy on some
    synthetic records, so a flag gate publishes the sentinel as though it were a
    measurement — and "<synthetic>" on a session card is indistinguishable from a
    real model name to the person reading it. When the sentinel is all a
    transcript has, the honest answer is that no model was reported.

    Bounded here rather than at the caller because this is the only door: the
    value is untrusted vendor text on its way to the DOM.
    """
    if not isinstance(value, str) or value.strip() in ("", SYNTHETIC_MODEL):
        return None
    return records.safe_text(value, runtime_sessions.MODEL_CAP_CHARS).strip() or None


def session_title(config: RuntimeConfig, state: RuntimeState, path: str) -> str | None:
    """Newest generated Claude title, then the held `/goal`, then the first non-`/goal` prompt.

    ``ai-title`` records can be older than the bounded activity tail, so walk
    the file backward to find the newest one. The cache is invalidated whenever
    the transcript's size or mtime changes because Claude repeats title records
    as a session grows.
    """
    try:
        stat = os.stat(path)
    except OSError:
        return None
    cache_key = (stat.st_mtime_ns, stat.st_size)
    with state.cache_lock:
        cached = state.claude_title_cache.get(path)
    if cached is not None and cached[:2] == cache_key:
        return cached[2]

    title = None
    # The chunk filter does the heavy lifting; the per-line test below only
    # re-checks the few lines inside a chunk that had a hit.
    for raw in runtime_io.reverse_lines(config, path, contains=b'"aiTitle"'):
        if b'"aiTitle"' not in raw:
            continue
        try:
            record = json.loads(raw)
        except ValueError:
            continue
        if not isinstance(record, dict):
            continue
        value = record.get("aiTitle")
        if record.get("type") == "ai-title" and isinstance(value, str) and value:
            # The only untrusted vendor string in the runtime that used to reach
            # the payload unbounded — the model branch a few lines up is guarded,
            # and `collectors/claude.py` passes this one through unclipped.
            # Measured harmless on the local corpus (max 69 characters, no C0 or
            # bidi across all 457 published values), so this is latent rather
            # than live, and closed here rather than preserved.
            title = records.safe_text(value, records.PROMPT_TITLE_CAP_CHARS).strip() or None
            if title:
                break

    if title is None:
        # A held `/goal` names the session, so the page never shows the condition of a goal that
        # was replaced or cleared (the opener is the first condition, and nothing else says so).
        # Behind the `ai-title` check: a generated name is the session's identity and stays.
        goal = session_goal(config, state, path)
        if goal is not None:
            title = transcripts.prompt_title(config, goal["text"])
    if title is None:
        try:
            with open(path, encoding="utf-8", errors="replace") as source:
                for line in source:
                    if not line.startswith("{"):
                        continue
                    try:
                        record = json.loads(line)
                    except ValueError:
                        continue
                    if not isinstance(record, dict):
                        continue
                    signal = records._turn_signal(record, "claude")  # noqa: SLF001
                    if not signal or signal[0] != "prompt":
                        continue
                    prompt = records.extract_text(
                        records.message_dict(record).get("content")
                    ).strip()
                    candidate = transcripts.prompt_title(config, prompt)
                    # The opener of a goal no longer held names nothing; the next prompt does.
                    # Only when no held goal is authoritative: a read that started mid-file and saw
                    # no goal event may have missed a set, so the opener stays as the last resort.
                    if (
                        candidate
                        and candidate.split()[0] == "/goal"
                        and goal_history_known(state, path)
                    ):
                        continue
                    title = candidate
                    break
        except OSError:
            pass

    with state.cache_lock:
        runtime_state.bounded_put(
            state.claude_title_cache, path, (*cache_key, title), limit=config.max_cache_entries
        )
    return title


def session_instruction(
    config: RuntimeConfig, state: RuntimeState, path: str
) -> dict[str, Any] | None:
    """What this Claude session was last asked to do, labelled, or nothing.

    The line beside `session_title`, not a replacement for it. That title is
    generated once from the opening prompt and never refreshed — 424 of the 425
    transcripts carrying two or more `ai-title` records carry one distinct value,
    and across the 22 files that compacted mid-session none changed — so on a
    long session it names work that finished hours ago. Line 1 keeps it, because
    it is the session's identity and a reader recognises the row by it; this is
    the line that answers what the session is doing NOW.

    Read backward for the same reason the title is: the newest real prompt sits
    a median 40 KB from EOF but p95 650 KB, outside the bounded tail.

    Claude writes no turn-start commentary, so the "agent" rung of the ladder is
    unreachable here and a bare continuation falls straight through to a labelled
    older prompt. That is deliberate: on the 204-session cohort 60 newest prompts
    (29.4%) are six words or fewer, and "proceed" published as the current
    instruction is true and useless.
    """
    try:
        stat = os.stat(path)
    except OSError:
        return None
    cache_key = (stat.st_mtime_ns, stat.st_size)
    with state.cache_lock:
        cached = state.claude_instruction_cache.get(path)
    if cached is not None and cached[:2] == cache_key:
        return cached[2]

    prompt: tuple[str, float] | None = None
    older: tuple[str, float] | None = None
    # Superset filter, as `last_user_event` uses: every record this reads is a
    # `user` one, including the compaction summary that bounds the walk.
    for raw in runtime_io.reverse_lines(config, path, contains=b'"user"'):
        if not raw.startswith(b"{") or b'"user"' not in raw:
            continue
        try:
            record = json.loads(raw)
        except ValueError:
            continue
        if not isinstance(record, dict) or record.get("type") != "user":
            continue
        if record.get("isCompactSummary") is True:
            # Everything behind this is context the session no longer holds, so
            # no older prompt beyond it may be quoted as current work. Records
            # NEWER than it are still in context, which is why this only stops
            # the walk once the newest prompt is already in hand.
            if prompt is not None:
                break
            continue
        signal = records._turn_signal(record, "claude")  # noqa: SLF001
        if not signal or signal[0] != "prompt":
            continue
        body = records.extract_text(records.message_dict(record).get("content")).strip()
        if not body or records.injected_prompt(body, "claude"):
            continue
        at = records.parse_ts(record.get("timestamp") or "") or 0.0
        if prompt is None:
            prompt = (body, at)
            if transcripts.states_work(config, body):
                break
        elif transcripts.states_work(config, body):
            older = (body, at)
            break

    line = transcripts.instruction_from(config, prompt, None, older)
    with state.cache_lock:
        runtime_state.bounded_put(
            state.claude_instruction_cache, path, (*cache_key, line), limit=config.max_cache_entries
        )
    return line


# The longest `/goal` condition published whole: the 4,000 characters Claude Code documents. The
# record reader's 2,000-character message cap was the first choice and was an interpretation, not a
# limit of the command: a condition between 2,000 and 4,000 was a real goal that published nothing.
# The Goal field holds 240 and `_with_excerpt` already offers a longer one cut and marked, so the
# whole words travel and nothing is clipped silently. Over the limit the record is not a goal
# Claude Code could have accepted, and publishes nothing.
GOAL_CAP_CHARS = 4000
# Antigravity's own bound is unmeasured: agy 1.4.7 accepted 5,000 characters and refused nothing
# (docs/captures/antigravity/goal-1.4.7-macos.jsonl). Owner ruling 2026-10-27: a higher bound than
# the other two, so a long agy goal is offered cut rather than published as nothing. 16,000 sits
# well above what was measured and still keeps one pasted document off every board payload.
ANTIGRAVITY_GOAL_CAP_CHARS = 16_000


# The longest evaluator reason published. The reason is the small fast model's own sentence or two,
# shown quoted on the card and read for the paths and checks it names; a cut one ends in an ellipsis
# and the page reads it as cut (DRC-4948).
VERDICT_REASON_CAP_CHARS = 500

GoalEvent = tuple[str, str, float | None, str]


def _goal_attachment_event(attachment: Any, at: float | None) -> GoalEvent | None:
    if not isinstance(attachment, dict) or attachment.get("type") != "goal_status":
        return None
    condition = attachment.get("condition")
    text = condition if isinstance(condition, str) else ""
    if attachment.get("sentinel") is True:
        # Measured on 2.1.309: the same sentinel carries `met: false` for a set and `met: true`
        # for a clear of an active goal, with no reason, just before `Goal cleared:` prints.
        # Only those two values are read; a missing or non-bool `met` is ignored, never a clear.
        met = attachment.get("met")
        if met is False:
            return ("set", text, at, "")
        return ("cleared", "", at, "") if met is True else None
    reason = attachment.get("reason")
    if attachment.get("met") is True:
        return ("verdict", text, at, reason if isinstance(reason, str) else "")
    if attachment.get("met") is False and attachment.get("failed") is True:
        # Measured (2.1.309): the evaluator giving up. Its own record carries the reason, and the
        # goal is ended afterwards, so this is neither a verdict nor a held goal.
        return ("gave_up", text, at, reason if isinstance(reason, str) else "")
    return None


def _goal_event(record: Any) -> GoalEvent | None:
    """One goal-relevant record as `(kind, condition, at, reason)`, or None.

    Kinds: `set` (the sentinel `goal_status` attachment that carries the condition and is
    stamped the moment the command ran), `verdict` (the evaluator's `met: true`, with its
    reason), `cleared` (the sentinel carrying `met: true`, or the command's own printed answer).
    `met: false` with `failed: true` is `gave_up`, the evaluator giving up: not a verdict, and
    the goal is ended afterwards. A subagent's record is never the session's. Shapes:
    docs/captures/claude/goal-2.1.308-macos.jsonl, goal-clear-replace-verdicts-2.1.309-macos.jsonl
    and goal-give-up-ends-goal-2.1.309-macos.jsonl.
    """
    if not isinstance(record, dict) or record.get("isSidechain") is True:
        return None
    at = records.parse_ts(record.get("timestamp") or "")
    if record.get("type") == "attachment":
        return _goal_attachment_event(record.get("attachment"), at)
    run = record.get("commandRun")
    content = record.get("content")
    if (
        record.get("type") != "system"
        or record.get("subtype") != "local_command"
        or not isinstance(run, dict)
        or run.get("command") != "goal"
        or not isinstance(content, str)
    ):
        return None
    printed = content.replace("<local-command-stdout>", "").strip()
    # `Goal cleared:` is measured for an active goal (2.1.309); a met goal had already cleared
    # itself and printed `No goal set`, which is not a clear.
    return ("cleared", "", at, "") if printed.startswith("Goal cleared") else None


# What Codex 0.164.0 stores as the objective of a goal over 4,000 characters, the words moved to an
# attachment file. The sentence is the harness's, not the reader's goal, and the file is not read.
CODEX_GOAL_FILE_POINTER = "Read the Codex goal objective file at "
CODEX_GOAL_CLEARED = "User cleared the goal."


def _codex_goal_event(record: Any) -> GoalEvent | None:
    """One goal-relevant Codex rollout record as `(kind, objective, at, "")`, or None.

    `set` is a `thread_goal_updated` event, which Codex writes for a set, an edit, a pause, a
    resume and the new goal of a replace, and never for a completion or for a goal the model
    creates itself. It is timed by the goal's own `createdAt`, which an edit keeps. `dropped` is
    the `user.goal` message saying `User cleared the goal.`; Codex also writes that for a clear
    with no goal and before every goal set over a completed one, so it ends only a goal the read
    holds. Completion reaches only `goals_1.sqlite`, so no verdict is read here. Shapes:
    docs/captures/codex/goal-0.164.0-macos.jsonl.
    """
    if not isinstance(record, dict) or not isinstance(record.get("payload"), dict):
        return None
    payload = record["payload"]
    if record.get("type") == "event_msg" and payload.get("type") == "thread_goal_updated":
        return _codex_goal_set(payload.get("goal"))
    if (
        record.get("type") == "response_item"
        and payload.get("type") == "message"
        and payload.get("role") == "user"
        and _codex_goal_cleared(payload)
    ):
        return ("dropped", "", records.parse_ts(record.get("timestamp") or ""), "")
    return None


# The fixed paragraph agy 1.4.7 adds to a `/goal` input's `<ADDITIONAL_METADATA>`, the same on all
# 9 goal inputs measured in print and interactive mode; a request that only starts with the word
# carries none.
ANTIGRAVITY_GOAL_MARKER = "/goal is a [Slash Command]"
_ANTIGRAVITY_REQUEST_RE = re.compile(r"<USER_REQUEST>\s*(.*?)\s*</USER_REQUEST>", re.DOTALL)


def _antigravity_goal_event(record: Any) -> GoalEvent | None:
    """A `/goal` an Antigravity person typed, as `("set", condition, at, "")`, or None.

    agy writes no goal record of its own: the goal is a `USER_INPUT` from `USER_EXPLICIT` whose
    request opens `/goal ` and whose metadata carries the slash command's fixed paragraph. Nothing
    ends one on the record: a met or cancelled goal is a marker in the model's own reply, which is
    not read (reading this harness's work is out of scope, owner 2026-09-27), and a replace writes
    only the next set. Shapes: docs/captures/antigravity/goal-1.4.7-macos.jsonl.
    """
    if not isinstance(record, dict):
        return None
    if record.get("type") != "USER_INPUT" or record.get("source") != "USER_EXPLICIT":
        return None
    content, stamp = record.get("content"), record.get("created_at")
    if not isinstance(content, str) or ANTIGRAVITY_GOAL_MARKER not in content:
        return None
    request = _ANTIGRAVITY_REQUEST_RE.search(content)
    words = request.group(1) if request else ""
    if not words.startswith("/goal") or not words[len("/goal") :][:1].isspace():
        return None
    at = records.iso_epoch(stamp) if isinstance(stamp, str) else None
    return ("set", words[len("/goal") :].strip(), at, "")


# Codex keeps each thread's current goal as one row of `thread_goals` in this file, beside
# `sessions/` under `CODEX_HOME`, and a completed goal reaches nothing else: across 21
# completions no rollout record said `complete` (codex-cli 0.164.0,
# docs/captures/codex/goal-0.164.0-macos.jsonl). The `_1` is the file's own schema version,
# measured from 0.149 to 0.164; a later name reads as no file.
CODEX_GOALS_DB = "goals_1.sqlite"
# A bound on what one read keeps. One row per thread that ever finished a goal; a person would need
# years of goals to reach it, and a file past it still answers for the newest rows.
CODEX_GOALS_ROW_CAP = 10_000


def _codex_goals_path(config: RuntimeConfig) -> str:
    sessions_root = runtime_config.primary_store(config, "codex.sessions")
    return os.path.join(os.path.dirname(sessions_root.rstrip(os.sep)), CODEX_GOALS_DB)


def _read_codex_goals(path: str) -> list[Any]:
    """The completed rows, read-only. Raises the SQLite error a failed open or query gives.

    Codex keeps the file in WAL mode, and once its last process closes SQLite removes the `-wal`
    and `-shm` beside it; a `mode=ro` open of such a file cannot create the `-shm` it needs and
    fails. With no pending `-wal` data the file on disk is the whole database, so it is read again
    as `immutable`, as the Antigravity stores are (`collectors/antigravity.py`). With pending WAL
    data an immutable read could miss committed rows, so the first error stands.
    """
    query = (
        "SELECT thread_id, objective, created_at_ms, updated_at_ms FROM thread_goals"
        " WHERE status = 'complete' AND length(objective) <= ?"
        " ORDER BY updated_at_ms DESC LIMIT ?"
    )

    def read(uri: str) -> list[Any]:
        con = runtime_io.sqlite_module.connect(uri, uri=True, timeout=0.2)
        try:
            return list(con.execute(query, (GOAL_CAP_CHARS, CODEX_GOALS_ROW_CAP)).fetchall())
        finally:
            con.close()

    try:
        return read(runtime_io.sqlite_ro_uri(path))
    except runtime_io.sqlite_module.Error:
        try:
            pending = os.path.getsize(path + "-wal") > 0
        except OSError:
            pending = False
        if pending:
            raise
        return read(runtime_io.sqlite_ro_uri(path, immutable=True))


def _codex_completed_goals(
    config: RuntimeConfig, state: RuntimeState
) -> Mapping[str, tuple[str, float, float]]:
    """Every completed goal in Codex's goal file, by thread id: `(objective, set, completed)`.

    Opened read-only; the database is never written, though SQLite's WAL index (`-shm`) records
    the reader as it does for any reader. Cached on the file's own size and mtime and on its `-wal`
    beside it, so a board with many Codex rows reads it once per change, a failed read included. No
    file, no `sqlite3`, or a read that fails is no completed goal; a failed read is recorded once
    as a store error. An objective over `GOAL_CAP_CHARS` is not read, since no published goal can
    hold it.
    """
    path = _codex_goals_path(config)
    try:
        stat = os.stat(path)
    except OSError:
        return {}
    try:
        wal = os.stat(path + "-wal")
        wal_key: tuple[int, int] = (wal.st_mtime_ns, wal.st_size)
    except OSError:
        wal_key = (0, 0)
    key, version = f"codex-goals:{path}", (stat.st_mtime_ns, stat.st_size, *wal_key)
    with state.cache_lock:
        cached = state.metadata_cache.get(key)
    if cached is not None and cached.get("version") == version:
        return cast("Mapping[str, tuple[str, float, float]]", cached["rows"])
    rows: dict[str, tuple[str, float, float]] = {}
    if runtime_io.sqlite_available():
        try:
            found = _read_codex_goals(path)
        except runtime_io.sqlite_module.Error as exc:
            runtime_io.record_store_error(state, path, exc)
            found = []
        for thread, objective, created, updated in found:
            if (
                isinstance(thread, str)
                and isinstance(objective, str)
                and isinstance(created, int)
                and isinstance(updated, int)
                and 0 < created <= updated
            ):
                rows[thread] = (objective, float(created // 1000), updated / 1000)
    with state.cache_lock:
        runtime_state.bounded_put(
            state.metadata_cache,
            key,
            {"version": version, "rows": rows},
            limit=config.max_cache_entries,
        )
    return rows


def codex_goal_verdict(
    config: RuntimeConfig, state: RuntimeState, sid: str, goal: dict[str, Any] | None
) -> dict[str, Any] | None:
    """Codex's own `complete` on the goal a Codex row holds, as `{met, at, reason}`, or None.

    The working model marks its own goal complete with `update_goal`, so this is a weaker claim
    than Claude Code's separate evaluator, and it is published the same way: as the harness's
    claim, which a reading tests. It carries no reason, because Codex records none. It is this
    goal's only when the row's set time and words match the file's: an edit keeps the set time and
    rewrites the words, a replace makes a new row, and a clear deletes it.
    """
    if goal is None or not sid:
        return None
    found = _codex_completed_goals(config, state).get(sid)
    if found is None:
        return None
    objective, created, completed = found
    if created != goal.get("at") or _goal_words(objective) != goal.get("text"):
        return None
    return {"met": True, "at": completed, "reason": ""}


def codex_session_goal(
    config: RuntimeConfig, state: RuntimeState, path: str, sid: str
) -> dict[str, Any] | None:
    """The `/goal` a Codex rollout holds, with Codex's own `complete` on it where recorded."""
    goal = session_goal(config, state, path, "codex")
    verdict = codex_goal_verdict(config, state, sid, goal)
    return {**goal, "verdict": verdict} if goal is not None and verdict is not None else goal


def _codex_goal_set(goal: Any) -> GoalEvent | None:
    if not isinstance(goal, dict):
        return None
    created, objective = goal.get("createdAt"), goal.get("objective")
    if isinstance(created, bool) or not isinstance(created, (int, float)) or created <= 0:
        return None
    text = objective if isinstance(objective, str) else ""
    if text.startswith(CODEX_GOAL_FILE_POINTER):
        text = ""
    return ("set", text, float(created), "")


def _codex_goal_cleared(payload: dict[str, Any]) -> bool:
    meta = payload.get("internal_chat_message_metadata_passthrough")
    kinds = meta.get("content_item_kinds") if isinstance(meta, dict) else None
    if not isinstance(kinds, list) or "user.goal" not in kinds:
        return False
    return CODEX_GOAL_CLEARED in records.extract_text(payload.get("content")).splitlines()


def _goal_words(condition: str, cap: int = GOAL_CAP_CHARS) -> str:
    """The condition as the one masked line a row publishes, or "" if it cannot be held whole."""
    if not condition.strip() or len(condition) > cap:
        return ""
    masked = records.safe_text(records.mask_prose(condition), 2 * len(condition) + 64)
    return " ".join(masked.split())


def _verdict_reason(reason: str) -> str:
    """The evaluator's reason as one masked line within its bound, ending in an ellipsis if cut."""
    masked = " ".join(records.safe_text(records.mask_prose(reason), 2 * len(reason) + 64).split())
    if len(masked) <= VERDICT_REASON_CAP_CHARS:
        return masked
    return masked[:VERDICT_REASON_CAP_CHARS].rstrip() + "…"


GoalState = dict[str, Any]


def _empty_goal_state() -> GoalState:
    return {"goal": None, "gave_up": None, "cleared": None}


def _earlier_goal(state: GoalState, at: float) -> dict[str, Any] | None:
    """What became of the goal a new `/goal` finds in the state, as `{"how", "at"}`, or None.

    `replaced` only when the earlier goal was still active, at the moment the next one arrived;
    a met or given-up goal is said to be that, at its own time. Never the earlier goal's words.
    """
    held, gave_up = state["goal"], state["gave_up"]
    if held is not None:
        verdict = held.get("verdict")
        if verdict is not None:
            return {"how": "met", "at": verdict["at"]}
        return {"how": "replaced", "at": at}
    if gave_up is not None:
        return {"how": "gave-up", "at": gave_up["at"]}
    return None


def _advance_goal(state: GoalState, event: GoalEvent, cap: int = GOAL_CAP_CHARS) -> GoalState:
    """The session's goal state after one more event: the latest set wins, a met one is kept.

    A verdict only confirms a goal already held, by its words, and is kept on it as the
    harness's claim; a later set or clear takes it away with the goal it was about. One for
    words not held, or with no set record behind it in the bytes read, has no known set
    time, and a time is never taken from the verdict instead.

    A give-up and a clear end the goal and are kept beside it, each under its own key and never
    as a verdict: `session_goal` stays None, so naming, drafting and adoption read as before. A
    second clear signal for the same clear (the sentinel, then the printed line in `claude -p`)
    changes nothing, so the first time wins. A new set takes both away and records, on the goal
    it holds, how the earlier one ended.
    """
    kind, condition, at, reason = event
    if kind == "cleared":
        return _after_clear(state, at)
    if kind == "dropped":
        return _after_clear(state, at) if state["goal"] is not None else state
    words = _goal_words(condition, cap)
    if kind == "set":
        return _after_set(state, words, at)
    if kind == "gave_up":
        return _after_give_up(state, words, at, reason)
    if kind == "verdict":
        return _after_verdict(state, words, at, reason)
    return state


def _after_clear(state: GoalState, at: float | None) -> GoalState:
    if state["goal"] is None and (state["cleared"] is not None or state["gave_up"] is not None):
        return state
    return {"goal": None, "gave_up": None, "cleared": {"at": at} if at is not None else None}


def _after_set(state: GoalState, words: str, at: float | None) -> GoalState:
    goal = state["goal"]
    if not words or at is None:
        return _empty_goal_state()
    if goal is not None and goal["text"] == words and goal["at"] == at:
        return state
    if goal is not None and goal["at"] == at:
        # A Codex edit rewrites the objective and keeps `createdAt`: the same goal in new words, so
        # it keeps how the earlier one ended and loses a verdict given on the old words. Claude
        # Code stamps each set when it runs, so no two of its sets share an instant.
        kept = {key: value for key, value in goal.items() if key != "verdict"}
        return {**state, "goal": {**kept, "text": words}}
    held: dict[str, Any] = {"text": words, "at": at}
    earlier = _earlier_goal(state, at)
    if earlier is not None:
        held["earlier"] = earlier
    return {"goal": held, "gave_up": None, "cleared": None}


def _after_give_up(state: GoalState, words: str, at: float | None, reason: str) -> GoalState:
    goal = state["goal"]
    if goal is None:
        return state
    if goal["text"] != words or at is None:
        return {**state, "goal": None}
    return {"goal": None, "gave_up": {"at": at, "reason": _verdict_reason(reason)}, "cleared": None}


def _after_verdict(state: GoalState, words: str, at: float | None, reason: str) -> GoalState:
    goal = state["goal"]
    if goal is None or goal["text"] != words:
        return {**state, "goal": None}
    if at is None:
        return state
    verdict = {"met": True, "at": at, "reason": _verdict_reason(reason)}
    return {**state, "goal": {**goal, "verdict": verdict}}


def session_goal(
    config: RuntimeConfig, state: RuntimeState, path: str, harness: str = "claude"
) -> dict[str, Any] | None:
    """The `/goal` this Claude, Codex or Antigravity session holds, `{"text", "at"}`, or None.

    `harness` picks the record reader (`_goal_event`, `_codex_goal_event` or
    `_antigravity_goal_event`); the state they advance, the cache and the published mapping are
    shared. A Codex or Antigravity goal carries no verdict, and an Antigravity one no `earlier`.

    Read forward and incrementally, as `turns.scan_turns` is: each call parses only the bytes
    appended since the last, because the newest goal can sit anywhere in a long file and a
    session with none would otherwise be reread end to end on every collection. A cold read
    starts at most `config.turn_scan_max_bytes` from the end; a goal set before that and not
    touched since is not seen, and publishes nothing rather than a guess. Only complete lines
    count, so a half-written record is read once it finishes.

    The published mapping is `{"text", "at"}`, with `offered` and `cut` added when the condition
    is longer than the Goal field holds (`_with_excerpt`), and `verdict` (`{met, at, reason}`, the
    harness's claim that the goal is met) once the evaluator has decided. The key is absent, not
    empty, before then. `earlier` (`{how, at}`, how being "replaced", "met" or "gave-up") is added
    when this goal followed one the read saw end, and carries never the earlier goal's words.
    """
    try:
        stat = os.stat(path)
    except OSError:
        return None
    key = f"session-goal:{path}"
    read_event = _GOAL_READERS.get(harness, _goal_event)
    cap = ANTIGRAVITY_GOAL_CAP_CHARS if harness == "antigravity" else GOAL_CAP_CHARS
    with state.cache_lock:
        cached = state.metadata_cache.get(key)
    if (
        cached is not None
        and cached.get("ino") == stat.st_ino
        and cached["pos"] <= stat.st_size
        and stat.st_size - cached["pos"] <= config.turn_scan_max_bytes
    ):
        pos, goal_state, cold = cached["pos"], _cached_goal_state(cached), False
        seen = cached.get("seen", False)
    else:
        pos, goal_state, cold = (
            max(0, stat.st_size - config.turn_scan_max_bytes),
            _empty_goal_state(),
            True,
        )
        # A read from byte 0 has seen everything, so no goal event means none was ever recorded.
        seen = pos == 0
    if pos < stat.st_size:
        try:
            with open(path, "rb") as source:
                source.seek(pos)
                data = source.read(stat.st_size - pos)
        except OSError:
            return None
        if cold and pos > 0:
            # A cold read that starts mid-file starts mid-line.
            skip = data.find(b"\n")
            data, pos = (b"", pos) if skip < 0 else (data[skip + 1 :], pos + skip + 1)
        end = data.rfind(b"\n")
        if end >= 0:
            for raw in data[:end].split(b"\n"):
                if b"goal" not in raw or not raw.startswith(b"{"):
                    continue
                try:
                    event = read_event(json.loads(raw))
                except (ValueError, RecursionError):
                    continue
                if event is not None:
                    seen = True
                    goal_state = _advance_goal(goal_state, event, cap)
            pos += end + 1
    with state.cache_lock:
        runtime_state.bounded_put(
            state.metadata_cache,
            key,
            {"ino": stat.st_ino, "pos": pos, **goal_state, "seen": seen},
            limit=config.max_cache_entries,
        )
    goal = goal_state["goal"]
    if goal is None:
        return None
    if harness == "antigravity":
        # agy records no end to a goal, so a later set says nothing true about the one before it.
        goal = {key: value for key, value in goal.items() if key != "earlier"}
    return _with_excerpt(goal, config.annotation_text_cap_chars)


_GOAL_READERS = {"codex": _codex_goal_event, "antigravity": _antigravity_goal_event}


def _cached_goal_state(cached: dict[str, Any]) -> GoalState:
    return {key: cached.get(key) for key in ("goal", "gave_up", "cleared")}


def _goal_ending(state: RuntimeState, path: str, key: str) -> dict[str, Any] | None:
    with state.cache_lock:
        cached = state.metadata_cache.get(f"session-goal:{path}")
    value = cached.get(key) if cached else None
    return dict(value) if value is not None else None


def session_goal_cleared(state: RuntimeState, path: str) -> dict[str, Any] | None:
    """`{"at"}` when the last `session_goal` read saw this session clear its goal and none since.

    Read from the same cache entry, so call it after `session_goal`. None means no clear was seen
    in the bytes read, which is unknown and not "was not cleared": a cold read that starts
    mid-file publishes only what it saw.
    """
    return _goal_ending(state, path, "cleared")


def session_goal_gave_up(state: RuntimeState, path: str) -> dict[str, Any] | None:
    """`{"at", "reason"}` when the harness gave up on the goal and no goal has been set since.

    The harness's claim, in a key of its own and never under `verdict`: every reader of a met
    goal keys on that. The reason is masked, one line, bounded. No iterations, tokens or
    duration are published. None is unknown, as for `session_goal_cleared`.
    """
    return _goal_ending(state, path, "gave_up")


def goal_history_known(state: RuntimeState, path: str) -> bool:
    """Whether the last `session_goal` read saw the whole file or at least one goal event.

    A cold read that starts mid-file returns None both when no goal event was seen and when one
    cleared the goal inside the window; only the second proves the goal is not held.
    """
    with state.cache_lock:
        cached = state.metadata_cache.get(f"session-goal:{path}")
    return bool(cached and cached.get("seen"))


def _with_excerpt(goal: dict[str, Any], cap: int) -> dict[str, Any]:
    """The goal as published, plus the excerpt the Goal field can hold when it cannot hold it whole.

    `offered` is what an adoption stores (`records.safe_text` at the store's own bound), so the page
    and the server agree on the words without either clipping on its own. It and `cut` exist only
    for a goal over the bound: a key every row carried would say nothing about this goal.
    """
    words = goal["text"]
    offered = records.safe_text(words, cap).strip()
    if offered == words:
        return dict(goal)
    return {**goal, "offered": offered, "cut": True}


def last_user_event(config: RuntimeConfig, state: RuntimeState, path: str) -> str | None:
    """Identity of the newest user record, independent of record timestamps."""
    try:
        stat = os.stat(path)
    except OSError:
        return None
    cache_key = (stat.st_mtime_ns, stat.st_size)
    with state.cache_lock:
        cached = state.claude_user_event_cache.get(path)
    if cached is not None and cached[:2] == cache_key:
        return cached[2]

    marker = None
    # Superset filter: a user record must contain the literal "user".
    for raw in runtime_io.reverse_lines(config, path, contains=b'"user"'):
        if not raw.startswith(b"{") or b'"user"' not in raw:
            continue
        try:
            record = json.loads(raw)
        except ValueError:
            continue
        if not isinstance(record, dict) or record.get("type") != "user":
            continue
        uuid = record.get("uuid")
        marker = (
            uuid
            if isinstance(uuid, str) and uuid
            else hashlib.blake2b(raw, digest_size=16).hexdigest()
        )
        break

    with state.cache_lock:
        runtime_state.bounded_put(
            state.claude_user_event_cache,
            path,
            (*cache_key, marker),
            limit=config.max_cache_entries,
        )
    return marker


def is_turn_stop_record(record: Any, after: str | None) -> bool:
    """Whether a transcript record is Claude Code's own turn stop for its session.

    The top-level `stop_hook_summary` Claude Code writes when its Stop hooks
    run, which is the event a hook stop is stamped from. `after` is the type of
    the newest `user` or `assistant` record before it in the file, and only an
    `assistant` reply admits it. A Stop hook that blocks the stop, and a goal
    check that is not met, write their feedback as an `isMeta` user record
    before the summary, then write the summary with `preventedContinuation`
    false and keep the turn going (verifier S1, read from Claude Code 2.1.287).
    `preventedContinuation` true is a hook ending the turn, which is a stop.
    A subagent's record is not the session's, and only the Stop hooks'
    summary is a stop: 2.1.287's Stop path writes no `hookLabel`, and its own
    reader knows one labelled `PreToolUse`, written mid-turn before a tool runs
    (verifier S2), so an absent label or `Stop` is admitted and no other.
    The scorer's
    `mark_abstention._transcript_stop` reads the same keys and the same rule,
    and a test holds the two to one table. No capture under `docs/captures/`
    records this shape: it rests on the 2026-10-01 measurement in
    `docs/design-reading-a-session.md`.
    """
    return bool(
        after == "assistant"
        and isinstance(record, dict)
        and record.get("type") == "system"
        and record.get("subtype") == "stop_hook_summary"
        and record.get("isSidechain") is False
        and isinstance(record.get("preventedContinuation"), bool)
        and isinstance(record.get("sessionId"), str)
        and record.get("hookLabel", "Stop") == "Stop"
    )


def analyze_transcript(config: RuntimeConfig, state: RuntimeState, path: str) -> dict[str, Any]:
    """Claude Code transcript tail.

    `model` and `model_sidechain` are the two halves of one reading, split on the
    `isSidechain` flag, because that flag **inverts** between a session and its
    subagents. A top-level transcript's own turns are not sidechains, so its model
    lands in `model`; a subagent writes its own transcript and every assistant
    record in it is flagged as a sidechain, so its model lands in
    `model_sidechain`. A caller holding a child transcript therefore reads
    `model_sidechain or model` — see `collectors.claude.child_model`.

    Newest wins for both: the last assistant record in the tail is the model the
    session is on now. A mid-session switch is real and rare (a plan change), and
    a transcript does not carry stray background models to be confused with one.
    Not cached on session identity for the same reason: the value is mutable
    while the session runs.
    """
    info: dict[str, Any] = {
        "title": session_title(config, state, path),
        "last_prompt": None,
        "model": None,
        "model_sidechain": None,
        "usage_events": [],  # (epoch, output_tokens)
        "pending_input_tool": None,  # {"name", "ts", "asks"} awaiting the human
        "last_tool": None,
        "last_event_ts": 0,
        # Newest record the *agent* wrote, which is not the same as the newest
        # record in the file. Bookkeeping records land in a parked transcript
        # from causes that are not the agent resuming, so a wait guard that
        # reads "has this session moved on" has to read this and not the mtime.
        "last_assistant_ts": 0,
        # Newest conversation record (`user` or `assistant`, tool results
        # included because Claude writes them as user records). The stop guard
        # reads this rather than the mtime: Claude Code appends `system`
        # records such as `away_summary` minutes after a turn stops, and read
        # as mtime one retired every observed stop (DRC-4770). The same
        # definition as `project_context.claude_activity_between`, which a
        # test holds it to.
        "last_conversation_ts": 0,
        # The newest turn stop Claude Code recorded itself (`is_turn_stop_record`)
        # and the session id it names, read in this same loop: no further read.
        # The collector decides whether it still stands (owner, 2026-10-02).
        "turn_stop_ts": 0,
        "turn_stop_sid": None,
        "last_user_event": last_user_event(config, state, path),
    }
    pending: dict[Any, Any] = {}  # tool_use id -> {"name", "ts", "asks"} for INPUT_TOOLS only
    # The type of the newest conversation record so far, in file order: the
    # context `is_turn_stop_record` reads a summary in.
    conversation: str | None = None
    for line in runtime_io.read_tail(config, path):
        if not line or line[0] != "{":
            continue
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue
        t = d.get("type")
        ep = records.parse_ts(d.get("timestamp") or "")
        if ep:
            info["last_event_ts"] = max(info["last_event_ts"], ep)
            if t in {"user", "assistant"}:
                info["last_conversation_ts"] = max(info["last_conversation_ts"], ep)
        if ep and ep >= info["turn_stop_ts"] and is_turn_stop_record(d, conversation):
            info["turn_stop_ts"] = ep
            info["turn_stop_sid"] = d["sessionId"]
        if t in ("user", "assistant"):  # a tuple: `t` may be any JSON value
            conversation = t
        if t == "last-prompt":
            info["last_prompt"] = d.get("lastPrompt")
        elif t == "assistant":
            if ep:
                info["last_assistant_ts"] = max(info["last_assistant_ts"], ep)
            msg = records.message_dict(d)
            model = model_reported(msg.get("model"))
            if model:
                # Last write wins, and a rejected value overwrites nothing: a
                # trailing synthetic error must not withdraw the model the turns
                # before it were measured on.
                info["model_sidechain" if d.get("isSidechain") else "model"] = model
            usage = records.as_dict(msg.get("usage"))
            if ep and usage.get("output_tokens"):
                info["usage_events"].append((ep, usage["output_tokens"]))
            for c in records.as_list(msg.get("content")):
                if isinstance(c, dict) and c.get("type") == "tool_use":
                    info["last_tool"] = c.get("name")
                    if c.get("name") in INPUT_TOOLS:
                        pending[c.get("id")] = {
                            "name": c.get("name"),
                            "ts": ep,
                            "asks": input_summary(c, limit=config.input_summary_cap_chars),
                        }
        elif t == "user":
            for c in records.as_list(records.message_dict(d).get("content")):
                if isinstance(c, dict) and c.get("type") == "tool_result":
                    pending.pop(c.get("tool_use_id"), None)
    if pending:
        info["pending_input_tool"] = max(pending.values(), key=lambda p: p["ts"] or 0)
    return info


def head_cwd(config: RuntimeConfig, path: str) -> str:
    """The first working directory a transcript's opening records carry, ``""`` if none.

    Uncached, for a reader that holds no state. A `cd` moves every later record's
    `cwd`, so this is the one place the directory the session began in survives.
    """
    try:
        lines = runtime_io.iter_bounded_text_lines(
            path,
            max_lines=config.claude_cwd_scan_lines,
            per_line_bytes=config.claude_cwd_line_bytes,
        )
        for line in lines:
            if '"cwd"' not in line:
                continue
            try:
                d = json.loads(line)
            except ValueError:
                continue
            value = d.get("cwd") if isinstance(d, dict) else None
            if isinstance(value, str) and value:
                return value
    except OSError:  # pragma: no cover - iterator handles filesystem failures
        return ""
    return ""


def session_cwd(config: RuntimeConfig, state: RuntimeState, path: str) -> str:
    """Working directory recorded on the transcript head, ``""`` if absent.

    Claude is the one harness whose store does not hand a collector a cwd: the
    ``projects/`` directory name encodes the path with every separator replaced
    by ``-``, and that cannot be split back apart because a directory may
    legitimately contain ``-``. The records themselves carry the real path, so
    read it rather than guessing at the encoding.

    An absent cwd is not cached: a transcript head can be written before any
    record carries one, and the answer changes as soon as one does.
    """
    with state.cache_lock:
        hit = state.cwd_cache.get(path)
    if hit is not None:
        return hit
    cwd = head_cwd(config, path)
    if cwd:
        with state.cache_lock:
            runtime_state.bounded_put(state.cwd_cache, path, cwd, limit=config.max_cache_entries)
    return cwd


def hook_user_event(
    config: RuntimeConfig,
    state: RuntimeState,
    path: str,
    prefix: str,
) -> tuple[bool, str | None]:
    """Return a safe transcript baseline for a Notification-hook payload."""
    try:
        real_path = os.path.realpath(path)
        projects_root = os.path.realpath(runtime_config.primary_store(config, "claude.projects"))
        inside_projects = os.path.commonpath((projects_root, real_path)) == projects_root
    except (OSError, ValueError):
        return (False, None)
    basename = os.path.basename(real_path)
    if not inside_projects or not basename.startswith(prefix) or not basename.endswith(".jsonl"):
        return (False, None)
    return (True, last_user_event(config, state, real_path))


# Record types that carry no conversation and never open a live session. A
# transcript made only of these is a harness artifact: measured 2026-09-23,
# 438 of 765 files in one project directory were a single `ai-title` record
# (DRC-4645), and `ai-title`, `agent-name` and `pr-link` covered 471 of the 488
# conversation-free files across every project. Session-start records (`mode`,
# `permission-mode`, `attachment`, `last-prompt`, `system`, `progress`,
# `file-history-snapshot`) are deliberately absent: a session opened and not
# yet prompted writes exactly those, for up to 85 minutes in the same sweep,
# and it must keep its row. Any record outside this set, or with no string
# type, keeps the file a session.
METADATA_RECORD_TYPES = frozenset({"ai-title", "agent-name", "pr-link"})


def has_conversation(config: RuntimeConfig, state: RuntimeState, path: str) -> bool:
    """Whether a top-level transcript is a session rather than harness metadata.

    Only a file that fits inside the bounded prefix is ever classified as
    metadata, because a longer one cannot be judged without reading it all.
    A True answer read from a complete file is final (transcripts only
    append); an empty or mid-write file is re-read next pass, and a False
    answer is keyed on the file's stat.
    """
    try:
        stat = os.stat(path)
    except OSError:
        return True
    key = (stat.st_mtime_ns, stat.st_size)
    with state.cache_lock:
        cached = state.conversation_cache.get(path)
    if cached is not None and (cached[1] or cached[0] == key):
        return cached[1]
    try:
        data = runtime_io.read_prefix_bytes(path, max_bytes=config.claude_agent_scan_bytes)
    except OSError:
        return True
    if stat.st_size > len(data):
        result, settled = True, True
    else:
        types: set[str | None] = set()
        for line in data.split(b"\n"):
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                types.add(None)
                continue
            kind = rec.get("type") if isinstance(rec, dict) else None
            types.add(kind if isinstance(kind, str) else None)
        result = not types or not types <= METADATA_RECORD_TYPES
        # A True read from an empty or torn file may only mean the harness had
        # not finished writing; it is not cached, so the next pass decides.
        settled = not result or (bool(data) and data.endswith(b"\n"))
    if settled:
        with state.cache_lock:
            runtime_state.bounded_put(
                state.conversation_cache, path, (key, result), limit=config.max_cache_entries
            )
    return result


def agent_identity(
    config: RuntimeConfig,
    state: RuntimeState,
    path: str,
) -> tuple[bool, str, str]:
    """Classify a top-level transcript: (is_subagent, agent_name, parent_prefix).

    Harness >= 2.x writes subagent transcripts as ordinary <uuid>.jsonl files
    in the project directory; their records carry ``agentName`` and
    ``teamName`` = "session-<parent 8-char prefix>". Older harnesses used
    <session>/subagents/agent-*.jsonl, still handled by
    load_claude_subagents().
    """
    with state.cache_lock:
        cached = state.agent_class_cache.get(path)
    if cached is not None:
        return cached
    name, parent = "", ""
    size = 0
    lines_seen = 0
    try:
        size = os.path.getsize(path)
        data = runtime_io.read_prefix_bytes(path, max_bytes=config.claude_agent_scan_bytes)
        lines = data.split(b"\n")
        if size > len(data) and data and not data.endswith(b"\n"):
            lines.pop()  # the byte prefix ended inside a JSON record
        for line in lines[: config.claude_agent_scan_lines]:
            if not line:
                continue
            lines_seen += 1
            if name and parent:
                break
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if not isinstance(rec, dict):
                continue
            agent_name = rec.get("agentName")
            if not name and isinstance(agent_name, str) and agent_name:
                name = agent_name
            team = rec.get("teamName")
            if not parent and isinstance(team, str) and team.startswith("session-"):
                parent = team[len("session-") :][:8]
    except OSError:
        return (False, "", "")
    result = (bool(parent), name, parent)
    # A complete subagent identity is conclusive; an incomplete result is only
    # trusted once the file has enough content that later records cannot change it.
    if (
        (parent and name)
        or lines_seen >= config.claude_agent_scan_lines
        or size >= config.claude_agent_cache_negative_min_bytes
    ):
        with state.cache_lock:
            runtime_state.bounded_put(
                state.agent_class_cache, path, result, limit=config.max_cache_entries
            )
    return result


def agent_setting(config: RuntimeConfig, state: RuntimeState, path: str) -> str:
    """The ``agentSetting`` a transcript declares in its head, else "".

    The launcher passes ``--agent spacedock:first-officer``, so the value is
    written at record index 0 or 1 — inside the same head bytes the subagent
    classifier already reads. Immutable per file once present.
    """
    with state.cache_lock:
        cached = state.spacedock_role_cache.get(path)
    if cached is not None:
        return cached
    setting = ""
    size = 0
    try:
        size = os.path.getsize(path)
        data = runtime_io.read_prefix_bytes(path, max_bytes=config.claude_agent_scan_bytes)
        lines = data.split(b"\n")
        if size > len(data) and data and not data.endswith(b"\n"):
            lines.pop()
        for line in lines[: config.claude_agent_scan_lines]:
            if not line or b"agentSetting" not in line:
                continue
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if not isinstance(record, dict):
                continue
            value = record.get("agentSetting")
            if isinstance(value, str) and value:
                setting = value
                break
    except OSError:
        return ""
    if setting or size >= config.claude_agent_cache_negative_min_bytes:
        with state.cache_lock:
            runtime_state.bounded_put(
                state.spacedock_role_cache, path, setting, limit=config.max_cache_entries
            )
    return setting


def prefix_is_agent(config: RuntimeConfig, state: RuntimeState, prefix: str) -> bool:
    """True when the newest transcript for this 8-char prefix belongs to a
    subagent. Used to suppress popups for agent sessions."""
    newest, newest_mtime = None, 0.0
    for fp in runtime_io.glob_stores(
        config,
        "claude.projects",
        "*",
        glob.escape(prefix) + "*.jsonl",
    ):
        try:
            mtime = os.path.getmtime(fp)
        except OSError:
            continue
        if mtime > newest_mtime:
            newest, newest_mtime = fp, mtime
    if not newest:
        return False
    return agent_identity(config, state, newest)[0]
