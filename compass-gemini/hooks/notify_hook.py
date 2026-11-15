#!/usr/bin/env python3
"""Forward a Claude Code hook payload to a running Compass dashboard.

This exists because the equivalent shell one-liner is not portable. The
documented `curl` form relies on POSIX single-quoting, `/dev/null`, `|| true`,
and `--data-binary @-`: cmd.exe accepts none of that, and Windows PowerShell
5.1 both aliases `curl` to Invoke-WebRequest and has no `||`. One interpreter
invocation reading stdin behaves identically in every shell.

Usage in ~/.claude/settings.json (Notification and SessionEnd hooks):

    python3 <skill-dir>/notify_hook.py            # macOS, Linux, WSL, Git Bash
    python  <skill-dir>\\notify_hook.py           # Windows

Pass a URL as the first argument to target a non-default port.

Always exits 0. A hook that fails must never disturb the agent it is reporting
on, and "the dashboard is not running" is an ordinary state, not an error.
"""

from __future__ import annotations

import contextlib
import errno
import http.client
import json
import os
import secrets
import socket
import stat
import sys
import time
import urllib.parse
from typing import TYPE_CHECKING, Any, BinaryIO

if TYPE_CHECKING:
    from collections.abc import Buffer, Iterator

DEFAULT_URL = "http://127.0.0.1:4553/api/notify"
MAX_PAYLOAD_BYTES = 65536  # matches the server's own cap
TIMEOUT_SEC = 2
LOOPBACK_HOSTS = frozenset({"127.0.0.1"})


def _open_state(path: str, *, root: str | None = None) -> int:
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


def _state_root(path: str) -> str:
    configured = os.path.abspath(os.path.expanduser(os.environ.get("COMPASS_HOME", "~/.compass")))
    return (
        configured
        if os.path.commonpath((configured, os.path.abspath(path))) == configured
        else os.path.dirname(path)
    )


def open_regular_binary(path: str) -> BinaryIO:
    return os.fdopen(_open_state(path, root=_state_root(path)), "rb")


def _is_reparse(info: os.stat_result) -> bool:
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0)
        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    )


def _windows_handle(path: str, *, directory: bool = False, append: bool = False) -> tuple[Any, Any]:
    """Open the reparse point itself; deny deletion while a directory is held."""
    # Imported here: on Python 3.14 `import ctypes` loads sysconfig, which reads the
    # user's home at import time, and only Windows needs it.
    import ctypes  # noqa: PLC0415
    from ctypes import wintypes  # noqa: PLC0415

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


def write_owner_json(path: str, value: dict[str, Any]) -> None:
    """Publish a memo relative to its owned configured root, without runtime imports."""
    home = os.path.dirname(path)
    parent = None
    guard = contextlib.ExitStack()
    if os.name == "nt":
        home = guard.enter_context(_windows_directory(home, root=_state_root(path), create=True))
        path = os.path.join(home, os.path.basename(path))
    else:
        parent = _owner_directory_fd(home, root=_state_root(path))
    tmp = path + "." + secrets.token_hex(16) + ".tmp"
    name = path if parent is None else os.path.basename(path)
    temp_name = tmp if parent is None else os.path.basename(tmp)
    options = {} if parent is None else {"dir_fd": parent}
    created = False
    try:
        with contextlib.suppress(FileNotFoundError):
            info = os.stat(name, follow_symlinks=False, **options)
            _check_regular(info, path)
        fd = os.open(
            temp_name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
            **options,
        )
        created = True
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle)
        os.replace(
            temp_name,
            name,
            **({} if parent is None else {"src_dir_fd": parent, "dst_dir_fd": parent}),
        )
    finally:
        if created:
            with contextlib.suppress(OSError):
                os.unlink(temp_name, **options)
        guard.close()
        if parent is not None:
            os.close(parent)


def is_loopback_url(url: str) -> bool:
    """Whether ``url`` targets this machine over plain HTTP loopback.

    Parsed rather than prefix-matched. ``startswith("http://localhost")`` also
    accepts ``http://localhost.evil.com/`` and ``http://localhost@evil.com/``,
    which are entirely different hosts — that is the bypass this exists to
    prevent.
    """
    try:
        parsed = urllib.parse.urlsplit(url)
    except ValueError:
        return False
    return parsed.scheme == "http" and (parsed.hostname or "") in LOOPBACK_HOSTS


class _Socket(socket.socket):
    """Mirror loopback_transport's deadline socket for the hooks-only plugin roots.

    Gemini and Droid ship this file without compass_runtime. Keep the same mechanism:
    every SocketIO receive and send resets its timeout to the remaining exchange budget.
    """

    def __init__(self, deadline: float) -> None:
        super().__init__(socket.AF_INET, socket.SOCK_STREAM)
        self.deadline = deadline

    def remaining(self) -> float:
        left = self.deadline - time.monotonic()
        if left <= 0:
            raise TimeoutError("loopback exchange deadline")
        return left

    def recv_into(self, buffer: object, nbytes: int = 0, flags: int = 0) -> int:
        self.settimeout(self.remaining())
        return super().recv_into(buffer, nbytes, flags)  # type: ignore[arg-type]

    def sendall(self, data: Buffer, flags: int = 0) -> None:
        self.settimeout(self.remaining())
        super().sendall(data, flags)


def forward(url: str, payload: bytes, headers: dict[str, str] | None = None) -> bool:
    """POST ``payload`` to ``url``. Returns whether it was delivered.

    ``headers`` adds to the content type rather than replacing it, and exists for
    the event adapter beside this file, which has to present a capability. The
    loopback and proxy guards below are the reason that adapter imports this
    function instead of writing its own: a header is the only thing about the
    request it needs to change.
    """
    if not is_loopback_url(url):
        # This script is wired into an agent's lifecycle hooks and receives
        # prompts and session ids. It must not become a way to ship those
        # somewhere else because a settings file was edited.
        return False
    conn = None
    try:
        parsed = urllib.parse.urlsplit(url)
        port = parsed.port or 80
        deadline = time.monotonic() + TIMEOUT_SEC
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=TIMEOUT_SEC)
        with _Socket(deadline) as sock:
            sock.settimeout(sock.remaining())
            sock.connect(("127.0.0.1", port))
            conn.sock = sock
            path = urllib.parse.urlunsplit(("", "", parsed.path or "/", parsed.query, ""))
            conn.request(
                "POST",
                path,
                body=payload,
                headers={"Content-Type": "application/json", **(headers or {})},
            )
            with conn.getresponse() as response:
                # No response content is used, but reading to a cap proves the whole
                # exchange finishes within its budget even for a trickling body.
                response.read(MAX_PAYLOAD_BYTES + 1)
                sock.remaining()
                return 200 <= response.status < 300
    except (OSError, ValueError, http.client.HTTPException):
        return False
    finally:
        if conn is not None:
            conn.close()


def main(argv: list[str]) -> int:
    url = argv[1] if len(argv) > 1 else DEFAULT_URL
    try:
        payload = sys.stdin.buffer.read(MAX_PAYLOAD_BYTES)
    except (OSError, ValueError, AttributeError):
        return 0  # no stdin (run interactively, or a harness that closes it)
    if not payload.strip():
        payload = b"{}"
    try:  # a malformed payload is the harness's problem, not worth forwarding
        json.loads(payload)
    except (ValueError, RecursionError):
        # RecursionError, not just ValueError: deeply nested JSON blows the
        # decoder's stack, and that escaped as a non-zero exit — exactly what
        # this script promises never to do.
        return 0
    # Last-resort guard. forward() already handles every failure it expects;
    # this catches the ones it does not, because a hook that raises would
    # surface as an error inside the very agent session it is reporting on.
    with contextlib.suppress(Exception):
        forward(url, payload)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
