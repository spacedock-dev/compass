"""Whether a drift press from inside a session follows the person's own typed command.

The `compass` skill's `drift` and `drift again` actions run `--drift` inside the Claude Code session
they read, and Claude Code runs them without a permission prompt. So an agent that starts the skill
on its own could spend a reading, and that reading would feed the session's later readings. The
client marks a press from inside a session with `typed_action`; the reading route then reads the
session's transcript tail at press time, not the collection, and admits the press only when the
latest main-thread prompt is the person's typed `/compass:compass` command for that action. Each
typed record pays for one press that starts, remembered beside the reading permission store, so a
retry, a loop or a second call cannot spend again on it; a press refused before it starts gives
the record back. The owner ruled it on 2026-11-06, after the pre-approval;
docs/design-reading-a-session.md records the ruling.

This is not a hard boundary: a process that can write the transcript can forge a record.
"""

from __future__ import annotations

import json
import os
import re
from typing import TYPE_CHECKING, Any, Final

from . import io as runtime_io
from . import records

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from .config import RuntimeConfig

# What a press from inside a session may name, and the typed actions each accepts. A plain `drift`
# presses only when no reading is stored, so the person who typed `drift again` asked for at least
# that much.
ACCEPTS: Final[dict[str, tuple[str, ...]]] = {
    "monitor on": ("monitor on",),
    "drift": ("drift", "drift again"),
    "drift again": ("drift again",),
}
# The closed reasons a refused press answers with: no typed command backs it, or Compass could not
# read what would say so. Neither spends.
REQUIRED: Final = "typed-command-required"
UNCONFIRMED: Final = "typed-command-unconfirmed"
# The typed command is the turn's first record and the press comes from its first tool call, so
# the tail between them is the skill body and one call. The skill body measured 145,219 bytes on
# this release; four MiB leaves room for a long session's last records without reading it whole.
TAIL_BYTES: Final = 4 * 1024 * 1024
STORE_NAME: Final = "compass-typed-presses.json"
# A typed record is consumed once; the newest this many are kept, which is more presses than the
# 100-attempt rolling cap allows in a day.
KEEP: Final = 512
LOCK_WAIT_SEC: Final = 2.0

_ARGS_RE = re.compile(r"<command-args>\s*(.*?)\s*</command-args>", re.DOTALL)
_UUID_RE = re.compile(r"[!-~]{1,200}")


def tail_lines(path: str, limit: int = TAIL_BYTES) -> list[bytes] | None:
    """The complete lines in the last `limit` bytes of `path`, or None when it cannot be read.

    A first line cut by the window and a last line still being written are left out.
    """
    try:
        with open(path, "rb") as source:
            size = os.fstat(source.fileno()).st_size
            start = max(0, size - limit)
            source.seek(start)
            data = source.read()
    except OSError:
        return None
    lines = data.split(b"\n")
    lines.pop()  # after the last newline: empty, or a line still being written
    if start:
        lines = lines[1:]
    return lines


def latest_prompt(lines: Sequence[bytes]) -> dict[str, Any] | None:
    """The newest main-thread prompt record: never `isMeta`, a tool result or a sidechain record.

    A model-started skill is a Skill tool call and its result, never a prompt record
    (docs/captures/claude/skill-action-shapes-2.1.318-macos.jsonl).
    """
    for raw in reversed(lines):
        if b'"user"' not in raw:
            continue
        try:
            record = json.loads(raw)
        except (ValueError, RecursionError):
            continue
        if (
            isinstance(record, dict)
            and "toolUseResult" not in record
            and records.claude_prompt_record(record)
        ):
            return record
    return None


def typed_action(record: dict[str, Any] | None) -> str | None:
    """The action a typed `/compass:compass` record names, spaces folded; None for any other."""
    if record is None or not records.compass_command_record(record):
        return None
    content = records.message_dict(record).get("content")
    found = _ARGS_RE.search(content) if isinstance(content, str) else None
    return " ".join(found.group(1).split()) if found else ""


def decide(lines: Sequence[bytes], action: str) -> tuple[str, str]:
    """`(reason, uuid)`: `""` and the typed record's uuid when it backs `action`, else a reason."""
    record = latest_prompt(lines)
    typed = typed_action(record)
    uuid = record.get("uuid") if record is not None else None
    if typed not in ACCEPTS.get(action, ()) or not isinstance(uuid, str):
        return REQUIRED, ""
    if not _UUID_RE.fullmatch(uuid):
        return REQUIRED, ""
    return "", uuid


def store_path(config: RuntimeConfig) -> Path:
    return config.state_dir / STORE_NAME


def _consumed(path: Path) -> list[str] | None:
    """The consumed uuids, oldest first; empty when none was ever written, None when unreadable."""
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return []
    except OSError:
        return None
    try:
        data = json.loads(raw)
    except (ValueError, RecursionError):
        return None
    held = data.get("consumed") if isinstance(data, dict) else None
    if not isinstance(held, list) or not all(isinstance(item, str) for item in held):
        return None
    return held


def _write(path: Path, consumed: list[str]) -> bool:
    try:
        runtime_io.atomic_write_owner_only(str(path), json.dumps({"consumed": consumed[-KEEP:]}))
    except OSError:
        return False
    return True


def consume(config: RuntimeConfig, uuid: str) -> str:
    """Hold `uuid` for the press it admits: `""`, or the reason it cannot.

    Under the file lock, so two presses on one typed record, from two tabs or two dashboards, admit
    one. Only a lock actually held counts: an unsupported lock is refused like a busy one, because
    unlocked, every concurrent press could read the store before any wrote it. A store that cannot
    be read or written refuses rather than admit twice. The caller gives it back with `release`
    when the press does not start.
    """
    path = store_path(config)
    try:
        runtime_io.ensure_owner_dir(str(path.parent))
    except OSError:
        return UNCONFIRMED
    with runtime_io.held_file_lock(f"{path}.lock", wait=LOCK_WAIT_SEC) as held:
        if held != runtime_io.LOCK_HELD:
            return UNCONFIRMED
        consumed = _consumed(path)
        if consumed is None:
            return UNCONFIRMED
        if uuid in consumed:
            return REQUIRED
        if not _write(path, [*consumed, uuid]):
            return UNCONFIRMED
    return ""


def release(config: RuntimeConfig, uuid: str) -> None:
    """Give `uuid` back after its press was refused or failed before a reading started.

    Best effort: a store that cannot be locked, read or written keeps the id, which costs the
    person a retype and never a second press.
    """
    path = store_path(config)
    with runtime_io.held_file_lock(f"{path}.lock", wait=LOCK_WAIT_SEC) as held:
        if held != runtime_io.LOCK_HELD:
            return
        consumed = _consumed(path)
        if consumed and uuid in consumed:
            _write(path, [item for item in consumed if item != uuid])


def admit(config: RuntimeConfig, transcript: str | None, action: str) -> tuple[str, str]:
    """`("", uuid)` when the typed record `uuid` backs this press and is now held for it.

    Otherwise `(reason, "")`. The caller releases the uuid when the press does not start.
    """
    lines = tail_lines(transcript) if transcript else None
    if lines is None:
        return UNCONFIRMED, ""
    reason, uuid = decide(lines, action)
    if not reason:
        reason = consume(config, uuid)
    return (reason, "") if reason else ("", uuid)
