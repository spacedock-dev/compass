"""Typed selectors from the owned Plan settings file."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from . import grammar

_OWNER = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}")
_REPO = re.compile(r"[A-Za-z0-9._-]{1,100}")
MAX_SOURCES = 32
MAX_NUMBER = 10_000_000


@dataclass(frozen=True)
class Declaration:
    provider: Literal["github"]
    kind: Literal["milestone"]
    repo: str
    number: int

    @property
    def key(self) -> tuple[str, str, str, int]:
        return self.provider, self.kind, self.repo, self.number

    @property
    def executable(self) -> str:
        return "gh"


def declaration(value: object) -> Declaration:
    raw = grammar.keys(value, "provider kind repo number")
    if raw["provider"] != "github" or raw["kind"] != "milestone":
        raise grammar.SettingsError
    owner, _, repo = grammar.string(raw["repo"], 140).partition("/")
    if not (_OWNER.fullmatch(owner) and _REPO.fullmatch(repo)):
        raise grammar.SettingsError
    if not repo.strip(".") or repo.lower().endswith(".git"):
        raise grammar.SettingsError
    number = grammar.integer(raw["number"], MAX_NUMBER)
    return Declaration("github", "milestone", f"{owner.lower()}/{repo.lower()}", number)


def declarations(value: object) -> tuple[Declaration, ...]:
    declared = tuple(declaration(item) for item in grammar.array(value, MAX_SOURCES, min_items=1))
    if len({item.key for item in declared}) != len(declared):
        raise grammar.SettingsError
    return declared
