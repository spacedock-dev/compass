#!/usr/bin/env python3
"""Decide whether a pull request the merge queue removed goes back in, once per head commit.

`.github/workflows/requeue-after-ejection.yml` runs this on `pull_request_target` `dequeued`,
from the default branch's own copy, with the workflow's token. It reads, comments and prints
`action=requeue`, `action=give_up` or `action=skip` to `$GITHUB_OUTPUT`. It never enqueues: the
workflow's next job does that with a separate credential, so this script never holds it.

The reason comes from the pull request's timeline, not the webhook. The webhook's `reason` is a
required string whose values GitHub does not document; the timeline's
`RemovedFromMergeQueueEvent.reason` was read on this repository on 2026-11-06 and said
`failed_checks` (#810, #813, #818), `manual` (#813) and `merged` (every landing).

Once per head is held by a comment carrying a hidden marker with the head SHA, written by the
workflow's own bot account and read back from it alone, so a comment anyone else writes can
neither consume the attempt nor fake one. Stdlib only: the runner's Python runs it as checked out.
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
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping

    Gh = Callable[[list[str], str | None], str | None]

Action = Literal["requeue", "give_up", "skip"]

MARKER = "compass-requeue-after-ejection"
MARKED = re.compile(rf"<!-- {MARKER}: (requeued|gave-up) head=([0-9a-f]{{40}}) -->")
BOT = "github-actions[bot]"
SHA = re.compile(r"^[0-9a-f]{40}$")
# Measured on this repository (see the module docstring).
FAILED_CHECKS = "failed_checks"
FAILED_JOB = frozenset({"failure", "timed_out", "cancelled", "startup_failure"})
LISTED_JOBS = 20

TIMELINE = """
query($owner: String!, $name: String!, $number: Int!) {
  repository(owner: $owner, name: $name) {
    pullRequest(number: $number) {
      state
      headRefOid
      isInMergeQueue
      timelineItems(itemTypes: [REMOVED_FROM_MERGE_QUEUE_EVENT], last: 1) {
        nodes { ... on RemovedFromMergeQueueEvent { reason } }
      }
    }
  }
}
"""


def requeueable(reason: str) -> bool:
    """Whether the queue removed the entry for a failed or timed-out check, and nothing else.

    No removal for a timeout has been seen here, so its spelling is unmeasured; GitHub's merge
    queue page names the cause ("Timed out awaiting a successful CI result"). Any reason not
    matched is left alone, which is the safe side: a missed re-queue costs one `gh pr merge`.
    """
    letters = re.sub(r"[^a-z]", "", reason.lower())
    return reason.strip().lower() == FAILED_CHECKS or "timedout" in letters or "timeout" in letters


@dataclass(frozen=True)
class Facts:
    """What the decision reads, gathered before it is made so it can be tested offline."""

    head: str
    current_head: str
    state: str
    reason: str
    requeued: frozenset[str]
    gave_up: frozenset[str]
    can_enqueue: bool
    in_queue: bool


@dataclass(frozen=True)
class Decision:
    action: Action
    why: str


def decide(facts: Facts) -> Decision:  # noqa: PLR0911 - one return per guard, in order
    """Re-queue once per head on a failed or timed-out check; report the second failure once."""
    if facts.state != "OPEN":
        return Decision("skip", f"the pull request is {facts.state.lower() or 'unreadable'}")
    if not SHA.match(facts.head) or facts.current_head != facts.head:
        return Decision("skip", "the head moved since the removal; its own checks decide")
    if facts.in_queue:
        # A person re-queued it before this ran. Re-queueing too would spend this head's attempt.
        return Decision("skip", "it is already back in the queue")
    if not requeueable(facts.reason):
        return Decision("skip", f"removed for {facts.reason or 'an unrecorded reason'!r}")
    if facts.head in facts.gave_up:
        return Decision("skip", "the second failure of this head is already reported")
    if facts.head in facts.requeued:
        return Decision("give_up", "this head was re-queued once already")
    if not facts.can_enqueue:
        return Decision("skip", "MERGE_QUEUE_TOKEN is not set, so nothing could re-queue it")
    return Decision("requeue", f"removed for {facts.reason!r}, first time for this head")


def marked_heads(comments: Iterable[Mapping[str, object]]) -> tuple[frozenset[str], frozenset[str]]:
    """The heads re-queued once and the heads already reported, from the bot's own comments."""
    found: dict[str, set[str]] = {"requeued": set(), "gave-up": set()}
    for comment in comments:
        if comment.get("login") != BOT or comment.get("type") != "Bot":
            continue
        for kind, head in MARKED.findall(str(comment.get("body") or "")):
            found[kind].add(head)
    return frozenset(found["requeued"]), frozenset(found["gave-up"])


def queue_prefix(base: str, number: int) -> str:
    # `gh-readonly-queue/<base>/pr-<N>-<sha>`, the sha being the base the group was built on.
    return f"gh-readonly-queue/{base}/pr-{number}-"


def latest_failed_runs(runs: Iterable[dict[str, object]], prefix: str) -> list[dict[str, object]]:
    """The failed runs of the most recent merge group built for this pull request."""
    mine = [run for run in runs if str(run.get("head_branch") or "").startswith(prefix)]
    if not mine:
        return []
    newest = max(mine, key=lambda run: str(run.get("created_at") or ""))
    group = [run for run in mine if run.get("head_sha") == newest.get("head_sha")]
    return [run for run in group if run.get("conclusion") in FAILED_JOB]


def _label(text: object) -> str:
    # Job names come from the workflow files in the merge group, which a pull request can edit.
    flat = re.sub(r"[`\r\n<>]", "", str(text)).strip()
    return flat[:120] or "unnamed"


def failed_job_names(
    runs: Iterable[dict[str, object]], jobs: dict[object, list[dict[str, object]]]
) -> list[str]:
    names = []
    for run in runs:
        failed = [job for job in jobs.get(run.get("id"), []) if job.get("conclusion") in FAILED_JOB]
        if not failed:
            names.append(_label(run.get("name")))
        names.extend(f"{_label(run.get('name'))} / {_label(job.get('name'))}" for job in failed)
    return names


def _job_list(names: list[str]) -> str:
    if not names:
        return "The failed jobs could not be read; the pull request's checks list them.\n"
    shown = [f"- `{name}`" for name in names[:LISTED_JOBS]]
    if len(names) > LISTED_JOBS:
        shown.append(f"- and {len(names) - LISTED_JOBS} more")
    return "\n".join(shown) + "\n"


def comment(action: Action, head: str, number: int, names: list[str]) -> str:
    marker = "requeued" if action == "requeue" else "gave-up"
    lines = [f"<!-- {MARKER}: {marker} head={head} -->"]
    if action == "requeue":
        lines.append(
            "The merge queue removed this pull request because a check failed or timed out "
            f"on `{head[:12]}`. "
            "It goes back in the queue once, automatically. These failed in the queue:\n"
        )
        lines.append(_job_list(names))
        lines.append("If the same commit fails again it stays out, and a comment here will say so.")
    else:
        lines.append(
            f"The merge queue removed this pull request again on `{head[:12]}`, after its one "
            "automatic re-queue, so it stays out. These failed in the queue:\n"
        )
        lines.append(_job_list(names))
        lines.append(
            "Fix them, or re-run them if they are flaky, "
            f"then queue it with `gh pr merge {number}`."
        )
    return "\n".join(lines) + "\n"


def _run_gh(args: list[str], stdin: str | None = None) -> str | None:
    result = subprocess.run(  # noqa: S603 - fixed gh argv, no shell
        ["gh", *args],  # noqa: S607 - gh from PATH, preinstalled on the runner
        input=stdin,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        sys.stderr.write(result.stderr)
        return None
    return result.stdout


def _json_lines(text: str | None) -> list[dict[str, object]]:
    rows = []
    for line in (text or "").splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def read_pull(repo: str, number: int, gh: Gh) -> tuple[str, str, bool, str]:
    """State, current head, queue membership and the latest removal reason.

    Unreadable reads as an empty state, which every decision skips.
    """
    owner, _, name = repo.partition("/")
    answer = gh(
        [
            "api",
            "graphql",
            "-f",
            f"query={TIMELINE}",
            "-f",
            f"owner={owner}",
            "-f",
            f"name={name}",
            "-F",
            f"number={number}",
        ],
        None,
    )
    try:
        pull = json.loads(answer or "")["data"]["repository"]["pullRequest"]
        nodes = pull["timelineItems"]["nodes"]
        reason = str(nodes[-1].get("reason") or "") if nodes else ""
        return str(pull["state"]), str(pull["headRefOid"]), pull["isInMergeQueue"] is True, reason
    except (ValueError, KeyError, TypeError, IndexError):
        return "", "", False, ""


def read_comments(repo: str, number: int, gh: Gh) -> list[dict[str, object]] | None:
    """The comments, or None when gh failed: an unreadable list is not an empty one."""
    jq = ".[] | {login: .user.login, type: .user.type, body: .body}"
    answer = gh(["api", "--paginate", f"repos/{repo}/issues/{number}/comments", "--jq", jq], None)
    return None if answer is None else _json_lines(answer)


def read_failed_jobs(repo: str, base: str, number: int, gh: Gh) -> list[str]:
    # One page: the removal is seconds old, and the newest hundred queue runs hold its group.
    jq = ".workflow_runs[] | {id, name, head_branch, head_sha, conclusion, created_at}"
    runs = _json_lines(
        gh(["api", f"repos/{repo}/actions/runs?event=merge_group&per_page=100", "--jq", jq], None)
    )
    failed = latest_failed_runs(runs, queue_prefix(base, number))
    jobs = {
        run.get("id"): _json_lines(
            gh(
                [
                    "api",
                    f"repos/{repo}/actions/runs/{run.get('id')}/jobs?per_page=100",
                    "--jq",
                    ".jobs[] | {name, conclusion}",
                ],
                None,
            )
        )
        for run in failed
    }
    return failed_job_names(failed, jobs)


def main(argv: list[str] | None = None, gh: Gh = _run_gh) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", default=os.environ.get("REPO", ""))
    parser.add_argument("--number", default=os.environ.get("PR_NUMBER", ""))
    parser.add_argument("--head", default=os.environ.get("HEAD_SHA", ""))
    parser.add_argument("--base", default=os.environ.get("BASE_REF", ""))
    parser.add_argument("--event-reason", default=os.environ.get("EVENT_REASON", ""))
    parser.add_argument("--can-enqueue", default=os.environ.get("QUEUE_TOKEN_SET", ""))
    args = parser.parse_args(argv)
    if not args.number.isdigit() or "/" not in args.repo or not args.base:
        print(f"::error::missing input: repo={args.repo!r} number={args.number!r}")
        return 1
    number = int(args.number)

    state, current_head, in_queue, reason = read_pull(args.repo, number, gh)
    comments = read_comments(args.repo, number, gh)
    requeued, gave_up = marked_heads(comments or [])
    facts = Facts(
        head=args.head,
        current_head=current_head,
        state=state,
        reason=reason,
        requeued=requeued,
        gave_up=gave_up,
        can_enqueue=args.can_enqueue == "true",
        in_queue=in_queue,
    )
    decision = decide(facts)
    if comments is None and decision.action != "skip":
        # The markers are the only record of an attempt, so without them either action could repeat.
        print(f"::error::could not read the comments on #{number}; not re-queued")
        return 1
    # The webhook's reason is logged beside the timeline's so the two vocabularies can be compared.
    print(f"#{number}: timeline reason {reason!r}, webhook reason {args.event_reason!r}")
    print(f"#{number}: {decision.action}: {decision.why}")
    if decision.action == "skip" and "MERGE_QUEUE_TOKEN" in decision.why:
        print(f"::warning::#{number} was not re-queued: {decision.why}")

    if decision.action != "skip":
        names = read_failed_jobs(args.repo, args.base, number, gh)
        body = comment(decision.action, args.head, number, names)
        posted = gh(
            [
                "api",
                "--method",
                "POST",
                f"repos/{args.repo}/issues/{number}/comments",
                "--input",
                "-",
            ],
            json.dumps({"body": body}),
        )
        if posted is None:
            # Without the marker a second failure would re-queue again, so nothing is enqueued.
            print(f"::error::could not comment on #{number}; not re-queued")
            return 1

    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with Path(output).open("a", encoding="utf-8") as handle:
            handle.write(f"action={decision.action}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
