"""Internal plan rows. Publication requires an explicit projection and text redaction."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from collections.abc import Mapping

BOARD_GROUPS = ("not_started", "running", "waiting", "blocked", "done", "dropped")


@dataclass(frozen=True)
class ItemDate:
    label: Literal["Changed", "Proposed, not merged", "from the log", "Due", "Updated"]
    value: str | None


@dataclass(frozen=True)
class Source:
    kind: str
    label: str
    path: str = field(repr=False)
    ref: str | None = None
    commit: str | None = None
    reason: str | None = None
    draft: bool = False
    # What tells two files of one kind in one repository apart, without their paths.
    file_label: str | None = None
    position: int | None = None

    @property
    def display_kind(self) -> str:
        return f"draft {self.kind}" if self.draft else self.kind


@dataclass(frozen=True)
class Origin:
    source: Source
    line: int | None = None
    related_lines: tuple[int, ...] = ()
    date: ItemDate | None = None

    @property
    def commit(self) -> str | None:
        return self.source.commit


@dataclass(frozen=True)
class Goal:
    id: str
    title: str
    done: str | None
    origin: Origin
    lanes: tuple[str, ...] = ()


@dataclass(frozen=True)
class Decision:
    title: str
    decided: bool
    origin: Origin


@dataclass(frozen=True)
class Item:
    title: str
    status: str
    origin: Origin
    lane: str | None = field(default=None, repr=False)
    # Lane IDs inside a lane cell that is not exactly one ID. They only make a lane ambiguous.
    mentions: tuple[str, ...] = field(default=(), repr=False)


@dataclass(frozen=True)
class Diagram:
    kind: str
    caption: str
    unredacted_body: str = field(repr=False)
    origin: Origin


@dataclass(frozen=True)
class FolderIdentity:
    path: str = field(repr=False)
    device: int
    inode: int


@dataclass(frozen=True)
class Lane:
    slug: str
    goal: str | None
    done: str | None
    serves: tuple[str, ...]
    source: Source
    folder: FolderIdentity | None = field(default=None, repr=False)
    folder_reason: str | None = None
    date: ItemDate | None = None
    # None means not measured, never a default group (AGENTS.md "Measured Invariants").
    state: str | None = None


@dataclass(frozen=True)
class TrackerAskIssue:
    lane: Lane
    open_and_assigned: bool
    labels: frozenset[str] = field(repr=False)

    def matches(self, labels: tuple[str, ...]) -> bool:
        return self.open_and_assigned and not self.labels.isdisjoint(labels)


@dataclass(frozen=True)
class TrackerAskRead:
    viewer: str = field(repr=False)
    issues: tuple[TrackerAskIssue, ...]


@dataclass(frozen=True)
class TrackerData:
    """An adapter returns these rows only after proving complete membership."""

    goals: tuple[Goal, ...]
    lanes: tuple[Lane, ...]
    # Preserves authority when the same issue serves multiple configured goals.
    project_status_lanes: frozenset[str] = frozenset()
    # None means the ask rule was not measured, even when issue membership was complete.
    ask_read: TrackerAskRead | None = field(default=None, repr=False)


@dataclass(frozen=True)
class Ask:
    id: str
    text: str | None
    timestamp: str | None
    source: str
    lane: str | None

    @property
    def date(self) -> ItemDate | None:
        return ItemDate("from the log", self.timestamp) if self.timestamp is not None else None


@dataclass(frozen=True)
class PlanModel:
    goals: tuple[Goal, ...]
    decisions: tuple[Decision, ...]
    inventory: tuple[Item, ...]
    tracker: tuple[Item, ...]
    diagrams: tuple[Diagram, ...]
    lanes: tuple[Lane, ...]
    asks: tuple[Ask, ...]
    sources: tuple[Source, ...]
    log_rejected: int | None
    # File tracker rows can name a lane even when it has no local brief.
    file_lane_states: Mapping[str, str | None] = field(default_factory=dict)


@dataclass(frozen=True)
class UnknownStatus:
    origin: Origin
    word: str = field(repr=False)


@dataclass(frozen=True)
class PlanDiagnostics:
    unknown_statuses: tuple[UnknownStatus, ...]
    goal_lane_mismatches: int | None


@dataclass(frozen=True)
class PlanResult:
    model: PlanModel
    diagnostics: PlanDiagnostics = field(repr=False)
