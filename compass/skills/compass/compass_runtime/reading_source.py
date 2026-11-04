"""Private canonical evidence from an already admitted, complete Claude scan.

This projection owns no reader, cache or model. It does not establish frozen-source
coverage or permission to send the private press evidence.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from . import project_context as context

if TYPE_CHECKING:
    from .config import RuntimeConfig


@dataclass(frozen=True)
class CanonicalEvidence:
    facts: tuple[dict[str, Any], ...]
    press: context.PressChecks


def from_complete_scan(
    config: RuntimeConfig,
    scan: context._CheckScan,
    harness: str,
    sid: str,
    *,
    index: Any = None,
    listed_cap: int = context.TOOL_REPORT_MAX_ENTRIES,
) -> CanonicalEvidence:
    """Project a caller-owned native scan; reject a known incomplete read.

    Admission and bounds belong to the scan's producer. Its complete byte reads
    do not prove strict newest-final identity or the absence of malformed records.
    The listing cap remains the canonical listing cap, not a coverage claim.
    """
    if harness != "claude" or not sid.strip():
        raise ValueError("complete source projection requires a Claude session")
    parent = scan.source_reads[0][1] if scan.source_reads else None
    if (
        parent is None
        or scan.unread
        or scan.horizon is not None
        or scan.named_unread
        or scan.parent_failed
        or scan.orphan_unread
        or any(
            read is None or not read.complete or read.failed or read.read_start != 0
            for _path, read in scan.source_reads
        )
    ):
        raise ValueError("complete source projection requires complete stream reads")
    tally = context._tally_from_scan(scan)  # noqa: SLF001
    lines = [raw.decode("utf-8", "replace") for raw in parent.lines]
    facts = context._user_message_facts(config, lines, sid, float("inf"))  # noqa: SLF001
    events = context._agent_message_lines(config, lines, harness, sid)  # noqa: SLF001
    events.extend(tally.entries(sid, index, cap=listed_cap))
    for event in events:
        kind = str(event["kind"])
        work_item, *_ = context._semantic_work_identity(event, kind)  # noqa: SLF001
        fact_type = context._SEMANTIC_FACT_TYPES[kind]  # noqa: SLF001
        facts.append(
            context._semantic_fact_from_event(  # noqa: SLF001
                event, kind, fact_type, work_item
            )
        )
    facts.sort(key=lambda fact: float(fact.get("at") or 0), reverse=True)
    # Canonical facts retain nested run lists, and PressChecks retains tail maps.
    # Neither may share mutable state with another projection or its native input.
    return CanonicalEvidence(tuple(copy.deepcopy(facts)), copy.deepcopy(context._press(tally)))  # noqa: SLF001
