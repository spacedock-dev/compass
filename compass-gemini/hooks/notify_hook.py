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
import stat
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, BinaryIO

DEFAULT_URL = "http://127.0.0.1:4553/api/notify"
MAX_PAYLOAD_BYTES = 65536  # matches the server's own cap
TIMEOUT_SEC = 2
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


def _open_state(path: str, *, root: str | None = None) -> int:
    """Strict state read: an owned regular leaf, with no untrusted descendant links."""
    path = os.path.abspath(path)
    parent = None
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
        fd = os.open(
            path if parent is None else os.path.basename(path),
            flags,
            **({} if parent is None else {"dir_fd": parent}),
        )
        try:
            info = os.fstat(fd)
            _check_regular(info, path)
        except BaseException:
            os.close(fd)
            raise
        return fd
    finally:
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


def _owned(info: os.stat_result) -> bool:
    return os.name == "nt" or info.st_uid == os.getuid()


def _check_directory(info: os.stat_result, path: str, *, require_owner: bool = True) -> None:
    if not stat.S_ISDIR(info.st_mode) or (require_owner and not _owned(info)):
        raise OSError(errno.EPERM, "Directory is not owned by this user", path)


def _check_regular(info: os.stat_result, path: str) -> None:
    if not stat.S_ISREG(info.st_mode) or not _owned(info):
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
    flags = os.O_RDONLY | (getattr(os, "O_DIRECTORY", 0) or 0) | os.O_NOFOLLOW
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
    except OSError:
        target = os.readlink(part, dir_fd=fd)
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
            os.path.join(walked, target),
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
) -> int:
    """Walk held directories and bound link traversal, preserving platform ancestor aliases."""
    links = [0] if links is None else links
    absolute = os.path.abspath(path)
    fd = os.open("/", os.O_RDONLY | (getattr(os, "O_DIRECTORY", 0) or 0))
    walked = "/"
    private = False
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
                    os.O_RDONLY | (getattr(os, "O_DIRECTORY", 0) or 0) | os.O_NOFOLLOW,
                    dir_fd=fd,
                )
            except FileNotFoundError:
                if not create:
                    raise
                with contextlib.suppress(FileExistsError):
                    os.mkdir(part, mode, dir_fd=fd)
                child = os.open(
                    part,
                    os.O_RDONLY | (getattr(os, "O_DIRECTORY", 0) or 0) | os.O_NOFOLLOW,
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
        # Windows ignores POSIX modes and does not expose openat directory handles.
        os.makedirs(path, mode=mode, exist_ok=True)
        if not os.path.isdir(path):
            raise OSError(errno.ENOTDIR, "State root is not a directory", path)
        return
    fd = _owner_directory_fd(path, root=root, mode=mode)
    os.close(fd)


def write_owner_json(path: str, value: dict[str, Any]) -> None:
    """Publish a memo relative to its owned configured root, without runtime imports."""
    home = os.path.dirname(path)
    parent = None
    if os.name == "nt":
        ensure_owner_dir(home, root=_state_root(path))
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


class _NoRedirects(urllib.request.HTTPRedirectHandler):
    """Refuse to follow redirects.

    urllib follows them by default, and 307/308 preserve the method and body.
    A hostile or misconfigured listener on the loopback port could otherwise
    bounce a hook payload — which carries prompts and session ids — straight
    off this machine, defeating the loopback check above.
    """

    def redirect_request(self, *_args: Any, **_kwargs: Any) -> None:
        return None


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
    request = urllib.request.Request(  # noqa: S310 — scheme/host checked above
        url,
        data=payload,
        headers={"Content-Type": "application/json", **(headers or {})},
        method="POST",
    )
    # ProxyHandler({}) disables proxying entirely. Without it the default
    # opener honours http_proxy/HTTP_PROXY — routine in corporate environments
    # — and a POST to 127.0.0.1 is handed to the proxy instead, carrying
    # prompts and session ids off the machine. That defeats the whole point of
    # the loopback check above.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirects)
    try:
        with opener.open(request, timeout=TIMEOUT_SEC):
            return True
    except (urllib.error.URLError, OSError, ValueError, http.client.HTTPException):
        # Dashboard not running, wrong port, mid-restart, or a malformed
        # response. HTTPException is not an OSError and urllib does not always
        # wrap it, so it is listed explicitly.
        return False


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
