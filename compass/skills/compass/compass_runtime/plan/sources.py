"""The allow list for repository tree paths and local plan files."""

from __future__ import annotations

import os
import re
import unicodedata
from contextlib import contextmanager
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from compass_runtime import io

from .grammar import SettingsError, folded, string
from .model import FolderIdentity

if TYPE_CHECKING:
    from collections.abc import Iterator

    from .grammar import Template

NOT_NAMED = "not named in settings"
OUTSIDE_ROOT = "outside declared root"
GIT_OFF = "git reads are off"
BRIEF_MAX_BYTES = 64 * 1024
FILE_KINDS = ("goals", "decisions", "inventory", "tracker", "diagrams")

OBJECT_ID = re.compile(r"[0-9a-f]{40}(?:[0-9a-f]{24})?")
_TREE_PART = re.compile(r"[A-Za-z0-9._ -]{1,128}")
_MARKER_SEPARATOR = re.compile(r"[-_. ]+")


def tree_parts(path: str) -> tuple[str, ...]:
    parts = tuple(path.split("/"))
    if any(part in {"", ".", ".."} for part in parts) or "\\" in path:
        return ()
    return parts


def tree_path(value: object) -> str:
    path = string(value, 1024)
    parts = tree_parts(path)
    if not parts or any(
        part.startswith("-") or _TREE_PART.fullmatch(part) is None for part in parts
    ):
        raise SettingsError
    return path


def absolute_path(value: object) -> str:
    path = string(value, 4096)
    if path != "/" and (not path.startswith("/") or not tree_parts(path[1:])):
        raise SettingsError
    return path


def local_name(name: str) -> bool:
    return bool(name) and name not in {".", ".."} and "/" not in name and "\\" not in name


@dataclass(frozen=True)
class Marker:
    value: str
    mode: str

    def matches(self, name: str) -> bool:
        if self.mode == "component":
            return self.value == name
        if self.mode == "token":
            return self.value in _MARKER_SEPARATOR.split(name)
        return self.value in name


@dataclass(frozen=True)
class Privacy:
    markers: tuple[Marker, ...]
    marker_files: tuple[str, ...]

    def marked(self, name: str) -> bool:
        normalized = folded(name)
        return any(marker.matches(normalized) for marker in self.markers)


@dataclass(frozen=True)
class Repository:
    label: str
    path: str
    ref: str
    draft_ref: str | None
    files: tuple[tuple[str, str], ...]
    reason: str | None = None
    identity: tuple[int, int] | None = None
    common: tuple[int, int] | None = None
    private_prefixes: tuple[tuple[str, ...], ...] = ()
    parent_refusals: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class Source:
    kind: str
    path: str
    reason: str | None = None


@dataclass(frozen=True)
class PlanRead:
    data: bytes | None = None
    reason: str | None = None


@dataclass(frozen=True)
class BriefNames:
    names: tuple[str, ...] = ()
    reason: str | None = None


@dataclass(frozen=True)
class Sources:
    repositories: tuple[Repository, ...]
    brief_folder: Source
    events: Source
    policy: io.PlanPathPolicy
    filename: Template
    max_briefs: int
    max_log_bytes: int
    git_enabled: bool

    def _repo_source(
        self,
        repo: Repository,
        kind: str,
        path: str,
        *,
        recheck: bool = False,
        directory: int | None = None,
    ) -> Source:
        source = Source(kind, path)
        if not self.git_enabled:
            return replace(source, reason=GIT_OFF)
        if self.policy.marked_name and any(
            self.policy.marked_name(part) for part in tree_parts(path)[:-1]
        ):
            return replace(source, reason=io.PlanRefusal.PRIVATE)
        reason = repo.reason or dict(repo.parent_refusals).get(path)
        if recheck and reason is None:
            try:
                if directory is None:
                    with self.hold_repository(repo) as held:
                        reason = _tree_parent_reason(repo, path, self.policy, held)
                else:
                    reason = _tree_parent_reason(repo, path, self.policy, directory)
            except io.PlanReadError as exc:
                reason = exc.reason
        return replace(source, reason=reason)

    @contextmanager
    def hold_repository(self, repo: Repository) -> Iterator[int]:
        with io.hold_plan_directory(repo.path, self.policy) as directory:
            info = os.fstat(directory)
            if repo.identity != (info.st_dev, info.st_ino):
                raise io.PlanReadError(io.PlanRefusal.CHANGED)
            yield directory

    def verify_repository(self, repo: Repository, objects: tuple[str, ...] = ()) -> None:
        """Walk the repository path afresh and require it to reach the admitted folder.

        Every ancestor passes the link, private identity, name marker and marker file checks
        again, which a stat of the path alone would not do, and the repository's Git files
        pass the boundary check against the common directory found at load.
        """
        with self.hold_repository(repo) as current:
            if git_boundary(current, self.policy, objects) != repo.common:
                raise io.PlanReadError(io.PlanRefusal.CHANGED)

    def tree_source(
        self,
        repo_label: str,
        ref: str,
        path: str,
        *,
        kind: str | None = None,
        directory: int | None = None,
    ) -> Source:
        """Admit this exact tuple before the Git reader may inspect the tree."""
        if not tree_parts(path):
            return Source("repository file", path, OUTSIDE_ROOT)
        for repo in self.repositories:
            if repo.label == repo_label and ref in (repo.ref, repo.draft_ref):
                for file_kind, declared in repo.files:
                    if declared == path and kind in (None, file_kind):
                        return self._repo_source(
                            repo, file_kind, path, recheck=True, directory=directory
                        )
        return Source("repository file", path, NOT_NAMED)

    def declarations(self) -> tuple[Source, ...]:
        return (
            *(
                self._repo_source(repo, kind, path)
                for repo in self.repositories
                for kind, path in repo.files
            ),
            self.brief_folder,
            self.events,
        )

    def declared_tree_source(self, repo: Repository, kind: str, path: str) -> Source:
        return self._repo_source(repo, kind, path)

    def _brief_name_matches(self, name: str) -> bool:
        return (
            local_name(name) and self.filename.match(unicodedata.normalize("NFC", name)) is not None
        )

    def brief_names(self) -> BriefNames:
        if self.brief_folder.reason:
            return BriefNames(reason=self.brief_folder.reason)
        try:
            names = io.list_plan_names(
                self.brief_folder.path, self.policy, self._brief_name_matches, self.max_briefs
            )
        except io.PlanReadError as exc:
            return BriefNames(reason=exc.reason)
        return BriefNames(names)

    def brief_source(self, name: str) -> Source:
        if not local_name(name):
            return Source("lane brief", name, OUTSIDE_ROOT)
        if not self._brief_name_matches(name):
            return Source("lane brief", name, NOT_NAMED)
        return Source(
            "lane brief", os.path.join(self.brief_folder.path, name), self.brief_folder.reason
        )

    def read_brief(self, name: str) -> PlanRead:
        return self._read(self.brief_source(name), BRIEF_MAX_BYTES)

    def read_log(self) -> PlanRead:
        return self._read(self.events, self.max_log_bytes)

    def lane_folder(self, path: str) -> tuple[FolderIdentity | None, str | None]:
        try:
            device, inode = io.inspect_plan_directory(path, self.policy)
        except io.PlanReadError as exc:
            return None, exc.reason
        return FolderIdentity(os.path.normpath(path), device, inode), None

    def _read(self, source: Source, max_bytes: int) -> PlanRead:
        if source.reason:
            return PlanRead(reason=source.reason)
        try:
            io.inspect_plan_source(source.path, self.policy, max_bytes)
            return PlanRead(io.read_plan_source(source.path, self.policy, max_bytes))
        except io.PlanReadError as exc:
            return PlanRead(reason=exc.reason)


def _directory_reason(path: str, policy: io.PlanPathPolicy) -> str | None:
    try:
        io.inspect_plan_directory(path, policy)
    except io.PlanReadError as exc:
        return exc.reason
    return None


def _tree_parent_reason(
    repo: Repository, path: str, policy: io.PlanPathPolicy, directory: int
) -> str | None:
    parents = tree_parts(path)[:-1]
    if any(
        tuple(map(folded, parents[: len(prefix)])) == prefix for prefix in repo.private_prefixes
    ):
        return io.PlanRefusal.PRIVATE
    try:
        # Recheck the held root even for a file at the top of the tree.
        policy.check(directory, os.path.basename(repo.path), os.fstat(directory))
        if parents:
            with io.hold_plan_directory("/".join(parents), policy, parent_fd=directory):
                pass
    except io.PlanReadError as exc:
        if exc.reason != io.PlanRefusal.MISSING or policy.private_ids or policy.marker_files:
            return exc.reason
    except OSError:
        return io.PlanRefusal.UNREADABLE
    return None


_INCLUDE_SECTIONS = frozenset({b"include", b"includeif"})
_SPACE = b" \t\r\v\f"


def _name_end(data: bytes, index: int, extra: bytes) -> int:
    while index < len(data) and (data[index : index + 1].isalnum() or data[index] in extra):
        index += 1
    return index


def _subsection_end(data: bytes, index: int) -> int | None:
    """The index after `"name"]`, starting at the opening quote."""
    if data[index : index + 1] != b'"':
        return None
    index += 1
    while index < len(data) and data[index] != ord('"'):
        index += 2 if data[index] == ord("\\") else 1
        if index > len(data) or b"\n" in data[index - 2 : index]:
            return None
    return index + 2 if data[index : index + 2] == b'"]' else None


def _config_header(data: bytes, index: int) -> tuple[bytes, int] | None:
    """The section name of a header starting after "[", and the index after its "]"."""
    end = _name_end(data, index, b"-.")
    name = data[index:end].lower()
    if not name:
        return None
    if data[end : end + 1] == b"]":
        return name, end + 1
    if data[end : end + 1] not in {b" ", b"\t"}:
        return None
    while data[end : end + 1] in {b" ", b"\t"}:
        end += 1
    close = _subsection_end(data, end)
    return None if close is None else (name, close)


def _value_end(data: bytes, index: int) -> int | None:
    """The index after a value that starts after "=", following Git's quotes and escapes."""
    quoted = comment = False
    while index < len(data):
        char = data[index : index + 1]
        index += 1
        if char == b"\n":
            return None if quoted else index
        if comment:
            continue
        if char == b"\\":
            # Git accepts only these escapes; a backslash at a line end continues the value.
            if data[index : index + 1] not in {b"", b"\n", b"t", b"b", b"n", b'"', b"\\"}:
                return None
            index += 1
        elif char == b'"':
            quoted = not quoted
        comment = comment or (not quoted and char in {b"#", b";"})
    return None if quoted else index


def _entry_end(data: bytes, index: int) -> int | None:
    """The index after a key (starting at its first letter) and its value."""
    index = _name_end(data, index, b"-")
    while data[index : index + 1] in {b" ", b"\t"}:
        index += 1
    if data[index : index + 1] in {b"", b"\n"}:
        return index
    if data[index : index + 1] != b"=":
        return None
    return _value_end(data, index + 1)


def config_reaches_outside(data: bytes) -> bool:
    """True when Git could include another file, or when this reading of it is unsure.

    A small reading of Git's config grammar: comments, quoted values and line continuations
    are honoured, so a commented or continued "[include]" is not a header. Anything the
    grammar would reject counts as an include, because Git would refuse it too.
    """
    data = data.removeprefix(b"\xef\xbb\xbf").replace(b"\r\n", b"\n")
    if b"\0" in data:
        return True
    index, comment = 0, False
    while index < len(data):
        char = data[index : index + 1]
        if char == b"\n" or comment or char in {b"#", b";"} or char in _SPACE:
            comment = char != b"\n" and (comment or char in {b"#", b";"})
            index += 1
            continue
        if char == b"[":
            header = _config_header(data, index + 1)
            if header is None or header[0].split(b".")[0] in _INCLUDE_SECTIONS:
                return True
            end: int | None = header[1]
        else:
            end = _entry_end(data, index) if char.isalpha() else None
        if end is None:
            return True
        index = end
    return False


def _borrows_objects(data: bytes) -> bool:
    # Git skips only empty lines and lines starting with "#"; any other line names a store.
    # A carriage return is part of the path to Git, so a line holding one is not blank.
    return any(line and not line.startswith(b"#") for line in data.split(b"\n"))


def git_boundary(
    directory: int, policy: io.PlanPathPolicy, objects: tuple[str, ...] = ()
) -> tuple[int, int]:
    """Refuse a repository whose Git would read a config file or object store outside it.

    `objects` names object IDs a Git command is about to read, whose loose files are checked
    for links too. Returns the identity of the repository's common Git directory.
    """
    loose = tuple(oid for oid in objects if OBJECT_ID.fullmatch(oid))
    files = io.inspect_plan_git(directory, policy, loose=loose)
    if any(config_reaches_outside(config) for config in files.configs):
        raise io.PlanReadError(io.PlanRefusal.GIT_INCLUDE)
    if files.linked or any(_borrows_objects(alternates) for alternates in files.alternates):
        raise io.PlanReadError(io.PlanRefusal.GIT_ALTERNATES)
    return files.common


def _private_prefixes(
    prefixes: io.PlanPrivatePrefixes, identity: tuple[int, int], common: tuple[int, int]
) -> tuple[tuple[str, ...], ...]:
    # A private root in any checkout of this repository covers the same tree path here:
    # linked worktrees share one common Git directory. Separate clones do not.
    private = prefixes.folders.get(identity, set()) | prefixes.commons.get(common, set())
    if () in private:
        raise io.PlanReadError(io.PlanRefusal.PRIVATE)
    return tuple(sorted({tuple(map(folded, prefix)) for prefix in private}))


def check_repositories(
    repositories: tuple[Repository, ...],
    policy: io.PlanPathPolicy,
    prefixes: io.PlanPrivatePrefixes,
) -> tuple[Repository, ...]:
    checked = []
    for repo in repositories:
        try:
            with io.hold_plan_directory(repo.path, policy) as directory:
                info = os.fstat(directory)
                identity = (info.st_dev, info.st_ino)
                common = git_boundary(directory, policy)
                admitted = replace(
                    repo,
                    identity=identity,
                    common=common,
                    private_prefixes=_private_prefixes(prefixes, identity, common),
                )
                refused = tuple(
                    (path, reason)
                    for _, path in repo.files
                    if (reason := _tree_parent_reason(admitted, path, policy, directory))
                    is not None
                )
                checked.append(replace(admitted, parent_refusals=refused))
        except io.PlanReadError as exc:
            checked.append(replace(repo, reason=exc.reason))
    return tuple(checked)


def local_sources(
    brief_folder: str, event_file: str, max_log_bytes: int, policy: io.PlanPathPolicy
) -> tuple[Source, Source]:
    brief = Source("lane briefs", brief_folder, _directory_reason(brief_folder, policy))
    reason = None
    try:
        io.inspect_plan_source(event_file, policy, max_log_bytes)
    except io.PlanReadError as exc:
        reason = exc.reason
    return brief, Source("event log", event_file, reason)
