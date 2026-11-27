"""Closed grammar fields and the validation shared by plan declarations."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable


class SettingsError(ValueError):
    """The settings file is malformed. Details are intentionally kept out of reports."""


_BIDI_CONTROLS = frozenset(
    "\u061c\u200e\u200f\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069"
)


def is_line(text: str) -> bool:
    return all(
        unicodedata.category(char) not in {"Cc", "Cs", "Zl", "Zp"}
        and char not in _BIDI_CONTROLS
        and char != "\ufeff"
        for char in text
    )


def string(value: object, max_chars: int = 128) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= max_chars or not is_line(value):
        raise SettingsError
    return value


def integer(value: object, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= maximum:
        raise SettingsError
    return value


def boolean(value: object) -> bool:
    if not isinstance(value, bool):
        raise SettingsError
    return value


def choice(value: object, options: Iterable[str]) -> str:
    if not isinstance(value, str) or value not in options:
        raise SettingsError
    return value


def array(value: object, limit: int, *, min_items: int = 0) -> list[object]:
    if not isinstance(value, list) or not min_items <= len(value) <= limit:
        raise SettingsError
    return value


def strings(
    value: object, limit: int, max_chars: int = 128, *, min_items: int = 0
) -> tuple[str, ...]:
    items = tuple(string(item, max_chars) for item in array(value, limit, min_items=min_items))
    if len(set(items)) != len(items):
        raise SettingsError
    return items


def dictionary(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise SettingsError
    return value


def keys(value: object, required: str, *, optional: str = "") -> dict[str, object]:
    record = dictionary(value)
    needed = set(required.split())
    if not needed <= record.keys() <= needed.union(optional.split()):
        raise SettingsError
    return record


def folded(value: str) -> str:
    return unicodedata.normalize("NFC", value).casefold()


_FIELD_PATTERNS = {
    "id": re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]*"),
    "goal_id": re.compile(r"[A-Z][A-Z0-9]*"),
    "numbered_goal_id": re.compile(r"[A-Z][0-9]+[a-z]?"),
    "slug": re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*"),
    "word": re.compile(r"[A-Za-z][A-Za-z0-9_-]*"),
    "integer": re.compile(r"[0-9]+"),
}
_FIELD_CAPS = {
    "id": 64,
    "goal_id": 8,
    "numbered_goal_id": 8,
    "slug": 64,
    "integer": 8,
    "word": 32,
    "enum": 64,
    "text": 512,
    "timestamp": 35,
}
_TIMESTAMP = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
    r"(\.[0-9]{1,9})?(Z|[+-](?:[01][0-9]|2[0-3]):[0-5][0-9])"
)
TIMESTAMP_FORMS = ("seconds_z", "fraction_z", "offset", "fraction_offset")


def _timestamp(text: str, forms: tuple[str, ...]) -> bool:
    matched = _TIMESTAMP.fullmatch(text)
    if matched is None:
        return False
    fraction, zone = matched.groups()
    if zone == "Z":
        style = "fraction_z" if fraction else "seconds_z"
    else:
        style = "fraction_offset" if fraction else "offset"
    if style not in forms:
        return False
    try:
        datetime.fromisoformat(text)
    except ValueError:
        return False
    return True


@dataclass(frozen=True)
class Field:
    name: str
    kind: str
    max_chars: int
    values: tuple[str, ...] = ()

    def accepts(self, part: str, timestamps: tuple[str, ...]) -> bool:
        if not 1 <= len(part) <= self.max_chars:
            return False
        if self.kind == "text":
            return True
        if self.kind == "enum":
            return part in self.values
        if self.kind == "timestamp":
            return _timestamp(part, timestamps)
        return _FIELD_PATTERNS[self.kind].fullmatch(part) is not None


def _field(value: object) -> Field:
    raw = keys(value, "name kind max_chars", optional="values")
    name = string(raw["name"], 24)
    if re.fullmatch(r"[a-z][a-z_0-9]*", name) is None:
        raise SettingsError
    kind = choice(raw["kind"], _FIELD_CAPS)
    max_chars = integer(raw["max_chars"], _FIELD_CAPS[kind])
    if kind == "enum":
        values = strings(raw.get("values"), 32, max_chars, min_items=1)
    elif "values" in raw:
        raise SettingsError
    else:
        values = ()
    return Field(name, kind, max_chars, values)


@dataclass(frozen=True)
class Template:
    tokens: tuple[str | Field, ...]

    @property
    def fields(self) -> tuple[Field, ...]:
        return tuple(part for part in self.tokens if isinstance(part, Field))

    def match(
        self, line: str, *, timestamps: tuple[str, ...] = TIMESTAMP_FORMS
    ) -> dict[str, str] | None:
        if len(line) > 4096 or not is_line(line):
            return None
        fields: dict[str, str] = {}
        rest = line
        for index, token in enumerate(self.tokens):
            if isinstance(token, str):
                if not rest.startswith(token):
                    return None
                rest = rest[len(token) :]
                continue
            separator = self.tokens[index + 1] if index + 1 < len(self.tokens) else None
            if isinstance(separator, str):
                end = rest.find(separator)
                if end == -1:
                    return None
            else:
                end = len(rest)
            part, rest = rest[:end], rest[end:]
            if not token.accepts(part, timestamps):
                return None
            fields[token.name] = part
        return fields if not rest else None


def template(value: object) -> Template:
    tokens: list[str | Field] = []
    names: set[str] = set()
    for raw in array(value, 16, min_items=1):
        if isinstance(raw, str):
            literal = string(raw)
            if tokens and isinstance(tokens[-1], str):
                tokens[-1] += literal
            else:
                tokens.append(literal)
            continue
        item = _field(raw)
        if item.name in names or (tokens and isinstance(tokens[-1], Field)):
            raise SettingsError
        tokens.append(item)
        names.add(item.name)
    if not names or any(isinstance(token, Field) and token.kind == "text" for token in tokens[:-1]):
        raise SettingsError
    return Template(tuple(tokens))


def templates(value: object) -> tuple[Template, ...]:
    result = tuple(template(item) for item in array(value, 32, min_items=1))
    if len(set(result)) != len(result):
        raise SettingsError
    return result


def word_map(
    value: object, groups: Iterable[str], normalise: Callable[[str], str]
) -> dict[str, str]:
    words = dictionary(value)
    if not 1 <= len(words) <= 64:
        raise SettingsError
    result = {}
    for word, group in words.items():
        name = normalise(string(word, 32))
        if not name.strip() or name in result:
            raise SettingsError
        result[name] = choice(group, groups)
    return result
