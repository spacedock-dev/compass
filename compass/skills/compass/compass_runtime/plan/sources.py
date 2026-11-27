"""The allow list for repository tree paths and local plan files."""

from __future__ import annotations

import os
import re
import unicodedata
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from compass_runtime import io

from .grammar import SettingsError, folded, string
from .model import FolderIdentity

if TYPE_CHECKING:
    from .grammar import Template

NOT_NAMED = "not named in settings"
OUTSIDE_ROOT = "outside declared root"
GIT_OFF = "git reads are off"
BRIEF_MAX_BYTES = 64 * 1024
FILE_KINDS = ("goals", "decisions", "inventory", "tracker", "diagrams")

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
        self, repo: Repository, kind: str, path: str, *, recheck: bool = False
    ) -> Source:
        source = Source(kind, path)
        if not self.git_enabled:
            return replace(source, reason=GIT_OFF)
        if self.policy.marked_name and any(
            self.policy.marked_name(part) for part in tree_parts(path)[:-1]
        ):
            return replace(source, reason=io.PlanRefusal.PRIVATE)
        reason = repo.reason
        if recheck and reason is None:
            reason = _directory_reason(repo.path, self.policy)
        return replace(source, reason=reason)

    def tree_source(
        self, repo_label: str, ref: str, path: str, *, kind: str | None = None
    ) -> Source:
        """Admit this exact tuple before the Git reader may inspect the tree."""
        if not tree_parts(path):
            return Source("repository file", path, OUTSIDE_ROOT)
        for repo in self.repositories:
            if repo.label == repo_label and ref in (repo.ref, repo.draft_ref):
                for file_kind, declared in repo.files:
                    if declared == path and kind in (None, file_kind):
                        return self._repo_source(repo, file_kind, path, recheck=True)
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


def check_repositories(
    repositories: tuple[Repository, ...], policy: io.PlanPathPolicy
) -> tuple[Repository, ...]:
    return tuple(
        replace(repo, reason=_directory_reason(repo.path, policy)) for repo in repositories
    )


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
