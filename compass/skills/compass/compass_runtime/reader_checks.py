"""Check commands a reader lists for a project, in a file under the Compass home.

A reader whose project's check is something no rule finds (a custom script, `bazel test //...`)
says so here, and a session's command that matches a listed one reads as a tier 2 check
([DEC-29](docs/design-reading-a-session.md#dec-29-a-commands-result-is-evidence-by-tier-and-a-command-that-cannot-fail-never-passes)).

The file is the reader's, in the Compass home (`COMPASS_HOME`), and nothing is ever read from a
`.compass` folder inside a repository: a repository's files are the agent's to write, and a
listing is what makes the agent's own command count as evidence. A session that writes this file
withdraws the listing for that session (`project_context`).

Read as the other Compass stores are: to a cap, and a file that will not parse is discarded and
never repaired, since it is the reader's. Which entries may count is decided by the command
reader in `project_context`, handed in as `refuse`, so this module holds no rule about commands.
"""

from __future__ import annotations

import json
import os
import re
import stat
from typing import TYPE_CHECKING, Any, Final, NamedTuple

from compass_runtime import sessions

if TYPE_CHECKING:
    from collections.abc import Callable

    from compass_runtime.config import RuntimeConfig

FILENAME: Final = "compass-project-checks.json"
MAX_FILE_BYTES: Final = 64 * 1024
MAX_PROJECTS: Final = 64
MAX_COMMANDS: Final = 32
MAX_COMMAND_CHARS: Final = 512
MAX_KEY_CHARS: Final = 512
MAX_IGNORED: Final = 64
_PROGRAM_CHARS: Final = 32

UNREADABLE_REASON: Final = "could not be parsed"
SIZE_REASON: Final = "over the byte cap"
NOT_REGULAR_REASON: Final = "not a regular file"
SHAPE_REASON: Final = "is not an object of project names and lists of commands"
BUILTIN_REASON: Final = "is a shell builtin, so it is never a check"
CANNOT_FAIL_REASON: Final = "cannot fail, so it is never a check"
READ_ONLY_REASON: Final = "only reads, so it is never a check"
NOT_ONE_COMMAND_REASON: Final = "is not one plain command"
WRITES_REASON: Final = "changes files, so it is never a check"
LENGTH_REASON: Final = "is over the length cap"
COUNT_REASON: Final = "is over the count cap for its project"
NOT_TEXT_REASON: Final = "is not text"

# What `refuse` answers for one entry: the reason it cannot count ("" when it can) and the program
# it names, which is all `--diagnose` prints of it.
Refusal = tuple[str, str]


class Ignored(NamedTuple):
    project: str
    program: str
    reason: str


class Stored(NamedTuple):
    """What the file held, by the project the reader wrote, and why not if it failed."""

    projects: dict[str, list[Any]]
    error: str | None
    dropped: int = 0


def store_path(config: RuntimeConfig) -> str:
    """Beside the other stores, outside any repository."""
    return os.path.join(config.state_home, FILENAME)


class _Refused(Exception):  # noqa: N818 - a closed reason, not an error the caller reports
    pass


def _read(path: str) -> bytes | None:
    """The file's bytes, None where it is absent, or `_Refused` with why it cannot be used."""
    try:
        # `stat` follows a link: a reader who keeps dotfiles under version control links this file,
        # and it is theirs. A repository's `.compass` is never asked for, so a link there is not
        # reached.
        before = os.stat(path)
    except FileNotFoundError:
        return None
    except OSError:
        raise _Refused(NOT_REGULAR_REASON) from None
    if not stat.S_ISREG(before.st_mode):
        raise _Refused(NOT_REGULAR_REASON)
    if before.st_size > MAX_FILE_BYTES:
        raise _Refused(SIZE_REASON)
    flags = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_CLOEXEC", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError:
        raise _Refused(NOT_REGULAR_REASON) from None
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise _Refused(NOT_REGULAR_REASON)
        data = os.read(descriptor, MAX_FILE_BYTES + 1)
    except OSError:
        raise _Refused(NOT_REGULAR_REASON) from None
    finally:
        os.close(descriptor)
    if len(data) > MAX_FILE_BYTES:
        raise _Refused(SIZE_REASON)
    return data


def read_store(config: RuntimeConfig) -> Stored:
    """The file's projects, or none and the reason. An absent file is not an error."""
    try:
        data = _read(store_path(config))
    except _Refused as refusal:
        return Stored({}, str(refusal))
    if data is None:
        return Stored({}, None)
    try:
        document = json.loads(data)
    except (ValueError, RecursionError):
        return Stored({}, UNREADABLE_REASON)
    projects = document.get("projects") if isinstance(document, dict) else None
    if not isinstance(projects, dict) or not all(
        isinstance(key, str) and isinstance(commands, list) for key, commands in projects.items()
    ):
        return Stored({}, SHAPE_REASON)
    kept = dict(list(projects.items())[:MAX_PROJECTS])
    return Stored(kept, None, len(projects) - len(kept))


_BARE_PROGRAM = re.compile(r"[A-Za-z0-9_.+:\[-]+")
_ASSIGNMENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=")


def published_program(word: str) -> str:
    """The one word `--diagnose` may print of an entry: a bare program name, else nothing.

    A leading `NAME=value` is an argument that can hold a credential, and a path can name one,
    so neither is published: a path is reduced to its program and anything else to nothing.
    """
    if "=" in word:
        return ""
    base = os.path.basename(word)
    return base[:_PROGRAM_CHARS] if _BARE_PROGRAM.fullmatch(base) else ""


def program_of(words: list[str] | tuple[str, ...]) -> str:
    """`published_program` of the first word that is not an assignment."""
    for word in words:
        if not _ASSIGNMENT.match(word):
            return published_program(word)
    return ""


def _program(entry: str) -> str:
    return program_of(entry.split(None, 16))


def _vetted(
    project: str, commands: list[Any], refuse: Callable[[str], Refusal]
) -> tuple[list[str], list[Ignored]]:
    accepted: list[str] = []
    ignored: list[Ignored] = []
    for entry in commands:
        if not isinstance(entry, str) or not entry.strip():
            ignored.append(Ignored(project, "", NOT_TEXT_REASON))
        elif len(entry) > MAX_COMMAND_CHARS:
            ignored.append(Ignored(project, _program(entry), LENGTH_REASON))
        else:
            reason, program = refuse(entry)
            if reason:
                ignored.append(Ignored(project, program, reason))
            elif len(accepted) < MAX_COMMANDS:
                accepted.append(entry.strip())
            else:
                ignored.append(Ignored(project, program, COUNT_REASON))
    return accepted, ignored


def _names(config: RuntimeConfig, key: str, root: str, identity: str) -> bool:
    """Whether a key the reader wrote names this project: its published key, or its folder."""
    if key == identity:
        return True
    expanded = key
    if key == "~" or key.startswith(("~/", "~\\")):
        expanded = os.path.join(config.home, key[2:])
    if not os.path.isabs(expanded):
        return False
    try:
        return os.path.normcase(os.path.realpath(expanded)) == os.path.normcase(root)
    except (OSError, ValueError):
        return False


def for_project(
    config: RuntimeConfig, began_in: str, refuse: Callable[[str], Refusal]
) -> tuple[str, ...]:
    """The commands the reader listed for the project a session began in, that may count."""
    if not began_in or not os.path.isabs(began_in):
        return ()
    stored = read_store(config)
    if not stored.projects:
        return ()
    root = sessions.project_root(began_in)
    identity = sessions.project_identity(config, began_in).get("key", "")
    if root is None:
        return ()
    found: list[str] = []
    for key, commands in stored.projects.items():
        if len(key) <= MAX_KEY_CHARS and _names(config, key, root, identity):
            found.extend(_vetted(key, commands, refuse)[0])
    return tuple(dict.fromkeys(found))


def report(config: RuntimeConfig, refuse: Callable[[str], Refusal]) -> dict[str, Any]:
    """What `--diagnose` says: the path, a read failure, and each entry that was ignored."""
    stored = read_store(config)
    listed = 0
    ignored: list[Ignored] = []
    for key, commands in stored.projects.items():
        accepted, skipped = _vetted(key[:MAX_KEY_CHARS], commands, refuse)
        listed += len(accepted)
        ignored.extend(skipped)
    return {
        "path": store_path(config),
        "error": stored.error,
        "projects": len(stored.projects),
        "projects_dropped": stored.dropped,
        "listed": listed,
        # A program and a reason only: never a project's path or an entry's arguments.
        "ignored": [
            {"program": item.program, "reason": item.reason} for item in ignored[:MAX_IGNORED]
        ],
        "ignored_more": max(0, len(ignored) - MAX_IGNORED),
    }
