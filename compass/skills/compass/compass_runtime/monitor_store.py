"""Private terminal-holder control records and persistent, process-owned lock paths."""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

from . import io as runtime_io

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping


class Store:
    def __init__(self, home: str, sid: str) -> None:
        self.root = Path(home) / "monitor"
        runtime_io.ensure_owner_dir(str(home))
        runtime_io.ensure_owner_dir(str(self.root), root=str(home))
        # Claude's published identity has eight characters. The record also keeps resume_id,
        # which must match before an off request may touch a same-prefix run.
        self.key = hashlib.sha256(("claude:" + sid[:8]).encode()).hexdigest()

    def path(self, kind: str) -> Path:
        return self.root / (self.key + "." + kind)

    @contextlib.contextmanager
    def lock(self, kind: str) -> Iterator[bool]:
        with runtime_io.held_file_lock(
            self.path(kind + ".lock"), wait=0, root=str(self.root.parent)
        ) as held:
            if held not in (runtime_io.LOCK_HELD, runtime_io.LOCK_BUSY):
                raise OSError("monitor lock is unavailable")
            yield held == runtime_io.LOCK_HELD
        # Never unlink a lock: a waiter may already have opened its inode.

    def read(self, kind: str) -> dict[str, Any]:
        try:
            with os.fdopen(
                runtime_io.open_regular(self.path(kind), root=str(self.root.parent)), "rb"
            ) as stream:
                raw = stream.read(8193)
            value = json.loads(raw) if len(raw) <= 8192 else None
        except (OSError, ValueError, RecursionError):
            return {}
        return value if isinstance(value, dict) else {}

    def write(self, kind: str, value: Mapping[str, Any]) -> None:
        runtime_io.atomic_write_owner_only(
            str(self.path(kind)),
            json.dumps(value, separators=(",", ":"), allow_nan=False),
            root=str(self.root.parent),
        )

    def running(self) -> bool:
        with self.lock("life") as free:
            return not free
