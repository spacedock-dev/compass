"""Load the reader's plan declarations from Compass home as one validated document."""

from __future__ import annotations

import hashlib
import json
import os
import re
import unicodedata
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING

from compass_runtime import io

from . import grammar, model, sources, tracker_source
from .grammar import SettingsError, array, boolean, choice, integer, keys, string, strings

if TYPE_CHECKING:
    from collections.abc import Mapping
    from typing import Any

FILENAME = "compass-plan.json"
MAX_SETTINGS_BYTES = 64 * 1024
MAX_LOG_BYTES = 1024 * 1024
NOT_CONFIGURED = "no settings file"
DISABLED = "plan is off"
MALFORMED = "malformed settings"
PRIVATE_UNREADABLE = "could not identify a private root"
BOARD_GROUPS = model.BOARD_GROUPS
BUILD_GROUPS = ("built", "partial", "not_built")
EMPHASIS = ("**", "*", "_")
CASE_MODES = ("exact", "fold")
CONTINUATIONS = ("line", "paragraph")
LABEL_FORMS = ("label", "heading", "either")
DECORATIONS = (*EMPHASIS, "`", "emoji")


def _options(value: object, options: tuple[str, ...], *, min_items: int = 0) -> tuple[str, ...]:
    return tuple(
        choice(item, options) for item in strings(value, len(options), min_items=min_items)
    )


def _ref(value: object) -> str:
    ref = string(value, 255)
    parts = sources.tree_parts(ref)
    if not parts or ".." in ref or ref.startswith("-") or ref.endswith("."):
        raise SettingsError
    if any(
        part.startswith(".")
        or part.endswith(".lock")
        or re.fullmatch(r"[A-Za-z0-9_./-]+", part) is None
        for part in parts
    ):
        raise SettingsError
    return ref


# Slashes and backslashes, and the characters that only look like one.
_LABEL_SLASHES = frozenset("/\\\u2215\uff0f\u29f8\u2044\uff3c\u2216\u29f5")
# The names the Plan page gives a file without a label, and its row for a missing draft branch.
_GENERATED_NAME = re.compile(
    rf"(?:draft(?: (?:{'|'.join(sources.FILE_KINDS)})(?: [0-9]+)?)?"
    rf"|(?:{'|'.join(sources.FILE_KINDS)})(?: [0-9]+)?)"
)


def _label_key(text: str) -> str:
    """What a reader sees: case folded, and runs of spaces drawn as one."""
    return " ".join(grammar.folded(text).split())


def _file_label(value: object) -> str:
    label = string(value, 40)
    # A label is published and must read as itself: nothing invisible, no spacing a reader cannot
    # tell from a space, no slash of any shape, and never a name the page draws for another row.
    if (
        any(
            char in _LABEL_SLASHES
            or (unicodedata.category(char).startswith("Z") and char != " ")
            or unicodedata.category(char) == "Cf"
            for char in label
        )
        or not _label_key(label)
        or _GENERATED_NAME.fullmatch(_label_key(label))
    ):
        raise SettingsError
    return label


def _repository_file(value: object) -> tuple[str, str | None]:
    """A tree path, optionally with a short label the Plan page shows instead of the file's kind."""
    if isinstance(value, str):
        return sources.tree_path(value), None
    raw = keys(value, "path", optional="label")
    label = _file_label(raw["label"]) if "label" in raw else None
    return sources.tree_path(raw["path"]), label


def _repository(value: object) -> sources.Repository:
    raw = keys(value, "label path ref files", optional="draft_ref")
    files = grammar.dictionary(raw["files"])
    if not files or not files.keys() <= set(sources.FILE_KINDS):
        raise SettingsError
    entries = tuple(
        (kind, *_repository_file(item))
        for kind, items in files.items()
        for item in array(items, 32, min_items=1)
    )
    declared = tuple((kind, path) for kind, path, _ in entries)
    if len(declared) != len(set(declared)) or len(declared) > 32:
        raise SettingsError
    file_labels = tuple(((kind, path), label) for kind, path, label in entries if label is not None)
    label_keys = [_label_key(label) for _, label in file_labels]
    # The page never shows a path, so a label may not repeat one in any case.
    path_keys = {
        _label_key(name) for _, path in declared for name in (path, sources.tree_parts(path)[-1])
    }
    if len(set(label_keys)) != len(label_keys) or path_keys.intersection(label_keys):
        raise SettingsError
    ref = _ref(raw["ref"])
    draft = _ref(raw["draft_ref"]) if "draft_ref" in raw else None
    if draft == ref:
        raise SettingsError
    label = string(raw["label"], 80)
    if not label.strip():
        raise SettingsError
    return sources.Repository(
        label, sources.absolute_path(raw["path"]), ref, draft, declared, file_labels=file_labels
    )


@dataclass(frozen=True)
class WordGrammar:
    case: str
    strip: tuple[str, ...]
    tail_separators: tuple[str, ...]
    words: Mapping[str, str]


def _word_grammar(raw: Mapping[str, object], groups: tuple[str, ...]) -> WordGrammar:
    case = choice(raw["case"], CASE_MODES)
    normalise = grammar.folded if case == "fold" else str
    return WordGrammar(
        case,
        _options(raw["strip"], DECORATIONS),
        strings(raw["tail_separators"], 8, 16),
        MappingProxyType(grammar.word_map(raw["words"], groups, normalise)),
    )


@dataclass(frozen=True)
class Tracker:
    form: str
    status_columns: tuple[str, ...]
    title_column: str
    status: WordGrammar
    # Names the lane whose state a row sets. Without it no lane state is measured.
    lane_column: str | None = None


def _tracker(value: object) -> Tracker:
    raw = keys(
        value,
        "form status_column title_column case strip tail_separators words",
        optional="lane_column",
    )
    status = raw["status_column"]
    columns = strings(status, 8, min_items=1) if isinstance(status, list) else (string(status),)
    title = string(raw["title_column"])
    lane = string(raw["lane_column"]) if "lane_column" in raw else None
    named = (*columns, title) if lane is None else (*columns, title, lane)
    # Table cells are stripped before matching, so a padded name could never match a header.
    if any(column != column.strip() for column in named):
        raise SettingsError
    if len({grammar.folded(column) for column in named}) != len(named):
        raise SettingsError
    return Tracker(
        choice(raw["form"], ("table",)), columns, title, _word_grammar(raw, BOARD_GROUPS), lane
    )


def _heading_level(raw: dict[str, object], name: str, *, accepts_heading: bool) -> int | None:
    if accepts_heading:
        return integer(raw.get(name), 6)
    if name in raw:
        raise SettingsError
    return None


@dataclass(frozen=True)
class BriefLabel:
    label: str
    max_chars: int
    required: bool
    continuation: str
    form: str
    heading_level: int | None


def _brief_label(value: object) -> BriefLabel:
    raw = keys(value, "label max_chars required continuation form", optional="heading_level")
    form = choice(raw["form"], LABEL_FORMS)
    return BriefLabel(
        string(raw["label"], 64),
        integer(raw["max_chars"], 512),
        boolean(raw["required"]),
        choice(raw["continuation"], CONTINUATIONS),
        form,
        _heading_level(raw, "heading_level", accepts_heading=form != "label"),
    )


@dataclass(frozen=True)
class Briefs:
    folder: str
    filename: grammar.Template
    max_files: int
    emphasis: tuple[str, ...]
    separators: tuple[str, ...]
    max_ids: int
    labels: Mapping[str, BriefLabel]
    lane_folders: Mapping[str, str]


def _briefs(value: object) -> Briefs:
    raw = keys(
        value,
        "folder filename max_files emphasis separators max_ids labels",
        optional="lane_folders",
    )
    filename = grammar.template(raw["filename"])
    if [(field.name, field.kind) for field in filename.fields] != [("lane", "slug")]:
        raise SettingsError
    if any(isinstance(part, str) and not sources.local_name(part) for part in filename.tokens):
        raise SettingsError
    labels = {
        role: _brief_label(item) for role, item in keys(raw["labels"], "goal done serves").items()
    }
    if len({grammar.folded(label.label) for label in labels.values()}) != len(labels):
        raise SettingsError
    folders = grammar.dictionary(raw.get("lane_folders", {}))
    if len(folders) > 200 or not all(grammar.is_safe_lane_id(lane) for lane in folders):
        raise SettingsError
    return Briefs(
        sources.absolute_path(raw["folder"]),
        filename,
        integer(raw["max_files"], 200),
        _options(raw["emphasis"], EMPHASIS),
        strings(raw["separators"], 8, 8, min_items=1),
        integer(raw["max_ids"], 8),
        MappingProxyType(labels),
        MappingProxyType({lane: sources.absolute_path(path) for lane, path in folders.items()}),
    )


@dataclass(frozen=True)
class Verb:
    role: str
    text: str

    def accepts(self, has_text: bool) -> bool:
        return self.text == ("required" if has_text else "forbidden")


def _verb(value: object) -> Verb:
    raw = keys(value, "role text")
    return Verb(
        choice(raw["role"], ("ask", "answer", "event")),
        choice(raw["text"], ("required", "forbidden")),
    )


@dataclass(frozen=True)
class LaneMapping:
    source: str
    separator: str | None = None
    part: int | None = None


def _lane_mapping(value: object) -> LaneMapping:
    raw = keys(value, "source", optional="separator part")
    source = choice(raw["source"], ("none", "field", "id_part"))
    if source == "id_part":
        part = raw.get("part")
        if isinstance(part, bool) or not isinstance(part, int) or not 0 <= part <= 7:
            raise SettingsError
        return LaneMapping(source, string(raw.get("separator"), 8), part)
    keys(raw, "source")
    return LaneMapping(source)


_LOG_FIELDS = {
    "ts": ("timestamp",),
    "verb": ("word", "enum"),
    "lane": ("slug", "id", "enum"),
    "id": ("id",),
    "text": ("text",),
}


def _log_template(value: object, verbs: Mapping[str, Verb]) -> grammar.Template:
    tokens = list(array(value, 16, min_items=1))
    # A literal verb takes the verb slot. Convert it to a one-value field so literal and
    # patterned forms apply the same closed role and text rules.
    offset = 2 if isinstance(tokens[0], dict) and tokens[0].get("name") == "ts" else 0
    if len(tokens) > offset and isinstance(literal := tokens[offset], str) and literal in verbs:
        tokens[offset] = {
            "name": "verb",
            "kind": "enum",
            "max_chars": len(literal),
            "values": [literal],
        }
    template = grammar.template(tokens)
    fields = {field.name: field.kind for field in template.fields}
    if not {"verb", "id"} <= fields.keys() or any(
        kind not in _LOG_FIELDS.get(name, ()) for name, kind in fields.items()
    ):
        raise SettingsError
    if not isinstance(template.tokens[-1], grammar.Field):
        raise SettingsError
    verb = next(field for field in template.fields if field.name == "verb")
    if not set(verb.values) <= verbs.keys():
        raise SettingsError
    return template


def _log_coverage(
    templates: tuple[grammar.Template, ...], verbs: Mapping[str, Verb], lane: LaneMapping
) -> None:
    covered: set[str] = set()
    for template in templates:
        fields = {field.name: field for field in template.fields}
        variant = {
            name
            for name, verb in verbs.items()
            if fields["verb"].accepts(name, ())
            and verb.accepts("text" in fields)
            and (verb.role != "ask" or lane.source != "field" or "lane" in fields)
        }
        if not variant:
            raise SettingsError
        covered.update(variant)
    if covered != verbs.keys():
        raise SettingsError


@dataclass(frozen=True)
class Log:
    path: str
    max_bytes: int
    max_line_bytes: int
    timestamps: tuple[str, ...]
    templates: tuple[grammar.Template, ...]
    verbs: Mapping[str, Verb]
    answer_key: str
    lane: LaneMapping
    label: str

    def match(self, line: str) -> dict[str, str] | None:
        if len(line) > self.max_line_bytes or not grammar.is_line(line):
            return None
        if len(line.encode("utf-8")) > self.max_line_bytes:
            return None
        for template in self.templates:
            match = template.match(line, timestamps=self.timestamps)
            if match is None:
                continue
            verb = self.verbs.get(match["verb"])
            if verb and verb.accepts("text" in match):
                if verb.role == "ask" and self.lane.source == "field" and "lane" not in match:
                    continue
                return match
        return None


def _log(value: object) -> Log:
    raw = keys(
        value,
        "path max_bytes max_line_bytes timestamps templates verbs answer_key lane",
        optional="label",
    )
    verbs_raw = grammar.dictionary(raw["verbs"])
    if not 1 <= len(verbs_raw) <= 24 or any(
        re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,31}", verb) is None for verb in verbs_raw
    ):
        raise SettingsError
    verbs = {name: _verb(item) for name, item in verbs_raw.items()}
    templates = tuple(
        _log_template(item, verbs) for item in array(raw["templates"], 32, min_items=1)
    )
    timestamps = _options(raw["timestamps"], grammar.TIMESTAMP_FORMS)
    if len(set(templates)) != len(templates) or (
        not timestamps and any(field.name == "ts" for t in templates for field in t.fields)
    ):
        raise SettingsError
    lane = _lane_mapping(raw["lane"])
    _log_coverage(templates, verbs, lane)
    max_bytes = integer(raw["max_bytes"], MAX_LOG_BYTES)
    label = string(raw.get("label", "Event log"), 80)
    if not label.strip():
        raise SettingsError
    return Log(
        sources.absolute_path(raw["path"]),
        max_bytes,
        integer(raw["max_line_bytes"], min(512, max_bytes)),
        timestamps,
        templates,
        MappingProxyType(verbs),
        choice(raw["answer_key"], ("id",)),
        lane,
        label,
    )


@dataclass(frozen=True)
class Diagrams:
    fences: tuple[str, ...]
    types: tuple[str, ...]
    caption: str
    max_blocks: int
    max_lines: int
    max_bytes: int
    bare_fence: bool


def _diagrams(value: object) -> Diagrams:
    raw = keys(value, "fences types caption max_blocks max_lines max_bytes", optional="bare_fence")
    caption = string(raw["caption"], 72)
    if caption not in {"heading", "number"} and (
        not caption.startswith("label:") or not caption.removeprefix("label:").strip()
    ):
        raise SettingsError
    fences = strings(raw["fences"], 8, 32)
    bare = boolean(raw.get("bare_fence", False))
    types = _options(
        raw["types"],
        ("flowchart", "graph", "sequenceDiagram", "stateDiagram-v2", "ascii"),
        min_items=1,
    )
    if (not fences and not bare) or (bare and "ascii" not in types):
        raise SettingsError
    return Diagrams(
        fences,
        types,
        caption,
        integer(raw["max_blocks"], 20),
        integer(raw["max_lines"], 200),
        integer(raw["max_bytes"], 16 * 1024),
        bare,
    )


@dataclass(frozen=True)
class Goals:
    section: str
    section_level: int
    form: str
    heading_level: int | None
    templates: tuple[grammar.Template, ...]
    done_label: str
    emphasis: tuple[str, ...]
    max_done_chars: int
    done_form: str
    done_continuation: str
    done_heading_level: int | None
    lanes_label: str | None
    numbered_id_prefix: str


def _goals(value: object) -> Goals:
    raw = keys(
        value,
        "section section_level form templates done_label emphasis max_done_chars "
        "done_form done_continuation",
        optional="heading_level done_heading_level lanes_label numbered_id_prefix",
    )
    form = choice(raw["form"], ("heading", "list"))
    done = choice(raw["done_form"], LABEL_FORMS)
    templates = grammar.templates(raw["templates"])
    prefix = string(raw["numbered_id_prefix"], 7) if "numbered_id_prefix" in raw else ""
    if prefix and re.fullmatch(r"[A-Z][A-Z0-9]*", prefix) is None:
        raise SettingsError
    for template in templates:
        fields = {field.name: field.kind for field in template.fields}
        if fields not in (
            {"id": "goal_id", "title": "text"},
            {"id": "numbered_goal_id", "title": "text"},
            {"n": "integer", "title": "text"},
        ):
            raise SettingsError
        if next(field.max_chars for field in template.fields if field.name == "title") > 200:
            raise SettingsError
        if any(
            field.name == "n" and field.max_chars + len(prefix) > 8 for field in template.fields
        ):
            raise SettingsError
    done_label = string(raw["done_label"], 80)
    lanes_label = string(raw["lanes_label"], 80) if "lanes_label" in raw else None
    if lanes_label is not None and grammar.folded(lanes_label) == grammar.folded(done_label):
        raise SettingsError
    return Goals(
        string(raw["section"], 80),
        integer(raw["section_level"], 6),
        form,
        _heading_level(raw, "heading_level", accepts_heading=form == "heading"),
        templates,
        done_label,
        _options(raw["emphasis"], EMPHASIS),
        integer(raw["max_done_chars"], 300),
        done,
        choice(raw["done_continuation"], CONTINUATIONS),
        _heading_level(raw, "done_heading_level", accepts_heading=done != "label"),
        lanes_label,
        prefix,
    )


@dataclass(frozen=True)
class DecisionMarker:
    value: str
    position: str
    trailing_date: bool


def _decision_marker(value: object) -> DecisionMarker:
    raw = keys(value, "value position", optional="trailing_date")
    marker = DecisionMarker(
        string(raw["value"], 96),
        choice(raw["position"], ("prefix", "suffix", "anywhere")),
        boolean(raw.get("trailing_date", False)),
    )
    if not marker.value.strip() or (marker.trailing_date and marker.position != "suffix"):
        raise SettingsError
    return marker


@dataclass(frozen=True)
class Decisions:
    form: str
    heading_level: int | None
    decided: tuple[DecisionMarker, ...]
    proposed: tuple[DecisionMarker, ...]
    case: str
    optional_comma: bool


def _decisions(value: object) -> Decisions:
    raw = keys(value, "form decided proposed case optional_comma", optional="heading_level")
    form = choice(raw["form"], ("heading", "list", "either"))
    return Decisions(
        form,
        _heading_level(raw, "heading_level", accepts_heading=form != "list"),
        tuple(_decision_marker(item) for item in array(raw["decided"], 16, min_items=1)),
        tuple(_decision_marker(item) for item in array(raw["proposed"], 16)),
        choice(raw["case"], CASE_MODES),
        boolean(raw["optional_comma"]),
    )


@dataclass(frozen=True)
class Inventory:
    form: str
    state_locator: str
    title_column: str | None = None
    status: WordGrammar | None = None
    checked: str | None = None
    unchecked: str | None = None


def _inventory(value: object) -> Inventory:
    raw = grammar.dictionary(value)
    form = choice(raw.get("form"), ("table", "json", "checklist"))
    if form == "checklist":
        keys(raw, "form state_locator checked unchecked")
        return Inventory(
            form,
            choice(raw["state_locator"], ("checkbox",)),
            checked=choice(raw["checked"], BUILD_GROUPS),
            unchecked=choice(raw["unchecked"], BUILD_GROUPS),
        )
    keys(raw, "form state_locator title_column case strip tail_separators words")
    return Inventory(
        form,
        string(raw["state_locator"]),
        string(raw["title_column"]),
        _word_grammar(raw, BUILD_GROUPS),
    )


def _private(value: object) -> tuple[tuple[str, ...], sources.Privacy]:
    raw = keys(value, "roots markers", optional="marker_files")
    roots = tuple(sources.absolute_path(item) for item in strings(raw["roots"], 32, 4096))
    markers = []
    for item in array(raw["markers"], 32):
        marker = keys(item, "value mode")
        text = grammar.folded(string(marker["value"], 128))
        if not text.strip():
            raise SettingsError
        mode = choice(marker["mode"], ("component", "token", "substring"))
        markers.append(sources.Marker(text, mode))
    filenames = strings(raw.get("marker_files", []), 8, 128)
    if not all(sources.local_name(name) for name in filenames):
        raise SettingsError
    return roots, sources.Privacy(tuple(markers), filenames)


@dataclass(frozen=True)
class _Declarations:
    repos: tuple[sources.Repository, ...]
    briefs: Briefs | None
    log: Log | None
    roots: tuple[str, ...]
    privacy: sources.Privacy
    tracker: Tracker | None
    diagrams: Diagrams | None
    goals: Goals | None
    decisions: Decisions | None
    inventory: Inventory | None
    summary_enabled: bool
    trackers: tuple[tracker_source.Declaration, ...]


def _unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise SettingsError
        result[key] = value
    return result


def _unknown_constant(_text: str) -> object:
    raise SettingsError


_LOCAL_FIELDS = "repos tracker briefs log private diagrams goals decisions inventory"


def _declarations(data: bytes) -> _Declarations:
    raw = keys(
        json.loads(
            data.decode("utf-8"), object_pairs_hook=_unique, parse_constant=_unknown_constant
        ),
        "version",
        optional=f"{_LOCAL_FIELDS} summary trackers",
    )
    integer(raw["version"], 1)
    trackers = tracker_source.declarations(raw["trackers"]) if "trackers" in raw else ()
    if not trackers and not set(_LOCAL_FIELDS.split()) <= raw.keys():
        raise SettingsError
    repos = tuple(_repository(item) for item in array(raw.get("repos", []), 32))
    if len(repos) != len({grammar.folded(repo.label) for repo in repos}):
        raise SettingsError
    if any(kind not in raw for repo in repos for kind, _ in repo.files):
        raise SettingsError
    roots, privacy = _private(raw.get("private", {"roots": [], "markers": []}))
    summary = boolean(keys(raw.get("summary", {"enabled": False}), "enabled")["enabled"])
    goals = _goals(raw["goals"]) if "goals" in raw else None
    if goals is not None and goals.lanes_label is not None and "briefs" not in raw:
        # Explicit goal membership uses the lane-list grammar declared by the briefs.
        raise SettingsError
    return _Declarations(
        repos,
        _briefs(raw["briefs"]) if "briefs" in raw else None,
        _log(raw["log"]) if "log" in raw else None,
        roots,
        privacy,
        _tracker(raw["tracker"]) if "tracker" in raw else None,
        _diagrams(raw["diagrams"]) if "diagrams" in raw else None,
        goals,
        _decisions(raw["decisions"]) if "decisions" in raw else None,
        _inventory(raw["inventory"]) if "inventory" in raw else None,
        summary,
        trackers,
    )


@dataclass(frozen=True)
class Settings:
    sources: sources.Sources
    tracker: Tracker | None
    briefs: Briefs | None
    log: Log | None
    diagrams: Diagrams | None
    goals: Goals | None
    decisions: Decisions | None
    inventory: Inventory | None
    summary_enabled: bool
    private_roots: int
    private_markers: int
    private_marker_files: int
    # SHA-256 of the admitted settings file's bytes: what the saved summary states are bound to.
    digest: str = ""
    trackers: tuple[tracker_source.Declaration, ...] = ()


@dataclass(frozen=True)
class Loaded:
    path: str
    settings: Settings | None = None
    reason: str | None = None


def _repo_ids(repos: tuple[sources.Repository, ...]) -> frozenset[tuple[int, int]]:
    return io.plan_directory_identities(tuple(repo.path for repo in repos))


def _make_settings(
    declared: _Declarations, path: str, *, git_enabled: bool, digest: str = ""
) -> Loaded:
    try:
        ids = io.plan_private_identities(declared.roots)
        prefixes = (
            io.plan_private_prefixes(declared.roots, ids)
            if git_enabled
            else io.PlanPrivatePrefixes()
        )
    except (OSError, io.PlanReadError):
        return Loaded(path, reason=PRIVATE_UNREADABLE)
    try:
        io.inspect_plan_directory(
            os.path.dirname(path), io.PlanPathPolicy(repo_ids=_repo_ids(declared.repos))
        )
    except io.PlanReadError as exc:
        return Loaded(path, reason=exc.reason)
    policy = io.PlanPathPolicy(ids, declared.privacy.marked, declared.privacy.marker_files)
    brief, log = declared.briefs, declared.log
    repos = (
        sources.check_repositories(declared.repos, policy, prefixes)
        if git_enabled
        else declared.repos
    )
    allowed = sources.Sources(
        repos,
        sources.local_briefs(brief.folder, policy) if brief else None,
        sources.local_log(log.path, log.max_bytes, policy) if log else None,
        policy,
        brief.filename if brief else None,
        brief.max_files if brief else 0,
        log.max_bytes if log else 0,
        git_enabled,
    )
    return Loaded(
        path,
        Settings(
            allowed,
            declared.tracker,
            brief,
            log,
            declared.diagrams,
            declared.goals,
            declared.decisions,
            declared.inventory,
            declared.summary_enabled,
            len(declared.roots),
            len(declared.privacy.markers),
            len(declared.privacy.marker_files),
            digest,
            declared.trackers,
        ),
    )


def load(home: str, *, enabled: bool = True, git_enabled: bool = True) -> Loaded:
    path = os.path.join(os.path.abspath(home), FILENAME)
    if not enabled:
        return Loaded(path, reason=DISABLED)
    try:
        data = io.read_plan_settings(path, MAX_SETTINGS_BYTES)
    except io.PlanReadError as exc:
        return Loaded(
            path, reason=NOT_CONFIGURED if exc.reason == io.PlanRefusal.MISSING else exc.reason
        )
    try:
        declared = _declarations(data)
    except (ValueError, RecursionError):
        return Loaded(path, reason=MALFORMED)
    return _make_settings(
        declared, path, git_enabled=git_enabled, digest=hashlib.sha256(data).hexdigest()
    )


def report(loaded: Loaded) -> dict[str, Any]:
    plan = loaded.settings
    return {
        "path": loaded.path,
        "reason": loaded.reason,
        "sources": [
            {"kind": source.kind, "reason": source.reason} for source in plan.sources.declarations()
        ]
        if plan
        else [],
        "private_roots": plan.private_roots if plan else None,
        "private_markers": plan.private_markers if plan else None,
        "private_marker_files": plan.private_marker_files if plan else None,
    }
