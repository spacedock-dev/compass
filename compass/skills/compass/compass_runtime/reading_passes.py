"""Exact packets of admitted originals; no model or source reader."""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from . import reading, reading_pass_context

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Sequence

FROZEN_INTENT_BOUNDARY = "\nFrozen saved intent (untrusted data):\n"
EVIDENCE_BOUNDARY = "\nOriginal evidence only; this is not the whole session.\n"


@dataclass(frozen=True)
class MessagePacket:
    prompt: str
    selection: reading.Selection
    start: int
    end: int
    total: int


def message_packets(
    row: reading.LedgerEntry,
    *,
    words: str,
    goal: str,
    lines: Sequence[str],
    max_bytes: int,
    final_state: str | None,
) -> Iterator[MessagePacket]:
    """Partition complete, already masked/normalized words without changing their identity.

    The caller supplies an eligible canonical agent row and complete words from the G2
    whole-message source path. That path owns source admission and masks before normalizing;
    this renderer must not remask individual fragments. Offsets index those supplied Unicode
    characters, never raw bytes. Saved intent is already admitted and is serialized intact.
    Unencodable words or intent are refused before any packet, rather than replaced on the wire.

    A strict-final result belongs to a separate whole-message path, including an unfit or
    unavailable result. This ordinary-only leaf cannot turn its fragments into final proof.
    It supplies no verdict protocol and never asserts whole-session agent-word coverage.
    """
    if final_state is not None:
        raise ValueError("Strict-final evidence cannot use ordinary message packets")
    if row["type"] != reading.AGENT_MESSAGE_TYPE or row["author"] != reading.AUTHOR_AGENT:
        raise ValueError("An ordinary agent message is required")
    if not words or type(max_bytes) is not int or max_bytes <= 0:
        raise ValueError("Nonempty complete words and a positive byte bound are required")
    frozen_lines = tuple(lines)
    header = (
        "Frozen saved intent (untrusted data):\n"
        + json.dumps({"goal": goal, "lines": frozen_lines}, ensure_ascii=False)
        + "\nOrdinary message evidence only; this is not the whole session.\n"
    )
    try:
        words.encode("utf-8")
        header.encode("utf-8")
    except UnicodeEncodeError:
        raise ValueError("Message words and saved intent must be UTF-8 encodable") from None
    return _packets(row.copy(), words, frozen_lines, header, max_bytes)


def _packets(
    original: reading.LedgerEntry,
    words: str,
    lines: tuple[str, ...],
    header: str,
    max_bytes: int,
) -> Iterator[MessagePacket]:
    total = len(words)
    start = 0
    while start < total:

        def render(end: int, start: int = start) -> tuple[str, reading.LedgerEntry]:
            selected = original.copy()
            selected["agent_words"] = json.dumps(words[start:end], ensure_ascii=False)
            selected["text_read"] = end - start
            selected["text_total"] = total
            selected.pop("agent_excerpt", None)
            if start or end < total:
                selected["agent_excerpt"] = f"characters {start}-{end} of {total}"
            return header + reading.render_admitted_row(1, selected, whole=True), selected

        lo, hi = start, min(total, start + max_bytes)
        # A whole row omits the range label. Test it before binary search: that shorter
        # representation can fit even when no labelled prefix does.
        if hi == total and len(render(total)[0].encode("utf-8")) <= max_bytes:
            lo = total
        while lo < hi:
            mid = (lo + hi + 1) // 2
            prompt, _selected = render(mid)
            if len(prompt.encode("utf-8")) <= max_bytes:
                lo = mid
            else:
                hi = mid - 1
        if lo == start:
            raise ValueError("Intact intent and one message character do not fit")
        prompt, selected = render(lo)
        yield MessagePacket(
            prompt,
            reading.Selection((selected,), asked_output=False, lines=lines),
            start,
            lo,
            total,
        )
        start = lo


@dataclass(frozen=True)
class Original:
    """A canonical eligible row joined by the caller to its complete G2 message words.

    Non-message rows have no words and remain atomic. Admission, physical ordering and
    applicability of boundary context belong to the caller, not this packet planner.
    """

    row: reading.LedgerEntry
    words: str | None = None
    final_state: str | None = None


@dataclass(frozen=True)
class EvidenceRange:
    """Masked Unicode character offsets, or three None values for an atomic row."""

    fact_id: str
    at: float
    start: int | None
    end: int | None
    total: int | None


@dataclass(frozen=True)
class EvidencePacket:
    prompt: str
    selection: reading.Selection
    primary: tuple[EvidenceRange, ...]
    context: tuple[EvidenceRange, ...]
    frozen_context: reading_pass_context.Frozen | None = None


@dataclass(frozen=True)
class PacketPlan:
    packets: tuple[EvidencePacket, ...]
    uncovered_primary: tuple[EvidenceRange, ...]
    reason: str
    transmitted_bytes: int
    covered_characters: int


def _span(original: Original, start: int = 0, end: int | None = None) -> EvidenceRange:
    words = original.words
    return EvidenceRange(
        original.row["id"],
        original.row["at"],
        start if words is not None else None,
        (len(words) if end is None else end) if words is not None else None,
        len(words) if words is not None else None,
    )


def _union(spans: Sequence[EvidenceRange]) -> dict[str, EvidenceRange]:
    combined: dict[str, EvidenceRange] = {}
    for span in spans:
        previous = combined.get(span.fact_id)
        if previous is None or span.start is None:
            combined[span.fact_id] = span
            continue
        if previous.start is None or previous.end is None or span.end is None:
            raise ValueError("An original cannot mix atomic and character ranges")
        if max(previous.start, span.start) > min(previous.end, span.end):
            raise ValueError("Disjoint ranges cannot become one original menu row")
        combined[span.fact_id] = EvidenceRange(
            span.fact_id,
            span.at,
            min(previous.start, span.start),
            max(previous.end, span.end),
            span.total,
        )
    return combined


def _project(original: Original, span: EvidenceRange) -> reading.LedgerEntry:
    selected = deepcopy(original.row)
    if original.words is None:
        return selected
    if span.start is None or span.end is None:
        raise ValueError("A message projection needs a character range")
    words = original.words[span.start : span.end]
    if selected["type"] == reading.AGENT_MESSAGE_TYPE:
        selected["agent_words"] = json.dumps(words, ensure_ascii=False)
        selected.pop("agent_excerpt", None)
        if span.start or span.end < len(original.words):
            selected["agent_excerpt"] = f"characters {span.start}-{span.end} of {span.total}"
    else:
        selected["words"] = words
        selected.pop("words_excerpt", None)
        if span.start or span.end < len(original.words):
            selected["words_excerpt"] = f"characters {span.start}-{span.end} of {span.total}"
    selected["text_read"] = len(words)
    selected["text_total"] = len(original.words)
    return selected


def _packet(
    sources: dict[str, tuple[int, Original]],
    primary: Sequence[EvidenceRange],
    context: Sequence[EvidenceRange],
    header: str,
    lines: tuple[str, ...],
    *,
    measure: bool = False,
    frozen_context: reading_pass_context.Frozen | None = None,
) -> EvidencePacket:
    combined = _union((*context, *primary))
    identities = sorted(combined, key=lambda key: sources[key][0])
    selected = tuple(_project(sources[key][1], combined[key]) for key in identities)
    selection = reading.Selection(selected, asked_output=False, lines=lines)
    if measure:
        selection = replace(
            selection,
            diagnostic=reading.selection_diagnostic(
                [original.row for _, original in sources.values()],
                selected,
                _render_rows(selection),
                expanded=True,
            ),
        )
    return EvidencePacket(
        header + render_packet_evidence(selection, primary, context),
        selection,
        tuple(primary),
        tuple(context),
        frozen_context,
    )


def render_packet_evidence(
    selection: reading.Selection,
    primary: Sequence[EvidenceRange],
    context: Sequence[EvidenceRange],
) -> str:
    """The exact role/menu suffix, shared by assembly and map citation binding."""
    numbers = {row["id"]: index for index, row in selection.by_index().items()}
    roles = {
        name: [[numbers[s.fact_id], s.start, s.end, s.total] for s in spans]
        for name, spans in (("primary", primary), ("context", context))
    }
    return (
        "Range roles (menu, start, end, total):\n"
        + json.dumps(roles)
        + "\n"
        + "".join(_render_rows(selection))
    )


def _render_rows(selection: reading.Selection) -> list[str]:
    body: list[str] = []
    for index, row in selection.by_index().items():
        rendered = row
        if row["type"] == "user_message":
            # The Selection keeps person words in their existing raw-string representation;
            # the prompt quotes them as data without changing their source character offsets.
            rendered = {**row, "words": json.dumps(row["words"], ensure_ascii=False)}
        body.append(
            reading.render_admitted_row(
                index, rendered, whole=row["type"] in {"user_message", reading.AGENT_MESSAGE_TYPE}
            )
        )
    return body


def _sources(originals: Sequence[Original]) -> dict[str, tuple[int, Original]]:
    sources: dict[str, tuple[int, Original]] = {}
    for index, original in enumerate(originals):
        row, words = original.row, original.words
        if not row["id"] or row["id"] in sources:
            raise ValueError("Each original must have a unique canonical identity")
        if original.final_state is not None:
            raise ValueError("Strict-final evidence cannot use ordinary message packets")
        message = row["type"] in {"user_message", reading.AGENT_MESSAGE_TYPE}
        if message:
            author = (
                reading.AUTHOR_PERSON if row["type"] == "user_message" else reading.AUTHOR_AGENT
            )
            if row["author"] != author or not isinstance(words, str) or not words:
                raise ValueError("Message originals require complete admitted words and authorship")
        elif words is not None:
            raise ValueError("Only message originals may supply words")
        try:
            json.dumps(row, ensure_ascii=False).encode("utf-8")
            if words is not None:
                words.encode("utf-8")
        except UnicodeEncodeError:
            raise ValueError("Originals must be UTF-8 encodable") from None
        sources[row["id"]] = index, Original(deepcopy(row), words)
    return sources


def _fill_primary(
    ordered: Sequence[Original],
    cursor: int,
    start: int,
    fits: Callable[[Sequence[EvidenceRange]], bool],
    max_bytes: int,
) -> tuple[list[EvidenceRange], int, int]:
    primary: list[EvidenceRange] = []
    while cursor < len(ordered):
        original = ordered[cursor]
        whole = _span(original, start)
        if fits([*primary, whole]):
            primary.append(whole)
            cursor, start = cursor + 1, 0
            continue
        if original.words is not None:
            lo, hi = start, min(len(original.words), start + max_bytes)
            while lo < hi:
                mid = (lo + hi + 1) // 2
                if fits([*primary, _span(original, start, mid)]):
                    lo = mid
                else:
                    hi = mid - 1
            if lo > start:
                primary.append(_span(original, start, lo))
                start = lo
        break
    return primary, cursor, start


def _observe_preparation(
    observer: Callable[[int, EvidencePacket | None], None] | None,
    ordinal: int,
    packet: EvidencePacket | None = None,
) -> None:
    if observer is not None:
        observer(ordinal, packet)


def _unfit_reason(context: Sequence[EvidenceRange], cap: int, maximum: int) -> str:
    if cap < maximum:
        return "input-limit"
    return "context-unfit" if context else "prompt-unfit"


def _validate_limits(
    max_bytes: int, max_passes: int, overlap_chars: int, total_bytes: int | None
) -> None:
    if (
        type(max_bytes) is not int
        or max_bytes <= 0
        or type(max_passes) is not int
        or not 1 <= max_passes <= 16
        or type(overlap_chars) is not int
        or overlap_chars < 0
    ):
        raise ValueError("Positive byte/pass bounds and nonnegative overlap are required")
    if total_bytes is not None and (type(total_bytes) is not int or total_bytes < 0):
        raise ValueError("Aggregate packet bytes must be a nonnegative count")


def plan_packets(  # noqa: PLR0913 - bounded packet allocation and preparation observation
    originals: Sequence[Original],
    *,
    goal: str,
    lines: Sequence[str],
    protocol_prefix: str,
    max_bytes: int,
    max_passes: int,
    boundary_context: Sequence[str] = (),
    overlap_chars: int = 0,
    total_bytes: int | None = None,
    on_preparation: Callable[[int, EvidencePacket | None], None] | None = None,
    frozen_context: reading_pass_context.Frozen | None = None,
) -> PacketPlan:
    """Pack caller-ordered originals, stopping at the first uncovered primary range.

    Boundary context names whole originals required in every packet. Overlap repeats at
    most `overlap_chars` from the last primary message range of the preceding packet.
    Both are bounded by the exact prompt cap; neither is silently dropped when unfit.
    Context never advances the primary cursor. `covered_characters` counts the union of
    all serialized message ranges, while `uncovered_primary` separately names unassigned
    primary ranges (which may already have appeared as required context).

    The caller's complete protocol prefix is included before any allocation. The returned
    prompts are final byte-budgeted packets: appending instructions invalidates their fit.
    An optional total byte cap charges every repeated serialized byte during allocation.
    Preparation observation receives (ordinal, None) before construction and then the
    final packet; an unfit position has no final packet. Shared preparation belongs to
    the first position. These observations establish no transmission or reservation.
    """
    _validate_limits(max_bytes, max_passes, overlap_chars, total_bytes)
    _observe_preparation(on_preparation, 1)
    sources = _sources(originals)
    ordered = [original for _, original in sources.values()]
    if any(key not in sources for key in boundary_context):
        raise ValueError("Boundary context must name an admitted original")
    required = tuple(_span(sources[key][1]) for key in dict.fromkeys(boundary_context))
    frozen_lines = tuple(lines)
    header = (
        protocol_prefix
        + FROZEN_INTENT_BOUNDARY
        + json.dumps(
            reading_pass_context.intent(goal, frozen_lines, frozen_context), ensure_ascii=False
        )
        + EVIDENCE_BOUNDARY
    )
    try:
        header.encode("utf-8")
    except UnicodeEncodeError:
        raise ValueError("Protocol and saved intent must be UTF-8 encodable") from None
    packets: list[EvidencePacket] = []
    cursor = start = transmitted = 0
    reason = "complete"
    while cursor < len(ordered) and len(packets) < max_passes:
        ordinal = len(packets) + 1
        if packets:
            _observe_preparation(on_preparation, ordinal)
        cap = max_bytes if total_bytes is None else min(max_bytes, total_bytes - transmitted)
        context = list(required)
        if (
            packets
            and overlap_chars
            and (last := packets[-1].primary[-1]).start is not None
            and last.end is not None
        ):
            context.append(
                EvidenceRange(
                    last.fact_id,
                    last.at,
                    max(last.start, last.end - overlap_chars),
                    last.end,
                    last.total,
                )
            )
        held = tuple(_union(context).values())

        def fits(
            candidate: Sequence[EvidenceRange],
            held: tuple[EvidenceRange, ...] = held,
            cap: int = cap,
        ) -> bool:
            prompt = _packet(sources, candidate, held, header, frozen_lines).prompt
            return len(prompt.encode()) <= cap

        if not fits(()):
            reason = _unfit_reason(held, cap, max_bytes)
            break
        primary, cursor, start = _fill_primary(ordered, cursor, start, fits, cap)
        if not primary:
            reason = _unfit_reason(held, cap, max_bytes)
            break
        packet = _packet(
            sources,
            primary,
            held,
            header,
            frozen_lines,
            measure=True,
            frozen_context=frozen_context,
        )
        packets.append(packet)
        transmitted += len(packet.prompt.encode())
        _observe_preparation(on_preparation, ordinal, packet)
    remaining = tuple(
        _span(original, start if index == cursor else 0)
        for index, original in enumerate(ordered)
        if index >= cursor
    )
    if remaining and reason == "complete":
        reason = "pass-limit"
    covered = _union(tuple(span for p in packets for span in (*p.context, *p.primary)))
    return PacketPlan(
        tuple(packets),
        remaining,
        reason,
        sum(len(packet.prompt.encode()) for packet in packets),
        sum(s.end - s.start for s in covered.values() if s.start is not None and s.end is not None),
    )
