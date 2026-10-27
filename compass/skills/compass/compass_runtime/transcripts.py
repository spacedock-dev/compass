"""Shared first-line metadata, prompt titles, and non-Claude transcript analysis."""

from __future__ import annotations

import itertools
import json
import os
import re
import unicodedata
from typing import TYPE_CHECKING, Any, Final, NamedTuple

from . import io as runtime_io
from . import records, sessions
from . import state as runtime_state

if TYPE_CHECKING:
    from collections.abc import Callable

    from .config import RuntimeConfig
    from .state import RuntimeState

# ---------------------------------------------------------------------------
# First-line metadata cache (JSONL harnesses write immutable line-1 metadata)


def first_line_meta(
    config: RuntimeConfig,
    state: RuntimeState,
    path: str,
    parse: Callable[[dict[str, Any]], dict[str, Any]],
) -> dict[str, Any]:
    """parse(first-line JSON dict) -> dict; cached per path. Not cached on
    read/parse failure so a partially written first line retries later."""
    with state.cache_lock:
        m = state.metadata_cache.get(path)
    if m is not None:
        return m
    d = runtime_io.read_first_json(config, path)
    if not d:
        return {}
    m = parse(d)
    with state.cache_lock:
        cached = state.metadata_cache.get(path)
        if cached is not None:
            return cached
        runtime_state.bounded_put(state.metadata_cache, path, m, limit=config.max_cache_entries)
        return m


def codex_meta(config: RuntimeConfig, state: RuntimeState, path: str) -> dict[str, Any]:
    """Codex rollout line 1 (session_meta): identity, cwd, and whether the
    file is a subagent thread (thread_source == "subagent")."""

    def parse(d: dict[str, Any]) -> dict[str, Any]:
        # Every field is untyped JSON from disk — one malformed rollout must
        # not AttributeError the whole Codex collector.
        p = d.get("payload")
        if not isinstance(p, dict):
            p = {}
        spawn = records.as_dict(
            records.as_dict(records.as_dict(p.get("source")).get("subagent")).get("thread_spawn")
        )
        nickname = p.get("agent_nickname")
        agent_path = p.get("agent_path") or spawn.get("agent_path")
        label = (
            nickname
            if isinstance(nickname, str) and nickname
            # basename(), not rsplit("/"): on Windows the recorded path is
            # backslash-separated, and a hardcoded "/" would keep the whole
            # path as the agent's label.
            else (
                os.path.basename(agent_path) if isinstance(agent_path, str) and agent_path else None
            )
        )
        return {
            "session_id": p.get("session_id") or p.get("id"),
            # Current Codex subagent metadata carries two identities: session_id
            # is the top-level root and id is this rollout thread. Collection
            # groups on the former; nested-parent traversal needs the latter.
            "thread_id": p.get("id") or p.get("session_id"),
            "parent_session_id": (
                spawn.get("parent_thread_id") if isinstance(spawn, dict) else None
            ),
            "cwd": p.get("cwd"),
            "subagent": p.get("thread_source") == "subagent",
            "agent_label": label or None,
            "agent_path": agent_path if isinstance(agent_path, str) and agent_path else None,
        }

    return first_line_meta(config, state, path, parse)


def gemini_meta(config: RuntimeConfig, state: RuntimeState, path: str) -> dict[str, Any]:
    """Gemini chat recording line 1: sessionId, kind (main|subagent),
    directories (cwd list)."""

    def parse(d: dict[str, Any]) -> dict[str, Any]:
        dirs = d.get("directories")
        return {
            "session_id": d.get("sessionId"),
            "kind": d.get("kind"),
            "cwd": dirs[0] if isinstance(dirs, list) and dirs else None,
        }

    return first_line_meta(config, state, path, parse)


def copilot_meta(config: RuntimeConfig, state: RuntimeState, path: str) -> dict[str, Any]:
    """Copilot events.jsonl line 1 is normally session.start with
    data.context.cwd."""

    def parse(d: dict[str, Any]) -> dict[str, Any]:
        data = records.as_dict(d.get("data"))
        ctx = records.as_dict(data.get("context"))
        return (
            {"cwd": ctx.get("cwd") or data.get("cwd")} if d.get("type") == "session.start" else {}
        )

    return first_line_meta(config, state, path, parse)


def droid_meta(config: RuntimeConfig, state: RuntimeState, path: str) -> dict[str, Any]:
    """Droid transcript line 1 (session_start): id, session title, cwd."""

    def parse(d: dict[str, Any]) -> dict[str, Any]:
        if d.get("type") != "session_start":
            return {}
        return {
            "session_id": d.get("id"),
            "title": d.get("sessionTitle") or d.get("title"),
            "cwd": d.get("cwd"),
        }

    return first_line_meta(config, state, path, parse)


def pi_meta(config: RuntimeConfig, state: RuntimeState, path: str) -> dict[str, Any]:
    """Pi v3's immutable session header: identity and workspace only."""

    def parse(d: dict[str, Any]) -> dict[str, Any]:
        if d.get("type") != "session":
            return {}
        session_id = d.get("id")
        cwd = d.get("cwd")
        parent_session = d.get("parentSession")
        return {
            "session_id": session_id if isinstance(session_id, str) else None,
            "cwd": cwd if isinstance(cwd, str) else None,
            "parent_session": parent_session if isinstance(parent_session, str) else None,
        }

    return first_line_meta(config, state, path, parse)


# ---------------------------------------------------------------------------
# Prompt titles

# Harness-injected wrappers around a user prompt. A slash command arrives as
# `<command-name>/plugin</command-name>` and a dispatched worker's instructions
# as `<teammate-message teammate_id="...">`, so the naive "first line of the
# first prompt" title renders raw markup. Measured over 248 real transcripts,
# 138 titles began with one of these.
#
# The underscore in the name class is not decoration. Claude spells its wrappers
# with hyphens, Codex spells its own with underscores — `<recommended_plugins>`,
# `<environment_context>`, `<subagent_notification>`, `<user_shell_command>`,
# `<turn_aborted>` — and without `_` those five survived stripping and the title
# rendered as the bare tag. Measured across 24,636 user-role texts: 312 titles
# change, every one of them from a bare tag to the text it wrapped, and 0 of the
# 21,899 Claude texts move at all, because no Claude wrapper carries an
# underscore.
_PROMPT_TAG_RE = re.compile(r"</?[a-z][a-z0-9_-]*(?:\s[^>]*?)?/?>", re.IGNORECASE)
_COMMAND_NAME_RE = re.compile(r"<command-name>\s*(.*?)\s*</command-name>", re.DOTALL)
_COMMAND_ARGS_RE = re.compile(r"<command-args>\s*(.*?)\s*</command-args>", re.DOTALL)
# A filesystem path, not a URL: `://` is excluded so a GitHub link survives
# whole, since the repo and PR number in it are the informative part. Absolute
# paths otherwise eat the entire title budget and say nothing a basename does
# not, and a dispatch prompt naming a UUID temp file is the worst of them.
_PROMPT_PATH_RE = re.compile(r"(?<!:)(?<![\w/])(?:~|/[^\s/]+)(?:/[^\s/]+)+/?")


def shorten_paths(config: RuntimeConfig, text: str) -> str:
    """Collapse long absolute filesystem paths in a title to their last segment."""

    def basename(match: re.Match[str]) -> str:
        path = match.group(0)
        # Only collapse a path long enough to be the problem this solves. Across
        # the transcripts sampled the median slash-run is 11 characters and the
        # 90th percentile is 140: the short ones are mostly not paths at all, and
        # collapsing them corrupts real content. `^/api/v1/users$` became
        # `^users$` before this.
        if len(path) < config.prompt_path_collapse_min_length:
            return path
        return path.rstrip("/").rpartition("/")[2] or path

    return _PROMPT_PATH_RE.sub(basename, text)


def clip(text: str, limit: int) -> str:
    """Trim to ``limit`` on a word boundary where one is close enough.

    Cutting mid-word reads as damage rather than as truncation: "tell all
    subagents and tea" looks like a bug. Falling back to a hard cut keeps the
    bound absolute for a single long token such as a URL.
    """
    if len(text) <= limit:
        return text
    head = text[:limit].rstrip()
    space = head.rfind(" ")
    # Only honour a boundary in the last third, so one long token cannot
    # shrink the title to a couple of words.
    kept = head[:space] if space > limit * 2 // 3 else head
    # A hard cut can land on punctuation, and ".…" reads as a typo.
    kept = kept.rstrip(" .,;:-_/(")
    # It can also land inside a decomposed grapheme, leaving accent marks whose
    # base character was cut away to combine with the ellipsis instead.
    while kept and unicodedata.combining(kept[-1]):
        kept = kept[:-1]
    return kept + "…"


def prompt_title(config: RuntimeConfig, text: str, limit: int | None = 80) -> str | None:
    """A readable one-line title from a raw user prompt, or None.

    Slash commands keep their name and any arguments, so `/plugin` reads as
    `/plugin` rather than as the markup it arrived in. Everything else has its
    wrapper tags removed and falls back to the first line with real content in
    it, which is what makes a `<teammate-message>` show the instruction instead
    of the envelope. ``None`` leaves the rendered words whole for a direction;
    ordinary titles retain their character bound.
    """
    # Capture the original framing first: a cued value next to a closing
    # wrapper can consume that wrapper when the entire record is redacted.
    name = _COMMAND_NAME_RE.search(text)
    if name and name.group(1):
        args = _COMMAND_ARGS_RE.search(text)
        command = records.redact_secrets(name.group(1)).strip()
        argument = (
            _PROMPT_TAG_RE.sub(" ", records.redact_secrets(args.group(1))).strip() if args else ""
        )
        joined = f"{command} {argument}".strip() if argument else command
        rendered = " ".join(shorten_paths(config, joined).split())
        return (clip(rendered, limit) if limit is not None else rendered) or None
    text = records.redact_secrets(text)
    for line in _PROMPT_TAG_RE.sub("", text).split("\n"):
        collapsed = " ".join(shorten_paths(config, line).split())
        if collapsed:
            return clip(collapsed, limit) if limit is not None else collapsed
    return None


# Which tag a Claude Code slash-command record opens with says who ran the
# command. Measured 2026-10-01 over the local store's main-thread, non-meta user
# records carrying `<command-name>`: all 1,477 that open with `<command-message>`
# are followed by an `isMeta` record holding the command's expanded prompt (a
# skill, or a built-in such as `/review` that asks the model for work), and all
# 945 that open with `<command-name>` are followed by `<local-command-stdout>`,
# `-stderr` or a system record, 903 of them after a `<local-command-caveat>` (a
# local command the harness ran itself: `/clear`, `/login`, `/plugin`, `/compact`
# and 15 more). No command name falls in both. The cross-record signals agree
# with the tag order, but a per-record reader cannot see them, so the order is
# the signal and they are the evidence for it.
_LOCAL_COMMAND_RE = re.compile(r"^\s*<command-name>")
_PROMPT_COMMAND_RE = re.compile(r"^\s*<command-message>")


def redact_command_framing(text: str) -> str:
    """Mask raw command fields before extraction, preserving their actual delimiters.

    A cue's value must end at the captured native field, not at its closing tag.
    Ordinary strings use the usual scrub. Missing closing tags remain missing;
    malformed overlapping fields fall back to the usual whole-record scrub.
    """
    if not (_LOCAL_COMMAND_RE.match(text) or _PROMPT_COMMAND_RE.match(text)):
        return records.redact_secrets(text)
    # This scrub runs before extraction's cap, so boundary discovery must be
    # linear even when a large malformed field ends in whitespace without a tag.
    spans = []
    for field in ("message", "name", "args"):
        opening = f"<command-{field}>"
        start = text.find(opening)
        if start < 0:
            continue
        start += len(opening)
        end = text.find(f"</command-{field}>", start)
        if end >= 0:
            spans.append((start, end))
    spans.sort()
    if any(left[1] > right[0] for left, right in itertools.pairwise(spans)):
        return records.redact_secrets(text)
    pieces: list[str] = []
    position = 0
    for start, end in spans:
        pieces.extend(
            (records.redact_secrets(text[position:start]), records.redact_secrets(text[start:end]))
        )
        position = end
    pieces.append(records.redact_secrets(text[position:]))
    return "".join(pieces)


def harness_control_prompt(config: RuntimeConfig, text: str) -> bool:
    """Whether a raw user prompt drives the harness rather than the work.

    The one rule the observed record (`command_direction`), the goal slot
    (`observer._user_directives`) and the instruction line (`states_work`) read,
    so the three cannot disagree about a command again. A local command is a
    control by the tag it opens with, arguments or none: `/compact keep notes`
    rendered past `records.harness_control`'s bare-token match and was published
    as both a goal and the work asked for. A prompt command is a control only by
    name on that list (`/insights`). Anything else, a Codex `/login` typed as
    plain text included, is asked of the list on the line `prompt_title` renders.
    """
    if _LOCAL_COMMAND_RE.match(text):
        return True
    if _PROMPT_COMMAND_RE.match(text):
        name = _COMMAND_NAME_RE.search(text)
        return name is None or records.harness_control(name.group(1))
    return records.harness_control(prompt_title(config, text, records.INSTRUCTION_CAP_CHARS))


def command_direction(config: RuntimeConfig, text: str) -> str | None:
    """A Claude Code slash-command record as the direction it gives, rendered whole.

    None when ``text`` is not a slash-command record, so the caller reads it as
    any other message. "" when `harness_control_prompt` calls it a control.
    Otherwise `prompt_title`'s own rendering, unclipped: the caller bounds it
    after redaction, as it bounds an ordinary message.
    """
    if not (_LOCAL_COMMAND_RE.match(text) or _PROMPT_COMMAND_RE.match(text)):
        return None
    if harness_control_prompt(config, text):
        return ""
    # Decide whether the original record was cut, before redaction can remove
    # a wrapper. Mask only the captured arguments before their tags become spaces.
    if command_cut(text):
        name = _COMMAND_NAME_RE.search(text)
        arrived = _PROMPT_TAG_RE.sub(
            " ", records.redact_secrets(text.split("<command-args>", 1)[1])
        )
        joined = " ".join(shorten_paths(config, arrived).split())
        command = records.redact_secrets(name.group(1)).strip() if name else ""
        return f"{command} {joined}".strip() + "\u2026"
    return prompt_title(config, text, limit=None) or ""


def command_cut(text: str) -> bool:
    """Whether a command's arguments were cut before their closing tag arrived.

    The record reader bounds a message at `records.EXTRACT_TEXT_CAP_CHARS`, and
    a command over it loses `</command-args>`: 2 of the 1,477 measured prompt
    commands. `prompt_title` then finds no arguments at all and renders the bare
    name as if it were the whole command, so the summary, the ledger and "Add it
    to my intent" all called a cut command whole (DRC-4764 review).
    """
    return "<command-args>" in text and "</command-args>" not in text


# ---------------------------------------------------------------------------
# The instruction line
#
# Two harnesses answer "what is this session working on" badly in opposite ways.
# Codex publishes nothing, because its prompt has moved record shape and sits a
# median 350 KB outside the bounded tail (DRC-4264); Claude publishes a title
# generated once from the opening prompt and never refreshed, which names
# finished work on three long sessions in four (DRC-4266). The answer to both is
# one labelled second line, built here so the two readers cannot disagree about
# what it may say.
#
# The rule, and every clause of it is load-bearing:
#
#   the newest GENUINE prompt states work  -> that, labelled "asked"
#   it is a bare continuation ("proceed")  -> the agent's own turn-start
#                                             statement of intent, labelled
#                                             "agent"; else the newest older
#                                             prompt that states work, labelled
#                                             "earlier", and only when no
#                                             compaction boundary intervenes
#   none of those                          -> NOTHING
#
# Nothing, rather than a best guess, because the page's fallback is a `||` chain:
# a wrong value there does not merely mislead, it permanently masks the project
# name that would otherwise show. A confident wrong line is worse than a blank.
#
# The label is not decoration either. It is what makes a second-hand line
# survivable: "agent" says an agent said this about itself, "earlier" says this
# is not the newest thing asked. Without one, the same text is a claim the
# runtime cannot support, which is why `records.instruction_line` refuses to
# publish an unlabelled reading.


def states_work(config: RuntimeConfig, text: str) -> bool:
    """Does this prompt, AS THE PAGE WILL RENDER IT, name work?

    Rendered first and counted second, never the other way round. A slash
    command arrives as 60 characters of markup that `prompt_title` reads back out
    as `/burndown DRC-4266 and the board`; counting words on the raw record calls
    that a bare continuation and buries the one thing the operator actually
    asked for.

    The RENDERING decides the shape; the BODY decides the word count. Those are
    two different questions and reading both off `prompt_title` conflated them,
    because that function returns line 1 only. Counting there called 97 of 2,066
    local newest prompts bare when the operator had written an instruction: a
    five-word opener over a five-line body ("a backend python test is failing:"),
    and one-line prompts whose first 140 characters are mostly a pasted URL, which
    `shorten_paths` leaves whole so it counts as a single word. Every one of the
    97 moves the same way — a real newest instruction published instead of an
    older one quoted in its place — and none moves the other.
    """
    rendered = prompt_title(config, text, records.INSTRUCTION_CAP_CHARS)
    if not rendered:
        return False
    # A harness control is not work, however it renders. `/clear` and `/login`
    # drive the session rather than describe it, and published in the labelled
    # slot they are indistinguishable from an instruction: 202 of 1,906 lines on
    # the local Claude corpus. The same predicate the observer's goal slot uses,
    # deliberately, because two primitives disagreeing about whether `/clear` is
    # an objective is the class of bug this shares with DRC-4265. Read off the
    # raw prompt, since only that says a command was a local one (DRC-4764).
    if harness_control_prompt(config, text):
        return False
    # A slash command names work by construction, however short. `/release` is
    # two words rendered and a whole instruction meant, and the word count is the
    # wrong instrument for the one prompt shape that is already explicit. A bare
    # SKILL invocation is the operator's intent and stays here — only the
    # measured control names above are refused.
    if rendered.startswith("/"):
        return True
    # `text`, not `rendered`: the count belongs on the whole prompt.
    # `bare_continuation` strips the wrapper tags itself, so the markup a
    # rendering would have removed is not counted either way.
    return not records.bare_continuation(text)


def instruction_from(
    config: RuntimeConfig,
    prompt: tuple[str, float] | None,
    preamble: tuple[str, float] | None,
    older: tuple[str, float] | None,
    *,
    title_is_prompt: bool = False,
) -> dict[str, Any] | None:
    """Pick line 2 from the three candidates a reader produced.

    ``title_is_prompt`` is what separates the two harnesses. Codex's line 1 IS
    the newest prompt, so repeating it underneath says nothing and costs a row
    two lines; Claude's line 1 is a title generated from the opening prompt, so
    the newest prompt underneath it is the whole point. The flag is the caller's
    to set because only the caller knows what its own line 1 will hold.

    Deleting the flag and leaning on the frontend's own echo test was measured
    and rejected: it emits 213 further "asked" lines across the 458 local
    rollouts and `nextInstructionEchoes` suppresses all 213, including the 151
    whose line 1 was clipped at 80 characters — that function's ellipsis clause
    is written for exactly that case. Surfacing the withheld characters needs the
    frontend rule to change, not this one, and until it does the flag is the
    cheaper half of one policy rather than a duplicate of it.
    """
    if prompt is None:
        return None
    cap = records.INSTRUCTION_CAP_CHARS
    text, at = prompt
    if states_work(config, text):
        if title_is_prompt:
            return None
        return records.instruction_line("asked", prompt_title(config, text, cap), at)
    for label, candidate in (("agent", preamble), ("earlier", older)):
        if candidate is not None:
            title = prompt_title(config, candidate[0], cap)
            return records.instruction_line(label, title, candidate[1])
    return None


# Byte prefilters, checked before any JSON parse. The reverse reader's own
# `contains` argument is a per-CHUNK filter and cannot express this set: the
# scan needs five unrelated record shapes, and the one substring common to them
# is short enough to match most of the file. So the walk takes no chunk filter
# and pays a `bytes.__contains__` per line instead, which is C-speed and skips
# the parse for better than nine records in ten.
_CODEX_SCAN_MARKERS: Final = (
    b'"user',  # `"user_message"`, and `"role":"user"`
    b"UserMessage",  # CLI 0.149's item_completed user shape
    b"agent_message",  # the pre-0.149 preamble
    b"AgentMessage",  # the 0.149 preamble
    b"task_started",  # the turn floor
    b"ompact",  # `compacted`, `context_compacted`, `ContextCompaction`
)


def _codex_scan_record(record: dict[str, Any]) -> tuple[str, str, float]:
    """Classify one Codex rollout record for the instruction scan.

    BOTH shapes of each thing are read, and that is not belt-and-braces. The
    turn-start preamble moved at CLI 0.149: verified across all 458 local
    rollouts, `event_msg`/`agent_message` with `phase == "commentary"` covers 294
    of the 305 release builds on 0.142.5-0.146.1 (96.4%) and none of the 89 on
    0.149.x, while
    `event_msg`/`item_completed` with an `AgentMessage` item reaches 87 of those
    89 and none of the older ones. A single-shape reader finds nothing on the
    build the operator is actually running.

    The narrowing below costs some of that reach and is kept anyway: requiring
    `phase == "commentary"` on the item takes it from 87 files to 79, because an
    unphased `AgentMessage` is the final answer rather than a statement of
    intent, and publishing one under an "agent" label would quote finished work
    as current.

    Both denominators above count RELEASE builds, and the distinction is load
    bearing rather than pedantic: fold the 0.145.0-alpha prereleases back in and
    the older figure falls to 296 of 357 (82.9%), because `phase == "commentary"`
    reached 1 of 51 alpha files. A prerelease is the one population where the
    shape was mid-move, so a single denominator spanning both would describe
    neither build a person runs.

    The user record split the same way — `event_msg`/`user_message` is gone by
    0.149.1 and `response_item`/message/user is in all but one rollout — and
    0.149 adds a third, `item_completed` with a `UserMessage` item. That third is
    read for the shape rather than for its reach: it appears on 26 files and is
    the ONLY path carrying the prompt on **0** of them, so it changes no reading
    today and exists so a build that drops the other two still has one.
    """
    payload = records.as_dict(record.get("payload"))
    at = records.parse_ts(record.get("timestamp") or "") or 0.0
    kind = payload.get("type")
    outer = record.get("type")
    found: tuple[str, Any] = ("", None)
    if outer == "response_item":
        if kind == "message" and payload.get("role") == "user":
            found = ("prompt", payload.get("content"))
    elif outer == "event_msg":
        if kind == "task_started":
            found = ("floor", None)
        elif kind == "user_message":
            found = ("prompt", payload.get("message"))
        elif kind in ("compacted", "context_compacted"):
            found = ("compaction", None)
        elif kind == "agent_message":
            # `phase` is absent on 6,562 of the older records and present as
            # "commentary" on 7,598. Absent is not commentary: the unphased shape
            # is the final answer under another name, and reading it as intent
            # would put a summary of finished work under an "agent" label.
            if payload.get("phase") == "commentary":
                found = ("commentary", payload.get("message"))
        elif kind == "item_completed":
            item = records.as_dict(payload.get("item"))
            item_type = item.get("type")
            # The text is at `item.content[].text`, a list of blocks, and never
            # at `item.text`. The block `type` is spelled "Text" on an
            # AgentMessage and "text" on a UserMessage; `extract_text` walks both.
            if item_type == "AgentMessage" and item.get("phase") == "commentary":
                found = ("commentary", item.get("content"))
            elif item_type == "UserMessage":
                found = ("prompt", item.get("content"))
            elif item_type == "ContextCompaction":
                found = ("compaction", None)
    return (found[0], records.extract_text(found[1]), at)


_CodexCandidates = tuple[
    "tuple[str, float] | None", "tuple[str, float] | None", "tuple[str, float] | None"
]


def _codex_walk(config: RuntimeConfig, path: str) -> _CodexCandidates:
    """Walk one rollout backward for its prompt, its preamble and an older prompt.

    The turn floor is explicit. `io.reverse_lines` carries no notion of a turn,
    so an unbounded walk crosses silently into the previous one whenever this
    turn has no commentary — and 26-43% of turns have none. A preamble survives
    only when the walk actually reached this turn's `task_started`; otherwise the
    ladder falls through to a labelled older prompt rather than presenting a
    previous turn's intent as this one's.

    `reached_floor` alone does not carry that guarantee, and reading it as though
    it did was the bug: it proves only that SOME turn opened behind the walk, not
    that it was this one. A turn that has not written `task_started` yet lets the
    walk run past the newest prompt, overwrite the preamble with the PREVIOUS
    turn's commentary, and then set the floor on that turn — publishing a
    statement of intent the operator's newest instruction has already superseded.

    So the preamble is bounded structurally instead: it is only ever assigned
    while no prompt has been seen, which makes it strictly newer than the newest
    genuine prompt and therefore this turn's by construction. Gating the RETURN
    on a "this turn wrote no floor" flag was tried first and is worse — the two
    differ only when a turn has commentary but no floor of its own, and there the
    flag suppresses a preamble that is genuinely current.
    """
    prompt: tuple[str, float] | None = None
    preamble: tuple[str, float] | None = None
    older: tuple[str, float] | None = None
    reached_floor = False
    compacted = False
    for raw in runtime_io.reverse_lines(config, path):
        if not raw.startswith(b"{") or not any(m in raw for m in _CODEX_SCAN_MARKERS):
            continue
        try:
            record = json.loads(raw)
        except ValueError:
            continue
        if not isinstance(record, dict):
            continue
        kind, text, at = _codex_scan_record(record)
        if kind == "commentary":
            # `prompt is None` is the load-bearing clause, not `reached_floor`:
            # commentary reached after the newest prompt belongs to an earlier
            # turn whatever the floor says.
            if not reached_floor and prompt is None and text.strip():
                preamble = (text, at)
        elif kind == "floor":
            reached_floor = True
        elif kind == "compaction":
            if prompt is None:
                continue
            # A compaction boundary older than the newest prompt puts everything
            # behind it in a context this turn no longer holds, so it may not be
            # quoted as what the session is doing. Codex crosses one in 28.2% of
            # mid-flight cases. Nothing further back can help, so stop.
            compacted = True
            if reached_floor:
                break
        elif kind == "prompt":
            body = text.strip()
            if not body or records.injected_prompt(body, "codex"):
                continue
            if prompt is None:
                prompt = (body, at)
                if states_work(config, body):
                    break
            elif not compacted and states_work(config, body):
                older = (body, at)
                break
    return (prompt, preamble if reached_floor else None, older)


def codex_instruction(config: RuntimeConfig, state: RuntimeState, path: str) -> dict[str, Any]:
    """Codex's session title, newest prompt and instruction line, or nothing.

    Read backward from EOF rather than out of the bounded tail, the mechanism
    `claude_data.session_title` already uses and for the same reason: of the 276
    local rollouts holding a genuine prompt, 171 (62.0%) have the newest one
    outside `tail_bytes`, because `reasoning` records carry encrypted blobs that
    flood the tail. Reverse against forward on the eight largest rollouts
    benchmarks 50 ms against 880 ms; the walk measures 2.5 ms median, 12 ms at
    the 95th percentile and 84 ms worst case across all 458 local rollouts.
    """
    try:
        stat = os.stat(path)
    except OSError:
        return {
            "title": None,
            "last_prompt": "",
            "instruction": None,
            "prompt_states_work": False,
            "prompt_at": None,
        }
    cache_key = (stat.st_mtime_ns, stat.st_size)
    with state.cache_lock:
        cached = state.codex_instruction_cache.get(path)
    if cached is not None and cached[:2] == cache_key:
        return cached[2]

    prompt, preamble, older = _codex_walk(config, path)

    # Rendered first and scrubbed second, never the other way round: `safe_text`
    # turns a newline into a space, so a prompt scrubbed first has no first line
    # left for `prompt_title` to take. The bound is the cap plus one because
    # `clip` appends its ellipsis after cutting, and `safe_text` only ever
    # shortens, so this cannot truncate what rendering already bounded.
    rendered = prompt_title(config, prompt[0], records.PROMPT_TITLE_CAP_CHARS) if prompt else None
    title = (
        records.safe_text(rendered, records.PROMPT_TITLE_CAP_CHARS + 1).strip() or None
        if rendered
        else None
    )
    result = {
        "title": title,
        # A title also exists for a bare continuation; the row must not adopt that as work.
        "prompt_states_work": bool(prompt and states_work(config, prompt[0])),
        "prompt_at": prompt[1] if prompt and prompt[1] > 0 else None,
        "last_prompt": records.safe_text(
            prompt[0] if prompt else "", records.LAST_PROMPT_CAP_CHARS
        ),
        "instruction": instruction_from(config, prompt, preamble, older, title_is_prompt=True),
    }
    with state.cache_lock:
        runtime_state.bounded_put(
            state.codex_instruction_cache,
            path,
            (*cache_key, result),
            limit=config.max_cache_entries,
        )
    return result


# ---------------------------------------------------------------------------
# Transcript analyzers (tail pass -> title, prompt, usage, activity)


def analyze_codex_transcript(config: RuntimeConfig, path: str) -> dict[str, Any]:
    """Codex rollout tail: token_count (usage), tool calls, rate limits.

    Turn spans come from scan_turns; cwd/subagents from meta; the prompt, the
    title and the instruction line from `codex_instruction`, which walks backward
    because a tail read misses the newest prompt on 62% of the rollouts that
    carry one. This function used to derive the title here too, at a second cap,
    off the one user record shape that CLI 0.149 no longer writes.
    """
    info: dict[str, Any] = {
        "last_output": None,
        "usage_events": [],
        "last_tool": None,
        "last_event_ts": 0,
        "rate_limits": None,  # newest in the tail: (epoch, the raw rate_limits dict)
    }
    for line in runtime_io.read_tail(config, path):
        if not line or line[0] != "{":
            continue
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue
        ep = records.parse_ts(d.get("timestamp") or "")
        if ep:
            info["last_event_ts"] = max(info["last_event_ts"], ep)
        t = d.get("type")
        p = records.as_dict(d.get("payload"))
        if t == "event_msg":
            pt = p.get("type")
            if pt == "token_count":
                out = records.as_dict(records.as_dict(p.get("info")).get("last_token_usage")).get(
                    "output_tokens"
                )
                if ep and out:
                    info["usage_events"].append((ep, out))
                # Quota snapshot, written by the CLI beside the token figures.
                limits = records.as_dict(p.get("rate_limits"))
                held = info["rate_limits"]
                if ep and limits and (held is None or ep >= held[0]):
                    info["rate_limits"] = (ep, limits)
        elif t == "response_item":
            if p.get("type") in ("function_call", "custom_tool_call"):
                info["last_tool"] = p.get("name")
            elif (
                p.get("type") == "message"
                and p.get("role") == "assistant"
                and p.get("phase") == "final_answer"
            ):
                chunks = [
                    str(block["text"])
                    for block in records.as_list(p.get("content"))
                    if isinstance(block, dict)
                    and block.get("type") == "output_text"
                    and isinstance(block.get("text"), str)
                ]
                raw = "\n".join(chunks)
                bounded = "\n".join(
                    records.safe_text(line, sessions.LAST_OUTPUT_CAP_CHARS)
                    for line in raw.split("\n")
                )[: sessions.LAST_OUTPUT_CAP_CHARS]
                info["last_output"] = bounded or None
    return info


def codex_analysis(config: RuntimeConfig, state: RuntimeState, path: str) -> dict[str, Any]:
    """`analyze_codex_transcript`, read through a per-file cache.

    A cached sibling rather than a `state` parameter on the analyzer itself:
    the analyzer is called as a `functools.partial` over its config in
    tests/test_transcripts.py and positionally in tests/test_codex.py, so
    widening its signature would be a contract change for a caching detail.

    Callers treat the result as read-only. It is now one dict shared by every
    reader in a cycle, so a consumer that mutated it would poison the entry
    rather than its own copy.
    """
    try:
        stat = os.stat(path)
    except OSError:
        # Gone between the glob and here. Let the analyzer return its own empty
        # shape rather than restating it, and cache nothing, so a rollout still
        # being written is read again next cycle instead of being remembered
        # as absent.
        return analyze_codex_transcript(config, path)
    cache_key = (stat.st_mtime_ns, stat.st_size)
    with state.cache_lock:
        cached = state.codex_analysis_cache.get(path)
    if cached is not None and cached[:2] == cache_key:
        return cached[2]
    info = analyze_codex_transcript(config, path)
    with state.cache_lock:
        runtime_state.bounded_put(
            state.codex_analysis_cache,
            path,
            (*cache_key, info),
            limit=config.max_cache_entries,
        )
    return info


def _published_title(title: Any) -> str | None:
    """One analyzer's newest prompt line, redacted and then bounded.

    Called once per transcript rather than once per user record, which is not a
    tidy-up: the loops below overwrite `title` on every prompt they pass, and
    redacting inside one of them put `redact_secrets` at the top of a whole
    collection's profile — 3,504 calls and 20% of the time on
    `bench_collect --simulate balanced-five`, where the assembled row needs one.
    """
    if not isinstance(title, str) or not title:
        return None
    return records.redact_clip(title, records.PROMPT_TITLE_CAP_CHARS) or None


def analyze_gemini_transcript(config: RuntimeConfig, path: str) -> dict[str, Any]:
    """Gemini chats/*.jsonl tail: type 'user' | 'gemini' records with
    per-message tokens; resumed-session $set snapshots are expanded."""
    info: dict[str, Any] = {
        "title": None,
        "last_prompt": None,
        "usage_events": [],
        "last_tool": None,
        "last_event_ts": 0,
    }
    seen = set()
    for line in runtime_io.read_tail(config, path):
        if not line or line[0] != "{":
            continue
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue
        for message in records.gemini_records(d):
            fingerprint = records.record_fingerprint(message)
            if fingerprint in seen:
                continue
            seen.add(fingerprint)
            ep = records.parse_ts(message.get("timestamp") or "")
            if ep:
                info["last_event_ts"] = max(info["last_event_ts"], ep)
            t = message.get("type")
            if t == "user":
                txt = records.extract_text(message.get("content")).strip()
                if txt:
                    info["last_prompt"] = txt
                    info["title"] = txt.split("\n")[0]
            elif t == "gemini":
                toks = message.get("tokens") or {}
                if ep and isinstance(toks, dict) and toks.get("output"):
                    info["usage_events"].append((ep, toks["output"]))
                for tc in records.as_list(message.get("toolCalls")):
                    if isinstance(tc, dict) and tc.get("name"):
                        info["last_tool"] = tc.get("name")
    info["title"] = _published_title(info["title"])
    return info


def _copilot_agent_key(d: dict[str, Any], data: dict[str, Any]) -> str:
    """One subagent's identity, the same across its started/completed/failed events.

    ``agentId`` is tried first because it is the only candidate that holds the
    same value on all three, measured on a live store. The others do not:
    ``subagent.completed`` carries a *different* top-level ``id`` from
    ``subagent.started``, so keying on ``id`` never matched and the caller's
    drop-oldest fallback did all the retiring. That is accidentally right for one
    child and wrong for two — it retires whichever pill happens to be first —
    and now that a pill carries a model, the wrong model goes with the wrong
    label. ``agentId`` is also the value the billing ledger's ``agent_id`` column
    holds, though nothing joins on it; see ``collectors/copilot.py``.

    Coerced to text because the result is a dict key and the record is untrusted:
    a JSON list under ``agentId`` is unhashable, and one would raise out of the
    analyzer and take every other reading of the session with it.
    """
    for candidate in (d.get("agentId"), data.get("id"), data.get("subagentId"), d.get("id")):
        if isinstance(candidate, (str, int, float)) and not isinstance(candidate, bool):
            text = str(candidate)
            if text:
                return text
    return ""


# The two `permissionRequest.kind` spellings recorded in
# `docs/captures/copilot/permission-events-1.0.78-macos.jsonl`. Nothing else is
# published: the value reaches a session card, and an allow-list of a closed
# vendor vocabulary is the only version of that which cannot put an unmeasured
# string on screen. A kind added upstream falls back to an unqualified wait,
# which still reports the gate.
_COPILOT_PERMISSION_KINDS: Final = frozenset({"shell", "url"})


def _copilot_request_key(data: dict[str, Any]) -> str:
    """One permission request's identity, or "" when the record does not carry one.

    ``data.requestId`` and nothing else: it is 1:1 across requested/completed in
    6 of 6 pairs in the capture, which is what lets an answer close the gate it
    actually answered rather than whichever one is open.

    Coerced to text for the same reason ``_copilot_agent_key`` is — the result is
    a dict key and the record is untrusted, so an unhashable value would raise out
    of the analyzer and take every other reading of the session with it. "" is
    returned for a request with no usable id, and the caller drops it: a gate that
    cannot be keyed cannot ever be closed, so recording one would leave a session
    red for the rest of its life.
    """
    value = data.get("requestId")
    if isinstance(value, (str, int, float)) and not isinstance(value, bool):
        return str(value)
    return ""


def _copilot_permission_kind(data: dict[str, Any]) -> str | None:
    """What kind of thing is being asked about, or None when it is not a known one.

    ``permissionRequest.kind`` is read and branched on before anything else under
    it, because the key set is kind-dependent rather than a union: ``kind="url"``
    carries ``{intention, kind, toolCallId, url}`` and none of the shell keys. An
    adapter written from a flattened key list reads fields that do not exist.

    Nothing else under ``permissionRequest`` is read at all. ``fullCommandText``,
    ``commands``, ``commandSegments``, ``possiblePaths``, ``possibleUrls`` and
    ``intention`` are the command line and a model's prose, which is the class
    ``docs/captures/README.md`` excludes and which has no business on a card.
    """
    request = records.as_dict(data.get("permissionRequest"))
    kind = request.get("kind")
    return kind if kind in _COPILOT_PERMISSION_KINDS else None


def analyze_copilot_events(config: RuntimeConfig, path: str) -> dict[str, Any]:
    """Copilot events.jsonl tail: typed events with data payloads. Field
    names inside data are de-facto (not a stable API) — extracted
    defensively."""
    info: dict[str, Any] = {
        "title": None,
        "last_prompt": None,
        "usage_events": [],
        "last_tool": None,
        "last_event_ts": 0,
        "cwd": None,
        # Started-but-not-finished subagents, one `{"name": str, "model": str |
        # None}` each. This is an internal pre-publication shape: the collector
        # adds the always-present `started_at` key, which stays None because
        # Copilot exposes no child transcript here. `model` is the child's own
        # reading and None means the event did not report one — never a guess.
        #
        # The model is carried raw and bounded by the collector, which caps it to
        # the width `sessions` declares for every model on the payload. That
        # width cannot be read from here: this module may not import `sessions`
        # (`test_contracts` pins the runtime import graph), and a second literal
        # 40 beside the declared one is how two caps drift apart. The collector
        # already sanitises the session's own model through one function, so the
        # child goes through the same door rather than a copy of it.
        "pending_agents": {},
        # Permission requests with no answer behind them, `requestId ->
        # {"at": float, "kind": str | None}` in the order they were asked. A
        # non-empty map at the end of the tail is a prompt standing in front of a
        # person: the capture has `permission.requested` on disk in the first
        # frame the dialog is visible, and `permission.completed` arriving only
        # when they answer, 23-48 s later.
        #
        # `at` is the request's own timestamp and 0 when it would not parse; the
        # collector dates the wait from it. `kind` is the closed vocabulary above
        # and nothing else from the request is carried, so no command line and no
        # model's prose can reach a card through this map.
        #
        # Bounded by the tail read, like every other accumulator here. Truncation
        # can only lose a request, never invent one, because the file is append
        # ordered and an answer never precedes its own question.
        #
        # Two things empty it: the answer, and a later `user.message`. The second
        # is the liveness bound — see the branch that does it.
        "pending_permissions": {},
    }
    for line in runtime_io.read_tail(config, path):
        if not line or line[0] != "{":
            continue
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue
        ep = records.parse_ts(d.get("timestamp") or "")
        if ep:
            info["last_event_ts"] = max(info["last_event_ts"], ep)
        t = d.get("type")
        data = records.as_dict(d.get("data"))
        if t == "session.start":
            ctx = records.as_dict(data.get("context"))
            info["cwd"] = ctx.get("cwd") or data.get("cwd") or info["cwd"]
        elif t == "user.message":
            # A prompt the person typed retires every request standing in front
            # of it, and this is the only thing that retires one but the answer.
            # A request whose answer never reached disk — the terminal closed on
            # the dialog, the process killed — otherwise stands for the whole
            # activity window, and it outranks the busy test, so a session that
            # was resumed and is demonstrably working reads Needs input against
            # its own live activity.
            #
            # Keyed on `user.message` and not on "any record written after the
            # request", which is the wider rule the same evidence would allow:
            # the capture has the file quiescent for the whole 36, 44 and 48 s a
            # gate stood, so nothing at all follows a standing request there. But
            # those arms ran no subagent, and a child writing into the parent's
            # file while the parent's dialog stands would silence a real gate
            # under exactly the fan-out where a gate is most likely. A typed
            # prompt needs no such assumption: the dialog owns the input while it
            # is up, so a new user message means it is gone.
            info["pending_permissions"].clear()
            txt = records.extract_text(data).strip()
            if txt:
                info["last_prompt"] = txt
                info["title"] = txt.split("\n")[0]
        elif t == "tool.execution_start":
            name = data.get("toolName") or data.get("name") or data.get("tool")
            if name:
                info["last_tool"] = str(name)
        elif t == "permission.requested":
            request_key = _copilot_request_key(data)
            if request_key:
                info["pending_permissions"][request_key] = {
                    "at": ep,
                    "kind": _copilot_permission_kind(data),
                }
        elif t == "permission.completed":
            # Every `result.kind` closes it, and that is the measured part rather
            # than a simplification. The capture records four spellings —
            # `approved`, `cancelled`, `denied-interactively-by-user`, and
            # `denied-no-approval-rule-and-could-not-request-from-user` — and the
            # last is a headless auto-denial that opens and closes its pair in
            # 1 ms. Branching on the answer would either hold a denied session red
            # forever or flicker a card for every run nobody is watching; the
            # question is over either way, so the join is on `requestId` alone.
            info["pending_permissions"].pop(_copilot_request_key(data), None)
        elif t == "subagent.started":
            label = (
                data.get("name")
                or data.get("agentName")
                or data.get("agent")
                or data.get("agentType")
                or "subagent"
            )
            # The model comes off the same JSON object the label does, so the two
            # are paired by construction rather than by a join. That is the whole
            # reason this is the source: the ledger's `agent_id` is
            # `sidekick-<agentName>-<epoch ms>`, related to the published label by
            # string construction only, and recovering one from the other means
            # prefix-parsing an id — inference, which a measured value must never
            # be mixed with.
            raw = data.get("model")
            info["pending_agents"][_copilot_agent_key(d, data)] = {
                "name": records.safe_text(label, 70),
                "model": raw if isinstance(raw, str) and raw.strip() else None,
            }
        elif t in ("subagent.completed", "subagent.failed"):
            # `failed` retires the pill for the same reason `completed` does: the
            # child is not running. It was unhandled, so a failed subagent kept
            # its pill for the rest of the session — measured live, on a child
            # that failed with "No response generated" — and it would now keep a
            # model badge with it.
            key = _copilot_agent_key(d, data)
            if key in info["pending_agents"]:
                info["pending_agents"].pop(key)
            elif info["pending_agents"]:  # unmatched key scheme: drop oldest
                info["pending_agents"].pop(next(iter(info["pending_agents"])))
    info["title"] = _published_title(info["title"])
    return info


def analyze_droid_transcript(config: RuntimeConfig, path: str) -> dict[str, Any]:
    """Droid transcript tail: {type: "message", timestamp, message: {role,
    content: [Anthropic-style blocks]}}."""
    info: dict[str, Any] = {
        "title": None,
        "last_prompt": None,
        "usage_events": [],
        "last_tool": None,
        "last_event_ts": 0,
    }
    for line in runtime_io.read_tail(config, path):
        if not line or line[0] != "{":
            continue
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue
        ep = records.parse_ts(d.get("timestamp") or "")
        if ep:
            info["last_event_ts"] = max(info["last_event_ts"], ep)
        if d.get("type") != "message":
            continue
        msg = records.message_dict(d)
        content = msg.get("content")
        blocks = content if isinstance(content, list) else []
        if msg.get("role") == "user":
            if any(isinstance(c, dict) and c.get("type") == "tool_result" for c in blocks):
                continue
            txt = records.extract_text(content).strip()
            if txt:
                info["last_prompt"] = txt
                info["title"] = txt.split("\n")[0]
        elif msg.get("role") == "assistant":
            for c in blocks:
                if isinstance(c, dict) and c.get("type") == "tool_use":
                    info["last_tool"] = c.get("name")
    info["title"] = _published_title(info["title"])
    return info


# ---------------------------------------------------------------------------
# Codex plan (`update_plan`) -> the task list the operator already sees in the CLI

# Codex caps its own plan well below this, but the record is untrusted input: a
# malformed one must not put an unbounded list on the wire.
CODEX_PLAN_MAX_STEPS: Final = 64
CODEX_PLAN_STEP_CAP_CHARS: Final = 160

_CODEX_PLAN_STATUSES: Final = frozenset({"pending", "in_progress", "completed"})
_JS_IDENT: Final = re.compile(r"[A-Za-z_$][A-Za-z0-9_$]*")


def _js_to_json(src: str) -> str:
    """A JS object/array literal rewritten as JSON text.

    Needed because the newer Codex `exec` tool carries the plan as JavaScript
    source rather than as a JSON argument, and the model writes it the way it
    writes JavaScript: bare keys (`step:`), single quotes, trailing commas. The
    scan is string-aware rather than a set of regex substitutions — a step whose
    text contains `word:` or an apostrophe is ordinary prose, and a naive rewrite
    corrupts exactly those steps.
    """
    out: list[str] = []
    i, n = 0, len(src)
    while i < n:
        ch = src[i]
        if ch == '"':
            j = i + 1
            while j < n:
                if src[j] == "\\":
                    j += 2
                    continue
                if src[j] == '"':
                    break
                j += 1
            out.append(src[i : j + 1])
            i = j + 1
            continue
        if ch == "'":
            j = i + 1
            body: list[str] = []
            while j < n:
                if src[j] == "\\":
                    body.append(src[j : j + 2])
                    j += 2
                    continue
                if src[j] == "'":
                    break
                body.append(src[j])
                j += 1
            # `\"` and `\'` are both legal inside a single-quoted JS string and
            # neither survives into the JSON one; `json.dumps` re-escapes.
            out.append(json.dumps("".join(body).replace('\\"', '"').replace("\\'", "'")))
            i = j + 1
            continue
        if ch == ",":
            k = i + 1
            while k < n and src[k].isspace():
                k += 1
            if k < n and src[k] in "}]":
                i += 1
                continue
        match = _JS_IDENT.match(src, i)
        if match:
            k = match.end()
            while k < n and src[k].isspace():
                k += 1
            out.append(json.dumps(match.group(0)) if k < n and src[k] == ":" else match.group(0))
            i = match.end()
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _js_balanced(src: str, start: int, opener: str, closer: str) -> str | None:
    """The balanced bracket span opening at ``src[start]``, or nothing."""
    depth, i, n = 0, start, len(src)
    while i < n:
        ch = src[i]
        if ch in "\"'":
            quote = ch
            i += 1
            while i < n:
                if src[i] == "\\":
                    i += 2
                    continue
                if src[i] == quote:
                    break
                i += 1
        elif ch == opener:
            depth += 1
        elif ch == closer:
            depth -= 1
            if depth == 0:
                return src[start : i + 1]
        i += 1
    return None


def _codex_plan_steps(value: Any) -> list[dict[str, Any]] | None:
    """A parsed plan array, if it is one: a non-empty list of `{step: str, …}`."""
    if not isinstance(value, list) or not value:
        return None
    if not all(isinstance(s, dict) and isinstance(s.get("step"), str) for s in value):
        return None
    return value


def _codex_plan_from_script(src: str) -> list[dict[str, Any]] | None:
    """The plan a Codex `exec` script hands to `update_plan`.

    The array is looked for directly rather than through the call site, because
    the model writes the call three ways and only two of them keep the literal
    inside the parentheses: 6 of the 211 local `exec` records bind it first
    (`const plan = [...]; tools.update_plan({plan})`), and a reader anchored on
    `update_plan(` finds an object with no array in it and reports no plan at
    all. The last qualifying array wins — a script that revises its plan before
    sending sends the later one.
    """
    best: list[dict[str, Any]] | None = None
    i = 0
    while True:
        i = src.find("[", i)
        if i < 0:
            return best
        chunk = _js_balanced(src, i, "[", "]")
        if chunk is None:
            return best
        # The cheap substring test first: an exec script holds arrays that are
        # not plans, and each miss would otherwise pay for a whole rewrite.
        if "step" in chunk:
            try:
                parsed = json.loads(_js_to_json(chunk))
            except ValueError:
                parsed = None
            best = _codex_plan_steps(parsed) or best
        i += 1


def _codex_plan_record(record: dict[str, Any]) -> list[dict[str, Any]] | None:
    """The plan one rollout record carries, across both live Codex shapes.

    Both are read because both are live, not for symmetry: across 487 local
    rollouts the older `function_call`/`update_plan` shape accounts for 279 plan
    records and the newer `exec` shape for 211, and a given build writes one or
    the other. All 490 parse.
    """
    payload = records.as_dict(record.get("payload"))
    kind = payload.get("type")
    if kind == "function_call" and payload.get("name") == "update_plan":
        raw = payload.get("arguments")
        try:
            parsed = json.loads(raw) if isinstance(raw, str) else raw
        except ValueError:
            return None
        return _codex_plan_steps(records.as_dict(parsed).get("plan"))
    if kind == "custom_tool_call":
        src = payload.get("input")
        if isinstance(src, str) and "update_plan" in src:
            return _codex_plan_from_script(src)
    return None


def codex_plan(config: RuntimeConfig, state: RuntimeState, path: str) -> list[dict[str, Any]]:
    """The newest plan a Codex rollout carries, shaped like a task list.

    Backward from EOF, stopping at the first plan found, for the reason
    `codex_instruction` walks backward: `reasoning` records carry encrypted
    blobs that flood the tail, so the newest plan sits outside a bounded tail
    read whenever the session has done any work since writing one.

    No compaction gate, unlike the prompt walk. A compaction boundary means the
    model no longer holds what is behind it in context, which is what disowns an
    older prompt — but a plan is state the CLI keeps rendering across a
    compaction, and the operator is still looking at it. Reading past the
    boundary reports what is on their screen; stopping at it would blank the
    panel for exactly the long sessions this exists to make legible.
    """
    try:
        stat = os.stat(path)
    except OSError:
        return []
    cache_key = (stat.st_mtime_ns, stat.st_size)
    with state.cache_lock:
        cached = state.codex_plan_cache.get(path)
    if cached is not None and cached[:2] == cache_key:
        return cached[2]

    steps: list[dict[str, Any]] = []
    for raw in runtime_io.reverse_lines(config, path, contains=b"update_plan"):
        if not raw.startswith(b"{"):
            continue
        try:
            record = json.loads(raw)
        except ValueError:
            continue
        if not isinstance(record, dict):
            continue
        found = _codex_plan_record(record)
        if found:
            steps = found
            break

    tasks: list[dict[str, Any]] = []
    for index, step in enumerate(steps[:CODEX_PLAN_MAX_STEPS]):
        status = step.get("status")
        subject = records.safe_text(str(step.get("step") or ""), CODEX_PLAN_STEP_CAP_CHARS).strip()
        if not subject:
            continue
        tasks.append(
            {
                # Positional, because a Codex plan step carries no id of its own
                # and its text is not unique — a revised plan reuses wording. The
                # page keys rows on this, so it has to be stable within a read.
                "id": f"plan-{index}",
                "subject": subject,
                # Codex writes no gerund form. Empty rather than an echo of the
                # subject: both views already fall back to `subject` when this is
                # blank, and an echo would render a step title as though it were
                # measured phrasing for work in flight.
                "activeForm": "",
                "status": status if status in _CODEX_PLAN_STATUSES else "pending",
            }
        )
    with state.cache_lock:
        runtime_state.bounded_put(
            state.codex_plan_cache,
            path,
            (*cache_key, tasks),
            limit=config.max_cache_entries,
        )
    return tasks


def first_prompt(
    config: RuntimeConfig, state: RuntimeState, path: str, harness: str
) -> dict[str, Any]:
    """The first genuine user record, never a generated title or compacted summary.

    A bounded prefix scan fails absent if a huge initial record hides the first
    prompt; it must not call a later prompt first. The cache follows file identity
    as well as size/mtime, so replacing a transcript cannot preserve an old source.

    A first record that drives the harness (`/clear`, `/login`) is still the
    first prompt, and `first_prompt_control` says so, so the goal drafted from
    it (DRC-4766) offers nothing rather than the command. The read stops there
    either way: a later record is never called first.
    """
    empty: dict[str, Any] = {
        "first_prompt": "",
        "first_prompt_at": None,
        "first_prompt_control": False,
    }
    try:
        stat = os.stat(path)
    except OSError:
        return empty
    key = f"first-prompt:{harness}:{path}"
    stamp = (stat.st_ino, stat.st_mtime_ns, stat.st_size)
    with state.cache_lock:
        cached = state.metadata_cache.get(key)
    if cached is not None and cached.get("stamp") == stamp:
        return dict(cached["result"])
    result = empty
    try:
        with open(path, "rb") as source:
            remaining = 2 * 1024 * 1024
            while remaining > 0:
                raw = source.readline(remaining + 1)
                if not raw or len(raw) > remaining:
                    break
                remaining -= len(raw)
                try:
                    record = json.loads(raw)
                except ValueError:
                    continue
                if not isinstance(record, dict):
                    continue
                candidate = _first_prompt_record(record, harness)
                if candidate is None:
                    continue
                body, at = candidate
                rendered = prompt_title(config, body, records.INSTRUCTION_CAP_CHARS)
                result = {
                    "first_prompt": records.safe_text(rendered, records.INSTRUCTION_CAP_CHARS + 1),
                    "first_prompt_at": at if at > 0 else None,
                    # The raw body, as the shared rule requires: only its
                    # opening tag says a command was a local one (DRC-4764).
                    "first_prompt_control": harness_control_prompt(config, body),
                }
                break
    except OSError:
        return empty
    with state.cache_lock:
        runtime_state.bounded_put(
            state.metadata_cache,
            key,
            {"stamp": stamp, "result": result},
            limit=config.max_cache_entries,
        )
    return result


def _first_prompt_record(record: dict[str, Any], harness: str) -> tuple[str, float] | None:
    if harness == "codex":
        kind, body, at = _codex_scan_record(record)
        if kind != "prompt":
            return None
    elif harness == "claude":
        if record.get("isCompactSummary") is True or record.get("isSidechain") is True:
            return None
        signal = records._turn_signal(record, "claude")  # noqa: SLF001
        if not signal or signal[0] != "prompt":
            return None
        body = records.extract_text(records.message_dict(record).get("content"))
        at = records.parse_ts(record.get("timestamp") or "") or 0.0
    else:
        return None
    return (body, at) if body.strip() and not records.injected_prompt(body, harness) else None


# ---------------------------------------------------------------------------
# Antigravity directions (DRC-4689)

# `transcript.jsonl` rather than `transcript_full.jsonl`: the two held the same
# records on 62 of 62 local conversations, and the short one bounds each field,
# so a bounded tail read reaches further back. It truncates `content` on 5 of
# 115 directions, which it marks in `truncated_fields` (1.2.11 capture,
# docs/captures/antigravity/transcript-shapes-1.2.11-macos.jsonl).
ANTIGRAVITY_TRANSCRIPT: Final = (".system_generated", "logs", "transcript.jsonl")
# The whole-field copy beside it, read only for a `/goal`: the short file keeps the first and
# last 2,048 characters of a long input around `<truncated N bytes>` (agy 1.4.7,
# docs/captures/antigravity/goal-1.4.7-macos.jsonl), so a long condition would lose its middle.
ANTIGRAVITY_FULL_TRANSCRIPT: Final = (".system_generated", "logs", "transcript_full.jsonl")


def antigravity_transcript(root: str, sid: str, *, full: bool = False) -> str | None:
    """The conversation's brain transcript under the Antigravity root, a regular
    file reached through no link below `brain/`, or None.

    Every component from `brain/<sid>` down is checked, not just the file: a
    linked conversation or `logs/` directory would otherwise hand the reader a
    file anywhere on disk. A link above `brain/` is the person's own layout and
    is followed. Readers open the path with `follow_links=False`, which closes
    the swap of the file itself after this check; a swap of a parent directory
    in between is not closable without an `openat` walk, and is the same class
    `spacedock.read_frontmatter` records.
    """
    if not sid or sid.startswith(".") or "/" in sid or os.sep in sid:
        return None
    brain = os.path.join(root, "brain")
    parts = ANTIGRAVITY_FULL_TRANSCRIPT if full else ANTIGRAVITY_TRANSCRIPT
    path = os.path.join(brain, sid, *parts)
    try:
        unlinked = os.path.realpath(path) == os.path.join(os.path.realpath(brain), sid, *parts)
        is_file = unlinked and os.path.isfile(path)
    except (OSError, ValueError):
        return None
    return path if is_file else None


class AntigravityDirection(NamedTuple):
    at: float
    record_id: str
    text: str
    truncated: bool


def antigravity_direction(record: Any) -> AntigravityDirection | None:
    """One direction the person typed, or None for every other record.

    Only `USER_INPUT` from `USER_EXPLICIT`, with string content and a time that
    parses. Nothing else in the file is read: not the planner's responses or
    thinking, not tool calls, not command records or their exit codes. Reading
    work from this harness is out of scope (owner, 2026-09-27), so its
    harness-limit sentence stays true.
    """
    if not isinstance(record, dict):
        return None
    if record.get("type") != "USER_INPUT" or record.get("source") != "USER_EXPLICIT":
        return None
    text, stamp = record.get("content"), record.get("created_at")
    at = records.iso_epoch(stamp) if isinstance(stamp, str) else None
    if not isinstance(text, str) or not text.strip() or at is None:
        return None
    step = record.get("step_index")
    truncated = record.get("truncated_fields")
    return AntigravityDirection(
        at,
        f"step-{step}" if isinstance(step, int) and not isinstance(step, bool) else "",
        text,
        isinstance(truncated, list) and "content" in truncated,
    )


def antigravity_newest_direction(config: RuntimeConfig, path: str) -> str:
    """The newest direction in the bounded tail, or ""."""
    newest: tuple[float, str] | None = None
    for raw in runtime_io.read_tail(config, path, follow_links=False):
        if not raw.lstrip().startswith("{"):
            continue
        try:
            direction = antigravity_direction(json.loads(raw))
        except (ValueError, RecursionError):
            continue
        if direction is not None and (newest is None or direction.at >= newest[0]):
            newest = (direction.at, direction.text)
    return newest[1] if newest else ""
