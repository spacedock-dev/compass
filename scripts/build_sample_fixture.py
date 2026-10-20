#!/usr/bin/env python3
"""Capture the sample session's page data from an isolated Compass server into one fixture file.

The sample session is a real, anonymized Claude Code session read by a real Compass server and a
real stored reading (see [sample-session/README.md](sample-session/README.md)). This script asks
that server for exactly what the Session page asks for, and writes the answers to one JSON file the
page bundles. That includes every page of the session's record, back to its start, so a citation
anywhere in the sample opens in Full activity. The server is never the user's own: it runs
against an isolated home, so nothing about a real machine or session can reach the capture.

    build_sample_fixture.py --base-url http://127.0.0.1:4712 --project acme/dashboard \
        --sid f7352072 --out frontend/src/sample/session.fixture.json

These rewrites make the capture a stable sample rather than a snapshot of one afternoon:

- The session id becomes `sample`, the id the page reserves for it.
- Every time within six hours of the capture moves to just after the session's last record, so "5m
  ago" reads the same on any day, and the stored summary and reading sit where they were made: the
  summary first, as it is made when the finished session is opened, then the reading, then the
  settling of the later directions.
- The one-line sentence that counted entries "about 3846h ago" counts them from the reading's own
  moment on that timeline, which is what the same words say when the reading is read on the day.
- The correction is composed here by `correction.compose`, from the fixture's own row and record,
  rather than kept from the capture, so it carries what the composer carries now (each departure's
  explanation, the agent's quoted words and no entry numbers since the owner's rulings of
  2026-10-20). Its times are kept as moments, which the sample's own server draws on the reader's
  local clock as the real route does. `--recompose` rewrites only that field of an existing
  fixture.
- The digests that bind the capture's stores (the board's intent revision, the summary's prompt
  digest in its model stamp) are cut to 32 characters, so nothing in the file is a credential-length
  value.
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
# The page's own page size and its cap on pages read to resolve a citation (`RECORD_PAGE_SIZE` and
# `RESOLVE_MAX_PAGES` in frontend/src/transport/record.ts). A sample whose record needs more pages
# than a citation could ever reach is too long to ship, so the capture refuses it.
RECORD_PAGE_SIZE = 50
RECORD_MAX_PAGES = 20
OLDER_CURSOR = "older-{}"
SUMMARIZED_AFTER_LAST_RECORD = 30
READ_AFTER_LAST_RECORD = 45
SETTLED_AFTER_LAST_RECORD = 60
# A correction's time, kept as its moment for the sample's server to draw (`recompose_correction`).
# `frontend/src/sample/sampleFetch.ts` reads the same shape.
CLOCK_MARK = "{{{{clock:{at}}}}}"
GENERATED_AFTER_LAST_RECORD = 95
DIGEST_CHARS = 32
SKILL = Path(__file__).resolve().parents[1] / "compass" / "skills" / "compass"


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


def cutoff_on_timeline(assessment: dict[str, Any]) -> str:
    """The cutoff sentence's age, counted from the reading's place on the sample's timeline.

    The server counts the oldest entry's age from the wall clock it read at
    (`reading._cutoff_window`), which the capture put months after the session; from the reading's
    own moment the same entries are an hour or two old.
    """
    oldest = assessment.get("window_start") or assessment["coverage"]["tail_start"]
    hours = max(0, int((assessment["read_at"] - oldest) // 3600))

    def age(match: re.Match[str]) -> str:
        # `_cutoff_window` says "It is" for one entry and "The oldest is" / "All are" for several.
        one = match.group(1) == "It is"
        if hours:
            return f"{match.group(1)} from about {hours}h ago"
        return ("It is" if one else "All are") + " from within the last hour"

    return re.sub(r"(The oldest is|It is) from about \d+h ago", age, assessment["cutoff"])


def place_summary(fixture: dict[str, Any], made_at: float) -> None:
    """Put the stored summary where it is made on the sample's timeline, and the summary grant as
    this build reads a store with no stored off.

    The summary was made when the finished session was opened, before the reading. Its job's start
    is the same distance before it as the job's own spend says it took. The summary grant is shown
    as a fresh store reads it: on, nothing refused and no notice recorded, with the calls the stored
    summary spent and none from an earlier run the capture replaced.
    """
    summary = fixture["context"]["sources"].get("summary")
    if not isinstance(summary, dict) or not summary.get("exists"):
        return
    seconds = float(summary["spend"]["seconds"])
    # Both focused answers (the context and its prompts read) carry the same stored summary.
    focused = [
        answer["sources"]["summary"]
        for answer in (fixture["context"], fixture["prompts"])
        if isinstance(answer.get("sources", {}).get("summary"), dict)
    ]
    for state in focused:
        stamp = str(state["model_stamp"]).rsplit(":", 1)
        state["model_stamp"] = (
            f"{stamp[0]}:{stamp[1][:DIGEST_CHARS]}" if len(stamp) == 2 else stamp[0]
        )
    for state in [*focused, fixture["board"]["sessions"][0]["summary"]]:
        state["made_at"] = made_at
        job = state.get("job")
        if isinstance(job, dict):
            job["started_at"] = made_at - seconds
            job["notice"] = None
    grant = fixture["board"].get("summaries")
    if isinstance(grant, dict):
        grant.update(
            consent=True,
            off=False,
            reason="",
            retry_at=None,
            notices={},
            used=int(summary["spend"]["calls"]),
        )


def place_reading(fixture: dict[str, Any], last: float) -> None:
    """Put the stored reading, and the settling of the later directions, on the sample's timeline.

    The reading may be kept from an earlier capture than the summary's (the README says when), so
    every moment of it is placed here rather than trusted to the six-hour shift: its read time in
    the row and in both focused answers' levels, its stamp, its age sentence, and the settle that
    followed it in the run that made it.
    """
    row = fixture["board"]["sessions"][0]
    assessment = row["annotation_assessment"]
    assessment["read_at"] = last + READ_AFTER_LAST_RECORD
    assessment["stamp"] = (
        f"{assessment['stamp'].split(' · ')[0]} · read at "
        f"{datetime.fromtimestamp(assessment['read_at'], UTC):%H:%M}"
    )
    assessment["cutoff"] = cutoff_on_timeline(assessment)
    for answer in (fixture["context"], fixture["prompts"]):
        for level in answer["sources"]["work"].get("analysis_levels", []):
            level["read_at"] = assessment["read_at"]
    if row.get("annotation_settled_at") is not None:
        row["annotation_settled_at"] = last + SETTLED_AFTER_LAST_RECORD


def capture_record(base: str, stem: str) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    """The newest record page and every older one, to the record's start.

    The server's cursors bind the capture machine's file (its device, inode, size and time) and are
    signed with a key that dies with the server, so each one is replaced by `older-<n>`: the
    sample's own server answers an older-page request by that name, and nothing about the capture
    survives.
    """
    pages: list[dict[str, Any]] = []
    before: str | None = None
    while len(pages) < RECORD_MAX_PAGES:
        query = f"/api/session-record?{stem}&limit={RECORD_PAGE_SIZE}"
        if before is not None:
            query += f"&before={urllib.parse.quote(before, safe='')}"
        page = fetch(base, query)
        if page.get("state") != "ok":
            msg = f"record page {len(pages) + 1} answered state {page.get('state')!r}"
            raise SystemExit(msg)
        pages.append(page)
        if page.get("reached_start"):
            break
        before = page.get("next")
        if not before:
            msg = f"record page {len(pages)} neither reached the start nor named an older page"
            raise SystemExit(msg)
    else:
        msg = f"the record needs more than {RECORD_MAX_PAGES} pages; cut the sample shorter"
        raise SystemExit(msg)
    for index, page in enumerate(pages):
        page["next"] = None if page.get("reached_start") else OLDER_CURSOR.format(index + 1)
    older = {OLDER_CURSOR.format(index): page for index, page in enumerate(pages[1:], 1)}
    return pages[0], older


def recompose_correction(fixture: dict[str, Any]) -> dict[str, Any]:
    """What `POST /api/correction` composes from the fixture's own row and record.

    The route's inputs as the fixture holds them: the Claude route judges lines, no line was
    re-requested, and the typed goal's floor is when it was saved. Each time is stored as a
    `CLOCK_MARK` holding its moment rather than drawn: the route writes the reader's local time
    (owner, 2026-10-20), and a stored text drawn in one zone would name 11:23 beside a page that
    says 19:23. The sample's server draws each mark on the reader's clock, by the rule
    `correction.zone_clock` draws by (`createSampleFetch`).
    """
    if str(SKILL) not in sys.path:
        sys.path.insert(0, str(SKILL))
    from compass_runtime import correction  # noqa: PLC0415 - the skill runtime, on demand

    row = fixture["board"]["sessions"][0]
    context = fixture["context"]
    semantic = context.get("semantic") or {}
    work = (context.get("sources") or {}).get("work") or {}
    scan: dict[str, Any] = next(
        (
            s
            for s in work.get("tool_reports") or []
            if s.get("harness") == row["harness"] and s.get("sid") == row["sid"]
        ),
        {},
    )
    floor = row.get("annotation_goal_source_at") or row.get("annotation_goal_saved_at")
    return correction.compose(
        row,
        semantic.get("facts") or [],
        floor=float(floor) if floor is not None else None,
        lines_judged=True,
        clock=lambda at: CLOCK_MARK.format(at=repr(float(at))),
        person_at=scan.get("last_user_at"),
        line_requests={},
    )


def build(base: str, project: str, sid: str) -> dict[str, Any]:
    quote = urllib.parse.quote
    session = f"claude:{sid}"
    stem = f"project={quote(project, safe='')}&session={quote(session, safe='')}"
    board = fetch(base, "/api/data")
    context = fetch(base, f"/api/project-context?{stem}")
    prompts = fetch(base, f"/api/project-context?{stem}&prompts=1")
    record, older = capture_record(base, stem)
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
    }
    if older:
        fixture["older"] = older
    fixture = shift_numbers(fixture, captured, delta)
    fixture = rename(fixture, sid, SAMPLE_SID)
    row = fixture["board"]["sessions"][0]
    place_reading(fixture, last)
    # The server wrote the turn's elapsed time from the wall clock ("154d 22h"); it is the time from
    # the first prompt to the moment the sample is frozen at.
    # A finished session publishes no turn.
    turn = row.get("turn")
    if isinstance(turn, dict):
        turn["elapsed_h"] = fmt_duration(fixture["board"]["generated"] - row["started_at"])
        turn["long"] = False
    place_summary(fixture, last + SUMMARIZED_AFTER_LAST_RECORD)
    # The board's digest of the isolated store the reading was saved in. Shortened so it is plainly
    # a label and not a credential-length value.
    fixture["board"]["intent_revision"] = str(fixture["board"]["intent_revision"])[:DIGEST_CHARS]
    # One reading was read; a refused attempt on the way to it is not part of the story.
    fixture["board"]["reading"]["used"] = 1
    # The reading was captured under the old Allow step, so its server read consent as missing. The
    # sample is shown as this build reads a store with no stored off: readings on, nothing refused,
    # and no notice recorded yet.
    fixture["board"]["reading"].update(consent=True, off=False, reason="", notices={})
    # The stored reading was made, so its notice was shown then, as the summary's was; a capture
    # whose reading was kept from an earlier run would otherwise say the notice is still due.
    for route in (fixture["board"].get("reading_routes") or {}).values():
        if isinstance(route, dict) and "notice_due" in route:
            route["notice_due"] = False
    row["annotation_reading_count"] = 1
    fixture["correction"] = recompose_correction(fixture)
    return fixture


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--base-url")
    parser.add_argument("--project")
    parser.add_argument("--sid")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument(
        "--recompose",
        action="store_true",
        help="rewrite only the correction of the fixture at --out, with no server",
    )
    args = parser.parse_args(argv)
    if args.recompose:
        fixture = json.loads(args.out.read_text(encoding="utf-8"))
        fixture["correction"] = recompose_correction(fixture)
    else:
        if not (args.base_url and args.project and args.sid):
            parser.error("--base-url, --project and --sid are required to capture")
        fixture = build(args.base_url.rstrip("/"), args.project, args.sid)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(fixture, indent=1, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"wrote {args.out} ({args.out.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
