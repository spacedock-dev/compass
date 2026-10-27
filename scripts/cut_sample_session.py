#!/usr/bin/env python3
"""Cut one contiguous stretch out of a Claude Code session log, before it is anonymized.

The sample session is a bounded stretch of a longer real session (see
[sample-session/README.md](../sample-session/README.md)). This script keeps the records from one
uuid to another, inclusive, and only the record kinds the page reads or the story needs: the
person's and the agent's messages, the conversation's compaction marker and turn timings, the
pull-request links and the title. Everything else Claude Code writes beside them (context
attachments such as the loaded instructions and tool lists, account and remote-session records,
editor snapshots, mode switches) is dropped, because Compass reads none of it and most of it
describes the machine rather than the work.

    cut_sample_session.py --input session.jsonl --output cut.jsonl --first UUID --last UUID

A kept record whose parent was dropped is re-parented to the nearest kept ancestor, so the chain
of records stays whole. The first record's parent lies before the cut, and the sanitizer nulls it.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

KEPT_TYPES = frozenset({"user", "assistant", "system", "pr-link", "ai-title"})
# A stop hook's summary names the hooks installed on the machine; the other system records are the
# compaction marker and turn timings, which say only when things happened.
KEPT_SYSTEM_SUBTYPES = frozenset({"compact_boundary", "turn_duration"})


def kept(record: dict[str, Any]) -> bool:
    kind = record.get("type")
    if kind not in KEPT_TYPES:
        return False
    return kind != "system" or record.get("subtype") in KEPT_SYSTEM_SUBTYPES


def cut(records: list[dict[str, Any]], first: str, last: str) -> list[dict[str, Any]]:
    """The records from `first` to `last` inclusive, filtered and re-parented."""
    positions = {record.get("uuid"): index for index, record in enumerate(records)}
    if first not in positions or last not in positions:
        msg = "both --first and --last must name a record uuid in the input"
        raise SystemExit(msg)
    start, end = positions[first], positions[last]
    if end < start:
        msg = "--last comes before --first"
        raise SystemExit(msg)
    stretch = records[start : end + 1]
    # Only the stretch's own records: a parent before the cut is left for the sanitizer to null,
    # rather than walked back to the session's first record.
    parent_of = {r["uuid"]: r.get("parentUuid") for r in stretch if r.get("uuid")}
    keep = [record for record in stretch if kept(record)]
    kept_ids = {record["uuid"] for record in keep if record.get("uuid")}
    out: list[dict[str, Any]] = []
    for record in keep:
        parent = record.get("parentUuid")
        seen: set[str] = set()
        # Walk up past dropped records; stop at a kept one, or at the start of the stretch.
        while parent and parent not in kept_ids and parent in parent_of and parent not in seen:
            seen.add(parent)
            parent = parent_of[parent]
        out.append({**record, "parentUuid": parent} if "parentUuid" in record else record)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--first", required=True, help="uuid of the first record to keep")
    parser.add_argument("--last", required=True, help="uuid of the last record to keep")
    args = parser.parse_args(argv)
    records = [
        json.loads(line)
        for line in args.input.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    out = cut(records, args.first, args.last)
    args.output.write_text(
        "".join(json.dumps(r, ensure_ascii=False, separators=(",", ":")) + "\n" for r in out),
        encoding="utf-8",
    )
    print(f"kept {len(out)} of the stretch's records")
    return 0


if __name__ == "__main__":
    sys.exit(main())
