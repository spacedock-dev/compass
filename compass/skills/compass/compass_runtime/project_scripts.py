"""A project's own check scripts, read as the commit a session began on held them.

`pnpm typecheck` or `make test` is a check only when the script behind it is one. The file that
declares the script (`package.json`, a Makefile, a justfile) is something the agent can write, so
this module reads it only where it cannot have been changed by the session:

- from the git object database, at the newest commit of HEAD that is no newer than the session's
  first recorded time, never from the working tree alone. Compass does not record the commit a
  session began on, so this is the stand-in; a commit the session made later is never the base;
- only at the toplevel of the work tree the session began in;
- and only while the working-tree file is a regular file whose bytes equal that commit's. A
  session that edited the file, by any tool or by a shell command, leaves it different, so it
  declares nothing. A file the session wrote and then restored is caught by the recorded write
  (`project_context`), which the byte comparison cannot see.

Every bound is a constant here and not a setting: one file at most `MAX_FILE_BYTES`, at most
`MAX_SCRIPTS` declarations, at most `len(DECLARING_FILES)` files, one `GIT_TIMEOUT_SEC` deadline for
all of git. A symlink, a FIFO, a file over the cap, one that will not parse, or one that uses
syntax this reader does not follow adds nothing, and `problems()` says so for `--diagnose`.

Workflow `run:` steps are out of scope: no YAML parser ships with Compass.

Nothing read here leaves the machine. Only a session's own command line, matched against these
declarations, is ever published, as any check's line is; the scripts' bodies never are
([DEC-31](docs/design-reading-a-session.md#dec-31-the-text-of-a-command-that-is-not-a-check-may-leave-the-machine-by-vendor)).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Final

from compass_runtime import git_status

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

DECLARING_FILES: Final = (
    "package.json",
    "GNUmakefile",
    "makefile",
    "Makefile",
    "justfile",
    "Justfile",
    ".justfile",
)
MAX_FILE_BYTES: Final = 256 * 1024
MAX_SCRIPTS: Final = 500
MAX_LINES: Final = 5000
MAX_BODY_CHARS: Final = 4096
# One line of a Makefile or justfile, before or after its continuations are joined. Without it a
# single long whitespace line is the input a backtracking pattern spends minutes on.
MAX_LINE_CHARS: Final = 4096
GIT_TIMEOUT_SEC: Final = 5.0
# A load is reused this long. The base commit and the file's bytes change on a human's time scale,
# and every collect asks again.
CACHE_SECONDS: Final = 30.0
_CACHE_ENTRIES: Final = 32
_PROBLEMS_MAX: Final = 64

SIZE_REASON: Final = "over the byte cap"
LINK_REASON: Final = "a symlink, not a regular file"
SPECIAL_REASON: Final = "not a regular file"
MISSING_REASON: Final = "missing from the work tree"
EDITED_REASON: Final = "differs from the commit the session began on"
PARSE_REASON: Final = "could not be parsed"
FEATURE_REASON: Final = "uses syntax this reader does not follow"
COUNT_REASON: Final = "declares too many scripts"
LINE_REASON: Final = "has a line over the length cap"


@dataclass(frozen=True)
class Script:
    """One declared script: its command lines, and the declared scripts it needs first."""

    lines: tuple[str, ...]
    needs: tuple[str, ...] = ()


@dataclass
class Declarations:
    """The scripts each declaring file held at the base commit, by kind."""

    toplevel: str
    commit: str
    package: Mapping[str, Script]
    make: Mapping[str, Script]
    just: Mapping[str, Script]
    skipped: tuple[tuple[str, str], ...] = ()
    # Names of the declaring files that were read and trusted, so a recorded write can say which
    # declarations to withdraw.
    files: frozenset[str] = frozenset()
    real_toplevel: str = ""
    # A digest of each trusted file's committed bytes, so a cached load can be checked against the
    # work tree again without asking git.
    digests: Mapping[str, bytes] = field(default_factory=dict, repr=False, compare=False)
    memo: dict[Any, bool] = field(default_factory=dict, repr=False, compare=False)

    def at(self, directory: str) -> bool:
        """Whether `directory` is the toplevel itself, and not a folder under it."""
        if not directory:
            return False
        try:
            return os.path.realpath(directory) == self.real_toplevel
        except (OSError, ValueError):
            return False

    def without(self, written: frozenset[str]) -> Declarations:
        """These declarations less every kind whose declaring file the session wrote."""
        gone = {_kind(name) for name in written if name in DECLARING_FILES}
        if not gone & {"package", "make", "just"}:
            return self
        empty: dict[str, Script] = {}
        return Declarations(
            self.toplevel,
            self.commit,
            empty if "package" in gone else self.package,
            empty if "make" in gone else self.make,
            empty if "just" in gone else self.just,
            self.skipped,
            self.files - written,
            self.real_toplevel,
            self.digests,
        )

    def kind(self, kind: str) -> Mapping[str, Script]:
        return {"package": self.package, "make": self.make, "just": self.just}[kind]


_lock = threading.Lock()
_cache: OrderedDict[tuple[str, int], tuple[float, Declarations | None]] = OrderedDict()
_problems: OrderedDict[tuple[str, str], str] = OrderedDict()


def problems() -> list[dict[str, str]]:
    """Each declaring file this process skipped, with why, for `--diagnose`. No file content."""
    with _lock:
        return [
            {"file": os.path.join(top, name), "reason": reason}
            for (top, name), reason in _problems.items()
        ]


def reset() -> None:
    """Forget every cached load and every noted problem (tests)."""
    with _lock:
        _cache.clear()
        _problems.clear()


def _note(toplevel: str, name: str, reason: str) -> None:
    with _lock:
        _problems[(toplevel, name)] = reason
        _problems.move_to_end((toplevel, name))
        while len(_problems) > _PROBLEMS_MAX:
            _problems.popitem(last=False)


def load(
    session_dir: str,
    at: float,
    *,
    runner: Callable[..., Any] = subprocess.run,
    now: Callable[[], float] = time.monotonic,
) -> Declarations | None:
    """The trusted declarations for the work tree `session_dir` is in, or None."""
    if not session_dir or not os.path.isabs(session_dir):
        return None
    key = (session_dir, int(at))
    with _lock:
        held = _cache.get(key)
        fresh = held is not None and now() - held[0] < CACHE_SECONDS
        if fresh and held is not None:
            _cache.move_to_end(key)
    if fresh and held is not None and (held[1] is None or _still_committed(held[1])):
        return held[1]
    loaded = _load(session_dir, at, runner)
    with _lock:
        _cache[key] = (now(), loaded)
        _cache.move_to_end(key)
        while len(_cache) > _CACHE_ENTRIES:
            _cache.popitem(last=False)
    return loaded


def _still_committed(held: Declarations) -> bool:
    """Whether every trusted file in the work tree still holds the bytes it was trusted with.

    The cache outlives a shell edit by up to `CACHE_SECONDS` otherwise, and a declaration read in
    that window would be one the session wrote. No git run is needed: the digests are held.
    """
    for name, digest in held.digests.items():
        working, reason = _working_bytes(os.path.join(held.toplevel, name))
        if reason is not None or working is None or hashlib.sha256(working).digest() != digest:
            return False
    return True


def _load(session_dir: str, at: float, runner: Callable[..., Any]) -> Declarations | None:
    committed = git_status.read_committed(
        session_dir,
        at,
        DECLARING_FILES,
        max_bytes=MAX_FILE_BYTES,
        timeout_sec=GIT_TIMEOUT_SEC,
        runner=runner,
    )
    if committed is None:
        return None
    top = committed.toplevel
    by_kind: dict[str, dict[str, Script]] = {"package": {}, "make": {}, "just": {}}
    skipped: list[tuple[str, str]] = []
    trusted: set[str] = set()
    digests: dict[str, bytes] = {}
    for entry in committed.entries:
        reason = _unusable(entry, top)
        parsed: dict[str, Script] | None = None
        if reason is None:
            assert entry.content is not None  # noqa: S101 - `_unusable` returned None only then
            parsed, reason = _parse(entry.name, entry.content)
        if reason is not None or parsed is None:
            skipped.append((entry.name, reason or PARSE_REASON))
            _note(top, entry.name, reason or PARSE_REASON)
            continue
        trusted.add(entry.name)
        assert entry.content is not None  # noqa: S101 - a trusted entry was read
        digests[entry.name] = hashlib.sha256(entry.content).digest()
        # A name two files of a kind both declare is read from the first, as `make` and `just` do.
        for name, script in parsed.items():
            by_kind[_kind(entry.name)].setdefault(name, script)
    try:
        real = os.path.realpath(top)
    except (OSError, ValueError):
        return None
    return Declarations(
        top,
        committed.commit,
        by_kind["package"],
        by_kind["make"],
        by_kind["just"],
        tuple(skipped),
        frozenset(trusted),
        real,
        digests,
    )


def _kind(name: str) -> str:
    if name == "package.json":
        return "package"
    return "make" if name.lower() in ("gnumakefile", "makefile") else "just"


def _unusable(entry: git_status.CommittedEntry, toplevel: str) -> str | None:
    """Why a committed file may not declare anything, or None when its bytes are trusted."""
    if entry.mode == "120000":
        return LINK_REASON
    if entry.mode not in ("100644", "100755"):
        return SPECIAL_REASON
    if entry.content is None or entry.size > MAX_FILE_BYTES:
        return SIZE_REASON
    working, reason = _working_bytes(os.path.join(toplevel, entry.name))
    if reason is not None:
        return reason
    return None if working == entry.content else EDITED_REASON


class _Refused(Exception):  # noqa: N818 - a refusal with its reason, not an error the caller reports
    """A declaring file the work tree does not hold as a plain, bounded, regular file."""


def _working_bytes(path: str) -> tuple[bytes | None, str | None]:
    """A regular file's bytes, read without following a link or waiting on a pipe, or why not."""
    try:
        return _read_regular(path), None
    except _Refused as refusal:
        return None, str(refusal)


def _read_regular(path: str) -> bytes:
    """`lstat` first so a FIFO or link is refused before it is opened; the open is non-blocking
    and refuses a link, and the opened descriptor must be the file `lstat` saw."""
    try:
        before = os.lstat(path)
    except FileNotFoundError:
        raise _Refused(MISSING_REASON) from None
    except OSError:
        raise _Refused(SPECIAL_REASON) from None
    if stat.S_ISLNK(before.st_mode):
        raise _Refused(LINK_REASON)
    if not stat.S_ISREG(before.st_mode):
        raise _Refused(SPECIAL_REASON)
    if before.st_size > MAX_FILE_BYTES:
        raise _Refused(SIZE_REASON)
    flags = (
        os.O_RDONLY
        | getattr(os, "O_NONBLOCK", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )
    try:
        descriptor = os.open(path, flags)
    except OSError:
        raise _Refused(SPECIAL_REASON) from None
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode) or (opened.st_ino, opened.st_dev) != (
            before.st_ino,
            before.st_dev,
        ):
            raise _Refused(SPECIAL_REASON)
        data = os.read(descriptor, MAX_FILE_BYTES + 1)
    except OSError:
        raise _Refused(SPECIAL_REASON) from None
    finally:
        os.close(descriptor)
    if len(data) > MAX_FILE_BYTES:
        raise _Refused(SIZE_REASON)
    return data


def _parse(name: str, content: bytes) -> tuple[dict[str, Script] | None, str | None]:
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        return None, PARSE_REASON
    if "\0" in text:
        return None, PARSE_REASON
    kind = _kind(name)
    if kind == "package":
        return _parse_package(text)
    return _parse_line_file(kind, text)


def _parse_line_file(kind: str, text: str) -> tuple[dict[str, Script] | None, str | None]:
    if text.count("\n") > MAX_LINES:
        return None, SIZE_REASON
    if any(len(line) > MAX_LINE_CHARS for line in text.splitlines()):
        return None, LINE_REASON
    try:
        scripts = _parse_make(text) if kind == "make" else _parse_just(text)
    except _LineTooLong:
        return None, LINE_REASON
    if scripts is None:
        return None, FEATURE_REASON
    return (scripts, None) if len(scripts) <= MAX_SCRIPTS else (None, COUNT_REASON)


class _LineTooLong(Exception):  # noqa: N818 - a refusal with a closed reason, not an error
    """A logical line over `MAX_LINE_CHARS` once its continuations are joined."""


def _parse_package(text: str) -> tuple[dict[str, Script] | None, str | None]:
    try:
        data = json.loads(text)
    except (ValueError, RecursionError):
        return None, PARSE_REASON
    scripts = data.get("scripts") if isinstance(data, dict) else None
    if scripts is None:
        return {}, None
    if not isinstance(scripts, dict):
        return None, PARSE_REASON
    if len(scripts) > MAX_SCRIPTS:
        return None, COUNT_REASON
    return {
        key: Script((value,))
        for key, value in scripts.items()
        if isinstance(key, str)
        and isinstance(value, str)
        and len(key) <= 200
        and 0 < len(value) <= MAX_BODY_CHARS
    }, None


# Make features that change which recipe runs or what it means, which a line-by-line reading
# cannot follow: the file is not read at all rather than read wrongly.
_MAKE_UNSUPPORTED = re.compile(
    r"^[ \t]*(?:-?include|sinclude|define|endef|ifn?eq|ifn?def|override|vpath"
    r"|export[ \t]+-?\w+[ \t]*:?=)\b"
    r"|^[ \t]*\.(?:ONESHELL|SHELLFLAGS|DEFAULT|SECONDEXPANSION|POSIX|EXPORT_ALL_VARIABLES)\b"
    r"|^[ \t]*SHELL[ \t]*[:?+]?=",
    re.MULTILINE,
)
_MAKE_ASSIGNMENT = re.compile(r"^[A-Za-z_][\w.\-]*\s*(?:[:+?!]|::)?=")
_PUNCTUATION = re.compile(r"[:=#]")


def _make_rule(line: str) -> tuple[list[str], str, str] | None:
    """The target names, the colons and the text after them of a rule line, or None.

    Found by index, not by a pattern: a lazy group between two whitespace runs backtracks
    quadratically on a long line of spaces. A `#` comment after the colons is dropped, unless the
    line also holds a `$` or a `\\#`, which this reader does not follow.
    """
    if not line or line[0] in ":=# \t":
        return None
    found = _PUNCTUATION.search(line)
    if found is None or found.group() != ":":
        return None
    at = found.start()
    colons = "::" if line[at + 1 : at + 2] == ":" and line[at + 2 : at + 3] != "=" else ":"
    rest = line[at + len(colons) :]
    if rest[:1] == "=":
        return None
    if "#" in rest:
        if "$" in line or "\\#" in line:
            return None
        rest = rest.partition("#")[0]
    return line[:at].split(), colons, rest


_RECIPE_PREFIX = "@+"


class _MakeReader:
    """Rules and recipe lines in file order: the target the current block belongs to."""

    def __init__(self) -> None:
        self.targets: dict[str, dict[str, Any]] = {}
        self.unusable: set[str] = set()
        self.phony: set[str] = set()
        self.current: str | None = None
        self.block_has_recipe = False

    def header(self, line: str) -> None:
        self.current, self.block_has_recipe = _make_header(
            line, self.targets, self.unusable, self.phony
        )
        if self.current is not None and (inline := line.partition(";")[2].strip()):
            self.recipe(inline)

    def recipe(self, line: str) -> None:
        if self.current is None:
            return
        entry = self.targets[self.current]
        if not self.block_has_recipe:
            self.block_has_recipe = True
            entry["blocks"] += 1
        while line[:1] in tuple(_RECIPE_PREFIX):
            line = line[1:].lstrip()
        # A leading `-` ignores the line's failure, and a `$` is expanded by make before the shell
        # sees it: neither is a command this reader can say anything about.
        if not line or line.startswith("-") or "$" in line:
            self.unusable.add(self.current)
        else:
            entry["lines"].append(line)

    def scripts(self) -> dict[str, Script]:
        return {
            name: Script(tuple(entry["lines"]), tuple(entry["needs"]))
            for name, entry in self.targets.items()
            # Two blocks with recipes for one target: make keeps one and warns, or runs both.
            if name not in self.unusable
            and entry["blocks"] <= 1
            # A target with no prerequisite and no `.PHONY` line is a file name: `make test` beside
            # a `test/` directory prints "up to date" and runs nothing.
            and (name in self.phony or entry["needs"])
        }


def _parse_make(text: str) -> dict[str, Script] | None:
    if _MAKE_UNSUPPORTED.search(text):
        return None
    reader = _MakeReader()
    for line in _logical_lines(text):
        if line.startswith("\t"):
            reader.recipe(line.strip())
        elif line.strip() and not line.lstrip().startswith("#"):
            reader.header(line)
    return reader.scripts()


def _make_header(
    line: str, targets: dict[str, dict[str, Any]], unusable: set[str], phony: set[str]
) -> tuple[str | None, bool]:
    """The target a rule line opens, or None for an assignment, a pattern or a special target."""
    if _MAKE_ASSIGNMENT.match(line):
        return None, False
    rule = _make_rule(line)
    if rule is None:
        return None, False
    names, colons, rest = rule[0], rule[1], rule[2].partition(";")[0]
    if names == [".PHONY"] and colons == ":":
        phony.update(rest.split())
        return None, False
    if len(names) != 1 or colons != ":" or names[0].startswith("."):
        unusable.update(names)
        return None, False
    target = names[0]
    prerequisites = rest.replace("|", " ").split()
    if "/" in target or any(re.search(r"[$%*?\[]", word) for word in (target, *prerequisites)):
        unusable.add(target)
        return None, False
    entry = targets.setdefault(target, {"needs": [], "lines": [], "blocks": 0})
    entry["needs"].extend(word for word in prerequisites if word not in entry["needs"])
    return target, False


def _logical_lines(text: str) -> list[str]:
    """Physical lines with a trailing backslash joined to the next, as make and just read them."""
    joined: list[str] = []
    carry = ""
    for raw in text.splitlines():
        physical = raw.lstrip() if carry else raw
        if physical.endswith("\\"):
            carry += physical[:-1] + " "
            if len(carry) > MAX_LINE_CHARS:
                raise _LineTooLong
            continue
        if len(carry) + len(physical) > MAX_LINE_CHARS:
            raise _LineTooLong
        joined.append(carry + physical)
        carry = ""
    if carry:
        joined.append(carry)
    return joined


_JUST_UNSUPPORTED = re.compile(
    r"^(?:import|mod)\b|^set\s+(?:windows-)?shell\b|^set\s+(?:script-interpreter)\b",
    re.MULTILINE,
)
_JUST_NAME = re.compile(r"(@?)([A-Za-z_][A-Za-z0-9_-]*)(\s.*)?")


def _just_header(line: str) -> tuple[str, str, str] | None:
    """The recipe name, its parameter text and the text after the colon, or None.

    Split at the first colon by index: the pattern this replaces spent cubic time on a long line.
    """
    at = line.find(":")
    if at < 0 or line[at + 1 : at + 2] == "=":
        return None
    head = _JUST_NAME.fullmatch(line[:at])
    if head is None:
        return None
    return head[2], head[3] or "", line[at + 1 :].strip()


_JUST_ATTRIBUTE = re.compile(r"^\[(.*)\]\s*$")
_JUST_QUIET_ATTRIBUTES = ("private", "group", "doc")


def _parse_just(text: str) -> dict[str, Script] | None:
    if _JUST_UNSUPPORTED.search(text):
        return None
    scripts: dict[str, Script] = {}
    unusable: set[str] = set()
    pending_unusable = False
    name: str | None = None
    lines: list[str] = []
    needs: tuple[str, ...] = ()

    def close() -> None:
        if name is not None and name not in unusable:
            scripts.setdefault(name, Script(tuple(lines), needs))

    for line in text.splitlines():
        indented = line[:1] in (" ", "\t")
        if indented and name is not None:
            _just_body(line.strip(), lines, unusable, name)
            continue
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        attribute = _JUST_ATTRIBUTE.match(line.strip())
        if attribute is not None:
            pending_unusable |= any(
                not part.strip().startswith(_JUST_QUIET_ATTRIBUTES)
                for part in attribute[1].split(",")
            )
            continue
        close()
        name, lines, needs = None, [], ()
        header = _just_header(line)
        if header is None or line.startswith(("alias ", "set ", "export ")):
            pending_unusable = False
            continue
        recipe, params, rest = header
        dependencies = rest.split()
        if (
            pending_unusable
            or (params and params.strip())
            or any(not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]*", dep) for dep in dependencies)
        ):
            unusable.add(recipe)
        name, needs = recipe, tuple(dependencies)
        pending_unusable = False
    close()
    return {key: value for key, value in scripts.items() if key not in unusable}


def _just_body(line: str, lines: list[str], unusable: set[str], name: str) -> None:
    if not line or (line.startswith("#") and not line.startswith("#!")):
        return
    while line[:1] == "@":
        line = line[1:].lstrip()
    # A shebang makes the recipe a script of its own, `{{ }}` interpolates, and a leading `-`
    # ignores the line's failure: none is a command this reader can say anything about.
    if not line or line.startswith(("#!", "-")) or "{{" in line:
        unusable.add(name)
        return
    lines.append(line)
