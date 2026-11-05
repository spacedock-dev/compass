"""Private map hypotheses bound to originals; never a criterion, fact or assessment."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any

from . import reading, reading_pass_context, reading_passes, records

if TYPE_CHECKING:
    from collections.abc import Collection, Sequence

MAX_CANDIDATES = 16
MAX_CITES = 6
DETAIL_CHARS = 400
KINDS = frozenset({"supports", "departs", "uncertain", "conflicting"})


@dataclass(frozen=True)
class BoundCitation:
    menu: int
    span: reading_passes.EvidenceRange
    primary: tuple[reading_passes.EvidenceRange, ...]
    context: tuple[reading_passes.EvidenceRange, ...]


@dataclass(frozen=True)
class Candidate:
    clause: str
    kind: str
    cites: tuple[BoundCitation, ...]
    detail: str


@dataclass(frozen=True)
class MapReply:
    reason: str
    candidates: tuple[Candidate, ...] = ()

    @property
    def usable(self) -> bool:
        return self.reason == "ok"


def _time(value: Any) -> bool:
    return type(value) in (int, float) and 0 < value < 2**53 and math.isfinite(value)


def _range(span: reading_passes.EvidenceRange) -> bool:
    values = (span.start, span.end, span.total)
    return all(v is None for v in values) or (
        all(type(v) is int and 0 <= v < 2**53 for v in values)
        and span.start is not None
        and span.end is not None
        and span.total is not None
        and span.start < span.end <= span.total
    )


def _roles(
    spans: Sequence[object], rows: dict[str, reading.LedgerEntry], *, multiple: bool = False
) -> dict[str, tuple[reading_passes.EvidenceRange, ...]] | None:
    result: dict[str, tuple[reading_passes.EvidenceRange, ...]] = {}
    for span in spans:
        if not isinstance(span, reading_passes.EvidenceRange):
            return None
        if (
            not isinstance(span.fact_id, str)
            or span.fact_id not in rows
            or (span.fact_id in result and (not multiple or span in result[span.fact_id]))
            or not _time(span.at)
            or span.at != rows[span.fact_id]["at"]
            or not _range(span)
        ):
            return None
        result[span.fact_id] = (*result.get(span.fact_id, ()), replace(span))
    return result


def _merged(
    spans: tuple[reading_passes.EvidenceRange, ...], row: reading.LedgerEntry
) -> reading_passes.EvidenceRange | None:
    message = row["type"] in {"user_message", reading.AGENT_MESSAGE_TYPE}
    if (
        not spans
        or len({s.total for s in spans}) != 1
        or (not message and spans[0].start is not None)
    ):
        return None
    if spans[0].start is None:
        return None if message else replace(spans[0])
    starts = [s.start for s in spans if s.start is not None]
    ends = [s.end for s in spans if s.end is not None]
    if len(starts) != len(spans) or len(ends) != len(spans):
        return None
    ordered = sorted(zip(starts, ends, strict=True))
    start, end = ordered[0]
    for next_start, next_end in ordered[1:]:
        if next_start > end:
            return None
        end = max(end, next_end)
    merged = replace(spans[0], start=start, end=end)
    words = (
        json.loads(row.get("agent_words", ""))
        if row["type"] == reading.AGENT_MESSAGE_TYPE
        else row.get("words")
    )
    length = end - start
    if (
        not isinstance(words, str)
        or len(words) != length
        or type(row.get("text_read")) is not int
        or row.get("text_read") != length
        or type(row.get("text_total")) is not int
        or row.get("text_total") != merged.total
    ):
        return None
    words.encode("utf-8")
    return merged


def _bindings(packet: reading_passes.EvidencePacket) -> dict[int, BoundCitation] | None:
    if (
        not isinstance(packet, reading_passes.EvidencePacket)
        or not isinstance(packet.selection, reading.Selection)
        or not packet.selection.entries
        or not packet.primary
    ):
        return None
    rows: dict[str, reading.LedgerEntry] = {}
    for row in packet.selection.entries:
        identity = row.get("id")
        if (
            not isinstance(identity, str)
            or not identity
            or identity in rows
            or not _time(row.get("at"))
        ):
            return None
        rows[identity] = row
    primary, context = _roles(packet.primary, rows), _roles(packet.context, rows, multiple=True)
    if primary is None or context is None:
        return None
    bound: dict[int, BoundCitation] = {}
    for index, row in packet.selection.by_index().items():
        own = primary.get(row["id"], ())
        adjacent = context.get(row["id"], ())
        merged = _merged((*own, *adjacent), row)
        if merged is None:
            return None
        bound[index] = BoundCitation(index, merged, own, adjacent)
    # Prefix instructions may contain citation examples. Only the renderer-owned final
    # role/menu suffix defines evidence; scanning every '[n]' would admit those examples.
    suffix = reading_passes.render_packet_evidence(packet.selection, packet.primary, packet.context)
    packet.prompt.encode("utf-8")
    return (
        bound
        if packet.prompt.endswith("\n" + suffix)
        and _intent_matches(
            packet.prompt[: -len(suffix)], packet.selection.lines, packet.frozen_context
        )
        else None
    )


def _intent_matches(
    header: str, lines: Sequence[str], context: reading_pass_context.Frozen | None
) -> bool:
    # Work backwards from the actual evidence suffix. Examples in the protocol prefix
    # cannot replace this adjacent header, and newlines inside JSON values are escaped.
    if not header.endswith(reading_passes.EVIDENCE_BOUNDARY):
        return False
    framed = header[: -len(reading_passes.EVIDENCE_BOUNDARY)]
    _prefix, boundary, raw = framed.rpartition(reading_passes.FROZEN_INTENT_BOUNDARY)
    if not boundary or "\n" in raw or "\r" in raw:
        return False
    value = json.loads(raw, object_pairs_hook=_object)
    if (
        not isinstance(value, dict)
        or set(value)
        != (
            ({"goal", "lines"} if context is None else {"goal", "lines", "context"})
            | (
                {"restored_goal"}
                if context is not None and context.goal_proof is not None
                else set()
            )
        )
        or not isinstance(value["goal"], str)
        or not isinstance(value["lines"], list)
        or any(not isinstance(line, str) for line in value["lines"])
    ):
        return False
    for text in (value["goal"], *value["lines"]):
        text.encode("utf-8")
    expected = reading_pass_context.intent(value["goal"], lines, context)
    expected["lines"] = list(lines)
    return value == expected


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def _candidate(value: Any, clauses: Sequence[str], bound: dict[int, BoundCitation]) -> bool:
    if not isinstance(value, dict) or set(value) != {"clause", "kind", "cites", "detail"}:
        return False
    cites = value["cites"]
    return (
        isinstance(value["clause"], str)
        and value["clause"] in clauses
        and isinstance(value["kind"], str)
        and value["kind"] in KINDS
        and isinstance(value["detail"], str)
        and isinstance(cites, list)
        and 1 <= len(cites) <= MAX_CITES
        and all(type(index) is int and index in bound for index in cites)
        and len(set(cites)) == len(cites)
    )


def _decode(raw: object) -> tuple[list[Any], str]:
    if not isinstance(raw, str):
        return [], "invalid-reply"
    try:
        if len(raw) > reading.REPLY_CAP_BYTES or len(raw.encode("utf-8")) > reading.REPLY_CAP_BYTES:
            return [], "reply-limit"
        payload = json.loads(raw, object_pairs_hook=_object)
    except (ValueError, RecursionError):
        return [], "invalid-reply"
    if (
        not isinstance(payload, dict)
        or set(payload) != {"version", "candidates"}
        or type(payload["version"]) is not int
        or payload["version"] != 1
        or not isinstance(payload["candidates"], list)
    ):
        return [], "invalid-reply"
    if len(payload["candidates"]) > MAX_CANDIDATES:
        return [], "reply-limit"
    return payload["candidates"], ""


def _detail(raw: str, masked_values: Collection[str], scrub_partial: bool) -> tuple[str, str]:
    if len(raw) > DETAIL_CHARS:
        return "", "reply-limit"
    try:
        raw.encode("utf-8")
    except UnicodeEncodeError:
        return "", "invalid-reply"
    scrubbed = records.scrub(
        records.mask_prose(raw), records.explanation_values(masked_values), prose=True
    )
    if scrub_partial or not scrubbed.complete:
        return "", "scrub-incomplete"
    detail = records.safe_text(scrubbed.text, reading.REPLY_CAP_BYTES)
    if len(detail) > DETAIL_CHARS:
        return "", "reply-limit"
    return detail, ""


def parse_reply(
    raw: object,
    packet: reading_passes.EvidencePacket,
    *,
    clauses: Sequence[str],
    masked_values: Collection[str] = (),
    scrub_partial: bool = False,
) -> MapReply:
    """Parse one closed v1 map reply, discarding the entire pass on any invalid member.

    An ok reply with no candidates only says no hypotheses were proposed. Neither it nor
    any candidate establishes a verdict or complete coverage. No reply salvage or detail
    truncation is allowed; retained prose remains private, scrubbed navigation for originals.
    """
    try:
        bound = _bindings(packet)
        allowed = reading.constraints_for(packet.selection.lines, claims=True)
        if (
            bound is None
            or len(packet.selection.lines) > reading.MAX_OUTCOME_LINES
            or not 1 <= len(clauses) <= reading.MAX_OUTCOME_LINES + 2
            or any(not isinstance(c, str) or c not in allowed for c in clauses)
            or len(set(clauses)) != len(clauses)
        ):
            return MapReply("invalid-packet")
    except (AttributeError, KeyError, TypeError, ValueError, RecursionError):
        return MapReply("invalid-packet")
    values, reason = _decode(raw)
    if reason:
        return MapReply(reason)
    candidates: list[Candidate] = []
    for value in values:
        if not _candidate(value, clauses, bound):
            return MapReply("invalid-reply")
        detail, reason = _detail(value["detail"], masked_values, scrub_partial)
        if reason:
            return MapReply(reason)
        candidates.append(
            Candidate(
                value["clause"], value["kind"], tuple(bound[i] for i in value["cites"]), detail
            )
        )
    return MapReply("ok", tuple(candidates))
