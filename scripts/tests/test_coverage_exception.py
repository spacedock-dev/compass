"""Which pull requests a coverage run answers for, and whether any of them carries the label."""

from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import coverage_exception

SHA = "a" * 40
QUEUE_REF = f"refs/heads/gh-readonly-queue/main/pr-12-{SHA}"


class FakeGh:
    """The one read the script makes, answered from a table, with every call recorded."""

    def __init__(self, labels: dict[int, list[str]]) -> None:
        self.labels = labels
        self.calls: list[list[str]] = []

    def __call__(self, args: list[str]) -> str | None:
        self.calls.append(args)
        number = int(args[2])
        if number not in self.labels:
            return None
        return json.dumps(self.labels[number])


def decide(
    event: str, pr: str, head_ref: str, gh: FakeGh
) -> tuple[coverage_exception.Decision, str]:
    out = io.StringIO()
    with redirect_stdout(out):
        found = coverage_exception.decide(event, pr, head_ref, "o/r", gh)
    return found, out.getvalue()


class WhichPullRequestTest(unittest.TestCase):
    def test_a_pull_request_answers_for_itself(self) -> None:
        gh = FakeGh({7: ["coverage-exception"]})
        found, _ = decide("pull_request", "7", "", gh)
        self.assertEqual(coverage_exception.Decision((7,), (7,)), found)
        self.assertEqual(
            [["pr", "view", "7", "--repo", "o/r", "--json", "labels"]],
            [call[:7] for call in gh.calls],
        )

    def test_a_queue_entry_answers_for_its_own_pull_request(self) -> None:
        gh = FakeGh({12: ["coverage-exception"]})
        found, _ = decide("merge_group", "", QUEUE_REF, gh)
        self.assertEqual(coverage_exception.Decision((12,), (12,)), found)

    def test_a_labelled_pull_request_ahead_in_the_queue_does_not_exempt_the_entry(self) -> None:
        # #9 is labelled and queued ahead of #12, so #12's entry is measured on a tree that
        # includes #9. Before the queue, #12 would have needed its own label once #9 landed; the
        # queue keeps that rule rather than letting queue timing decide it. The only pull request
        # asked about is the one the queue ref names.
        gh = FakeGh({9: ["coverage-exception"], 12: []})
        found, _ = decide("merge_group", "", QUEUE_REF, gh)
        self.assertEqual(coverage_exception.Decision((12,), ()), found)
        self.assertEqual([["pr", "view", "12"]], [call[:3] for call in gh.calls])

    def test_a_base_branch_with_a_slash_still_names_the_entry(self) -> None:
        ref = f"refs/heads/gh-readonly-queue/release/1.x/pr-31-{SHA}"
        self.assertEqual((31,), coverage_exception.queue_entry(ref))
        for ref in ("refs/heads/main", "gh-readonly-queue/main/pr-x-abc", ""):
            with self.subTest(ref=ref):
                self.assertEqual((), coverage_exception.queue_entry(ref))


class FailsClosedTest(unittest.TestCase):
    """Anything the script cannot read leaves the threshold in force, and says so in the log."""

    def test_a_push_reads_nothing_and_is_held_to_the_threshold(self) -> None:
        gh = FakeGh({})
        found, _ = decide("push", "", "", gh)
        self.assertEqual(coverage_exception.Decision((), ()), found)
        self.assertEqual([], gh.calls)

    def test_an_unreadable_or_garbled_label_list_is_no_exception_and_a_warning(self) -> None:
        for answer in (None, "not json", '{"name": "coverage-exception"}'):

            def gh(_args: list[str], answer: str | None = answer) -> str | None:
                return answer

            with self.subTest(answer=answer):
                out = io.StringIO()
                with redirect_stdout(out):
                    found = coverage_exception.decide("pull_request", "7", "", "o/r", gh)
                self.assertEqual((), found.labelled)
                # A broken read must not look like a pull request that simply has no label.
                self.assertIn("::warning::", out.getvalue())
                self.assertIn("#7", out.getvalue())

    def test_a_queue_entry_nothing_names_is_no_exception_and_a_warning(self) -> None:
        gh = FakeGh({})
        found, printed = decide("merge_group", "", "refs/heads/x", gh)
        self.assertEqual(coverage_exception.Decision((), ()), found)
        self.assertIn("::warning::", printed)
        self.assertIn("refs/heads/x", printed)

    def test_a_label_that_is_simply_absent_is_not_a_warning(self) -> None:
        _, printed = decide("pull_request", "7", "", FakeGh({7: ["documentation"]}))
        self.assertNotIn("::warning::", printed)


class OutputTest(unittest.TestCase):
    def test_main_writes_the_answer_the_threshold_step_reads(self) -> None:
        with tempfile.TemporaryDirectory(prefix="coverage-exception-") as tmp:
            output = Path(tmp) / "output"
            previous = os.environ.get("GITHUB_OUTPUT")
            os.environ["GITHUB_OUTPUT"] = str(output)
            self.addCleanup(
                lambda: (
                    os.environ.pop("GITHUB_OUTPUT")
                    if previous is None
                    else os.environ.__setitem__("GITHUB_OUTPUT", previous)
                )
            )
            for labels, expected in (([["coverage-exception"]], "1"), ([[]], "0")):
                gh = FakeGh(dict(zip([7], labels, strict=True)))
                out = io.StringIO()
                with redirect_stdout(out):
                    coverage_exception.main(
                        ["--event", "pull_request", "--pr", "7", "--repo", "o/r"], gh=gh
                    )
                with self.subTest(expected=expected):
                    self.assertEqual(
                        f"has_exception={expected}\n", output.read_text(encoding="utf-8")
                    )
                    if expected == "1":
                        self.assertIn("::warning::", out.getvalue())
                output.unlink()


if __name__ == "__main__":
    unittest.main()
