#!/usr/bin/env python3
"""Tally flaky tests from recent CI runs and compare the tally with the ledger.

Read-only: it asks `gh` for runs and their logs and prints what it finds. It writes nothing,
including the ledger, `docs/flaky-tests.md`, which a person or an agent edits from its output.

Two kinds of evidence count, one sighting per test per run:

- A `FLAKY-RETRY-PASSED: <test id>` line, which `scripts/run_tests.py` prints for a test that
  failed and then passed on its retry. Every finished run in the window is read for these.
- A `FAIL:` or `ERROR:` test in an attempt that failed on code that also passed: the same commit
  passed in the same workflow, a later merge queue entry for the same pull request passed, or a
  later attempt of the same run passed. Those are candidates, not verdicts. A queue entry can pass
  later because a fix was pushed between, so confirm each one as AGENTS.md says before recording.

A run named in a ledger row counts as recorded there, so the diff lists only what the ledger is
missing: NEW tests, UPDATE for unrecorded runs of a known test, REOPEN for a fixed test that
failed again.

Cost: one log download per finished run in the window, plus one per candidate attempt, `--jobs`
at a time. `--since` and `--limit` bound it.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    Gh = Callable[[list[str]], str]

# The two workflows that run the Python suites through scripts/run_tests.py.
WORKFLOWS = ("quality-gate.yml", "validate.yml")
EVENTS = frozenset({"push", "pull_request", "merge_group"})
RUN_FIELDS = "databaseId,attempt,conclusion,createdAt,event,headBranch,headSha,status,workflowName"
LEDGER = Path(__file__).resolve().parents[1] / "docs" / "flaky-tests.md"
LEDGER_COLUMNS = (
    "Test",
    "First seen",
    "Last seen",
    "Count",
    "Where",
    "Symptom",
    "Status",
    "Fixing PR",
)
STATUSES = frozenset({"open", "fixed"})

QUEUE_BRANCH = re.compile(r"^gh-readonly-queue/.+/pr-(\d+)-[0-9a-f]+$")
# `<job>\t<step>\t<timestamp> <text>`, as `gh run view --log` prints it. Some lines carry a byte
# order mark before the timestamp.
LOG_LINE = re.compile(
    r"^(?P<job>[^\t]*)\t[^\t]*\t\ufeff?(?:\d{4}-\d\d-\d\dT[\d:.]+Z )?(?P<text>.*)$"
)
RETRY_PASSED = re.compile(r"^FLAKY-RETRY-PASSED: (?P<id>\S+)\s*$")
# `FAIL: test_x (module.Class.test_x)`, with a subtest's parameters after it when there are any.
FAILED = re.compile(r"^(?:FAIL|ERROR): (?P<name>\S+) \((?P<id>[\w.]+)\)")
RUN_ID = re.compile(r"\b\d{8,}\b")
ISO_DATE = re.compile(r"^\d{4}-\d\d-\d\d$")


class GhError(RuntimeError):
    """A `gh` call that did not succeed."""


@dataclass(frozen=True)
class Run:
    """One workflow run, at its latest attempt."""

    id: int
    attempt: int
    conclusion: str
    created: str
    event: str
    branch: str
    sha: str
    workflow: str

    @property
    def date(self) -> str:
        """The day the run was created, in UTC."""
        return self.created[:10]

    @property
    def pull(self) -> str | None:
        """The pull request a merge queue entry was built for."""
        match = QUEUE_BRANCH.match(self.branch) if self.event == "merge_group" else None
        return match.group(1) if match else None


@dataclass(frozen=True)
class Sighting:
    """A test seen failing in one attempt of one run, in one job."""

    test: str
    kind: str  # "retry": passed on its retry; "failed": failed in an attempt on code that passed
    run: int
    attempt: int
    job: str
    event: str
    date: str


@dataclass(frozen=True)
class Row:
    """One ledger row."""

    test: str
    first_seen: str
    last_seen: str
    count: int
    status: str
    fixing_pr: str
    text: str


def _run_gh(args: list[str]) -> str:
    result = subprocess.run(  # noqa: S603 - fixed gh argv, no shell
        ["gh", *args],  # noqa: S607 - gh from PATH
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise GhError(result.stderr.strip() or f"gh {' '.join(args)} exited {result.returncode}")
    return result.stdout


def short_id(full: str) -> str:
    """`module.Class.method` from a full unittest id, the form the ledger uses."""
    return ".".join(full.split(".")[-3:])


def parse_log(text: str) -> list[tuple[str, str, str]]:
    """Every retried and every failed test in a log, as (kind, job, short test id)."""
    found: list[tuple[str, str, str]] = []
    for raw in text.splitlines():
        line = LOG_LINE.match(raw)
        job, body = (line.group("job"), line.group("text")) if line else ("", raw)
        if retried := RETRY_PASSED.match(body):
            found.append(("retry", job, short_id(retried.group("id"))))
            continue
        failed = FAILED.match(body)
        if failed is None or failed.group("id").startswith("unittest."):
            continue  # not a test, or an import failure, which is not flaky in itself
        name, full = failed.group("name"), failed.group("id")
        if full.endswith(f".{name}"):
            found.append(("failed", job, short_id(full)))
        else:  # a class or module fixture: `setUpClass (module.Class)`
            found.append(("failed", job, f"{'.'.join(full.split('.')[-2:])} ({name})"))
    return found


def _cells(line: str) -> list[str]:
    return [cell.strip() for cell in re.split(r"(?<!\\)\|", line.strip())[1:-1]]


def read_ledger(text: str) -> dict[str, Row]:
    """Read the ledger table, refusing a row that does not hold its shape."""
    lines = text.splitlines()
    try:
        start = next(i for i, line in enumerate(lines) if tuple(_cells(line)) == LEDGER_COLUMNS)
    except StopIteration:
        message = f"no table with the columns {' | '.join(LEDGER_COLUMNS)}"
        raise ValueError(message) from None
    rows: dict[str, Row] = {}
    for line in lines[start + 2 :]:
        if not line.startswith("|"):
            break
        cells = _cells(line)
        problem = _row_problem(cells, rows)
        if problem:
            message = f"ledger row {line[:80]!r}: {problem}"
            raise ValueError(message)
        test = cells[0][1:-1]
        rows[test] = Row(
            test=test,
            first_seen=cells[1],
            last_seen=cells[2],
            count=int(cells[3]),
            status=cells[6],
            fixing_pr=cells[7],
            text=line,
        )
    return rows


def _row_problem(cells: list[str], rows: dict[str, Row]) -> str:
    if len(cells) != len(LEDGER_COLUMNS):
        return f"{len(cells)} cells, not {len(LEDGER_COLUMNS)}"
    test, first, last, count, _where, _symptom, status, _pr = cells
    checks = (
        (len(test) > 2 and test[0] == test[-1] == "`", "the test id is not in backticks"),
        (test[1:-1] not in rows, "the test has a row already"),
        (bool(ISO_DATE.match(first) and ISO_DATE.match(last)), "a date is not YYYY-MM-DD"),
        (first <= last, "first seen is after last seen"),
        (count.isdigit() and int(count) >= 1, "the count is not a positive number"),
        (status in STATUSES, f"the status is not one of {', '.join(sorted(STATUSES))}"),
    )
    return next((problem for ok, problem in checks if not ok), "")


def list_runs(gh: Gh, workflow: str, since: str, limit: int, repo: str | None) -> list[Run]:
    """The workflow's runs created on or after `since`, from the events the tally reads."""
    args = ["run", "list", "--workflow", workflow, "--limit", str(limit), "--json", RUN_FIELDS]
    runs = []
    for item in json.loads(gh(args + _repo(repo))):
        run = Run(
            id=int(item["databaseId"]),
            attempt=int(item.get("attempt") or 1),
            conclusion=item.get("conclusion") or "",
            created=item["createdAt"],
            event=item["event"],
            branch=item.get("headBranch") or "",
            sha=item.get("headSha") or "",
            workflow=item.get("workflowName") or workflow,
        )
        if run.date >= since and run.event in EVENTS:
            runs.append(run)
    return runs


def failed_attempts(runs: Iterable[Run]) -> list[tuple[Run, int]]:
    """Attempts that failed on code that also passed: the flake candidates."""
    runs = list(runs)
    passed = [run for run in runs if run.conclusion == "success"]
    passed_commits = {(run.workflow, run.sha) for run in passed}
    found: list[tuple[Run, int]] = []
    for run in runs:
        if run.conclusion == "success":
            found += [(run, attempt) for attempt in range(1, run.attempt)]
        elif run.conclusion == "failure":
            same_commit = (run.workflow, run.sha) in passed_commits
            later_entry = run.pull is not None and any(
                other.pull == run.pull
                and other.workflow == run.workflow
                and other.created > run.created
                for other in passed
            )
            if same_commit or later_entry:
                found.append((run, run.attempt))
    return found


def _repo(repo: str | None) -> list[str]:
    return ["--repo", repo] if repo else []


def tally(
    gh: Gh, since: str, limit: int, repo: str | None, workers: int = 8
) -> tuple[list[Sighting], int]:
    """Every sighting in the window, and how many runs were read."""
    runs = [run for workflow in WORKFLOWS for run in list_runs(gh, workflow, since, limit, repo)]
    finished = [run for run in runs if run.conclusion in {"success", "failure"}]
    reads = [(run, run.attempt, "retry") for run in finished]
    reads += [(run, attempt, "failed") for run, attempt in failed_attempts(finished)]

    def read(item: tuple[Run, int, str]) -> set[Sighting]:
        run, attempt, kind = item
        if kind == "retry":
            args = ["run", "view", str(run.id), "--log"]
        else:
            args = ["run", "view", str(run.id), "--attempt", str(attempt), "--log-failed"]
        return {
            Sighting(test, kind, run.id, attempt, job, run.event, run.date)
            for found, job, test in parse_log(gh(args + _repo(repo)))
            if found == kind
        }

    # One log download took about five seconds (2026-11-06), so a week of runs read one at a time
    # took most of half an hour. The downloads are independent.
    seen: set[Sighting] = set()
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        for found in pool.map(read, reads):
            seen |= found
    return sorted(seen, key=lambda s: (s.test, s.run, s.attempt, s.job)), len(finished)


def _by_test(sightings: list[Sighting]) -> dict[str, list[Sighting]]:
    grouped: dict[str, list[Sighting]] = {}
    for sighting in sightings:
        grouped.setdefault(sighting.test, []).append(sighting)
    return grouped


def _runs(sightings: Iterable[Sighting]) -> list[int]:
    return sorted({sighting.run for sighting in sightings})


def diff(sightings: list[Sighting], ledger: dict[str, Row]) -> list[str]:
    """What the ledger is missing, one line per test."""
    lines = []
    for test, found in sorted(_by_test(sightings).items()):
        row = ledger.get(test)
        new = [s for s in found if row is None or str(s.run) not in RUN_ID.findall(row.text)]
        if not new:
            continue
        runs = ", ".join(str(run) for run in _runs(new))
        last = max(s.date for s in new)
        if row is None:
            first = min(s.date for s in new)
            lines.append(
                f"NEW     {test}: {len(_runs(new))} runs ({runs}), first {first}, last {last}"
            )
        elif row.status == "fixed":
            lines.append(f"REOPEN  {test}: fixed in {row.fixing_pr or '?'}, failed again in {runs}")
        else:
            count = row.count + len(_runs(new))
            lines.append(
                f"UPDATE  {test}: count {row.count} -> {count}, "
                f"last seen {row.last_seen} -> {max(last, row.last_seen)} ({runs})"
            )
    return lines


def render(
    sightings: list[Sighting], read: int, since: str, ledger: Path, changes: list[str]
) -> str:
    """The tally, most frequent first, and then the diff against the ledger."""
    grouped = _by_test(sightings)
    out = [f"Flaky-test tally: {read} finished runs since {since} ({', '.join(WORKFLOWS)})", ""]
    for test, found in sorted(grouped.items(), key=lambda item: (-len(_runs(item[1])), item[0])):
        out.append(f"  {len(_runs(found))}  {test}")
        for s in found:
            what = "passed on retry" if s.kind == "retry" else "failed, then passed"
            attempt = f" attempt {s.attempt}" if s.kind == "failed" else ""
            out.append(f"       {what}: run {s.run}{attempt} ({s.event}, {s.date}), {s.job}")
    if not grouped:
        out.append("  No flaky tests found.")
    out += ["", f"Against {ledger}:"]
    out += [f"  {line}" for line in changes] or ["  Nothing to record."]
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None, gh: Gh = _run_gh, today: date | None = None) -> int:
    """Read the window's runs, print the tally and the ledger diff."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--since", type=int, default=7, metavar="DAYS", help="days back to read")
    parser.add_argument("--limit", type=int, default=300, help="runs listed per workflow")
    parser.add_argument("--repo", default=None, help="OWNER/REPO; gh's default when omitted")
    parser.add_argument("--ledger", type=Path, default=LEDGER, help="the ledger to compare with")
    parser.add_argument("-j", "--jobs", type=int, default=8, help="logs downloaded at once")
    args = parser.parse_args(argv)
    since = ((today or datetime.now(UTC).date()) - timedelta(days=args.since)).isoformat()
    try:
        ledger = read_ledger(args.ledger.read_text(encoding="utf-8"))
        sightings, read = tally(gh, since, args.limit, args.repo, args.jobs)
    except (GhError, OSError, ValueError) as error:
        print(f"flaky_tally: {error}", file=sys.stderr)
        return 1
    shown = args.ledger.resolve()
    if shown.is_relative_to(LEDGER.parents[1]):
        shown = shown.relative_to(LEDGER.parents[1])
    sys.stdout.write(render(sightings, read, since, shown, diff(sightings, ledger)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
