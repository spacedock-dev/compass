"""Bounded filesystem and read-only database operations."""

from __future__ import annotations

import contextlib
import errno
import glob
import json
import ntpath
import os
import posixpath
import secrets
import stat
import sys
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, BinaryIO
from urllib.parse import quote

from . import state as runtime_state

if sys.platform == "win32":
    import msvcrt
else:
    import fcntl

if TYPE_CHECKING:
    import sqlite3 as sqlite3_types
    from collections.abc import Callable, Iterator

    from .config import RuntimeConfig
    from .state import RuntimeState

try:
    import sqlite3 as _sqlite_module
except ImportError as exc:  # pragma: no cover - depends on the interpreter build
    SQLITE_IMPORT_ERROR: str | None = str(exc)
    sqlite_module: Any = None
else:
    SQLITE_IMPORT_ERROR = None
    sqlite_module = _sqlite_module


def open_regular(path: str | os.PathLike[str], *, follow_links: bool = False) -> int:
    """Open a regular file without waiting on a FIFO or following a leaf link."""
    if not follow_links and os.path.islink(path):
        raise OSError(errno.ELOOP, "Refusing a symlink", path)
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NONBLOCK", 0)
    if not follow_links:
        flags |= getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise OSError(errno.EINVAL, "Not a regular file", path)  # noqa: TRY301
    except BaseException:
        os.close(fd)
        raise
    return fd


def _open_binary(path: str, *, follow_links: bool = False) -> BinaryIO:
    return os.fdopen(open_regular(path, follow_links=follow_links), "rb")


@dataclass
class ReadBudget:
    """Actual transcript-content bytes spent by one check-evidence scan."""

    limit: int
    spent: int = 0

    @property
    def remaining(self) -> int:
        return max(0, self.limit - self.spent)

    def charge(self, raw: bytes) -> None:
        self.spent += len(raw)


@dataclass(frozen=True)
class TranscriptRead:
    """Private evidence and extent for one input in a shared read budget."""

    lines: tuple[bytes, ...]
    consumed: int
    byte_end: int | None
    read_start: int
    complete: bool
    cutoff_reached: bool = False
    failed: bool = False


def _open_scan_binary(path: str, *, follow_links: bool) -> BinaryIO:
    """No BufferedReader prefetch may escape a check scan's byte allowance."""
    return os.fdopen(open_regular(path, follow_links=follow_links), "rb", buffering=0)


def scan_reverse_lines(
    config: RuntimeConfig,
    path: str,
    budget: ReadBudget,
    *,
    follow_links: bool = False,
) -> TranscriptRead:
    """Read the newest complete lines, charging each returned binary byte."""
    before = budget.spent
    byte_end: int | None = None
    position = 0
    chunks: list[bytes] = []
    failed = False
    try:
        with _open_scan_binary(path, follow_links=follow_links) as source:
            byte_end = os.fstat(source.fileno()).st_size
            position = byte_end
            while position and budget.remaining:
                size = min(config.reverse_chunk_bytes, position, budget.remaining)
                position -= size
                source.seek(position)
                raw = source.read(size)
                budget.charge(raw)
                if len(raw) != size:
                    failed = True
                    break
                chunks.append(raw)
    except (OSError, ValueError):
        failed = True
    data = b"".join(reversed(chunks))
    lines = data.split(b"\n")
    if data.endswith(b"\n"):
        lines.pop()
    if position or failed:
        # The first line might start before the bounded window. Its bytes
        # still cost the allowance; they cannot establish a record.
        lines = lines[1:]
    return TranscriptRead(
        tuple(lines),
        budget.spent - before,
        byte_end,
        position,
        not position and not failed,
        failed=failed,
    )


def scan_stood_lines(
    path: str,
    budget: ReadBudget,
    is_future: Callable[[bytes], bool],
    *,
    follow_links: bool = False,
) -> TranscriptRead:
    """Find the first future record or held EOF within the same byte budget."""
    before = budget.spent
    byte_end: int | None = None
    lines: list[bytes] = []
    reached = False
    failed = False
    try:
        with _open_scan_binary(path, follow_links=follow_links) as source:
            byte_end = os.fstat(source.fileno()).st_size
            while source.tell() < byte_end and budget.remaining:
                raw = source.readline(min(budget.remaining, byte_end - source.tell()))
                budget.charge(raw)
                if not raw:
                    failed = True
                    break
                if not raw.endswith(b"\n") and source.tell() < byte_end:
                    failed = True
                    break
                if is_future(raw):
                    reached = True
                    break
                lines.append(raw)
            else:
                reached = source.tell() >= byte_end
    except (OSError, ValueError):
        failed = True
    return TranscriptRead(
        tuple(lines),
        budget.spent - before,
        byte_end,
        0,
        not failed and reached,
        reached,
        failed=failed,
    )


def read_tail(
    config: RuntimeConfig, path: str, *, end: int | None = None, follow_links: bool = False
) -> list[str]:
    """The last `tail_bytes` of a file as lines, or of its first `end` bytes when given."""
    try:
        with _open_binary(path, follow_links=follow_links) as source:
            size = os.fstat(source.fileno()).st_size if end is None else end
            truncated = False
            if size > config.tail_bytes:
                source.seek(size - config.tail_bytes - 1)
                truncated = source.read(1) != b"\n"
            raw = source.read() if end is None else source.read(size - source.tell())
            data = raw.decode("utf-8", "replace")
    except OSError:
        return []
    lines = data.split("\n")
    if truncated:
        lines = lines[1:]
    return lines


def read_first_json(config: RuntimeConfig, path: str) -> dict[str, Any]:
    try:
        with os.fdopen(open_regular(path), "rb") as source:
            size = os.fstat(source.fileno()).st_size
            raw = source.readline(config.first_line_json_cap_bytes)
    except OSError:
        return {}
    if size > len(raw) and raw and not raw.endswith(b"\n"):
        return {}
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def read_prefix_bytes(path: str, *, max_bytes: int) -> bytes:
    with os.fdopen(open_regular(path), "rb") as source:
        return source.read(max_bytes)


def iter_bounded_text_lines(
    path: str,
    *,
    max_lines: int,
    per_line_bytes: int,
) -> Iterator[str]:
    try:
        with os.fdopen(open_regular(path), "rb") as source:
            for _ in range(max_lines):
                raw = source.readline(per_line_bytes)
                if not raw:
                    break
                yield raw.decode("utf-8", "replace")
    except OSError:
        return


def reverse_lines(
    config: RuntimeConfig,
    path: str,
    end_pos: int | None = None,
    *,
    max_bytes: int | None = None,
    contains: bytes | None = None,
    follow_links: bool = False,
) -> Iterator[bytes]:
    """Yield complete lines from ``path`` newest-first, reading fixed chunks."""
    try:
        with _open_binary(path, follow_links=follow_links) as source:
            size = os.fstat(source.fileno()).st_size
            stop = size if end_pos is None else min(end_pos, size)
            floor = 0 if max_bytes is None else max(0, stop - max_bytes)
            pos = stop
            carry: list[bytes] = []
            while pos > floor:
                read_size = min(config.reverse_chunk_bytes, pos - floor)
                pos -= read_size
                source.seek(pos)
                chunk = source.read(read_size)
                if len(chunk) < read_size:
                    return
                last_newline = chunk.rfind(b"\n")
                if last_newline < 0:
                    carry.append(chunk)
                    continue
                carry.append(chunk[last_newline + 1 :])
                completed = b"".join(reversed(carry))
                parts = chunk[:last_newline].split(b"\n")
                carry = [parts[0]]
                if contains is None or contains in chunk or contains in completed:
                    yield completed
                    yield from reversed(parts[1:])
            if floor == 0 and stop > 0:
                yield b"".join(reversed(carry))
    except OSError:
        return


def glob_under(root: str, *pattern: str) -> list[str]:
    return sorted(glob.glob(os.path.join(glob.escape(root), *pattern)))


def glob_stores(config: RuntimeConfig, key: str, *pattern: str) -> list[str]:
    return [path for root in config.store_roots.get(key, ()) for path in glob_under(root, *pattern)]


def any_glob_under(root: str, *pattern: str) -> bool:
    """Whether anything under ``root`` matches, without building the list.

    A predicate's answer is one bit, and `glob_under` pays for a full match list
    and a sort to produce it. `iglob` stops at the first hit. Same escaping
    contract as `glob_under`: the root is a real path and is escaped, the
    pattern is a pattern and is not.
    """
    return next(glob.iglob(os.path.join(glob.escape(root), *pattern)), None) is not None


def any_glob_stores(config: RuntimeConfig, key: str, *pattern: str) -> bool:
    """`glob_stores` as a predicate: the first root that matches ends the walk."""
    return any(any_glob_under(root, *pattern) for root in config.store_roots.get(key, ()))


def any_store_dir(config: RuntimeConfig, key: str, *parts: str) -> bool:
    return any(
        os.path.isdir(os.path.join(root, *parts)) for root in config.store_roots.get(key, ())
    )


def existing_stores(config: RuntimeConfig, key: str) -> list[str]:
    return [path for path in config.store_roots.get(key, ()) if os.path.isfile(path)]


def sqlite_available() -> bool:
    return SQLITE_IMPORT_ERROR is None


def sqlite_ro_uri(path: str, *, immutable: bool = False, windows: bool | None = None) -> str:
    if windows is None:
        windows = os.name == "nt"
    absolute = (ntpath if windows else posixpath).abspath(path)
    if windows:
        absolute = absolute.replace("\\", "/")
        if not absolute.startswith("/"):
            absolute = "/" + absolute
    quoted = quote(absolute, safe="/:")
    if quoted.startswith("//") and not quoted.startswith("///"):
        quoted = "//" + quoted
    query = "?mode=ro&immutable=1" if immutable else "?mode=ro"
    return f"file:{quoted}{query}"


_STORE_ERROR_MESSAGE_CHARS = 1024
_STORE_ERROR_TRUNCATION = "... [truncated]"


def record_store_error(state: RuntimeState, path: str, exc: BaseException) -> None:
    """Keep the real type and at most 1,024 message characters, including the marker."""
    # Even SQLite errors can carry store text:
    # [U-2](docs/design-unread-sources.md#u-2).
    message = str(exc)
    if len(message) > _STORE_ERROR_MESSAGE_CHARS:
        message = (
            message[: _STORE_ERROR_MESSAGE_CHARS - len(_STORE_ERROR_TRUNCATION)]
            + _STORE_ERROR_TRUNCATION
        )
    with state.cache_lock:
        runtime_state.bounded_put(
            state.store_errors,
            path,
            f"{type(exc).__name__}: {message}",
            limit=state.config.max_cache_entries,
        )


def check_sqlite_file(path: str) -> None:
    """SQLite reopens by pathname; reject unsafe leaves before handing it one."""
    try:
        fd = open_regular(path)
        os.close(fd)
    except OSError as exc:
        message = (
            "Database is not a regular non-symlink file"
            if exc.errno in {errno.ELOOP, errno.EINVAL}
            else "unable to open database file"
        )
        raise sqlite_module.OperationalError(message) from exc


def open_sqlite_read_only(path: str, state: RuntimeState) -> sqlite3_types.Connection:
    try:
        check_sqlite_file(path)
        connection: sqlite3_types.Connection = sqlite_module.connect(
            sqlite_ro_uri(path),
            uri=True,
            timeout=0.2,
        )
    except sqlite_module.Error as exc:
        record_store_error(state, path, exc)
        raise
    connection.row_factory = sqlite_module.Row
    return connection


def diag(message: str, sink: Callable[[str], object]) -> None:
    try:
        sink(message)
    except (OSError, ValueError):
        with contextlib.suppress(OSError, ValueError):
            sink(message.encode("ascii", "backslashreplace").decode("ascii"))


def ensure_owner_dir(path: str, mode: int = 0o700) -> None:
    """Create directory with `mode`, or tighten if it exists with looser permissions.

    Refuse a final symlink or foreign-owned directory rather than chmod its target.
    On POSIX, tighten excess permission bits; leave stricter modes alone.
    The mode is advisory and Windows ignores it.
    """
    os.makedirs(path, mode=mode, exist_ok=True)
    info = os.lstat(path)
    if not stat.S_ISDIR(info.st_mode):
        raise OSError(errno.ENOTDIR, "State directory is not a directory", path)
    if os.name != "nt":
        if info.st_uid != os.getuid():
            raise OSError(errno.EPERM, "State directory is not owned by this user", path)
        if stat.S_IMODE(info.st_mode) & ~mode:
            os.chmod(path, mode)


def open_owner_append(path: str) -> BinaryIO:
    """Open a private daemon log, refusing links and nonregular leaves."""
    ensure_owner_dir(os.path.dirname(path) or ".")
    if os.path.islink(path):
        raise OSError(errno.ELOOP, "Refusing a log symlink", path)
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_APPEND
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
        | getattr(os, "O_BINARY", 0)
    )
    fd = os.open(path, flags, 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or (os.name != "nt" and info.st_uid != os.getuid()):
            raise OSError(errno.EPERM, "Log is not a privately owned regular file", path)  # noqa: TRY301
        if os.name != "nt":
            os.fchmod(fd, 0o600)
    except BaseException:
        os.close(fd)
        raise
    return os.fdopen(fd, "ab", buffering=0)


def atomic_write_owner_only(
    target: str,
    content: bytes | str,
    *,
    encoding: str = "utf-8",
    sync: bool = False,
    replace: Callable[[str, str], None] | None = None,
) -> None:
    """Atomically write `content` to `target` owner-only (0o600).

    Ensures the parent directory exists and is tightened to 0o700.
    The temporary file is opened with O_WRONLY | O_CREAT | O_EXCL and
    O_NOFOLLOW (where supported) with mode 0o600 and a randomized name
    beside `target`. Cleans up the temporary file on error. Existing symlinks,
    nonregular targets and foreign-owned files refuse. `sync` flushes the file
    before publication; `replace` preserves a caller's bounded sharing-violation
    retry. Directory durability remains the caller's policy.
    """
    directory = os.path.dirname(target)
    if directory:
        ensure_owner_dir(directory)
    if os.path.lexists(target):
        info = os.lstat(target)
        if not stat.S_ISREG(info.st_mode) or (os.name != "nt" and info.st_uid != os.getuid()):
            raise OSError(errno.EPERM, "State target is not a privately owned regular file", target)
    rand = secrets.token_hex(16)
    tmp = f"{target}.{os.getpid()}.{rand}.tmp"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(tmp, flags, 0o600)
    try:
        if isinstance(content, str):
            with os.fdopen(fd, "w", encoding=encoding) as handle:
                handle.write(content)
                if sync:
                    handle.flush()
                    os.fsync(handle.fileno())
        else:
            with os.fdopen(fd, "wb") as handle:
                handle.write(content)
                if sync:
                    handle.flush()
                    os.fsync(handle.fileno())
        (replace or os.replace)(tmp, target)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


# What `held_file_lock` yields. Four answers rather than a bool and None,
# because the annotation store refuses a lock file it cannot use but falls back
# where the filesystem cannot lock at all, and the recovery pass runs in both.
LOCK_HELD = "held"
LOCK_BUSY = "busy"
LOCK_UNSUPPORTED = "unsupported"
LOCK_DENIED = "denied"
LOCK_UNCREATABLE = "uncreatable"

# The errnos with which a filesystem says it has no locks, rather than that
# this file refuses this user. ENOTSUP and EOPNOTSUPP are one value on Linux
# and two on macOS. Windows has none here: the CRT reports every `LockFile`
# failure as EACCES, which reads as busy and so refuses (not measured there).
_LOCKS_UNSUPPORTED = frozenset({errno.ENOLCK, errno.EOPNOTSUPP, errno.ENOTSUP})

# Why a lock file that does not exist could not be made: the directory cannot
# take a new file. A store beside it cannot be written then either, since its
# write is a temp file and a rename in that same directory. EMFILE and ENFILE
# are absent on purpose: they are this process running out of descriptors,
# which says nothing about the directory, so they stay a refusal.
_DIRECTORY_REFUSES = frozenset(
    {errno.ENOENT, errno.ENOTDIR, errno.EROFS, errno.EACCES, errno.EPERM, errno.ENOSPC}
    | ({errno.EDQUOT} if hasattr(errno, "EDQUOT") else set())
)


@contextlib.contextmanager
def held_file_lock(path: str | os.PathLike[str], *, wait: float) -> Iterator[str]:
    """Hold an OS lock on `path` for the block, waiting at most `wait` seconds.

    Yields `LOCK_HELD` while held, `LOCK_BUSY` when another holder kept it past
    the wait, `LOCK_UNSUPPORTED` when the filesystem reports it cannot lock,
    `LOCK_UNCREATABLE` when there is no lock file and its directory refuses a
    new one, and `LOCK_DENIED` when the file cannot be opened or locked for any
    other reason: a lock file left mode 000, one another user owns, a sharing
    violation. The caller decides what each means. An OS lock dies with its
    process, so a holder that crashed leaves nothing stale behind.

    Moved here from `reading_jobs`' recovery pass so the annotation store takes
    the same lock rather than a third mechanism (DRC-4661). `flock` on POSIX,
    one byte of `msvcrt.locking` on Windows. Locally each belongs to the open
    handle, so two opens in one process conflict. Where `flock` is emulated
    with POSIX locks, as Linux NFS clients do, the lock belongs to the process:
    a second open in it succeeds, and any close releases it. A caller with
    threads must let only one of them hold this at a time.
    """
    try:
        if os.path.islink(path):
            raise OSError(errno.ELOOP, "Refusing a symlink", path)  # noqa: TRY301
        flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        fd = os.open(path, flags, 0o600)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or (os.name != "nt" and info.st_uid != os.getuid()):
                raise OSError(errno.EPERM, "Lock is not a privately owned regular file", path)  # noqa: TRY301
            if os.name != "nt":
                os.fchmod(fd, 0o600)
        except BaseException:
            os.close(fd)
            raise
    except OSError as exc:
        if exc.errno in _LOCKS_UNSUPPORTED:
            yield LOCK_UNSUPPORTED
        elif exc.errno in _DIRECTORY_REFUSES and not os.path.lexists(path):
            yield LOCK_UNCREATABLE
        else:
            yield LOCK_DENIED
        return
    try:
        held = _lock_fd(fd, wait)
        try:
            yield held
        finally:
            if held == LOCK_HELD:
                _unlock_fd(fd)
    finally:
        os.close(fd)


def _lock_fd(fd: int, wait: float) -> str:
    """Lock `fd`, waiting a bounded time. One of `held_file_lock`'s answers."""
    # Held elsewhere: `flock` raises BlockingIOError and `msvcrt.locking`
    # PermissionError (EACCES), each for this and nothing else.
    busy: type[OSError] = PermissionError if sys.platform == "win32" else BlockingIOError
    deadline = time.monotonic() + wait
    while True:
        try:
            if sys.platform == "win32":
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            else:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except busy:
            if time.monotonic() >= deadline:
                return LOCK_BUSY
            time.sleep(0.05)
        except OSError as exc:
            return LOCK_UNSUPPORTED if exc.errno in _LOCKS_UNSUPPORTED else LOCK_DENIED
        else:
            return LOCK_HELD


def _unlock_fd(fd: int) -> None:
    with contextlib.suppress(OSError):
        if sys.platform == "win32":
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        else:
            fcntl.flock(fd, fcntl.LOCK_UN)
