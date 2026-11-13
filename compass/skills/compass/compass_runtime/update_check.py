"""Daily release lookups and the explicit internal-use marker.

The attempt precedes the request, including on failure:
[the daily-cap contract](docs/design-install-tracking.md#compasss-update-check)
"""

from __future__ import annotations

import http.client
import json
import math
import os
import re
import stat
import sys
import threading
import time
import urllib.parse
import urllib.request
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING, Any, Final

from . import config as runtime_config
from . import https_transport, settings
from . import io as runtime_io
from .reach import build_reach_opener

if TYPE_CHECKING:
    from collections.abc import Callable

    from .config import RuntimeConfig

RELEASE_URL: Final = "https://spacedock.md/latest-release/compass"
STORE_FILENAME: Final = "compass-update-check.json"
INTERNAL_FILENAME: Final = "compass-internal.json"
_ASCII_LOWER: Final = str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz")
_VERSION: Final = re.compile(
    r"^([0-9]+)\.([0-9]+)\.([0-9]+)(?:-([0-9A-Za-z.-]+))?(?:\+[0-9A-Za-z.-]+)?$"
)
_MAX_ANSWER_BYTES: Final = 1_048_576
_TIMEOUT_SEC: Final = 5.0
_TICK_SEC: Final = 5.0


def normalise_os(value: str) -> str:
    value = value.translate(_ASCII_LOWER)
    if value.startswith("freebsd"):
        return "freebsd"
    if value in {"darwin", "linux", "windows"}:
        return value
    if value == "win32" or re.fullmatch(r"(?:mingw.*|msys)_nt-.*", value):
        return "windows"
    return "unknown"


def normalise_arch(value: str) -> str:
    value = value.translate(_ASCII_LOWER)
    if value in {"amd64", "x86_64", "x64"}:
        return "amd64"
    return "arm64" if value in {"arm64", "aarch64"} else "unknown"


def _read(path: str) -> dict[str, Any] | None:
    try:
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        with os.fdopen(os.open(path, flags), "rb") as source:
            if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
                return None
            raw = source.read(4097)
        if len(raw) > 4096:
            return None
        value = json.loads(raw)
    except FileNotFoundError:
        return {}
    except (OSError, ValueError, RecursionError):
        return None
    return value if isinstance(value, dict) else None


def _saved_day(value: Any) -> str:
    try:
        return date.fromisoformat(value).isoformat() if isinstance(value, str) else ""
    except ValueError:
        return ""


def _attempt_state(path: str, *, initialise: bool = False) -> dict[str, Any]:
    stored = _read(path)
    if initialise and stored == {} and not os.path.lexists(path):
        return {}
    if stored is None or not _saved_day(stored.get("attempt_day")):
        raise ValueError("unreadable release lookup history")
    return stored


def internal(config: RuntimeConfig) -> bool:
    return (
        config.update_check_internal_env
        or (_read(os.path.join(config.state_home, INTERNAL_FILENAME)) or {}).get("internal") is True
    )


def save_internal(config: RuntimeConfig, enabled: bool) -> None:
    runtime_io.atomic_write_owner_only(
        os.path.join(config.state_home, INTERNAL_FILENAME), json.dumps({"internal": enabled}) + "\n"
    )


def request(config: RuntimeConfig) -> urllib.request.Request:
    if urllib.parse.urlsplit(RELEASE_URL).scheme != "https":
        raise ValueError("release lookup requires HTTPS")
    version = (config.release_version or "").removeprefix("v")
    if len(version) > 32 or not _VERSION.fullmatch(version):
        version = "unknown"
    tokens = [normalise_os(config.platform_name), normalise_arch(config.update_check_arch)]
    if config.update_check_ci:
        tokens.append("ci")
    if internal(config):
        tokens.append("internal")
    return urllib.request.Request(
        RELEASE_URL,
        headers={"User-Agent": "compass/" + version + " (" + "; ".join(tokens) + ")"},
        method="GET",
    )


def _version(value: Any) -> tuple[Any, ...] | None:
    if not isinstance(value, str) or len(value) > 32:
        return None
    matched = _VERSION.fullmatch(value.removeprefix("v"))
    if matched is None:
        return None
    major, minor, patch, pre = matched.groups()
    identifiers = tuple(
        (0, int(part)) if part.isascii() and part.isdigit() else (1, part)
        for part in (pre.split(".") if pre else [])
    )
    return int(major), int(minor), int(patch), pre is None, identifiers


# Its own slot rather than the quota fetch's: one lane's hung resolver cannot fail the other's.
_DNS_SLOT = threading.BoundedSemaphore(1)


def fetch_release(config: RuntimeConfig) -> str:
    req = request(config)
    # request() admits only HTTPS; the shared opener refuses every redirect and proxy.
    with https_transport.open_bounded(
        build_reach_opener(), req, timeout=_TIMEOUT_SEC, dns_slot=_DNS_SLOT
    ) as response:
        if response.status != 200:
            raise ValueError("release lookup did not answer successfully")
        raw = response.read(_MAX_ANSWER_BYTES + 1)
    if len(raw) > _MAX_ANSWER_BYTES:
        raise ValueError("release answer too large")
    answer = json.loads(raw)
    tag = answer.get("tag_name") if isinstance(answer, dict) else None
    if _version(tag) is None:
        raise ValueError("invalid release tag")
    return str(tag).removeprefix("v")


class UpdateChecker:
    def __init__(self, config: RuntimeConfig, *, clock: Callable[[], float] = time.time) -> None:
        self.config = config
        self.clock = clock
        self.last_day: str | None = None
        self.path = os.path.join(config.state_home, STORE_FILENAME)

    def tick(self) -> None:
        if not runtime_config.UPDATE_CHECK_DEFAULT_ENABLED or self.config.update_check_disabled:
            return
        try:
            now = self.clock()
            day = datetime.fromtimestamp(now, UTC).date().isoformat()
            if (self.last_day is not None and day <= self.last_day) or settings.no_update_check(
                self.config
            ):
                return
            os.makedirs(self.config.state_home, mode=0o700, exist_ok=True)
            with runtime_io.held_file_lock(self.path + ".lock", wait=0) as held:
                # No unsupported-lock fallback: failing closed preserves the one-home daily cap.
                if held != runtime_io.LOCK_HELD:
                    return
                # A server may have waited across midnight while another reserved the new day.
                day = datetime.fromtimestamp(self.clock(), UTC).date().isoformat()
                stored = _attempt_state(self.path, initialise=True)
                attempted = _saved_day(stored.get("attempt_day"))
                if attempted >= day:
                    self.last_day = attempted
                    return
                stored["attempt_day"] = day
                runtime_io.atomic_write_owner_only(self.path, json.dumps(stored) + "\n")
                self.last_day = day
            # A setting changed since the tick began can still stop the reserved attempt.
            if settings.no_update_check(self.config):
                return
            version = fetch_release(self.config)
            at = self.clock()
            with runtime_io.held_file_lock(self.path + ".lock", wait=2.0) as held:
                if held == runtime_io.LOCK_HELD:
                    stored = _attempt_state(self.path)
                    previous = stored.get("checked_at", 0)
                    if isinstance(previous, (int, float)) and previous <= at:
                        stored.update(version=version, checked_at=at)
                        runtime_io.atomic_write_owner_only(self.path, json.dumps(stored) + "\n")
        except (OSError, ValueError, OverflowError, RecursionError, http.client.HTTPException):
            # Offline is ordinary: no retry, diagnostic, or error state on the board.
            return


def start(config: RuntimeConfig, stop: threading.Event) -> None:
    if runtime_config.UPDATE_CHECK_DEFAULT_ENABLED and not config.update_check_disabled:
        threading.Thread(target=run, args=(config, stop), daemon=True).start()


def run(
    config: RuntimeConfig, stop: threading.Event, *, clock: Callable[[], float] = time.time
) -> None:
    check = UpdateChecker(config, clock=clock)
    while not stop.is_set():
        check.tick()
        if stop.wait(_TICK_SEC):
            return


def published(config: RuntimeConfig) -> dict[str, Any] | None:
    stored = _read(os.path.join(config.state_home, STORE_FILENAME)) or {}
    latest = _version(stored.get("version"))
    installed = _version(config.release_version)
    at = stored.get("checked_at")
    if latest is None or installed is None or not latest[3] or latest <= installed:
        return None
    if (
        not isinstance(at, (int, float))
        or isinstance(at, bool)
        or not 0 < at <= sys.float_info.max
        or not math.isfinite(at)
    ):
        return None
    return {"version": stored["version"].removeprefix("v"), "checked_at": at}


def print_startup_hint(config: RuntimeConfig) -> None:
    if (
        runtime_config.UPDATE_CHECK_DEFAULT_ENABLED
        and not config.update_check_disabled
        and not settings.no_update_check(config)
        and (notice := published(config)) is not None
    ):
        print(
            f"Compass {notice['version']} is available. Update Compass through your installer.",
            flush=True,
        )
