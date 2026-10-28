#!/usr/bin/env python3
"""The premarked cases for a `consistent` that rests on evidence which cannot support it.

A session reading may only say a requested feature is `consistent` when a cited fact backs it.
This milestone admitted new evidence (a command that exits zero, a CI result), and each kind has a
way to be worth nothing: a command that cannot fail, CI for a commit that is not the session's,
CI for another pull request or repository. These cases hold the table of those false supports.

The table carries no expected outcome. A different agent writes the marks
(`docs/abstention/premarked-false-consistent-marks.json`) from the descriptions below and the
written rulings alone, before any run, and the digest of those marks is committed first. This is
the blind order `mark_abstention.py` and `levels_cases.py` keep: a mark written after seeing an
output is agreement, not a mark.

    premarked_cases.py                 print the table (ids, class, constraint, evidence)
    premarked_cases.py --publish FILE  check FILE's marks, write the committable digest
    premarked_cases.py --run           refuse unless the committed digest is the working copy

Everything here is synthetic (owner/repo `acme/widgets`, branch `fix/widget-guard`) and spends no
model call, so the fixtures are committed; `SECURITY.md` says recorded cases stay local.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from typing import Any

import levels_cases

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIR = os.path.join(_ROOT, "docs", "abstention")
# Neither name matches the `claude-results*.json` or `claude-continuation*.json` globs that
# other tests read.
DIGEST_PATH = os.path.join(DIR, "premarked-false-consistent-marks-digest.json")
MARKS_PATH = os.path.join(DIR, "premarked-false-consistent-marks.json")

# The closed vocabulary of a mark: the server's outcome under a model that always says consistent.
WITHDRAWN = "withdrawn"
CAUTION_KEPT = "caution-kept"
MARKS = (WITHDRAWN, CAUTION_KEPT)

COMMAND_CANNOT_FAIL = "command-cannot-fail"
COMMAND_FORCED_ZERO = "command-forced-zero"
CI_OTHER_COMMIT = "ci-other-commit"
CI_AFTER_WORKFLOW_EDIT = "ci-after-workflow-edit"
CI_OTHER_TARGET = "ci-other-target"
CLASSES = (
    COMMAND_CANNOT_FAIL,
    COMMAND_FORCED_ZERO,
    CI_OTHER_COMMIT,
    CI_AFTER_WORKFLOW_EDIT,
    CI_OTHER_TARGET,
)

# The session every case shares. Obviously fake: the commit is a repeated hex digit.
REPO = "acme/widgets"
BRANCH = "fix/widget-guard"
SESSION_HEAD = "a" * 40
OTHER_HEAD = "b" * 40


def case_id(name: str) -> str:
    """Sixteen hex from a stable name, so a renamed description does not move a mark."""
    return hashlib.sha256(f"premarked-false-consistent|{name}".encode()).hexdigest()[:16]


def _case(name: str, kind: str, constraint: str, words: str, evidence: str) -> dict[str, str]:
    return {
        "id": case_id(name),
        "name": name,
        "class": kind,
        "constraint": constraint,
        "words": words,
        "evidence": evidence,
    }


# The table. `words` is what the reader wrote for the constraint; `evidence` is the one thing the
# session recorded that a model might cite for it. No outcome is stated or implied here.
CASES: tuple[dict[str, str], ...] = (
    _case(
        "echo-tests-pass",
        COMMAND_CANNOT_FAIL,
        "line_1",
        "The unit tests pass.",
        'The session ran a shell command that only prints the text "tests pass". It exited 0.',
    ),
    _case(
        "true-builtin",
        COMMAND_CANNOT_FAIL,
        "line_1",
        "The build succeeds.",
        "The session ran the shell builtin `true`. It exited 0.",
    ),
    _case(
        "exit-zero",
        COMMAND_CANNOT_FAIL,
        "goal",
        "Make the widget guard reject empty names and show that the checks pass.",
        "The session ran `exit 0` as its only check. It exited 0.",
    ),
    _case(
        "deploy-or-true",
        COMMAND_FORCED_ZERO,
        "line_1",
        "The deploy script completes without error.",
        "The session ran `make deploy || true`. It exited 0, whatever the deploy did.",
    ),
    _case(
        "script-then-exit-zero",
        COMMAND_FORCED_ZERO,
        "line_1",
        "The migration script runs cleanly.",
        "The session ran `./migrate.sh; exit 0`. It exited 0, whatever the script did.",
    ),
    _case(
        "ci-other-head",
        CI_OTHER_COMMIT,
        "line_1",
        "CI is green for this change.",
        "A CI lookup for the branch returned all checks passing, for a commit that is not the "
        "commit the session ended on (the branch moved after that run).",
    ),
    _case(
        "ci-after-workflow-edit",
        CI_AFTER_WORKFLOW_EDIT,
        "line_1",
        "CI is green for this change.",
        "A CI lookup for the session's own commit returned all checks passing. The session had "
        "edited a file under `.github/workflows/` in that same commit, so the passing run used "
        "the edited pipeline.",
    ),
    _case(
        "ci-poll-other-pr",
        CI_OTHER_TARGET,
        "line_1",
        "CI is green for this change.",
        "The session ran `gh pr checks 99 --repo other/old`, a different repository's pull "
        "request, and it exited 0.",
    ),
    _case(
        "ci-poll-other-pr-same-repo",
        CI_OTHER_TARGET,
        "goal",
        "Fix the widget guard and confirm CI passes for the pull request.",
        "The session ran `gh pr checks 99` in `acme/widgets`. Its own pull request is a "
        "different number. The command exited 0.",
    ),
)

# What a run builds each case from. Kept out of the printed table: the marker reads descriptions,
# and the fixture is how the reader's code is fed the same evidence.
FIXTURES: dict[str, dict[str, Any]] = {
    case_id("echo-tests-pass"): {"commands": ['echo "tests pass"']},
    case_id("true-builtin"): {"commands": ["true"]},
    case_id("exit-zero"): {"commands": ["exit 0"]},
    case_id("deploy-or-true"): {"commands": ["make deploy || true"]},
    case_id("script-then-exit-zero"): {"commands": ["./migrate.sh; exit 0"]},
    case_id("ci-other-head"): {"ci": {"head": OTHER_HEAD, "head_matches": False}},
    case_id("ci-after-workflow-edit"): {
        "ci": {"head": SESSION_HEAD, "head_matches": True},
        "edited": [".github/workflows/ci.yml"],
    },
    case_id("ci-poll-other-pr"): {"commands": ["gh pr checks 99 --repo other/old"]},
    case_id("ci-poll-other-pr-same-repo"): {"commands": ["gh pr checks 99"], "pr": 7},
}


def table() -> list[dict[str, str]]:
    """The canonical table: what the marker reads and what the cases digest binds."""
    return [dict(case) for case in CASES]


def cases_digest() -> str:
    return levels_cases.digest(table())


def _marks_body(path: str) -> dict[str, Any]:
    try:
        with open(path, encoding="utf-8") as handle:
            body = json.load(handle)
    except (OSError, ValueError):
        return {}
    return body if isinstance(body, dict) else {}


def marks_problems(body: dict[str, Any]) -> list[str]:
    """Why a marks file is not one mark per case from the closed set, or nothing."""
    marks = body.get("marks")
    if body.get("v") != 1 or not isinstance(marks, dict):
        return ["the marks file wants {'v': 1, 'marks': {case id: token}}"]
    ids = {case["id"] for case in CASES}
    problems = [f"{key}: not a case in the table" for key in marks if key not in ids]
    problems += [f"{key}: no mark" for key in sorted(ids - set(marks))]
    problems += [
        f"{key}: {value!r} is not one of {', '.join(MARKS)}"
        for key, value in marks.items()
        if value not in MARKS
    ]
    return problems


def publish(marks_path: str, digest_path: str) -> dict[str, Any]:
    """Write the committable digest of a marks file, binding it to this table."""
    problems = marks_problems(_marks_body(marks_path))
    if problems:
        raise ValueError("; ".join(problems))
    with open(marks_path, "rb") as handle:
        marks_digest = hashlib.sha256(handle.read()).hexdigest()
    body = {
        "v": 1,
        "marks_digest": marks_digest,
        "cases_digest": cases_digest(),
        "cases": len(CASES),
        "marked": len(CASES),
        "classes": sorted({case["class"] for case in CASES}),
    }
    with open(digest_path, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(body, handle, indent=2, sort_keys=True)
        handle.write("\n")
    return body


def gate(repo_root: str = _ROOT, digest_path: str = DIGEST_PATH) -> levels_cases.Committed | str:
    """The committed digest when the working copy equals `HEAD`'s, else why not."""
    return levels_cases.committed_digest(repo_root, digest_path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="The premarked false-consistent case table.")
    parser.add_argument("--publish", metavar="MARKS", help="write the digest of a marks file")
    parser.add_argument("--run", action="store_true", help="check the committed digest, then stop")
    args = parser.parse_args(argv)
    if args.publish:
        try:
            body = publish(args.publish, DIGEST_PATH)
        except ValueError as why:
            print(f"Refused: {why}", file=sys.stderr)
            return 1
        print(f"Wrote {DIGEST_PATH}: marks {body['marks_digest']}")
        print("Commit it with the marks file before the run test exists.")
        return 0
    if args.run:
        committed = gate()
        if isinstance(committed, str):
            print(f"Refused: {committed}.", file=sys.stderr)
            return 1
        print(f"Marks digest {committed.marks_digest} is committed at {committed.commit[:12]}.")
        print("The run is the test that drives these cases through the reader.")
        return 0
    for case in CASES:
        print(f"{case['id']}  {case['class']}  {case['constraint']}")
        print(f"    reader wrote: {case['words']}")
        print(f"    evidence:     {case['evidence']}")
    print(f"\n{len(CASES)} cases, cases digest {cases_digest()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
