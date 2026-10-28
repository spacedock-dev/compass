"""What the reader set on the Settings screen, kept beside the other stores.

Four limits on how much of a session an Analyze press reads. All were constants until 2026-10-28,
when a measured press on an 18-hour Claude Code session read 103 of its 187 messages, every one
before the newest six and a half hours dropped by the 100-event project cap, and sent a
16,384-byte prompt in which each of the agent's messages was cut to one line. The reading came back
"Can't tell". The scan itself reached the window's start in a quarter of a second; the caps were the
loss. Raised, the same press kept all 187 messages.

- `analyze_prompt_bytes` is the most an Analyze prompt may hold. Every share of it (the reader's
  words, the agent's, the turn-closing messages) is a fraction of this number, so raising it raises
  them all.
- `analyze_record_events` is how many of the focused session's messages and checks a press keeps
  once it has read back to the window's start. The project page keeps its own 100; only a press
  reads this.
- `analyze_listed_checks` is how many of the session's checks and written files a press lists. The
  scan already reads the whole transcript and counts them all; the page lists the newest 12, which
  left 52 passes on the same session counted and unsent.
- `analyze_scan_megabytes` is how much of the session's transcript and its subagents' a press scans
  for checks. The board scans 8 MiB, which on the same session read half the parent and none of
  its 282 subagents, where every builder and reviewer ran its tests; 512 MiB read all of them, in
  about half a minute. The scan holds what it read until the press ends, about five times the
  bytes it scanned (review, 2026-10-28), so the ceiling is 1 GiB rather than more.

A value missing, unreadable or out of range reads as its default, so a damaged file costs the
reader their settings and never their reading. Writes are refused, not clamped, when out of range:
the screen shows the bounds, and a number silently changed would not be the one they typed.
"""

from __future__ import annotations

import json
import os
import stat
from typing import TYPE_CHECKING, Any, Final, NamedTuple

from . import io as runtime_io

if TYPE_CHECKING:
    from collections.abc import Mapping

    from .config import RuntimeConfig

STORE_FILENAME: Final = "compass-settings.json"
# A store of a few integers. Anything larger is not this file, and is not parsed.
_MAX_STORE_BYTES: Final = 4096
_LOCK_WAIT_SEC: Final = 2.0


class Limit(NamedTuple):
    key: str
    default: int
    minimum: int
    maximum: int


# The old constants are the floors, so no setting can make a press read less than it used to.
# The prompt's default is its ceiling, by the owner's choice (2026-10-28). The ceiling is 512 KiB,
# about 130,000 tokens, which leaves a 200,000-token context room for the instructions and the
# answer; a larger prompt would fail the press on such a model rather than read more. The record's
# ceiling is well past the 187 messages and 385 entries the 18-hour session measured above held.
LIMITS: Final = (
    Limit("analyze_prompt_bytes", default=524_288, minimum=16_384, maximum=524_288),
    Limit("analyze_record_events", default=2_000, minimum=100, maximum=20_000),
    Limit("analyze_listed_checks", default=1_000, minimum=12, maximum=5_000),
    Limit("analyze_scan_megabytes", default=512, minimum=8, maximum=1_024),
)


class Settings(NamedTuple):
    analyze_prompt_bytes: int
    analyze_record_events: int
    analyze_listed_checks: int
    analyze_scan_megabytes: int


DEFAULTS: Final = Settings(**{limit.key: limit.default for limit in LIMITS})


class InvalidSettingError(ValueError):
    """A write that named an unknown key or a value outside its bounds. Nothing was written."""

    def __init__(self, key: str) -> None:
        super().__init__(key)
        self.key = key


def store_path(config: RuntimeConfig) -> str:
    """Beside the annotation store and not per port: one reader's settings, whichever board."""
    return os.path.join(config.state_home, STORE_FILENAME)


def _valid(limit: Limit, value: Any) -> bool:
    return (
        isinstance(value, int)
        and not isinstance(value, bool)
        and limit.minimum <= value <= limit.maximum
    )


def _read_store(path: str) -> bytes:
    """The store's first bytes, from a regular file only: a link or a FIFO left at the path would
    otherwise be followed, or block every press that reads the settings."""
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    descriptor = os.open(path, flags)
    with os.fdopen(descriptor, "rb") as handle:
        if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
            raise OSError(path)
        return handle.read(_MAX_STORE_BYTES + 1)


def _stored(config: RuntimeConfig) -> dict[str, Any]:
    try:
        raw = _read_store(store_path(config))
    except OSError:
        return {}
    if len(raw) > _MAX_STORE_BYTES:
        return {}
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, RecursionError):
        return {}
    return data if isinstance(data, dict) else {}


def load(config: RuntimeConfig) -> Settings:
    """The settings in force: each stored value that is valid, else its default."""
    stored = _stored(config)
    return Settings(
        **{
            limit.key: stored[limit.key] if _valid(limit, stored.get(limit.key)) else limit.default
            for limit in LIMITS
        }
    )


def save(config: RuntimeConfig, changes: Mapping[str, Any]) -> Settings:
    """Apply `changes` (a subset of the keys) and return what is now in force.

    `None` for a key restores its default. Every key is checked before anything is written, so a
    write with one bad value changes nothing.
    """
    known = {limit.key: limit for limit in LIMITS}
    for key, value in changes.items():
        limit = known.get(key)
        if limit is None or (value is not None and not _valid(limit, value)):
            raise InvalidSettingError(str(key))
    path = store_path(config)
    os.makedirs(config.state_home, mode=0o700, exist_ok=True)
    with runtime_io.held_file_lock(f"{path}.lock", wait=_LOCK_WAIT_SEC) as held:
        # A filesystem that cannot lock still takes the write, as the annotation store does; one
        # whose lock another writer holds or that refuses it does not, so two saves never
        # interleave their read and write.
        if held not in (runtime_io.LOCK_HELD, runtime_io.LOCK_UNSUPPORTED):
            raise OSError(held)
        current = load(config)._asdict()
        for key, value in changes.items():
            current[key] = known[key].default if value is None else value
        kept = {key: value for key, value in current.items() if value != known[key].default}
        runtime_io.atomic_write_owner_only(path, json.dumps(kept, sort_keys=True) + "\n")
    return load(config)


def published(settings: Settings) -> dict[str, Any]:
    """The values in force and each one's default and bounds, as the Settings screen reads them."""
    return {
        "values": settings._asdict(),
        "limits": [limit._asdict() for limit in LIMITS],
    }
