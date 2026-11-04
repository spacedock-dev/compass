"""Exact packets of one admitted ordinary agent message; no model or source reader."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING

from . import reading

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence


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
