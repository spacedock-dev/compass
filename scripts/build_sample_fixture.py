#!/usr/bin/env python3
"""Capture the sample session's page data from an isolated Compass server into one fixture file.

The sample session is a real, anonymized Claude Code session read by a real Compass server and a
real stored reading (see [sample-session/README.md](sample-session/README.md)). This script asks
that server for exactly what the Session page asks for, and writes the answers to one JSON file the
page bundles. The server is never the user's own: it runs against an isolated home, so nothing
about a real machine or session can reach the capture.

    build_sample_fixture.py --base-url http://127.0.0.1:4712 --project acme/dashboard \
        --sid f7352072 --out frontend/src/sample/session.fixture.json

Three rewrites make the capture a stable sample rather than a snapshot of one afternoon:

- The session id becomes `sample`, the id the page reserves for it.
- Every time within six hours of the capture moves to just after the session's last record, so "5m
  ago" reads the same on any day and the stored reading sits where it was read.
- The one-line sentence that counted entries "about 3718h ago" says "all within the last hour",
  which is what the same words say when the reading is read on the day.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SAMPLE_SID = "sample"
SIX_HOURS = 6 * 3600
READ_AFTER_LAST_RECORD = 45
GENERATED_AFTER_LAST_RECORD = 95


def fetch(base: str, path: str, body: dict[str, Any] | None = None) -> Any:
    request = urllib.request.Request(  # noqa: S310 - the caller names a local server
        base + path,
        data=None if body is None else json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="GET" if body is None else "POST",
    )
    with urllib.request.urlopen(request, timeout=60) as reply:  # noqa: S310
        return json.load(reply)


def fmt_duration(seconds: float) -> str:
    """The server's own short form (`sessions.fmt_duration`): 45s, 11m, 2h 5m, 3d 4h."""
    whole = int(seconds)
    if whole < 60:
        return f"{whole}s"
    if whole < 3600:
        return f"{whole // 60}m"
    if whole < 86400:
        return f"{whole // 3600}h {(whole % 3600) // 60}m"
    return f"{whole // 86400}d {(whole % 86400) // 3600}h"


def last_record_time(context: dict[str, Any]) -> float:
    times = [
        float(f["at"])
        for f in context["semantic"]["facts"]
        if isinstance(f.get("at"), (int, float))
    ]
    return max(times)


def shift_numbers(node: Any, captured: float, delta: float) -> Any:
    """Move every time within six hours of the capture by `delta`; leave every other number."""
    if isinstance(node, bool):
        return node
    if isinstance(node, (int, float)):
        return node - delta if abs(node - captured) < SIX_HOURS and node > 1e9 else node
    if isinstance(node, list):
        return [shift_numbers(item, captured, delta) for item in node]
    if isinstance(node, dict):
        return {key: shift_numbers(item, captured, delta) for key, item in node.items()}
    return node


def rename(node: Any, old: str, new: str) -> Any:
    if isinstance(node, str):
        return node.replace(old, new)
    if isinstance(node, list):
        return [rename(item, old, new) for item in node]
    if isinstance(node, dict):
        return {rename(key, old, new): rename(item, old, new) for key, item in node.items()}
    return node


def build(base: str, project: str, sid: str) -> dict[str, Any]:
    quote = urllib.parse.quote
    session = f"claude:{sid}"
    stem = f"project={quote(project, safe='')}&session={quote(session, safe='')}"
    board = fetch(base, "/api/data")
    context = fetch(base, f"/api/project-context?{stem}")
    prompts = fetch(base, f"/api/project-context?{stem}&prompts=1")
    record = fetch(base, f"/api/session-record?{stem}&limit=50")
    correction = fetch(base, "/api/correction", {"harness": "claude", "sid": sid})
    rows = [row for row in board["sessions"] if row["sid"] == sid]
    if len(rows) != 1:
        msg = f"expected exactly one session {sid}, found {len(rows)}"
        raise SystemExit(msg)
    captured = float(board["generated"])
    last = last_record_time(context)
    delta = captured - (last + GENERATED_AFTER_LAST_RECORD)
    board["sessions"] = rows
    fixture: dict[str, Any] = {
        "board": board,
        "context": context,
        "prompts": prompts,
        "record": record,
        "correction": correction,
    }
    fixture = shift_numbers(fixture, captured, delta)
    fixture = rename(fixture, sid, SAMPLE_SID)
    row = fixture["board"]["sessions"][0]
    assessment = row["annotation_assessment"]
    assessment["read_at"] = last + READ_AFTER_LAST_RECORD
    assessment["stamp"] = (
        f"{assessment['stamp'].split(' · ')[0]} · read at "
        f"{datetime.fromtimestamp(assessment['read_at'], UTC):%H:%M}"
    )
    assessment["cutoff"] = re.sub(
        r"the oldest about \d+h ago", "all within the last hour", assessment["cutoff"]
    )
    for level in fixture["context"]["sources"]["work"].get("analysis_levels", []):
        level["read_at"] = assessment["read_at"]
    # The server wrote the turn's elapsed time from the wall clock ("154d 22h"); it is the time from
    # the first prompt to the moment the sample is frozen at.
    turn = row["turn"]
    turn["elapsed_h"] = fmt_duration(fixture["board"]["generated"] - row["started_at"])
    turn["long"] = False
    # The board's digest of the isolated store the reading was saved in. Shortened so it is plainly
    # a label and not a credential-length value.
    fixture["board"]["intent_revision"] = str(fixture["board"]["intent_revision"])[:32]
    # One reading was read; a refused attempt on the way to it is not part of the story.
    fixture["board"]["reading"]["used"] = 1
    # The reading was captured under the old Allow step, so its server read consent as missing. The
    # sample is shown as this build reads a store with no stored off: readings on, nothing refused,
    # and no notice recorded yet.
    fixture["board"]["reading"].update(consent=True, off=False, reason="", notices={})
    row["annotation_reading_count"] = 1
    return fixture


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--project", required=True)
    parser.add_argument("--sid", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    fixture = build(args.base_url.rstrip("/"), args.project, args.sid)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(fixture, indent=1, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"wrote {args.out} ({args.out.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
