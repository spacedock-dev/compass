"""Private terminal-holder control records and persistent, process-owned lock paths."""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import stat
import sys
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping


class Store:
    def __init__(self, home: str, sid: str) -> None:
        self.root = Path(home) / "monitor"
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        info = self.root.lstat()
        if not stat.S_ISDIR(info.st_mode) or (os.name != "nt" and info.st_uid != os.getuid()):
            raise OSError("monitor directory is not privately owned")
        self.root.chmod(0o700)
        # Claude's published identity has eight characters. The record also keeps resume_id,
        # which must match before an off request may touch a same-prefix run.
        self.key = hashlib.sha256(("claude:" + sid[:8]).encode()).hexdigest()

    def path(self, kind: str) -> Path:
        return self.root / (self.key + "." + kind)

    @contextlib.contextmanager
    def lock(self, kind: str) -> Iterator[bool]:
        flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(self.path(kind + ".lock"), flags, 0o600)
        held = False
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise OSError("monitor lock is not a regular file")
            os.fchmod(fd, 0o600) if os.name != "nt" else None
            if sys.platform == "win32":
                import msvcrt  # noqa: PLC0415

                os.lseek(fd, 0, os.SEEK_SET)
                try:
                    msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                    held = True
                except PermissionError:
                    pass
            else:
                import fcntl  # noqa: PLC0415

                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    held = True
                except BlockingIOError:
                    pass
            yield held
        finally:
            if held and sys.platform == "win32":
                with contextlib.suppress(OSError):
                    os.lseek(fd, 0, os.SEEK_SET)
                    msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            os.close(fd)
        # Never unlink a lock: a waiter may already have opened its inode.

    def read(self, kind: str) -> dict[str, Any]:
        try:
            fd = os.open(
                self.path(kind),
                os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0),
            )
            with os.fdopen(fd, "rb") as stream:
                if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                    return {}
                raw = stream.read(8193)
            value = json.loads(raw) if len(raw) <= 8192 else None
        except (OSError, ValueError, RecursionError):
            return {}
        return value if isinstance(value, dict) else {}

    def write(self, kind: str, value: Mapping[str, Any]) -> None:
        fd, name = tempfile.mkstemp(prefix=self.key + ".", dir=self.root)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(value, stream, separators=(",", ":"), allow_nan=False)
            os.replace(name, self.path(kind))
        finally:
            with contextlib.suppress(OSError):
                os.unlink(name)

    def running(self) -> bool:
        with self.lock("life") as free:
            return not free
