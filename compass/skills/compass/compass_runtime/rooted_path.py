"""Which program a PATH lookup may start: only one no working directory can reinterpret.

A standard-library leaf. Every command Compass starts by name runs with a working directory
that is often a repository Compass does not trust (a git probe, a Spacedock discovery), or from
a daemon whose own working directory nobody chose. A relative, empty or `.` PATH element
resolves against that directory, so the repository could supply the program.

The rule was first written in `git_status` (DRC-4454, DRC-4469) and restated in `observer`;
it lives here so the two, `project_context`, `focus` and `interaction_prototype` hold one copy.
`launch.py` keeps its own restatement, because it must parse on Python 3.6 and runs before the
version check, so it cannot import this package.
"""

from __future__ import annotations

import os
import shutil
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

# Windows' `CreateProcess` and `cmd` search the current directory before PATH unless this is
# set, and Python 3.12+ `shutil.which` consults the same switch. A child started with a scrubbed
# PATH would otherwise still find a program in the repository it was started in.
NO_CURRENT_DIRECTORY: Final = "NoDefaultCurrentDirectoryInExePath"


def rooted(part: str) -> bool:
    r"""True when no working directory can reinterpret `part`.

    Not `os.path.isabs`, which is not that property on Windows: measured 2026-09-08,
    `ntpath.isabs(r"\bin")` is True on 3.11.9 and 3.12.13 and False on 3.13.13, and the floor
    is 3.12. A driveless root resolves against the process's current drive, which is part of its
    working directory. The drive test is Windows-only because `posixpath.splitdrive` never
    reports one.
    """
    if not os.path.isabs(part):
        return False
    return os.name != "nt" or bool(os.path.splitdrive(part)[0])


def search_path(path: str) -> str:
    """`path` with every element that is not rooted removed, order kept.

    Every such element goes, not a named list of them: `{"", "."}` was the list once, and a
    bare `relbin`, `./bin` and `..` all survived it (DRC-4454).
    """
    return os.pathsep.join(part for part in path.split(os.pathsep) if rooted(part))


def child_environment(environ: Mapping[str, str]) -> dict[str, str]:
    """A child's environment: the caller's, with PATH scrubbed and the current directory off."""
    child = dict(environ)
    if "PATH" in child:
        child["PATH"] = search_path(child["PATH"])
    child[NO_CURRENT_DIRECTORY] = "1"
    return child


def default_path() -> str:
    """The PATH `shutil.which` searches when none is set: `CS_PATH`, else `os.defpath`."""
    try:
        return os.confstr("CS_PATH") or ""
    except (AttributeError, ValueError):
        return os.defpath


def _windows_lookup(name: str, path: str, pathext: str) -> str | None:
    """The first rooted PATH element holding `name` as a program, walked by hand.

    Windows `shutil.which` looks in the current folder first: always before 3.12, and from 3.12
    unless this process's own environment sets `NO_CURRENT_DIRECTORY`. A planted `.\\uv.exe`
    then answered first, was refused as unrooted, and hid the real `uv` later on PATH. The
    extensions are PATHEXT's, in its order, unless `name` already carries one of them.
    """
    if os.path.dirname(name):
        return None
    extensions = [ext for ext in (pathext or ".COM;.EXE;.BAT;.CMD").split(os.pathsep) if ext]
    has_extension = any(name.lower().endswith(ext.lower()) for ext in extensions)
    names = [name] if has_extension else [name + ext for ext in extensions]
    for directory in path.split(os.pathsep):
        if not rooted(directory):
            continue
        for candidate in (os.path.join(directory, each) for each in names):
            if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                return candidate
    return None


def executable(name: str, environ: Mapping[str, str]) -> str | None:
    """Where the named program is, on the rooted elements of `environ`'s PATH, or None.

    POSIX asks `shutil.which` at call time (so a test that patches it reaches this), which
    never looks in the current folder for a PATH without relative elements. Windows walks the
    elements by hand, because its `which` does (`_windows_lookup`). Either answer is held to
    `rooted` as well as the PATH it was searched on.
    """
    path = environ.get("PATH")
    search = search_path(default_path() if path is None else path)
    if os.name == "nt":
        resolved = _windows_lookup(name, search, environ.get("PATHEXT", ""))
    else:
        resolved = shutil.which(name, path=search)
    if resolved is None or not rooted(resolved):
        return None
    return resolved


def which(name: str) -> str | None:
    """`executable` against this process's environment as it is now.

    The signature of `shutil.which` with one argument, so it can stand where a module took
    `binary_resolver=shutil.which`.
    """
    return executable(name, os.environ)


def prepared(argv: Sequence[str]) -> tuple[list[str], dict[str, str]]:
    """`argv` with its program resolved by `which`, and the child environment to start it with.

    A program no rooted element holds raises `FileNotFoundError`, the error `subprocess.run`
    raises for a program that is not installed, so a caller's existing handling of a missing
    program covers it. The caller starts the process itself, so the module that launches is
    still the one the launch table names.
    """
    program = which(argv[0])
    if program is None:
        raise FileNotFoundError(argv[0])
    return [program, *argv[1:]], child_environment(os.environ)
