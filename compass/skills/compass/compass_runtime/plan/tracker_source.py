"""Typed selectors from the owned Plan settings file."""

from __future__ import annotations

import re
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Literal

from . import grammar, model

if TYPE_CHECKING:
    from collections.abc import Mapping

_OWNER = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}")
_REPO = re.compile(r"[A-Za-z0-9._-]{1,100}")
_NODE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_=/+:-]{0,255}")
MAX_SOURCES = 32
MAX_NUMBER = 10_000_000
MAX_ASK_LABELS = 32
MAX_ASK_LABEL_CHARS = 128
GITHUB_SOURCE_LABELS = MappingProxyType(
    {
        "milestone": "GitHub milestone",
        "parent-issue": "GitHub parent issue",
        "project": "GitHub project",
    }
)
LINEAR_SOURCE_LABELS = MappingProxyType(
    {"project": "Linear project", "milestone": "Linear project milestone"}
)

type SourceKey = tuple[str, str, str, int] | tuple[str, str, str, str, str | None]
type GitHubDeclaration = RepositoryDeclaration | ProjectDeclaration
type Declaration = GitHubDeclaration | LinearDeclaration


class InvalidAskLabels(grammar.SettingsError):
    """Report the refused field without exposing its values."""


@dataclass(frozen=True)
class RepositoryDeclaration:
    provider: Literal["github"]
    kind: Literal["milestone", "parent-issue"]
    repo: str
    number: int
    ask_labels: tuple[str, ...] = ()

    @property
    def key(self) -> SourceKey:
        return self.provider, self.kind, self.repo, self.number

    @property
    def executable(self) -> str:
        return "gh"


@dataclass(frozen=True)
class ProjectDeclaration:
    provider: Literal["github"]
    kind: Literal["project"]
    owner: str
    number: int
    status_field: str
    words: Mapping[str, str]
    ask_labels: tuple[str, ...] = ()

    @property
    def key(self) -> SourceKey:
        return self.provider, self.kind, self.owner, self.number

    @property
    def executable(self) -> str:
        return "gh"


def repository(value: object) -> str:
    owner, _, repo = grammar.string(value, 140).partition("/")
    if not (_OWNER.fullmatch(owner) and _REPO.fullmatch(repo)):
        raise grammar.SettingsError
    if not repo.strip(".") or repo.lower().endswith(".git"):
        raise grammar.SettingsError
    return f"{owner.lower()}/{repo.lower()}"


def node_id(value: object) -> str:
    identity = grammar.string(value, 256)
    if not _NODE_ID.fullmatch(identity):
        raise grammar.SettingsError
    return identity


def _ask_labels(raw: dict[str, object]) -> tuple[str, ...]:
    if "ask_labels" not in raw:
        return ()
    try:
        labels = grammar.strings(
            raw["ask_labels"], MAX_ASK_LABELS, MAX_ASK_LABEL_CHARS, min_items=1
        )
    except grammar.SettingsError:
        raise InvalidAskLabels from None
    if any(not label.strip() for label in labels):
        raise InvalidAskLabels
    return labels


def declaration(value: object) -> Declaration:
    raw = grammar.dictionary(value)
    if raw.get("provider") == "linear":
        return _linear_declaration(raw)
    if raw.get("provider") != "github":
        raise grammar.SettingsError
    number = grammar.integer(raw.get("number"), MAX_NUMBER)
    kind = raw.get("kind")
    if kind == "project":
        raw = grammar.keys(
            raw, "provider kind owner number status_field words", optional="ask_labels"
        )
        owner = grammar.string(raw["owner"], 39)
        if not _OWNER.fullmatch(owner):
            raise grammar.SettingsError
        words = grammar.word_map(raw["words"], model.BOARD_GROUPS, grammar.folded)
        return ProjectDeclaration(
            "github",
            "project",
            owner.lower(),
            number,
            node_id(raw["status_field"]),
            MappingProxyType(words),
            _ask_labels(raw),
        )
    if kind in ("milestone", "parent-issue"):
        raw = grammar.keys(raw, "provider kind repo number", optional="ask_labels")
        return RepositoryDeclaration(
            "github", kind, repository(raw["repo"]), number, _ask_labels(raw)
        )
    raise grammar.SettingsError


def declarations(value: object) -> tuple[Declaration, ...]:
    declared = tuple(declaration(item) for item in grammar.array(value, MAX_SOURCES, min_items=1))
    if len({item.key for item in declared}) != len(declared):
        raise grammar.SettingsError
    return declared


_WORKSPACE = re.compile(r"[a-z0-9][a-z0-9-]{0,62}")
_LINEAR_ID = re.compile(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", re.IGNORECASE)


@dataclass(frozen=True)
class LinearDeclaration:
    provider: Literal["linear"]
    kind: Literal["project", "milestone"]
    workspace: str
    project: str
    milestone: str | None
    words: Mapping[str, str]
    ask_labels: tuple[str, ...] = ()

    @property
    def key(self) -> SourceKey:
        milestone = grammar.folded(self.milestone) if self.milestone is not None else None
        return self.provider, self.kind, self.workspace, self.project, milestone

    @property
    def executable(self) -> str:
        return "linear"


def is_linear_id(value: str) -> bool:
    return _LINEAR_ID.fullmatch(value) is not None


def linear_id(value: object) -> str:
    identity = grammar.string(value, 36)
    if not is_linear_id(identity):
        raise grammar.SettingsError
    return identity.lower()


def _linear_selector(value: object) -> str:
    text = grammar.string(value, 160)
    if text != text.strip() or text.startswith("-"):
        raise grammar.SettingsError
    return text.lower() if is_linear_id(text) else text


def _linear_declaration(value: object) -> LinearDeclaration:
    raw = grammar.keys(
        value, "provider kind workspace project", optional="milestone words ask_labels"
    )
    workspace = grammar.string(raw["workspace"], 63)
    if _WORKSPACE.fullmatch(workspace) is None:
        raise grammar.SettingsError
    milestone = _linear_selector(raw["milestone"]) if "milestone" in raw else None
    kind: Literal["project", "milestone"] = "project" if milestone is None else "milestone"
    if raw["kind"] != kind:
        raise grammar.SettingsError
    words = (
        grammar.word_map(raw["words"], model.BOARD_GROUPS, grammar.folded) if "words" in raw else {}
    )
    return LinearDeclaration(
        "linear",
        kind,
        workspace,
        _linear_selector(raw["project"]),
        milestone,
        MappingProxyType(words),
        _ask_labels(raw),
    )
