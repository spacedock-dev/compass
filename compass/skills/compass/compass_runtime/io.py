"""Bounded filesystem and read-only database operations."""

from __future__ import annotations

import contextlib
import ctypes
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
from ctypes import wintypes
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, BinaryIO, TextIO
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


def open_regular(path: str | os.PathLike[str], *, root: str | None = None) -> int:
    """Strict state read: an owned regular leaf, with no untrusted descendant links."""
    path = os.path.abspath(path)
    parent = None
    guard = contextlib.ExitStack()
    if os.name == "nt":
        directory = guard.enter_context(
            _windows_directory(
                os.path.dirname(path),
                root=root if root is not None else os.path.splitdrive(path)[0] + os.sep,
                create=False,
            )
        )
        path = os.path.join(directory, os.path.basename(path))
    if os.name != "nt":
        parent = (
            _owner_directory_fd(os.path.dirname(path), root=root, create=False)
            if root is not None
            else _directory_fd(os.path.dirname(path), follow_links=False)
        )
    try:
        if os.path.islink(path):
            raise OSError(errno.ELOOP, "Refusing a state symlink", path)
        flags = (
            os.O_RDONLY
            | getattr(os, "O_BINARY", 0)
            | getattr(os, "O_NONBLOCK", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )
        fd = (
            _windows_file_fd(path)
            if sys.platform == "win32"
            else os.open(
                path if parent is None else os.path.basename(path),
                flags,
                **({} if parent is None else {"dir_fd": parent}),
            )
        )
        try:
            info = os.fstat(fd)
            _check_regular(info, path)
        except BaseException:
            os.close(fd)
            raise
        return fd
    finally:
        guard.close()
        if parent is not None:
            os.close(parent)


def open_harness(
    path: str | os.PathLike[str],
    *,
    follow_links: bool = True,
    _links: list[int] | None = None,
    _parent_fd: int | None = None,
) -> int:
    """Read an owned regular harness file from its admitted descriptor, never a FIFO."""
    _links = [0] if _links is None else _links
    if _links[0] >= 40:
        raise OSError(errno.ELOOP, "Too many harness links", path)
    path = os.fspath(path)
    if os.name == "nt":
        # On Windows the resolved target is checked by open_regular; no POSIX UID exists.
        return open_regular(os.path.realpath(path) if follow_links else path)
    parent = _directory_fd(os.path.dirname(path), links=_links, parent_fd=_parent_fd)
    try:
        name = os.path.basename(path)
        flags = os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW
        try:
            fd = os.open(name, flags, dir_fd=parent)
        except OSError as exc:
            if not follow_links or exc.errno != errno.ELOOP:
                raise
            target = os.readlink(name, dir_fd=parent)
            _links[0] += 1
            return open_harness(target, _links=_links, _parent_fd=parent)
        try:
            info = os.fstat(fd)
            _check_regular(info, path)
        except BaseException:
            os.close(fd)
            raise
        return fd
    finally:
        os.close(parent)


def open_harness_text(path: str, *, errors: str = "strict") -> TextIO:
    return os.fdopen(open_harness(path), "r", encoding="utf-8", errors=errors)


def _open_binary(path: str, *, follow_links: bool = True) -> BinaryIO:
    return os.fdopen(open_harness(path, follow_links=follow_links), "rb")


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
    return os.fdopen(open_harness(path, follow_links=follow_links), "rb", buffering=0)


def scan_reverse_lines(
    config: RuntimeConfig,
    path: str,
    budget: ReadBudget,
    *,
    follow_links: bool = True,
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
    follow_links: bool = True,
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
    config: RuntimeConfig, path: str, *, end: int | None = None, follow_links: bool = True
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
        with os.fdopen(open_harness(path), "rb") as source:
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


def read_prefix_bytes(
    path: str, *, max_bytes: int, harness: bool = False, root: str | None = None
) -> bytes:
    with os.fdopen(
        (open_harness(path) if harness else open_regular(path, root=root)), "rb"
    ) as source:
        return source.read(max_bytes)


def iter_bounded_text_lines(
    path: str,
    *,
    max_lines: int,
    per_line_bytes: int,
) -> Iterator[str]:
    try:
        with os.fdopen(open_harness(path), "rb") as source:
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
    follow_links: bool = True,
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


def admit_harness_root(path: str) -> bool:
    """Validate an existing configured store directory without creating absent stores."""
    if os.name == "nt":
        return os.path.isdir(path)
    try:
        fd = _directory_fd(path)
        try:
            if stat.S_IMODE(os.fstat(fd).st_mode) & ~0o700:
                os.fchmod(fd, 0o700)
        finally:
            os.close(fd)
    except OSError:
        return False
    return True


def glob_under(root: str, *pattern: str) -> list[str]:
    if not admit_harness_root(root):
        return []
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
    return (
        admit_harness_root(root)
        and next(glob.iglob(os.path.join(glob.escape(root), *pattern)), None) is not None
    )


def any_glob_stores(config: RuntimeConfig, key: str, *pattern: str) -> bool:
    """`glob_stores` as a predicate: the first root that matches ends the walk."""
    return any(any_glob_under(root, *pattern) for root in config.store_roots.get(key, ()))


def any_store_dir(config: RuntimeConfig, key: str, *parts: str) -> bool:
    return any(
        admit_harness_root(root) and os.path.isdir(os.path.join(root, *parts))
        for root in config.store_roots.get(key, ())
    )


def existing_stores(config: RuntimeConfig, key: str) -> list[str]:
    return [
        path
        for path in config.store_roots.get(key, ())
        if admit_harness_root(os.path.dirname(path)) and os.path.isfile(path)
    ]


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


def check_sqlite_file(path: str, *, harness: bool = False, root: str | None = None) -> None:
    """SQLite reopens by pathname; reject unsafe leaves before handing it one."""
    try:
        fd = open_harness(path) if harness else open_regular(path, root=root)
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
        check_sqlite_file(path, harness=True)
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


def _is_reparse(info: os.stat_result) -> bool:
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0)
        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    )


def _windows_handle(path: str, *, directory: bool = False, append: bool = False) -> tuple[Any, Any]:
    """Open the reparse point itself; deny deletion while a directory is held."""
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
    kernel.CreateFileW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    kernel.GetFileInformationByHandleEx.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
    ]
    kernel.GetFileInformationByHandleEx.restype = wintypes.BOOL
    # The CRT seeks before appending, which requires GENERIC_WRITE rather than
    # FILE_APPEND_DATA alone. Deny directory write sharing too: an open directory
    # must not become a junction between admission and the child operation.
    access = 0x80 if directory else (0x40000080 if append else 0x80000000)
    share = 0x1 if directory else 0x3
    handle = kernel.CreateFileW(path, access, share, None, 4 if append else 3, 0x02200000, None)
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())  # type: ignore[attr-defined]
    try:
        attributes = (wintypes.DWORD * 2)()
        if not kernel.GetFileInformationByHandleEx(
            handle, 9, attributes, ctypes.sizeof(attributes)
        ):
            raise ctypes.WinError(ctypes.get_last_error())  # type: ignore[attr-defined]  # noqa: TRY301 - close the opened handle on refusal
        if attributes[0] & 0x400:
            raise OSError(errno.ELOOP, "Refusing a state reparse point", path)  # noqa: TRY301 - close the opened handle on refusal
        if directory and not attributes[0] & 0x10:
            raise OSError(errno.ENOTDIR, "State parent is not a directory", path)  # noqa: TRY301 - close the opened handle on refusal
    except BaseException:
        kernel.CloseHandle(handle)
        raise
    return kernel, handle


def _windows_file_fd(path: str, *, append: bool = False) -> int:
    import msvcrt  # noqa: PLC0415 - the CRT handle transfer exists only on Windows

    kernel, handle = _windows_handle(path, append=append)
    try:
        flags = os.O_APPEND if append else os.O_RDONLY
        return int(msvcrt.open_osfhandle(handle, flags | getattr(os, "O_BINARY", 0)))  # type: ignore[attr-defined]
    except BaseException:
        kernel.CloseHandle(handle)
        raise


@contextlib.contextmanager
def _windows_directory(path: str, *, root: str | None, create: bool) -> Iterator[str]:
    """Admit the root's target, then hold each non-reparse descendant until I/O ends."""
    absolute = os.path.abspath(path)
    anchor = os.path.abspath(path if root is None else root)
    if os.path.commonpath((absolute, anchor)) != anchor:
        raise OSError(errno.EPERM, "State directory is outside its configured root", path)
    relative = os.path.relpath(absolute, anchor)
    resolved = os.path.realpath(anchor)
    with contextlib.ExitStack() as held:
        if create:
            os.makedirs(resolved, mode=0o700, exist_ok=True)
        parts = () if relative == "." else relative.split(os.sep)
        for part in (None, *parts):
            if part is not None:
                resolved = os.path.join(resolved, part)
                if create:
                    with contextlib.suppress(FileExistsError):
                        os.mkdir(resolved, 0o700)
            info = os.lstat(resolved)
            if _is_reparse(info):
                raise OSError(errno.ELOOP, "Refusing a state directory reparse point", resolved)
            _check_directory(info, resolved)
            if sys.platform == "win32":
                kernel, handle = _windows_handle(resolved, directory=True)
                held.callback(kernel.CloseHandle, handle)
        yield resolved


def _owned(info: os.stat_result) -> bool:
    return os.name == "nt" or info.st_uid == os.getuid()


def _check_directory(info: os.stat_result, path: str, *, require_owner: bool = True) -> None:
    if not stat.S_ISDIR(info.st_mode) or (require_owner and not _owned(info)):
        raise OSError(errno.EPERM, "Directory is not owned by this user", path)


def _check_regular(info: os.stat_result, path: str) -> None:
    if not stat.S_ISREG(info.st_mode) or _is_reparse(info) or not _owned(info):
        raise OSError(errno.EINVAL, "Not an owned regular file", path)


def _platform_alias(path: str, target: str) -> bool:
    # Only the OS's known ancestor aliases bypass the user-ownership requirement.
    aliases = {"/tmp": "/private/tmp", "/var": "/private/var", "/etc": "/private/etc"}  # noqa: S108 - platform aliases, not temporary storage
    return sys.platform == "darwin" and aliases.get(path) == os.path.normpath(
        os.path.join("/", target)
    )


def _directory_child(
    fd: int,
    part: str,
    walked: str,
    *,
    create: bool,
    mode: int,
    links: list[int],
    follow_links: bool,
) -> int:
    child = os.path.join(walked, part)
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        return os.open(part, flags, dir_fd=fd)
    except FileNotFoundError:
        if not create:
            raise
        _check_directory(os.fstat(fd), walked)
        with contextlib.suppress(FileExistsError):
            os.mkdir(part, mode, dir_fd=fd)
        new_fd = os.open(part, flags, dir_fd=fd)
        try:
            _check_directory(os.fstat(new_fd), child)
            os.fchmod(new_fd, mode)
        except BaseException:
            os.close(new_fd)
            raise
        return new_fd
    except OSError as open_error:
        try:
            target = os.readlink(part, dir_fd=fd)
        except OSError:
            raise open_error from None
        trusted = (
            _platform_alias(child, target)
            and os.stat(part, dir_fd=fd, follow_symlinks=False).st_uid == 0
        )
        if not follow_links and not trusted:
            raise
        links[0] += 1
        if links[0] > 40:
            raise OSError(errno.ELOOP, "Too many directory links", child) from None
        return _directory_fd(
            target,
            parent_fd=fd,
            create=False,
            mode=mode,
            links=links,
            require_owner=not trusted,
            follow_links=follow_links,
        )


def _directory_fd(
    path: str,
    *,
    create: bool = False,
    mode: int = 0o700,
    links: list[int] | None = None,
    require_owner: bool = True,
    follow_links: bool = True,
    parent_fd: int | None = None,
) -> int:
    """Walk held directories and bound link traversal, preserving platform ancestor aliases."""
    links = [0] if links is None else links
    # Relative link targets, including "..", belong to the held parent, not its
    # lexical name: an earlier directory link may have changed the physical depth.
    relative = parent_fd is not None and not os.path.isabs(path)
    absolute = path if relative else os.path.join(os.getcwd(), path)
    fd = (
        os.dup(parent_fd)
        if relative and parent_fd is not None
        else os.open("/", os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    )
    walked = "" if relative else "/"
    private = relative and require_owner
    try:
        for part in absolute.split("/"):
            if not part:
                continue
            child = _directory_child(
                fd, part, walked, create=create, mode=mode, links=links, follow_links=follow_links
            )
            os.close(fd)
            fd = child
            walked = os.path.join(walked, part)
            info = os.fstat(fd)
            if private:
                _check_directory(info, walked)
            private = private or _owned(info)
        _check_directory(os.fstat(fd), path, require_owner=require_owner)
    except BaseException:
        os.close(fd)
        raise
    return fd


def _owner_directory_fd(
    path: str, *, root: str | None = None, mode: int = 0o700, create: bool = True
) -> int:
    """Anchor a configured root, then refuse every descendant directory link."""
    root = path if root is None else root
    absolute, anchor = os.path.abspath(path), os.path.abspath(root)
    if os.path.commonpath((absolute, anchor)) != anchor:
        raise OSError(errno.EPERM, "State directory is outside its configured root", path)
    fd = _directory_fd(anchor, create=create, mode=mode)
    try:
        if create and stat.S_IMODE(os.fstat(fd).st_mode) & ~mode:
            os.fchmod(fd, mode)
        relative = os.path.relpath(absolute, anchor)
        for part in () if relative == "." else relative.split(os.sep):
            try:
                child = os.open(
                    part,
                    os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
                    dir_fd=fd,
                )
            except FileNotFoundError:
                if not create:
                    raise
                with contextlib.suppress(FileExistsError):
                    os.mkdir(part, mode, dir_fd=fd)
                child = os.open(
                    part,
                    os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
                    dir_fd=fd,
                )
            os.close(fd)
            fd = child
            _check_directory(os.fstat(fd), path)
            if create and stat.S_IMODE(os.fstat(fd).st_mode) & ~mode:
                os.fchmod(fd, mode)
    except BaseException:
        os.close(fd)
        raise
    return fd


def ensure_owner_dir(path: str, mode: int = 0o700, *, root: str | None = None) -> None:
    """Resolve an owned configured root and privately create every missing parent."""
    if os.name == "nt":
        with _windows_directory(path, root=root, create=True):
            pass
        return
    fd = _owner_directory_fd(path, root=root, mode=mode)
    os.close(fd)


def open_owner_append(path: str, *, root: str | None = None) -> BinaryIO:
    """Open a private daemon log relative to its validated directory descriptor."""
    directory = os.path.dirname(path) or "."
    parent = None
    guard = contextlib.ExitStack()
    if os.name == "nt":
        directory = guard.enter_context(_windows_directory(directory, root=root, create=True))
        path = os.path.join(directory, os.path.basename(path))
    else:
        parent = _owner_directory_fd(directory, root=root)
    try:
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
        fd = (
            _windows_file_fd(path, append=True)
            if sys.platform == "win32"
            else os.open(
                path if parent is None else os.path.basename(path),
                flags,
                0o600,
                **({} if parent is None else {"dir_fd": parent}),
            )
        )
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or (os.name != "nt" and info.st_uid != os.getuid()):
                raise OSError(errno.EPERM, "Log is not a privately owned regular file", path)  # noqa: TRY301 - close the admitted descriptor on refusal
            if os.name != "nt":
                os.fchmod(fd, 0o600)
        except BaseException:
            os.close(fd)
            raise
        return os.fdopen(fd, "ab", buffering=0)
    finally:
        guard.close()
        if parent is not None:
            os.close(parent)


def atomic_write_owner_only(
    target: str,
    content: bytes | str,
    *,
    encoding: str = "utf-8",
    sync: bool = False,
    replace: Callable[..., None] | None = None,
    root: str | None = None,
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
    directory = os.path.dirname(target) or "."
    parent = None
    guard = contextlib.ExitStack()
    if os.name == "nt":
        directory = guard.enter_context(_windows_directory(directory, root=root, create=True))
        target = os.path.join(directory, os.path.basename(target))
    else:
        parent = _owner_directory_fd(directory, root=root)
    tmp = f"{target}.{os.getpid()}.{secrets.token_hex(16)}.tmp"
    created = False
    file_options = {} if parent is None else {"dir_fd": parent}
    temp_name = tmp if parent is None else os.path.basename(tmp)
    target_name = target if parent is None else os.path.basename(target)
    try:
        with contextlib.suppress(FileNotFoundError):
            info = os.stat(target_name, follow_symlinks=False, **file_options)
            _check_regular(info, target)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(temp_name, flags, 0o600, **file_options)
        created = True
        with os.fdopen(fd, "wb") as handle:
            handle.write(content.encode(encoding) if isinstance(content, str) else content)
            if sync:
                handle.flush()
                os.fsync(handle.fileno())
        (replace or os.replace)(
            temp_name,
            target_name,
            **({} if parent is None else {"src_dir_fd": parent, "dst_dir_fd": parent}),
        )
    finally:
        if created:
            with contextlib.suppress(OSError):
                os.unlink(temp_name, **file_options)
        guard.close()
        if parent is not None:
            os.close(parent)


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
