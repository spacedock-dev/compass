"""Strict newest-final proof from a verified whole parent, without content I/O."""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any

from . import project_context as context
from . import reading
from . import reading_source_stream as raw_source

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from .config import RuntimeConfig


def _current(parent: raw_source.FrozenParent, stamp: raw_source.Stamp | None) -> bool:
    if stamp is None or stamp[:2] != (parent.device, parent.inode) or stamp[2] != parent.end_offset:
        return False
    try:
        info = os.stat(parent.path)
        return stat.S_ISREG(info.st_mode) and raw_source._stamp(info) == stamp  # noqa: SLF001
    except OSError:
        return False


@dataclass(frozen=True)
class Proof:
    result: dict[str, Any]
    # Retain and charge all proof indices/words until collection relinquishes them.
    scratch: context._FinalWordRead | None = None
    stamp: raw_source.Stamp | None = None

    @property
    def unfit(self) -> tuple[str, float] | None:
        if self.result.get("outcome") == "too-long":
            return self.result["fact_id"], self.result["at"]
        return None

    def recheck(self, parent: raw_source.FrozenParent) -> Proof:
        if self.stamp is not None and not _current(parent, self.stamp):
            return replace(self, result={"outcome": "source-moved"})
        return self


class _IncompleteError(Exception):
    pass


def _lines(
    rows: tuple[raw_source.RawRecord, ...], end: int, checkpoint: Callable[[], None]
) -> Iterator[bytes]:
    # A complete raw corpus has newline-terminated physical records. The old
    # reverse reader sees the trailing empty line too; preserve its byte proof.
    checkpoint()
    yield b""
    frontier = end
    for row in reversed(rows):
        checkpoint()
        if (
            row.end_offset != frontier
            or len(row.raw) != row.end_offset - row.start_offset
            or not row.raw.endswith(b"\n")
        ):
            raise _IncompleteError
        yield row.raw[:-1]
        checkpoint()
        frontier = row.start_offset
    if frontier:
        raise _IncompleteError
    checkpoint()


def build(  # noqa: PLR0911 - explicit strict-bound and current-version refusals
    config: RuntimeConfig,
    parent: raw_source.FrozenParent,
    rows: tuple[raw_source.RawRecord, ...],
    facts: tuple[dict[str, Any], ...],
    *,
    stamp: raw_source.Stamp | None,
    checkpoint: Callable[[], None],
) -> Proof:
    """Apply the unchanged strict proof; current extent must equal verified extent.

    Construction is bounded scratch under the strict file/record/UUID/text
    limits. The collector measures the returned graph before accepting it.
    """
    checkpoint()
    wanted = [
        {"id": fact["fact_id"], "at": fact["at"], "type": "agent_message", "author": "agent"}
        for fact in facts
        if fact.get("type") == "agent_message"
        and fact.get("source_session") == {"harness": parent.harness, "sid": parent.sid}
        and fact.get(reading.COMPASS_TURN_FLAG) is not True
    ]
    selected = context._final_word_rows(wanted)  # noqa: SLF001
    if parent.harness not in context.AGENT_MESSAGE_HARNESSES or not selected:
        return Proof({"outcome": "none"})
    if not _current(parent, stamp):
        return Proof({"outcome": "source-moved"})
    if parent.end_offset > context.FINAL_WORDS_SCAN_MAX_BYTES:
        return Proof({"outcome": "scan-limit"}, stamp=stamp)
    scratch = context._FinalWordRead(  # noqa: SLF001
        selected,
        parent.harness,
        parent.sid,
        context._final_source_sid(parent.path, parent.harness, parent.sid),  # noqa: SLF001
    )
    try:
        scratch = context._read_final_word_proof(  # noqa: SLF001
            config, scratch, _lines(rows, parent.end_offset, checkpoint)
        )
    except _IncompleteError:
        return Proof({"outcome": "unproven"}, scratch, stamp)
    checkpoint()
    if not _current(parent, stamp):
        return Proof({"outcome": "source-moved"}, scratch, stamp)
    if scratch.failure:
        return Proof({"outcome": scratch.failure}, scratch, stamp)
    if scratch.scanned_bytes != parent.end_offset + 1:
        return Proof({"outcome": "unproven"}, scratch, stamp)
    result = context._final_word_outcome(scratch)  # noqa: SLF001
    checkpoint()
    return Proof(result, scratch, stamp)
