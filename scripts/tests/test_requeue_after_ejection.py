"""Whether a pull request the merge queue removed goes back in: once per head, and only on a check."""

from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
import unittest.mock
from contextlib import redirect_stdout
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import requeue_after_ejection as requeue

HEAD = "a" * 40
OTHER = "b" * 40
BASE = "c" * 40
REPO = "spacedock-dev/compass"
FIRST = requeue.Facts(
    head=HEAD,
    current_head=HEAD,
    state="OPEN",
    reason="failed_checks",
    requeued=frozenset(),
    gave_up=frozenset(),
    can_enqueue=True,
)


def bot(body: str) -> dict[str, object]:
    return {"login": requeue.BOT, "type": "Bot", "body": body}


def marker(kind: str, head: str = HEAD) -> str:
    return f"<!-- {requeue.MARKER}: {kind} head={head} -->\nwords"


class DecideTest(unittest.TestCase):
    def test_a_first_failed_check_is_requeued(self) -> None:
        self.assertEqual("requeue", requeue.decide(FIRST).action)

    def test_a_second_failure_of_the_same_head_is_reported_not_requeued(self) -> None:
        found = requeue.decide(replace(FIRST, requeued=frozenset({HEAD})))
        self.assertEqual("give_up", found.action)

    def test_a_report_is_made_once(self) -> None:
        found = requeue.decide(
            replace(FIRST, requeued=frozenset({HEAD}), gave_up=frozenset({HEAD}))
        )
        self.assertEqual("skip", found.action)

    def test_a_new_head_gets_its_own_attempt(self) -> None:
        found = requeue.decide(
            replace(FIRST, requeued=frozenset({OTHER}), gave_up=frozenset({OTHER}))
        )
        self.assertEqual("requeue", found.action)

    def test_only_failed_or_timed_out_checks_are_requeued(self) -> None:
        # Measured spellings first; then what a timeout might be called, then everything else.
        cases = {
            "failed_checks": "requeue",
            "FAILED_CHECKS": "requeue",
            "timed_out": "requeue",
            "CI_TIMEOUT": "requeue",
            "manual": "skip",
            "merged": "skip",
            "ALREADY_MERGED": "skip",
            "merge_conflict": "skip",
            "branch_protections": "skip",
            "queue_cleared": "skip",
            "": "skip",
        }
        for reason, expected in cases.items():
            with self.subTest(reason=reason):
                self.assertEqual(expected, requeue.decide(replace(FIRST, reason=reason)).action)

    def test_a_manual_removal_after_a_requeue_says_nothing(self) -> None:
        found = requeue.decide(replace(FIRST, reason="manual", requeued=frozenset({HEAD})))
        self.assertEqual("skip", found.action)

    def test_a_closed_or_merged_or_unreadable_pull_request_is_left(self) -> None:
        for state in ("CLOSED", "MERGED", ""):
            with self.subTest(state=state):
                self.assertEqual("skip", requeue.decide(replace(FIRST, state=state)).action)

    def test_a_head_that_moved_since_the_removal_is_left_to_its_own_checks(self) -> None:
        for current in (OTHER, ""):
            with self.subTest(current=current):
                found = requeue.decide(replace(FIRST, current_head=current))
                self.assertEqual("skip", found.action)

    def test_a_malformed_head_is_never_requeued(self) -> None:
        found = requeue.decide(replace(FIRST, head="main", current_head="main"))
        self.assertEqual("skip", found.action)

    def test_without_the_token_nothing_is_requeued_but_a_second_failure_is_still_reported(
        self,
    ) -> None:
        self.assertEqual("skip", requeue.decide(replace(FIRST, can_enqueue=False)).action)
        found = requeue.decide(replace(FIRST, can_enqueue=False, requeued=frozenset({HEAD})))
        self.assertEqual("give_up", found.action)


class MarkersTest(unittest.TestCase):
    def test_the_bots_markers_are_read(self) -> None:
        requeued, gave_up = requeue.marked_heads(
            [bot(marker("requeued")), bot(marker("gave-up", OTHER))]
        )
        self.assertEqual((frozenset({HEAD}), frozenset({OTHER})), (requeued, gave_up))

    def test_a_marker_anyone_else_writes_counts_for_nothing(self) -> None:
        forged = [
            {"login": "someone", "type": "User", "body": marker("requeued")},
            {"login": requeue.BOT, "type": "User", "body": marker("requeued")},
            {"login": "github-actions", "type": "Bot", "body": marker("gave-up")},
        ]
        self.assertEqual((frozenset(), frozenset()), requeue.marked_heads(forged))

    def test_a_short_or_quoted_marker_is_not_a_marker(self) -> None:
        bodies = [
            f"<!-- {requeue.MARKER}: requeued head={HEAD[:12]} -->",
            f"`<!-- {requeue.MARKER}: requeued head={HEAD.upper()} -->`",
            None,
        ]
        found = requeue.marked_heads([bot(body) for body in bodies])  # type: ignore[arg-type]
        self.assertEqual((frozenset(), frozenset()), found)

    def test_the_comment_carries_the_marker_it_is_read_back_by(self) -> None:
        cases: tuple[tuple[requeue.Action, int], ...] = (("requeue", 0), ("give_up", 1))
        for action, slot in cases:
            with self.subTest(action=action):
                body = requeue.comment(action, HEAD, 7, ["Quality Gate / test"])
                self.assertEqual(frozenset({HEAD}), requeue.marked_heads([bot(body)])[slot])
                self.assertIn("- `Quality Gate / test`", body)


class FailedJobsTest(unittest.TestCase):
    RUNS = (
        # An older group for the same pull request, failed: not the one just removed.
        {
            "id": 1,
            "name": "Quality Gate",
            "head_branch": f"gh-readonly-queue/main/pr-7-{BASE}",
            "head_sha": "1" * 40,
            "conclusion": "failure",
            "created_at": "2026-11-06T10:00:00Z",
        },
        {
            "id": 2,
            "name": "Quality Gate",
            "head_branch": f"gh-readonly-queue/main/pr-7-{BASE}",
            "head_sha": "2" * 40,
            "conclusion": "failure",
            "created_at": "2026-11-06T11:00:00Z",
        },
        {
            "id": 3,
            "name": "Validate",
            "head_branch": f"gh-readonly-queue/main/pr-7-{BASE}",
            "head_sha": "2" * 40,
            "conclusion": "success",
            "created_at": "2026-11-06T11:00:00Z",
        },
        # Pull request 70 shares the digits, not the prefix.
        {
            "id": 4,
            "name": "Quality Gate",
            "head_branch": f"gh-readonly-queue/main/pr-70-{BASE}",
            "head_sha": "4" * 40,
            "conclusion": "failure",
            "created_at": "2026-11-06T12:00:00Z",
        },
    )

    def test_the_newest_group_of_this_pull_request_is_read(self) -> None:
        found = requeue.latest_failed_runs(self.RUNS, requeue.queue_prefix("main", 7))
        self.assertEqual([2], [run["id"] for run in found])

    def test_failed_jobs_are_named_and_a_run_without_them_names_itself(self) -> None:
        runs = [{"id": 2, "name": "Quality Gate"}, {"id": 5, "name": "Validate"}]
        jobs: dict[object, list[dict[str, object]]] = {
            2: [
                {"name": "Tests (3.14)", "conclusion": "failure"},
                {"name": "lint", "conclusion": "success"},
                {"name": "Storybook", "conclusion": "timed_out"},
            ],
        }
        self.assertEqual(
            ["Quality Gate / Tests (3.14)", "Quality Gate / Storybook", "Validate"],
            requeue.failed_job_names(runs, jobs),
        )

    def test_a_job_name_cannot_break_out_of_its_code_span(self) -> None:
        runs = [{"id": 1, "name": "Gate`\n<!-- x -->"}]
        names = requeue.failed_job_names(runs, {1: [{"name": "a`b", "conclusion": "failure"}]})
        self.assertEqual(["Gate!-- x -- / ab"], names)

    def test_the_list_is_bounded_and_an_empty_one_points_at_the_checks(self) -> None:
        body = requeue.comment("give_up", HEAD, 7, [f"job {n}" for n in range(25)])
        self.assertIn("- and 5 more", body)
        self.assertNotIn("job 20", body)
        self.assertIn("could not be read", requeue.comment("give_up", HEAD, 7, []))


class FakeGh:
    """GitHub as the script reads it: one pull request, its comments and its queue runs."""

    def __init__(
        self,
        state: str = "OPEN",
        reason: str = "failed_checks",
        comments: list[dict[str, object]] | None = None,
        post_fails: bool = False,
    ) -> None:
        self.state = state
        self.reason = reason
        self.comments = comments or []
        self.post_fails = post_fails
        self.posted: list[str] = []
        self.calls: list[list[str]] = []

    def __call__(self, args: list[str], stdin: str | None) -> str | None:  # noqa: PLR0911 - one answer per read
        self.calls.append(args)
        if args[:2] == ["api", "graphql"]:
            pull = {
                "state": self.state,
                "headRefOid": HEAD,
                "timelineItems": {"nodes": [{"reason": self.reason}]},
            }
            return json.dumps({"data": {"repository": {"pullRequest": pull}}})
        if "--method" in args:
            if self.post_fails:
                return None
            self.posted.append(json.loads(stdin or "{}")["body"])
            return "{}"
        if args[1] == "--paginate":
            return "\n".join(json.dumps(row) for row in self.comments)
        if "event=merge_group" in args[1]:
            run = {
                "id": 9,
                "name": "Quality Gate",
                "head_branch": f"gh-readonly-queue/main/pr-7-{BASE}",
                "head_sha": "9" * 40,
                "conclusion": "failure",
                "created_at": "t",
            }
            return json.dumps(run)
        if args[1].endswith("/jobs?per_page=100"):
            return json.dumps({"name": "Tests (3.14)", "conclusion": "failure"})
        return None


class MainTest(unittest.TestCase):
    def run_main(self, gh: requeue.Gh, can_enqueue: str = "true") -> tuple[int, str, str]:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "out"
            output.touch()
            out = io.StringIO()
            env = {**os.environ, "GITHUB_OUTPUT": str(output)}
            argv = [
                "--repo",
                REPO,
                "--number",
                "7",
                "--head",
                HEAD,
                "--base",
                "main",
                "--event-reason",
                "CI_FAILURE",
                "--can-enqueue",
                can_enqueue,
            ]
            with unittest.mock.patch.dict(os.environ, env, clear=True), redirect_stdout(out):
                code = requeue.main(argv, gh)
            return code, output.read_text(encoding="utf-8"), out.getvalue()

    def test_a_first_failure_comments_with_the_failed_jobs_then_says_requeue(self) -> None:
        gh = FakeGh()
        code, output, printed = self.run_main(gh)
        self.assertEqual((0, "action=requeue\n"), (code, output))
        (body,) = gh.posted
        self.assertIn(f"requeued head={HEAD}", body)
        self.assertIn("- `Quality Gate / Tests (3.14)`", body)
        self.assertIn("'failed_checks'", printed)
        self.assertIn("'CI_FAILURE'", printed)

    def test_a_second_failure_comments_and_says_give_up(self) -> None:
        gh = FakeGh(comments=[bot(marker("requeued"))])
        code, output, _ = self.run_main(gh)
        self.assertEqual((0, "action=give_up\n"), (code, output))
        self.assertIn(f"gave-up head={HEAD}", gh.posted[0])

    def test_a_manual_removal_posts_nothing(self) -> None:
        gh = FakeGh(reason="manual")
        code, output, _ = self.run_main(gh)
        self.assertEqual((0, "action=skip\n", []), (code, output, gh.posted))

    def test_a_missing_token_warns_and_posts_nothing(self) -> None:
        gh = FakeGh()
        code, output, printed = self.run_main(gh, can_enqueue="false")
        self.assertEqual((0, "action=skip\n", []), (code, output, gh.posted))
        self.assertIn("::warning::", printed)

    def test_no_marker_means_no_requeue(self) -> None:
        # The marker is the only record of the attempt, so an enqueue without it could repeat.
        code, output, printed = self.run_main(FakeGh(post_fails=True))
        self.assertEqual((1, ""), (code, output))
        self.assertIn("::error::", printed)

    def test_an_unreadable_pull_request_is_left(self) -> None:
        def broken(_args: list[str], _stdin: str | None) -> str | None:
            return None

        code, output, _ = self.run_main(broken)
        self.assertEqual((0, "action=skip\n"), (code, output))


if __name__ == "__main__":
    unittest.main()
