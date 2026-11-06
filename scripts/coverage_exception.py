#!/usr/bin/env python3
"""Decide whether this coverage run may finish below the threshold: the `coverage-exception` label.

Both coverage jobs in `quality-gate.yml` run this before their threshold step, with the job's
read-only token. A pull request answers for itself, and so does a merge queue entry: the entry
is named by the queue's head ref (`gh-readonly-queue/<base>/pr-<N>-<sha>`), and only pull
request N's label counts. A labelled pull request queued ahead does not exempt the entries
behind it, though their tree includes it. Before the queue, a pull request merging after a
labelled one needed its own label once that one landed (AGENTS.md, Quality Gate); reading the
whole group would have let queue timing decide instead.

It FAILS CLOSED, the opposite of `ci_scope.py`: a read it cannot make or understand finds no
label, so the threshold applies, and it says so as a warning so a broken read is not mistaken
for a missing label. A wrong "no exception" costs a re-queue; a wrong "exception" lands
coverage nobody agreed to lose. Stdlib only, because the frontend job runs it on the runner's
own Python before any dependency is installed.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

    Gh = Callable[[list[str]], str | None]

LABEL = "coverage-exception"
QUEUE_REF = re.compile(r"^(?:refs/heads/)?gh-readonly-queue/.+/pr-(\d+)-[0-9a-f]+$")


@dataclass(frozen=True)
class Decision:
    """The pull request this run answers for, and it again if it carries the label."""

    pulls: tuple[int, ...]
    labelled: tuple[int, ...]


def queue_entry(head_ref: str) -> tuple[int, ...]:
    """The pull request a merge queue head ref was built for, if it is one."""
    match = QUEUE_REF.match(head_ref)
    return (int(match.group(1)),) if match else ()


def _run_gh(args: list[str]) -> str | None:
    result = subprocess.run(  # noqa: S603 - fixed gh argv, no shell
        ["gh", *args],  # noqa: S607 - gh from PATH, preinstalled on the runner
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        sys.stderr.write(result.stderr)
        return None
    return result.stdout


def _warn(message: str) -> None:
    print(f"::warning::{message}; {LABEL} not applied, the threshold will block")


def _has_label(number: int, repo: str, gh: Gh) -> bool:
    answer = gh(
        ["pr", "view", str(number), "--repo", repo, "--json", "labels", "--jq", "[.labels[].name]"]
    )
    if answer is None:
        _warn(f"could not read the labels of #{number} (gh pr view failed)")
        return False
    try:
        names = json.loads(answer)
    except ValueError:
        names = None
    if not isinstance(names, list):
        _warn(f"could not understand the labels of #{number}: {answer.strip()[:200]!r}")
        return False
    return LABEL in names


def decide(event: str, pr: str, head_ref: str, repo: str, gh: Gh = _run_gh) -> Decision:
    """The pull request this run answers for, and whether it carries the label."""
    if event == "pull_request":
        pulls: tuple[int, ...] = (int(pr),) if pr.isdigit() else ()
        if not pulls:
            _warn(f"a pull_request run with no pull request number ({pr!r})")
    elif event == "merge_group":
        pulls = queue_entry(head_ref)
        if not pulls:
            _warn(f"a merge queue ref that names no pull request ({head_ref!r})")
    else:
        pulls = ()
    return Decision(pulls, tuple(number for number in pulls if _has_label(number, repo, gh)))


def main(argv: list[str] | None = None, gh: Gh = _run_gh) -> int:
    """Print the decision; append `has_exception` to `$GITHUB_OUTPUT` when it is set."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--event", default=os.environ.get("EVENT", ""))
    parser.add_argument("--pr", default=os.environ.get("PR", ""))
    parser.add_argument("--queue-ref", default=os.environ.get("QUEUE_REF", ""))
    parser.add_argument("--repo", default=os.environ.get("REPO", ""))
    args = parser.parse_args(argv)
    found = decide(args.event, args.pr, args.queue_ref, args.repo, gh)
    print(f"pull requests: {' '.join(f'#{n}' for n in found.pulls) or 'none'}")
    if found.labelled:
        names = " ".join(f"#{n}" for n in found.labelled)
        print(f"::warning::{LABEL} label present on {names}; threshold will not block")
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with Path(output).open("a", encoding="utf-8") as handle:
            handle.write(f"has_exception={1 if found.labelled else 0}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
