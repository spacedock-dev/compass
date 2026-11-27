"""The configured Markdown (and inventory JSON) shapes in plan sources."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from itertools import pairwise
from typing import TYPE_CHECKING, NamedTuple

from . import grammar, model
from .settings import BriefLabel

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Sequence

    from . import settings

MALFORMED = "malformed"
TOO_LARGE = "over the byte cap"
TOO_MANY_ROWS = "over the row cap"
STATUS_UNKNOWN = "Status not recognised"
MAX_ROWS = 1000
MAX_TEXT_CHARS = 512

_HEADING = re.compile(r" {0,3}(#{1,6}) +(\S.*)")
_LIST_ITEM = re.compile(r" {0,3}(?:[-*+]|[0-9]{1,9}[.)]) +(.+)")
_FENCE = re.compile(r" {0,3}(`{3,}|~{3,})(.*)")
_TABLE_DIVIDER = re.compile(r":?-{3,}:?")
_PIPE = re.compile(r"\\.|\|")
_CHECKBOX = re.compile(r"\[([ xX])\] +(.+)")
_EMOJI = re.compile(
    r"[\U0001f000-\U0001faff\u2600-\u27bf]"
    r"[\u200d\ufe0f\u20e3\U0001f000-\U0001faff\u2600-\u27bf]* +"
)
_DIRECTIVE = re.compile(
    r"%%\{|\b(?:click|href|callback)\b|<\s*script|javascript\s*:", re.IGNORECASE
)
_FLOW = re.compile(r"(flowchart|graph) +(?:LR|RL|TB|TD|BT)")
_TRAILING_DATE = re.compile(r" +[0-9]{4}-[0-9]{2}-[0-9]{2}$")


class ParseError(ValueError):
    def __init__(self, reason: str = MALFORMED) -> None:
        self.reason = reason
        super().__init__(reason)


class Line(NamedTuple):
    number: int
    text: str

    def heading(self) -> tuple[int, str] | None:
        match = _HEADING.fullmatch(self.text)
        if match is None:
            return None
        title = match[2].rstrip()
        without_closing_hashes = title.rstrip("#")
        if without_closing_hashes.endswith(" "):
            title = without_closing_hashes.rstrip()
        return len(match[1]), title


@dataclass(frozen=True)
class Fence:
    first: Line
    last: Line | None
    info: str
    body: tuple[Line, ...]


def _blocks(text: str) -> Iterator[Line | Fence]:
    lines = iter(Line(number, line) for number, line in enumerate(text.split("\n"), 1))
    for line in lines:
        opening = _FENCE.fullmatch(line.text)
        if opening is None:
            yield line
            continue
        marker, info = opening.groups()
        body: list[Line] = []
        for end in lines:
            closing = _FENCE.fullmatch(end.text)
            if closing and closing[1].startswith(marker) and not closing[2].strip():
                yield Fence(line, end, info, tuple(body))
                break
            body.append(end)
        else:
            yield Fence(line, None, info, tuple(body))


def decode(data: bytes) -> str:
    try:
        text = data.decode("utf-8").replace("\r\n", "\n")
    except UnicodeDecodeError:
        raise ParseError from None
    if any(not grammar.is_line(line) for line in text.split("\n")):
        raise ParseError
    return text


def prose(text: str) -> tuple[Line, ...]:
    return tuple(
        block if isinstance(block, Line) else Line(block.first.number, "")
        for block in _blocks(text)
    )


def _text(value: str, maximum: int = MAX_TEXT_CHARS) -> str:
    if not value.strip():
        raise ParseError
    if len(value) > maximum:
        raise ParseError(TOO_LARGE)
    return value


def _label(line: Line, spec: settings.BriefLabel, emphasis: tuple[str, ...]) -> str | None:
    if spec.form != "label" and line.heading() == (spec.heading_level, spec.label):
        return ""
    if spec.form == "heading":
        return None
    text = line.text.lstrip(" ")
    label = spec.label
    prefixes = [f"{label}:"]
    for marker in emphasis:
        prefixes.extend((f"{marker}{label}{marker}:", f"{marker}{label}:{marker}"))
    for prefix in prefixes:
        if text == prefix:
            return ""
        if text.startswith(prefix + " "):
            return text[len(prefix) :].strip()
    return None


def _labels(
    lines: Sequence[Line],
    specs: Sequence[tuple[str, settings.BriefLabel]],
    emphasis: tuple[str, ...],
) -> tuple[dict[str, str], tuple[int, ...]]:
    found: dict[str, str] = {}
    used_lines: list[int] = []
    active: tuple[str, settings.BriefLabel] | None = None

    def finish() -> None:
        nonlocal active
        if active is not None:
            role, spec = active
            found[role] = _text(found[role], spec.max_chars)
            active = None

    for line in lines:
        matches = [
            (role, spec, value)
            for role, spec in specs
            if (value := _label(line, spec, emphasis)) is not None
        ]
        if matches:
            finish()
            role, spec, value = matches[0]
            if len(matches) != 1 or role in found:
                raise ParseError
            active = role, spec
            found[role] = value
            used_lines.append(line.number)
        elif active is not None:
            role, spec = active
            if spec.continuation == "line" or not line.text.strip() or line.heading() is not None:
                finish()
                continue
            found[role] = " ".join(filter(None, (found[role], line.text.strip())))
            used_lines.append(line.number)
            if len(found[role]) > spec.max_chars:
                raise ParseError(TOO_LARGE)
    finish()
    if any(spec.required and role not in found for role, spec in specs):
        raise ParseError
    return found, tuple(used_lines)


def _ids(
    value: str, separators: tuple[str, ...], limit: int, valid: Callable[[str], bool]
) -> tuple[str, ...]:
    pattern = "|".join(re.escape(sep) for sep in sorted(separators, key=len, reverse=True))
    items = tuple(part.strip() for part in re.split(f"(?:{pattern})+", value))
    if len(items) > limit:
        raise ParseError(TOO_MANY_ROWS)
    if not all(valid(part) for part in items) or len(set(items)) != len(items):
        raise ParseError
    return items


def brief(text: str, spec: settings.Briefs) -> tuple[str | None, str | None, tuple[str, ...]]:
    values, _ = _labels(prose(text), tuple(spec.labels.items()), spec.emphasis)
    if not values:
        raise ParseError
    serves = (
        _ids(values["serves"], spec.separators, spec.max_ids, grammar.is_goal_id)
        if "serves" in values
        else ()
    )
    return values.get("goal"), values.get("done"), serves


def _section(lines: tuple[Line, ...], spec: settings.Goals) -> Iterator[Line]:
    inside = False
    seen = False
    for line in lines:
        heading = line.heading()
        if heading == (spec.section_level, spec.section):
            if seen:
                raise ParseError
            inside = seen = True
        elif inside:
            if heading and heading[0] <= spec.section_level:
                inside = False
            else:
                yield line
    if not seen:
        raise ParseError


def _goal_match(line: Line, spec: settings.Goals) -> dict[str, str] | None:
    if spec.form == "heading":
        heading = line.heading()
        if heading is None or heading[0] != spec.heading_level:
            return None
        text = heading[1]
    else:
        text = line.text.lstrip(" ")
    for template in spec.templates:
        fields = template.match(text)
        if fields is not None:
            return fields
    for template in spec.templates:
        trailing = template.trailing_text(text)
        if trailing is not None:
            raise ParseError(TOO_LARGE if trailing.strip() else MALFORMED)
    if spec.form == "heading":
        raise ParseError
    return None


def goals(
    text: str, spec: settings.Goals, briefs: settings.Briefs, source: model.Source
) -> tuple[tuple[model.Goal, tuple[str, ...]], ...]:
    labels = [
        (
            "done",
            BriefLabel(
                spec.done_label,
                spec.max_done_chars,
                False,
                spec.done_continuation,
                spec.done_form,
                spec.done_heading_level,
            ),
        )
    ]
    if spec.lanes_label is not None:
        labels.append(
            ("lanes", BriefLabel(spec.lanes_label, MAX_TEXT_CHARS, False, "line", "label", None))
        )
    rows: dict[str, tuple[model.Goal, tuple[str, ...]]] = {}
    pending: tuple[str, str, int] | None = None
    block: list[Line] = []

    def finish() -> None:
        if pending is None:
            return
        goal_id, title, number = pending
        if goal_id in rows:
            raise ParseError
        if len(rows) >= MAX_ROWS:
            raise ParseError(TOO_MANY_ROWS)
        values, used_lines = _labels(block, labels, spec.emphasis)
        expected = (
            _ids(values["lanes"], briefs.separators, briefs.max_files, grammar.is_slug)
            if "lanes" in values
            else ()
        )
        rows[goal_id] = (
            model.Goal(
                goal_id,
                _text(title),
                values.get("done"),
                model.Origin(source, number, used_lines),
            ),
            expected,
        )

    for line in _section(prose(text), spec):
        match = _goal_match(line, spec)
        if match is None:
            if pending:
                block.append(line)
            continue
        finish()
        goal_id = match["id"] if "id" in match else spec.numbered_id_prefix + match["n"]
        pending = goal_id, match["title"].strip(), line.number
        block.clear()
    finish()
    return tuple(rows.values())


def _marker(
    title: str, markers: tuple[settings.DecisionMarker, ...], spec: settings.Decisions
) -> str | None:
    for marker in markers:
        short_title = _TRAILING_DATE.sub("", title) if marker.trailing_date else title
        if marker.trailing_date and short_title == title:
            continue
        subject = short_title
        value = marker.value
        if spec.case == "fold":
            subject, value = grammar.folded(subject), grammar.folded(value)
        if spec.optional_comma:
            subject, value = subject.rstrip(",").rstrip(), value.rstrip(",").rstrip()
        left = r"(?<!\w)" if value[:1].isalnum() else ""
        right = r"(?!\w)" if value[-1:].isalnum() else ""
        prefix = "^" if marker.position == "prefix" else left
        suffix = "$" if marker.position == "suffix" else right
        if re.search(prefix + re.escape(value) + suffix, subject):
            return short_title
    return None


def decisions(
    text: str, spec: settings.Decisions, source: model.Source
) -> tuple[model.Decision, ...]:
    rows = []
    for line in prose(text):
        heading = line.heading()
        item = _LIST_ITEM.fullmatch(line.text) if spec.form != "heading" else None
        if heading and heading[0] == spec.heading_level and spec.form != "list":
            title = heading[1]
        elif item:
            title = item[1]
        else:
            continue
        title = _text(title.strip())
        proposed = _marker(title, spec.proposed, spec)
        decided = None if proposed else _marker(title, spec.decided, spec)
        marked = proposed or decided
        rows.append(
            model.Decision(
                _text(marked or title), decided is not None, model.Origin(source, line.number)
            )
        )
        if len(rows) > MAX_ROWS:
            raise ParseError(TOO_MANY_ROWS)
    if not rows:
        raise ParseError
    return tuple(rows)


def _cells(text: str) -> tuple[str, ...]:
    text = text.strip()
    edges = [m.start() for m in _PIPE.finditer(text) if m[0] == "|"]
    if len(edges) < 2 or edges[0] != 0 or edges[-1] != len(text) - 1:
        return ()
    return tuple(
        text[left + 1 : right].strip().replace(r"\|", "|") for left, right in pairwise(edges)
    )


def _column(headers: tuple[str, ...], names: tuple[str, ...]) -> int:
    indices = [i for i, value in enumerate(headers) if value in names]
    if len(indices) != 1:
        raise ParseError
    return indices[0]


def _divider(line: Line, width: int) -> bool:
    cells = _cells(line.text)
    return len(cells) == width and all(_TABLE_DIVIDER.fullmatch(cell) for cell in cells)


def _table(
    text: str, state_columns: tuple[str, ...], title_column: str, lane_column: str | None = None
) -> Iterator[tuple[str, str, int, str | None]]:
    lines = prose(text)
    index = 0
    found = False
    while index + 1 < len(lines):
        head = _cells(lines[index].text)
        if not any(cell in state_columns for cell in head):
            index += 1
            continue
        # A neighboring table can start without an intervening blank line.
        states = _column(head, state_columns)
        titles = _column(head, (title_column,))
        # A declared lane column is required like the title, so a header typo refuses the
        # source instead of reading as every lane unmeasured.
        lanes = _column(head, (lane_column,)) if lane_column is not None else None
        if not _divider(lines[index + 1], len(head)):
            raise ParseError
        found = True
        index += 2
        while index < len(lines) and (cells := _cells(lines[index].text)):
            if (
                title_column in cells
                and any(cell in state_columns for cell in cells)
                and index + 1 < len(lines)
                and _divider(lines[index + 1], len(cells))
            ):
                break
            if len(cells) != len(head):
                raise ParseError
            lane = cells[lanes] if lanes is not None else None
            yield cells[titles], cells[states], lines[index].number, lane
            index += 1
        if (
            index < len(lines)
            and lines[index].text.lstrip().startswith("|")
            and not _cells(lines[index].text)
        ):
            raise ParseError
    if not found:
        raise ParseError


def _status_word(cell: str, spec: settings.WordGrammar) -> str | None:
    end = min((cell.index(sep) for sep in spec.tail_separators if sep in cell), default=len(cell))
    word = cell[:end].strip()
    if len(word) > MAX_TEXT_CHARS:
        return None
    return _undecorated(word, spec)


def _lane_id(cell: str | None, spec: settings.WordGrammar) -> str | None:
    if cell is None or len(cell) > MAX_TEXT_CHARS:
        return None
    word = _undecorated(cell.strip(), spec)
    lane = grammar.folded(word) if spec.case == "fold" else word
    return lane if grammar.is_safe_lane_id(lane) else None


def _undecorated(word: str, spec: settings.WordGrammar) -> str:
    while word:
        for decoration in spec.strip:
            if decoration == "emoji":
                matched = _EMOJI.match(word)
                if matched:
                    word = word[matched.end() :].lstrip()
                    break
            elif (
                word.startswith(decoration)
                and word.endswith(decoration)
                and len(word) >= 2 * len(decoration)
            ):
                word = word[len(decoration) : -len(decoration)].strip()
                break
        else:
            break
    return word


def _items(
    rows: Iterator[tuple[str, str, int | None, str | None]],
    spec: settings.WordGrammar,
    source: model.Source,
) -> tuple[tuple[model.Item, ...], tuple[model.UnknownStatus, ...]]:
    items: list[model.Item] = []
    unknown: list[model.UnknownStatus] = []
    for title, state, line, lane in rows:
        if len(items) >= MAX_ROWS:
            raise ParseError(TOO_MANY_ROWS)
        word = _status_word(state, spec)
        key = grammar.folded(word) if word is not None and spec.case == "fold" else word
        status = spec.words.get(key, STATUS_UNKNOWN) if key is not None else STATUS_UNKNOWN
        origin = model.Origin(source, line)
        items.append(model.Item(_text(title), status, origin, _lane_id(lane, spec)))
        if status == STATUS_UNKNOWN:
            if not word:
                detail = "empty status" if word == "" else "over the status word cap"
            else:
                detail = word if len(word) <= 32 else "over the status word cap"
            unknown.append(model.UnknownStatus(origin, detail))
    return tuple(items), tuple(unknown)


def tracker(
    text: str, spec: settings.Tracker, source: model.Source
) -> tuple[tuple[model.Item, ...], tuple[model.UnknownStatus, ...]]:
    rows = _table(text, spec.status_columns, spec.title_column, spec.lane_column)
    return _items(rows, spec.status, source)


def _json_items(text: str, state: str, title: str) -> Iterator[tuple[str, str, None, None]]:
    try:
        rows = json.loads(text)
    except (ValueError, RecursionError):
        raise ParseError from None
    if not isinstance(rows, list):
        raise ParseError
    for row in rows:
        if not isinstance(row, dict):
            raise ParseError
        name, word = row.get(title), row.get(state)
        if (
            not isinstance(name, str)
            or not isinstance(word, str)
            or not all(grammar.is_line(value) for value in (name, word))
        ):
            raise ParseError
        yield name, word, None, None


def inventory(
    text: str, spec: settings.Inventory, source: model.Source
) -> tuple[tuple[model.Item, ...], tuple[model.UnknownStatus, ...]]:
    if spec.checked is not None and spec.unchecked is not None:
        items = []
        for line in prose(text):
            item = _LIST_ITEM.fullmatch(line.text)
            box = _CHECKBOX.fullmatch(item[1]) if item else None
            if box:
                state = spec.checked if box[1] != " " else spec.unchecked
                items.append(model.Item(_text(box[2]), state, model.Origin(source, line.number)))
                if len(items) > MAX_ROWS:
                    raise ParseError(TOO_MANY_ROWS)
        if not items:
            raise ParseError
        return tuple(items), ()
    if spec.title_column is None or spec.status is None:
        raise ParseError
    rows = (
        _json_items(text, spec.state_locator, spec.title_column)
        if spec.form == "json"
        else _table(text, (spec.state_locator,), spec.title_column)
    )
    return _items(rows, spec.status, source)


def _diagram_kind(first: str, fence: str, spec: settings.Diagrams) -> str:
    flow = _FLOW.fullmatch(first)
    if flow:
        return flow[1]
    if first in {"sequenceDiagram", "stateDiagram-v2"}:
        return first
    if fence != "mermaid" and "ascii" in spec.types:
        return "ascii"
    raise ParseError


def _diagram_body(block: Fence, spec: settings.Diagrams) -> tuple[str, str, int]:
    if (
        block.first.text != "```" + block.info
        or block.last is None
        or block.last.text != "```"
        or not block.body
    ):
        raise ParseError
    body = "\n".join(line.text for line in block.body)
    if len(body.encode("utf-8")) > spec.max_bytes:
        raise ParseError(TOO_LARGE)
    if len(block.body) > spec.max_lines:
        raise ParseError(TOO_MANY_ROWS)
    kind = _diagram_kind(block.body[0].text, block.info, spec)
    if kind not in spec.types or (kind != "ascii" and _DIRECTIVE.search(body)):
        raise ParseError
    return kind, body, block.last.number


def diagrams(text: str, spec: settings.Diagrams, source: model.Source) -> tuple[model.Diagram, ...]:
    rows: list[model.Diagram] = []
    caption = None
    label = spec.caption.removeprefix("label:") + ": "
    for block in _blocks(text):
        if isinstance(block, Line):
            if spec.caption == "heading" and (heading := block.heading()):
                caption = heading[1], block.number
            elif spec.caption.startswith("label:") and block.text.startswith(label):
                caption_text = block.text.removeprefix(label).strip()
                caption = (caption_text, block.number) if caption_text else None
            continue
        if block.info not in spec.fences and not (spec.bare_fence and not block.info):
            continue
        if len(rows) >= spec.max_blocks:
            raise ParseError(TOO_MANY_ROWS)
        kind, body, last = _diagram_body(block, spec)
        name = _text(caption[0] if caption else f"Diagram {len(rows) + 1}")
        related = tuple(range(block.first.number + 1, last + 1))
        if caption is not None:
            related = (caption[1], *related)
        origin = model.Origin(source, block.first.number, related)
        rows.append(model.Diagram(kind, name, body, origin))
    if not rows:
        raise ParseError
    return tuple(rows)
