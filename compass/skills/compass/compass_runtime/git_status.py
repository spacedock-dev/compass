"""The end-of-session git probe: one bounded command, two scalars, no pathnames.

The committed-file read (`read_committed`) is the second command family here: four read-only
commands that return a few named files as a commit held them.

This is the only place in the runtime that runs a program inside a directory the
user chose, and `SECURITY.md`'s "Repository git reads (the end-of-session probe)"
section is the contract it implements. The bounds are
[DEC-3](SECURITY.md#repository-git-reads-the-end-of-session-probe)'s ruling (Linear
DRC-4122) as amended, not this module's preferences.

Why the argv is a constant and not built per call: all three safety flags are
independently load-bearing, and each disarms exactly one hazard that was measured.
The first two were re-measured 2026-08-28 at git 2.55.0 across four fresh
repositories, one probe each, from an identical racy-clean state; the third was
measured 2026-09-07 at git 2.55.0 with git-lfs 3.8.0:

- without `--no-optional-locks`, git rewrites `.git/index` to resolve a racy stat,
  which breaks the read-only posture the product states for everything it touches;
- without `-c core.fsmonitor=`, a `core.fsmonitor` script named by the inspected
  repository's own config executes under Compass's identity;
- without `-c core.hooksPath=/dev/null`, hashing a tracked path whose COMMITTED
  attributes name a filter driver lets that driver install its own hooks: four
  files at mode 0755 — post-checkout, post-commit, post-merge, pre-push — written
  inside a repository the probe was only meant to read. `.git/index` was untouched
  in that arm, so neither of the other two flags sees it.

Neither of the first two disarms the other's hazard, the third disarms one they
both miss, so none may be dropped and there is no fallback to a plain
`git status`. `tests/test_git_status.py` asserts all three against real
repositories, because these are properties of git rather than of this file.

What the third flag does NOT close, measured the same day: the filter driver still
RUNS. A repository whose `.git/config` names a clean filter had that command
executed by one probe. Only the hook installation is suppressed, because git-lfs
asks git where hooks belong and is answered with a path it cannot write. Arbitrary
filter execution needs `.git/config` rather than committed content, which is the
threat model `SECURITY.md` already accepts for `core.fsmonitor`, and that section
states the residual rather than this comment restating it.

`/dev/null` as a hooks path is measured on darwin only. It is a path git cannot
find a hook under on any supported platform, but the suppression itself was
observed here, and `tests/test_git_status.py` skips where the mechanism cannot be
armed rather than passing vacuously.

What leaves this module is `GitStatus` or `None`, and `None` means not probed
rather than clean. Porcelain names paths; those pathnames are counted and dropped
here, and no caller is ever given a way to reach them.
"""

from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
import threading
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

# Bound 1 of [DEC-3](SECURITY.md#repository-git-reads-the-end-of-session-probe), as amended. A
# tuple rather than a list so a caller cannot
# append to the argv it was handed.
#
# `GIT_STATUS_ARGV[0]` stays the bare name because it is what the contract prints
# and what the oracles compare. What actually spawns is `_executable()` below,
# resolved once against a PATH the probe controls: measured 2026-09-07, a bare
# name let ANY empty or relative PATH element before the first real `git` supply
# the binary, and it resolved from the session-supplied directory being probed.
GIT_STATUS_ARGV: Final[tuple[str, ...]] = (
    "git",
    "-c",
    "core.fsmonitor=",
    "-c",
    "core.hooksPath=/dev/null",
    "-c",
    "status.showUntrackedFiles=normal",
    "--no-optional-locks",
    "status",
    "--porcelain",
)


# Removed from the child's environment, not merely ignored by this module. Either
# one redirects git at a different repository entirely: measured 2026-09-07, a
# probe of a CLEAN repository published a dirty reading belonging to another one,
# and a directory that is not a repository at all published it too, so the
# `isdir` gate below does not help.
DETACHING_ENV: Final = ("GIT_DIR", "GIT_WORK_TREE")


def _rooted(part: str) -> bool:
    r"""True when no working directory can reinterpret `part`.

    Not `os.path.isabs`, which is not that property on Windows and is permissive
    in the direction this repository ships: measured 2026-09-08,
    `ntpath.isabs(r"\bin")` is True on 3.11.9 and 3.12.13 and False on 3.13.13,
    and the gate runs 3.11 and 3.12 (DRC-4469). A driveless root resolves against
    the process's current drive, which is part of its working directory.

    The drive test is Windows-only because `posixpath.splitdrive` never reports
    one, so requiring it everywhere would scrub every element. And this is the
    filter being narrower than its own claim rather than a second DRC-4454:
    Windows hands the resolved path to `CreateProcess` as `lpApplicationName`,
    which the CALLING process resolves, so parent and child cannot disagree.
    """
    if not os.path.isabs(part):
        return False
    return os.name != "nt" or bool(os.path.splitdrive(part)[0])


def probe_environment(environ: Mapping[str, str]) -> dict[str, str]:
    """The child's environment: the caller's, minus what detaches the reading.

    Kept public and separate so a test can assert the scrub without spawning
    anything, and so the two names above have exactly one place that drops them.

    Every non-absolute PATH element goes, not a named list of them. The named
    list is what this was, and it was wrong: `{"", "."}` reads like the whole of
    the property but a bare `relbin`, `./bin`, `..` and `sub/bin` all survived it
    (DRC-4454, measured 2026-09-07). Any element the resolver would resolve
    against a working directory is untrusted, because the working directory
    during a probe is the session's own and the child's is the directory being
    probed — which is how one relative element let the probed directory supply
    the program. `_rooted` rather than `os.path.isabs` is what makes that
    sentence true on Windows as well (DRC-4469).
    """
    scrubbed = {key: value for key, value in environ.items() if key not in DETACHING_ENV}
    path = scrubbed.get("PATH", "")
    if path:
        kept = [part for part in path.split(os.pathsep) if _rooted(part)]
        scrubbed["PATH"] = os.pathsep.join(kept)
    return scrubbed


def executable(name: str, environ: Mapping[str, str]) -> str | None:
    """Where the named program is, resolved once against the scrubbed PATH, or None.

    None means the same published thing as every other refusal in this module:
    not probed. `shutil.which` is given the scrubbed PATH explicitly rather than
    reading the ambient one, because the ambient one is what the hijack uses.

    `_rooted` is applied here AS WELL AS in the scrub, and the duplication is the
    point rather than an oversight: the scrub is one filter and that filter has
    already been wrong twice, so a future change to it cannot reopen the hijack
    while this end refuses too. This is also the end that holds if `which` is ever
    handed a PATH from anywhere but `probe_environment` — and on Windows `which`
    answers with a path built from the PATH element it matched, so a driveless
    root reaching it would otherwise be handed straight to the child.
    """
    resolved = shutil.which(name, path=environ.get("PATH"))
    if resolved is None or not _rooted(resolved):
        return None
    return resolved


def _executable(environ: Mapping[str, str]) -> str | None:
    """Where `git` is; `executable` with the name this module runs."""
    return executable("git", environ)


@dataclass(frozen=True)
class GitStatus:
    """What one probe observed. Frozen: a reading, not a mutable row field."""

    dirty: bool
    # Porcelain ENTRIES, not files. Git collapses an untracked directory into one
    # entry, so a new directory holding three files counts 1. Every rendering of
    # this number has to say entries, or it is a file count under a false name.
    changed: int


def probe(
    cwd: str,
    *,
    timeout_sec: float,
    runner: Callable[..., Any] = subprocess.run,
) -> GitStatus | None:
    """Run the one bounded command in `cwd`, or return None having run nothing.

    None is the whole of the disclosure for a row that was not probed, and it
    covers every cause: the directory is gone or is not a repository, git is not
    on PATH, the probe timed out, or git refused. `False` is never substituted for
    it — a confident clean over no evidence is the DRC-4101 failure, one field
    over.

    `stdin` is closed rather than inherited so that a repository configured to ask
    for a credential or an askpass answer cannot block the probe until its
    timeout; the timeout would catch it, but a probe that reliably burns its full
    budget is a probe that stalls its own worker.
    """
    if not os.path.isdir(cwd):
        return None
    environ = probe_environment(os.environ)
    resolved = _executable(environ)
    if resolved is None:
        return None
    try:
        result = runner(
            # The fixed argv above, with argv[0] replaced by the resolved absolute
            # path: no shell, no interpolation, nothing from the payload.
            #
            # The child's OUTPUT is not capped, and that is deferred rather than
            # overlooked: `subprocess.run` reads to EOF and takes no size limit, so
            # a cap means `Popen` plus a bounded read loop, and seven tests inject
            # through this `runner=` seam — two of them pinning `env`, `stdin` and
            # `timeout` as keyword arguments, so a rewrite has to preserve the
            # kwarg surface and not only the argv. What bounds the output today is
            # `timeout_sec` on how long git has to produce it, and `_reading`
            # counting one line at a time rather than materialising every line.
            (resolved, *GIT_STATUS_ARGV[1:]),
            cwd=cwd,
            capture_output=True,
            stdin=subprocess.DEVNULL,
            timeout=timeout_sec,
            check=False,
            env=environ,
        )
    except (OSError, ValueError, subprocess.SubprocessError):
        # OSError covers git absent from PATH and a cwd that vanished between the
        # isdir check and the spawn; SubprocessError covers the timeout. Caught as
        # one because every one of them means the same published thing: not probed.
        return None
    if getattr(result, "returncode", 1) != 0:
        # Not a repository, or a repository this process may not read. stderr is
        # deliberately not read, logged or returned: it quotes pathnames.
        return None
    return _reading(getattr(result, "stdout", b""))


# What the pull request read needs of a session's folder: the commit it is on and where its own
# `origin` points. Read-only plumbing with the same flags as the status probe that matter here,
# because the hazards are the same program run in the same inspected directory. The remote URL can
# carry a credential (`https://user:token@host/...`), so it is parsed here and only host and
# repository leave this module; the raw string is never returned, logged or stored.
HEAD_ARGV: Final[tuple[str, ...]] = (
    "git",
    "-c",
    "core.fsmonitor=",
    "-c",
    "core.hooksPath=/dev/null",
    "--no-optional-locks",
    "rev-parse",
    "--verify",
    "--quiet",
    "HEAD",
)
REMOTE_ARGV: Final[tuple[str, ...]] = (
    "git",
    "-c",
    "core.fsmonitor=",
    "-c",
    "core.hooksPath=/dev/null",
    "--no-optional-locks",
    "config",
    "--get",
    "remote.origin.url",
)
_HEAD_RE = re.compile(r"[0-9a-f]{40}")
_REMOTE_FORMS = (
    re.compile(r"https://(?:[^/@\s]+@)?(?P<host>[A-Za-z0-9.-]+)(?::\d+)?/(?P<repo>[^\s?#]+)"),
    re.compile(r"ssh://(?:[^/@\s]+@)?(?P<host>[A-Za-z0-9.-]+)(?::\d+)?/(?P<repo>[^\s?#]+)"),
    re.compile(r"(?:[^/@\s]+@)?(?P<host>[A-Za-z0-9.-]+):(?P<repo>[^\s?#/][^\s?#]*)"),
)


@dataclass(frozen=True)
class GitIdentity:
    """The commit a folder is on, and the host and repository its `origin` names (maybe empty)."""

    head: str
    host: str
    repository: str


def parse_remote(url: str) -> tuple[str, str]:
    """`(host, "owner/repo")` from an `origin` URL, or two empty strings.

    The user part, any port, a trailing `.git` and everything past the repository are dropped.
    A URL with more or fewer than two path parts names no repository this module will hand on.
    """
    for form in _REMOTE_FORMS:
        matched = form.fullmatch(url.strip())
        if matched is None:
            continue
        parts = matched["repo"].removesuffix("/").removesuffix(".git").split("/")
        if len(parts) == 2 and all(parts):
            return matched["host"].lower(), f"{parts[0]}/{parts[1]}"
    return "", ""


def _read_regular(path: str, limit: int = 1024) -> str | None:
    """The first `limit` bytes of a regular file, or None for anything else or on any error.

    A named pipe, a device or a socket planted where a git file belongs would block a plain
    `open` for ever and the thread collecting a board with it, so the type is checked first and
    the file is opened without waiting, then checked again on the descriptor it gave.
    """
    try:
        if not stat.S_ISREG(os.lstat(path).st_mode):
            return None
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0))
    except OSError:
        return None
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            return None
        return os.read(descriptor, limit).decode("utf-8", "replace").strip()
    except OSError:
        return None
    finally:
        os.close(descriptor)


def _gitdir_of(dot_git: str) -> tuple[str, str] | None:
    """The git directory and the common directory a `.git` entry stands for, or None.

    A linked worktree's `.git` is a one-line file naming its own directory, whose `commondir`
    file names the repository's, where the shared `config` and so the remotes live.
    """
    if os.path.isdir(dot_git):
        return dot_git, dot_git
    line = _read_regular(dot_git)
    if line is None or not line.startswith("gitdir:"):
        return None
    base = os.path.dirname(dot_git)
    gitdir = os.path.normpath(os.path.join(base, line[len("gitdir:") :].strip()))
    common = _read_regular(os.path.join(gitdir, "commondir"))
    if common is None:
        return gitdir, gitdir
    return gitdir, os.path.normpath(os.path.join(gitdir, common))


def remote_stamp(folder: str) -> tuple[Any, ...] | None:
    """What a cached `origin` reading of `folder` is keyed on, or None where it cannot be.

    The stat of the repository's `HEAD` and of the `config` that names its remotes, found by
    walking up to the nearest `.git`, a linked worktree's included. It reads two stats and one
    short file and runs no program. A global or included config can also move a remote, which
    this does not see: a reading is then stale until one of those two files moves, which is the
    price of starting no git for a folder that has not changed.
    """
    current = os.path.abspath(folder)
    while True:
        found = _gitdir_of(os.path.join(current, ".git"))
        if found is not None:
            break
        parent = os.path.dirname(current)
        if parent == current:
            return None
        current = parent
    stats: list[tuple[int, int, int]] = []
    for path in (os.path.join(found[0], "HEAD"), os.path.join(found[1], "config")):
        try:
            seen = os.stat(path)
        except OSError:
            return None
        # The inode is in the stamp because a same-size rewrite inside one clock tick keeps the
        # other two; an editor or `git config` that replaces the file gets a new one.
        stats.append((seen.st_mtime_ns, seen.st_size, seen.st_ino))
    return (found, *stats)


# Folders with a poll are the session folders plus the few a call `cd`s into, so a few hundred
# only bounds a process that runs for weeks.
STAMP_CACHE_ENTRIES: Final = 256


class StampCache:
    """Readings of a folder's `origin`, each kept while `remote_stamp` of its folder is unchanged.

    Held on `RuntimeState`. It lives here, and not with the reader that fills it, because the
    state module is imported by the one that reads.
    """

    def __init__(self, limit: int = STAMP_CACHE_ENTRIES) -> None:
        self._limit = max(1, limit)
        self._lock = threading.Lock()
        self._held: dict[str, tuple[tuple[Any, ...], tuple[str, str]]] = {}

    def get(self, folder: str, stamp: tuple[Any, ...]) -> tuple[str, str] | None:
        with self._lock:
            held = self._held.get(folder)
        return held[1] if held is not None and held[0] == stamp else None

    def put(self, folder: str, stamp: tuple[Any, ...], remote: tuple[str, str]) -> None:
        with self._lock:
            if folder not in self._held and len(self._held) >= self._limit:
                self._held.pop(next(iter(self._held)))
            self._held[folder] = (stamp, remote)


def identity(
    cwd: str,
    *,
    timeout_sec: float,
    runner: Callable[..., Any] = subprocess.run,
) -> GitIdentity | None:
    """HEAD and the parsed `origin` of the repository at `cwd`, or None having run nothing.

    None covers every cause the status probe's None does. A folder that is a repository with no
    `origin` still answers, with an empty host and repository, so the caller can tell a folder it
    cannot place from one it could not read.
    """
    if not os.path.isdir(cwd):
        return None
    environ = probe_environment(os.environ)
    resolved = _executable(environ)
    if resolved is None:
        return None

    def run(argv: tuple[str, ...]) -> str | None:
        try:
            result = runner(
                (resolved, *argv[1:]),
                cwd=cwd,
                capture_output=True,
                stdin=subprocess.DEVNULL,
                timeout=timeout_sec,
                check=False,
                env=environ,
            )
        except (OSError, ValueError, subprocess.SubprocessError):
            return None
        raw = getattr(result, "stdout", b"")
        if getattr(result, "returncode", 1) != 0 or not isinstance(raw, (bytes, bytearray)):
            return None
        # Capped before decoding: a remote URL is one short line, and anything longer is not one.
        return bytes(raw[:2048]).decode("utf-8", "replace").strip()

    head = run(HEAD_ARGV)
    if head is None or _HEAD_RE.fullmatch(head) is None:
        return None
    # An absent `origin` is exit 1 with no output, which `run` reports as None: the head stands.
    host, repository = parse_remote(run(REMOTE_ARGV) or "")
    return GitIdentity(head, host, repository)


# Whether a commit is in the history of the folder's own commit: how a merged pull request's checks
# reach a session whose folder has moved on past the pull request's head. Plumbing with the same
# flags as the two reads above; both commits are 40-hex ids checked before any process starts, so
# no option or revision expression can be smuggled in.
_ANCESTOR_ARGV: Final[tuple[str, ...]] = (
    "git",
    "-c",
    "core.fsmonitor=",
    "-c",
    "core.hooksPath=/dev/null",
    "--no-optional-locks",
    "merge-base",
    "--is-ancestor",
)


def is_ancestor(
    cwd: str,
    commit: str,
    head: str,
    *,
    timeout_sec: float,
    runner: Callable[..., Any] = subprocess.run,
) -> bool:
    """Whether `commit` is `head` or an ancestor of it in the repository at `cwd`.

    False for anything else, including a commit the folder does not have and every failure:
    `merge-base --is-ancestor` exits 0 for yes and 1 for no, and only a 0 is an answer.
    """
    if not (_HEAD_RE.fullmatch(commit) and _HEAD_RE.fullmatch(head)) or not os.path.isdir(cwd):
        return False
    if commit == head:
        return True
    environ = probe_environment(os.environ)
    resolved = _executable(environ)
    if resolved is None:
        return False
    try:
        result = runner(
            (resolved, *_ANCESTOR_ARGV[1:], commit, head),
            cwd=cwd,
            capture_output=True,
            stdin=subprocess.DEVNULL,
            timeout=timeout_sec,
            check=False,
            env=environ,
        )
    except (OSError, ValueError, subprocess.SubprocessError):
        return False
    return getattr(result, "returncode", 1) == 0


def _reading(stdout: object) -> GitStatus:
    """Count porcelain entries. The only thing that ever looks at the output."""
    if isinstance(stdout, str):
        raw = stdout.encode("utf-8", "replace")
    elif isinstance(stdout, (bytes, bytearray)):
        raw = bytes(stdout)
    else:
        raw = b""
    # One entry per line. Counted rather than parsed, because the parse would have
    # to hold pathnames and nothing published needs them.
    #
    # One line at a time rather than `raw.split(b"\n")`: re-measured with
    # tracemalloc at N=20000 on Python 3.12.13, the split allocates a flat ~41 B
    # per entry ON TOP OF each line's own bytes — 1.69 MB beside an 880 KB output
    # at a 43-byte porcelain line, and 1.20x to 5.07x the output as path length
    # falls from 204 characters to 9, so there is no single multiple to quote.
    # This loop's own peak is one line (271 B in that arm), and pathnames still
    # reach nothing but `strip`.
    entries = 0
    start = 0
    size = len(raw)
    while start < size:
        stop = raw.find(b"\n", start)
        if stop < 0:
            stop = size
        if raw[start:stop].strip():
            entries += 1
        start = stop + 1
    return GitStatus(dirty=entries > 0, changed=entries)


# The committed-file read: a second command family beside the status probe, for the one reader that
# needs a file as a commit held it, a project's own check scripts. The ruling:
# [DEC-29](docs/design-reading-a-session.md#dec-29-a-commands-result-is-evidence-by-tier-and-a-command-that-cannot-fail-never-passes)  # noqa: E501
# Same resolved executable and scrubbed environment as `probe`, with the two of its three flags
# that matter to commands that never touch the work tree or the index. Every argument is a
# constant, an object id this module validated as hex, or a name the caller passed that matched
# a closed pattern: nothing session-supplied is interpolated.
_SAFE_READ: Final[tuple[str, ...]] = (
    "-c",
    "core.fsmonitor=",
    "-c",
    "core.hooksPath=/dev/null",
    "--no-optional-locks",
)
_OBJECT_ID = re.compile(r"[0-9a-f]{40}(?:[0-9a-f]{24})?")
_TREE_ENTRY = re.compile(rb"^(\d{6}) (\w+) ([0-9a-f]+) +(\d+|-)\t(.+)$", re.DOTALL)
_PATH_NAME = re.compile(r"[A-Za-z0-9._-]{1,64}")
# The least a repository can be asked to name: a regular file (100644 or 100755).
_REGULAR_MODES: Final = frozenset({"100644", "100755"})


@dataclass(frozen=True)
class CommittedEntry:
    """One named file as a commit holds it. `content` is None unless it was read."""

    name: str
    mode: str
    size: int
    content: bytes | None = None


@dataclass(frozen=True)
class CommittedFiles:
    """The toplevel of a work tree, the commit read, and the named files that commit holds."""

    toplevel: str
    commit: str
    entries: tuple[CommittedEntry, ...]


def _read(
    args: tuple[str, ...],
    cwd: str,
    environ: Mapping[str, str],
    resolved: str,
    *,
    deadline: float,
    runner: Callable[..., Any],
) -> bytes | None:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        return None
    try:
        result = runner(
            (resolved, *_SAFE_READ, *args),
            cwd=cwd,
            capture_output=True,
            stdin=subprocess.DEVNULL,
            timeout=remaining,
            check=False,
            env=dict(environ),
        )
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    if getattr(result, "returncode", 1) != 0:
        return None
    out = getattr(result, "stdout", b"")
    return bytes(out) if isinstance(out, (bytes, bytearray)) else None


def read_committed(
    cwd: str,
    at: float,
    names: tuple[str, ...],
    *,
    max_bytes: int,
    timeout_sec: float,
    runner: Callable[..., Any] = subprocess.run,
) -> CommittedFiles | None:
    """The named files at the toplevel of `cwd`'s work tree, as the commit HEAD named at time `at`.

    None means nothing was read: not a repository, git absent, a deadline passed, or no commit
    that old. The commit is the newest first-parent commit of HEAD whose commit date is at or
    before `at`, because Compass does not record the commit a session began on (the transcript
    carries a branch name at most). A commit the session made after `at` is therefore never the
    base. A file whose blob is over `max_bytes` is listed with no content; a mode other than a
    regular file (a link, a submodule) is listed with no content either, so the caller can say why
    it read nothing.

    Measured 2026-10-27 at git 2.x: `--before=<digits>` is not a timestamp (it matched a commit
    newer than the bound), so the bound is written as an ISO date in UTC.
    """
    if not os.path.isdir(cwd) or any(_PATH_NAME.fullmatch(name) is None for name in names):
        return None
    # A replace ref can point a blob at another one while `git status` still reads the file as
    # modified, so none of the four reads honours one.
    environ = {**probe_environment(os.environ), "GIT_NO_REPLACE_OBJECTS": "1"}
    resolved = _executable(environ)
    if resolved is None:
        return None
    deadline = time.monotonic() + timeout_sec

    def run(args: tuple[str, ...], where: str) -> bytes | None:
        return _read(args, where, environ, resolved, deadline=deadline, runner=runner)

    top = run(("rev-parse", "--show-toplevel"), cwd)
    toplevel = top.decode("utf-8", "replace").strip() if top else ""
    if not toplevel or not os.path.isdir(toplevel):
        return None
    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(max(at, 0.0)))
    found = run(("rev-list", "-1", "--first-parent", f"--before={stamp}", "HEAD"), toplevel)
    commit = found.decode("ascii", "replace").strip() if found else ""
    if _OBJECT_ID.fullmatch(commit) is None:
        return None
    listing = run(("ls-tree", "-l", "-z", commit, "--", *names), toplevel)
    if listing is None:
        return None
    entries: list[CommittedEntry] = []
    for raw in listing.split(b"\0"):
        match = _TREE_ENTRY.match(raw)
        if match is None:
            continue
        mode, kind, oid = match[1].decode(), match[2], match[3].decode()
        size = int(match[4]) if match[4] != b"-" else 0
        name = match[5].decode("utf-8", "replace")
        content = None
        if (
            kind == b"blob"
            and mode in _REGULAR_MODES
            and size <= max_bytes
            and _OBJECT_ID.fullmatch(oid)
        ):
            content = run(("cat-file", "blob", oid), toplevel)
        entries.append(CommittedEntry(name, mode, size, content))
    return CommittedFiles(toplevel, commit, tuple(entries))
