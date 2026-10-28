"""A pull request's CI checks, read from GitHub when a reader presses Analyze.

The contract is DEC-30 (docs/design-reading-a-session.md). Every launch goes through a stub `gh`:
a real executable on a temporary PATH, so the argv, the working directory and the environment
the child saw are measured, never assumed.
"""

from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import types
import unittest
from typing import TYPE_CHECKING, Any, cast
from unittest import mock

from compass_runtime import (
    ci_read,
    git_status,
    http_api,
    levels,
    observer,
    project_context,
    reading,
    supervise,
)

from . import test_reading as base
from .test_goal_verdict import goal_row

if TYPE_CHECKING:
    from collections.abc import Callable

REPO = "acme/widgets"
SESSION_HEAD = "a" * 40
OTHER_HEAD = "b" * 40
GOAL_URL = f"https://github.com/{REPO}/pull/12"
GOAL_TEXT = f"Fix the failing GitHub Actions on PR {GOAL_URL}"


def check(name: str, bucket: str, done: str = "2026-10-27T10:00:00Z") -> dict[str, str]:
    """One row as `gh pr checks --json name,state,bucket,completedAt` prints it."""
    return {
        "name": name,
        "state": bucket.upper(),
        "bucket": bucket,
        "completedAt": done if bucket in {"pass", "fail"} else "0001-01-01T00:00:00Z",
    }


GREEN = [check("lint", "pass"), check("unit-tests", "pass"), check("docs-preview", "skipping")]


class StubGh:
    """A `gh` on a temporary PATH that answers from a scenario file and logs what it saw."""

    SCRIPT = """#!{python}
import json, os, sys
folder = os.environ["CI_STUB_DIR"]
args = sys.argv[1:]
seen = {{"args": args, "cwd": os.getcwd(), "env": dict(os.environ)}}
with open(os.path.join(folder, "calls.jsonl"), "a") as log:
    log.write(json.dumps(seen) + "\\n")
scenario = json.load(open(os.path.join(folder, "scenario.json")))
key = "view" if args[1] == "view" else "required" if "--required" in args else "checks"
answer = scenario[key]
if key == "view":
    views = sum(1 for line in open(os.path.join(folder, "calls.jsonl")) if '"view"' in line)
    if views > 1 and "view_second" in scenario:
        answer = scenario["view_second"]
if answer.get("sleep"):
    import time
    time.sleep(answer["sleep"])
sys.stdout.write(answer.get("stdout", ""))
sys.stderr.write(answer.get("stderr", ""))
sys.exit(answer.get("rc", 0))
"""

    def __init__(self, test: unittest.TestCase) -> None:
        self.folder = pathlib.Path(tempfile.mkdtemp())
        test.addCleanup(shutil.rmtree, self.folder, True)
        self.bin = self.folder / "bin"
        self.bin.mkdir()
        gh = self.bin / "gh"
        gh.write_text(self.SCRIPT.format(python=sys.executable))
        gh.chmod(0o755)
        self.set()

    def set(  # noqa: PLR0913 - a scenario is its keyword switches
        self,
        *,
        head: str = SESSION_HEAD,
        number: int = 12,
        checks: list[dict[str, str]] | None = None,
        checks_rc: int = 0,
        required: list[dict[str, str]] | None = None,
        view: dict[str, Any] | None = None,
        checks_raw: dict[str, Any] | None = None,
        required_raw: dict[str, Any] | None = None,
        head_after: str | None = None,
    ) -> None:
        scenario = {
            "view": view or {"stdout": json.dumps({"headRefOid": head, "number": number})},
            "checks": checks_raw
            or {"stdout": json.dumps(GREEN if checks is None else checks), "rc": checks_rc},
            "required": required_raw or {"stdout": json.dumps(required or [])},
        }
        if head_after is not None:
            scenario["view_second"] = {
                "stdout": json.dumps({"headRefOid": head_after, "number": number})
            }
        (self.folder / "scenario.json").write_text(json.dumps(scenario))

    @property
    def environ(self) -> dict[str, str]:
        return {"PATH": str(self.bin), "CI_STUB_DIR": str(self.folder)}

    @property
    def calls(self) -> list[dict[str, Any]]:
        path = self.folder / "calls.jsonl"
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text().splitlines()]


def binding(number: int = 12, source: str = ci_read.SOURCE_GOAL, branch: str = "") -> Any:
    return ci_read.Binding(REPO, number, source, branch)


def read(stub: StubGh, **over: Any) -> dict[str, Any]:
    options: dict[str, Any] = {
        "session_head": SESSION_HEAD,
        "caution": False,
        "now": 1_000.0,
        "environ": stub.environ,
    }
    options.update(over)
    chosen = options.pop("binding", None) or binding()
    return ci_read.read(chosen, **options)


class TheBindingNamesOnePullRequest(unittest.TestCase):
    def test_a_goal_url_binds(self) -> None:
        found = ci_read.bind([GOAL_TEXT], [], [], ("", ""))
        self.assertEqual(ci_read.Binding(REPO, 12, ci_read.SOURCE_GOAL), found)

    def test_the_goal_wins_over_a_record_that_names_another_pull_request(self) -> None:
        found = ci_read.bind([GOAL_TEXT], [(REPO, 99)], [], ("github.com", REPO))
        self.assertEqual(12, found.number if found else 0)

    def test_two_pull_requests_in_the_goal_bind_none(self) -> None:
        text = f"{GOAL_URL} and https://github.com/{REPO}/pull/13"
        self.assertIsNone(ci_read.bind([text], [(REPO, 99)], [], ("github.com", REPO)))

    def test_a_record_binds_only_when_its_repository_is_the_folders_remote(self) -> None:
        links = [("other-org/other", 5), (REPO, 7)]
        found = ci_read.bind([""], links, [], ("github.com", REPO))
        self.assertEqual(ci_read.Binding(REPO, 7, ci_read.SOURCE_RECORD), found)
        self.assertIsNone(ci_read.bind([""], [("other-org/other", 5)], [], ("github.com", REPO)))
        self.assertIsNone(ci_read.bind([""], links, [], ("", "")))
        self.assertIsNone(ci_read.bind([""], links, [], ("gitlab.com", REPO)))

    def test_a_push_binds_by_branch_when_no_link_does(self) -> None:
        found = ci_read.bind([""], [], ["fix/widget-guard"], ("github.com", REPO))
        self.assertEqual(ci_read.Binding(REPO, 0, ci_read.SOURCE_RECORD, "fix/widget-guard"), found)
        self.assertIsNone(ci_read.bind([""], [], ["fix/widget-guard"], ("", "")))

    def test_a_branch_a_command_line_could_misread_is_never_bound(self) -> None:
        for branch in ("--web", "-x", "12", "a..b", "a b", "x;y", "$(id)", "../up", "bad.lock", ""):
            with self.subTest(branch=branch):
                self.assertIsNone(ci_read.bind([""], [], [branch], ("github.com", REPO)))

    def test_owner_repository_and_number_must_be_plain(self) -> None:
        for url in (
            "https://github.com/ac me/widgets/pull/1",
            "https://github.com/acme/../pull/1",
            "https://github.com/acme/widgets/pull/0",
            "https://github.com/acme/widgets/pull/123456789",
            "https://gitlab.com/acme/widgets/pull/1",
            "http://github.com/acme/widgets/pull/1",
            "https://evil.example/github.com/acme/widgets/pull/1x",
        ):
            with self.subTest(url=url):
                self.assertEqual((), ci_read.pull_request_urls(url) if "evil" not in url else ())

    def test_a_remote_url_never_carries_its_credential_on(self) -> None:
        # The token is obviously fake; what matters is that nothing past the host and repository
        # survives the parse.
        host, repository = git_status.parse_remote(
            "https://user:FakePass99@github.com/acme/widgets.git"
        )
        self.assertEqual(("github.com", REPO), (host, repository))
        self.assertNotIn("FakePass99", f"{host}{repository}")


class TheLaunchKeepsEverySafeguard(unittest.TestCase):
    def setUp(self) -> None:
        self.stub = StubGh(self)

    def test_a_green_pull_request_on_the_sessions_commit(self) -> None:
        record = read(self.stub)
        self.assertEqual("", record["error"])
        self.assertTrue(record["head_matches"])
        self.assertEqual(
            {"pass": 2, "fail": 0, "pending": 0, "skipping": 1, "cancel": 0}, record["counts"]
        )
        self.assertIsNotNone(ci_read.validate(record))
        self.assertTrue(ci_read.green(record))

    def test_no_required_checks_keeps_the_whole_listing(self) -> None:
        self.stub.set(
            required_raw={
                "stdout": "",
                "stderr": "no required checks reported on the 'x' branch",
                "rc": 1,
            }
        )
        record = read(self.stub)
        self.assertEqual("", record["error"])
        self.assertFalse(record["required_only"])
        self.assertEqual(2, record["counts"]["pass"])
        self.assertTrue(ci_read.green(record))

    def test_a_signed_out_required_call_still_fails_the_read(self) -> None:
        self.stub.set(required_raw={"stdout": "", "stderr": "gh auth login", "rc": 1})
        self.assertEqual(ci_read.ERROR_SIGNED_OUT, read(self.stub)["error"])

    def test_the_argv_names_the_host_and_repository_and_asks_for_four_fields(self) -> None:
        read(self.stub)
        view, checks, required, after = (call["args"] for call in self.stub.calls)
        self.assertEqual(["pr", "view", "12", "--repo", f"github.com/{REPO}"], after[:5])
        self.assertEqual(["pr", "view", "12", "--repo", f"github.com/{REPO}"], view[:5])
        self.assertEqual("headRefOid,number", view[-1])
        self.assertEqual(["pr", "checks", "12", "--repo", f"github.com/{REPO}"], checks[:5])
        self.assertEqual("name,state,bucket,completedAt", checks[-1])
        self.assertIn("--required", required)

    def test_the_child_runs_in_an_empty_directory_with_no_override_and_no_prompt(self) -> None:
        hostile = {
            **self.stub.environ,
            "GH_HOST": "evil.example",
            "GH_TOKEN": "FakePass99",
            "GH_REPO": "evil/repo",
            "GITLAB_TOKEN": "FakePass99",
            "GL_HOST": "evil.example",
            "KEEP_ME": "yes",
        }
        read(self.stub, environ=hostile)
        for call in self.stub.calls:
            env = call["env"]
            for name in ("GH_HOST", "GH_TOKEN", "GH_REPO", "GITLAB_TOKEN", "GL_HOST"):
                self.assertNotIn(name, env)
            self.assertEqual("1", env["GH_PROMPT_DISABLED"])
            self.assertEqual("1", env["GH_NO_UPDATE_NOTIFIER"])
            self.assertEqual("yes", env["KEEP_ME"])
            # Private and empty when it was made; gone by the time anyone looks.
            self.assertIn("compass-ci-cwd-", call["cwd"])
            self.assertFalse(os.path.exists(call["cwd"]))

    def test_a_relative_path_element_never_supplies_the_binary(self) -> None:
        planted = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, planted, True)
        shutil.copy(self.stub.bin / "gh", planted / "gh")
        (planted / "gh").chmod(0o755)
        shutil.rmtree(self.stub.bin)
        previous = pathlib.Path.cwd()
        os.chdir(planted)
        self.addCleanup(os.chdir, previous)
        record = ci_read.read(
            binding(),
            session_head=SESSION_HEAD,
            caution=False,
            now=1.0,
            environ={"PATH": f".{os.pathsep}", "CI_STUB_DIR": str(self.stub.folder)},
        )
        self.assertEqual(ci_read.ERROR_MISSING, record["error"])
        self.assertEqual([], self.stub.calls)

    def test_nothing_is_launched_for_a_name_that_is_not_plain(self) -> None:
        for bad in (
            ci_read.Binding("acme/wid gets", 12, ci_read.SOURCE_GOAL),
            ci_read.Binding("acme/../x", 12, ci_read.SOURCE_GOAL),
            ci_read.Binding(REPO, 0, ci_read.SOURCE_RECORD, "--web"),
            ci_read.Binding(REPO, -3, ci_read.SOURCE_GOAL),
        ):
            with self.subTest(bad=bad):
                record = read(self.stub, binding=bad)
                self.assertEqual(ci_read.ERROR_FAILED, record["error"])
        self.assertEqual([], self.stub.calls)

    def test_a_push_looks_the_number_up_from_its_branch_once(self) -> None:
        record = read(self.stub, binding=binding(0, ci_read.SOURCE_RECORD, "fix/widget-guard"))
        self.assertEqual(12, record["number"])
        self.assertEqual("fix/widget-guard", self.stub.calls[0]["args"][2])

    def test_pending_checks_are_read_whatever_the_exit_code(self) -> None:
        self.stub.set(checks=[check("lint", "pass"), check("e2e", "pending")], checks_rc=8)
        record = read(self.stub)
        self.assertEqual("", record["error"])
        self.assertEqual(1, record["counts"]["pending"])
        self.assertFalse(ci_read.green(record))

    def test_a_failing_check_exits_one_and_is_still_read(self) -> None:
        self.stub.set(checks=[check("lint", "pass"), check("e2e", "fail")], checks_rc=1)
        record = read(self.stub)
        self.assertEqual(1, record["counts"]["fail"])

    def test_no_checks_reported_is_an_empty_read_not_an_error(self) -> None:
        self.stub.set(
            checks_raw={"stdout": "", "stderr": "no checks reported on the 'x' branch", "rc": 1}
        )
        record = read(self.stub)
        self.assertEqual("", record["error"])
        self.assertEqual([], record["checks"])
        self.assertFalse(ci_read.green(record))

    def test_required_checks_are_preferred_where_github_names_any(self) -> None:
        self.stub.set(
            checks=[check("lint", "pass"), check("nightly-soak", "fail")],
            required=[check("lint", "pass")],
        )
        record = read(self.stub)
        self.assertTrue(record["required_only"])
        self.assertEqual(["lint"], [row["name"] for row in record["checks"]])
        self.assertEqual(0, record["counts"]["fail"])
        self.assertTrue(ci_read.green(record))

    def test_a_moved_head_is_named_and_does_not_match(self) -> None:
        self.stub.set(head=OTHER_HEAD)
        record = read(self.stub)
        self.assertFalse(record["head_matches"])
        self.assertEqual(OTHER_HEAD, record["head"])

    def test_a_head_that_moved_while_the_checks_were_read_matches_nothing(self) -> None:
        # The session's commit equals the head the first look saw, and the second look differs: the
        # checks could be the new commit's, so they are reported under the new head and settle nothing.
        self.stub.set(head=SESSION_HEAD, head_after=OTHER_HEAD)
        record = read(self.stub)
        self.assertFalse(record["head_matches"])
        self.assertEqual(OTHER_HEAD, record["head"])

    def test_a_second_press_inside_the_floor_reads_nothing_new(self) -> None:
        floor = ci_read.Floor()
        first = read(self.stub, floor=floor)
        again = read(self.stub, floor=floor, now=1_010.0)
        self.assertEqual(first, again)
        self.assertEqual(4, len(self.stub.calls))
        read(self.stub, floor=floor, now=1_000.0 + ci_read.Floor.FLOOR_SEC + 1)
        self.assertEqual(8, len(self.stub.calls))

    def test_a_failed_read_is_never_kept_by_the_floor(self) -> None:
        floor = ci_read.Floor()
        self.stub.set(view={"stderr": "gh auth login", "rc": 4})
        self.assertEqual(ci_read.ERROR_SIGNED_OUT, read(self.stub, floor=floor)["error"])
        self.stub.set()
        self.assertEqual("", read(self.stub, floor=floor, now=1_001.0)["error"])

    def test_an_unknown_session_head_never_matches(self) -> None:
        self.assertFalse(read(self.stub, session_head="")["head_matches"])

    def test_the_closed_error_tokens(self) -> None:
        cases = (
            (
                "To get started with GitHub CLI, please run:  gh auth login",
                4,
                ci_read.ERROR_SIGNED_OUT,
            ),
            (
                "GraphQL: Could not resolve to a PullRequest with the number of 12.",
                1,
                ci_read.ERROR_NOT_FOUND,
            ),
            ("API rate limit exceeded for user", 1, ci_read.ERROR_RATE_LIMITED),
            ("something else entirely, with FakePass99 in it", 1, ci_read.ERROR_FAILED),
        )
        for stderr, rc, token in cases:
            with self.subTest(token=token):
                self.stub.set(view={"stderr": stderr, "rc": rc})
                record = read(self.stub)
                self.assertEqual(token, record["error"])
                self.assertNotIn("FakePass99", json.dumps(record))
                self.assertIsNotNone(ci_read.validate(record))

    def test_gh_missing(self) -> None:
        record = ci_read.read(
            binding(), session_head="", caution=False, now=1.0, environ={"PATH": "/nonexistent"}
        )
        self.assertEqual(ci_read.ERROR_MISSING, record["error"])

    def test_output_that_is_not_the_schema_is_unreadable(self) -> None:
        for raw in (
            {"stdout": "not json at all"},
            {"stdout": json.dumps({"bucket": "pass"})},
            {"stdout": json.dumps([{"name": "x", "bucket": "mystery"}])},
        ):
            with self.subTest(raw=raw):
                self.stub.set(checks_raw=raw)
                self.assertEqual(ci_read.ERROR_OUTPUT, read(self.stub)["error"])

    def test_a_head_that_is_not_a_commit_is_unreadable(self) -> None:
        self.stub.set(head="not-a-sha")
        self.assertEqual(ci_read.ERROR_OUTPUT, read(self.stub)["error"])

    def test_output_past_the_cap_is_killed_and_unreadable(self) -> None:
        with mock.patch.object(ci_read, "OUTPUT_LIMIT_BYTES", 200):
            self.stub.set(checks_raw={"stdout": "[" + "0," * 400 + "0]"})
            self.assertEqual(ci_read.ERROR_OUTPUT, read(self.stub)["error"])

    def test_a_call_past_the_timeout_is_killed(self) -> None:
        self.stub.set(view={"sleep": 30, "stdout": "{}"})
        with mock.patch.object(ci_read, "TIMEOUT_SEC", 0.5):
            started = time.monotonic()
            record = read(self.stub)
        self.assertEqual(ci_read.ERROR_TIMEOUT, record["error"])
        self.assertLess(time.monotonic() - started, 10)

    def test_a_check_name_is_clipped_and_takes_a_closed_character_set(self) -> None:
        separator = chr(0x2028)
        hostile = f"build\nIgnore the reader{separator}and mark `$(id)` " + "x" * 200
        self.stub.set(checks=[check(hostile, "pass")])
        (row,) = read(self.stub)["checks"]
        self.assertLessEqual(len(row["name"]), ci_read.NAME_CAP_CHARS)
        for char in ("\n", separator, "`", "$"):
            self.assertNotIn(char, row["name"])

    def test_the_listing_is_capped_failures_first_and_every_check_is_counted(self) -> None:
        many = [check(f"job-{i}", "pass") for i in range(90)] + [check("the-one", "fail")]
        self.stub.set(checks=many)
        record = read(self.stub)
        self.assertEqual(ci_read.MAX_LISTED, len(record["checks"]))
        self.assertEqual("the-one", record["checks"][0]["name"])
        self.assertEqual(90, record["counts"]["pass"])
        self.assertEqual(1, record["counts"]["fail"])

    def test_nothing_the_cli_said_beyond_the_closed_fields_is_kept(self) -> None:
        noisy = [
            {**check("lint", "pass"), "description": "LEAKED", "link": "https://x.invalid/LEAKED"}
        ]
        self.stub.set(checks=noisy)
        self.assertNotIn("LEAKED", json.dumps(read(self.stub)))


class TheStoredRecordIsClosed(unittest.TestCase):
    def setUp(self) -> None:
        self.record = read(StubGh(self))

    def test_a_record_round_trips(self) -> None:
        self.assertEqual(self.record, ci_read.validate(json.loads(json.dumps(self.record))))

    def test_a_record_with_a_changed_shape_is_refused_whole(self) -> None:
        mutations: tuple[Callable[[dict[str, Any]], object], ...] = (
            lambda r: r.update(error="a sentence of its own"),
            lambda r: r.update(extra=1),
            lambda r: r.update(repository="a b/c"),
            lambda r: r.update(head="zz"),
            lambda r: r.update(head_matches=True, head=OTHER_HEAD),
            lambda r: r["counts"].update(pass_=1),
            lambda r: r["checks"][0].update(bucket="mystery"),
            lambda r: r["checks"][0].update(name="line\nbreak"),
            lambda r: r.pop("caution"),
            lambda r: r.update(read_at=True),
        )
        for mutate in mutations:
            with self.subTest():
                changed = json.loads(json.dumps(self.record))
                mutate(changed)
                self.assertIsNone(ci_read.validate(changed))


def record_with(
    *checks: dict[str, str],
    head_matches: bool = True,
    caution: bool = False,
    required: bool = False,
) -> dict[str, Any]:
    listed = sorted(
        (
            {
                "name": c["name"],
                "bucket": c["bucket"],
                "completed_at": 1_700_000_000.0 if c["bucket"] in {"pass", "fail"} else None,
            }
            for c in checks
        ),
        key=lambda row: row["bucket"] != "fail",
    )
    counts = dict.fromkeys(ci_read.BUCKETS, 0)
    for row in listed:
        counts[str(row["bucket"])] += 1
    return {
        "read_at": 150.0,
        "error": "",
        "source": ci_read.SOURCE_GOAL,
        "repository": REPO,
        "number": 12,
        "head": SESSION_HEAD if head_matches else OTHER_HEAD,
        "session_head": SESSION_HEAD,
        "head_matches": head_matches,
        "required_only": required,
        "counts": counts,
        "caution": caution,
        "checks": listed,
    }


def counted(record: dict[str, Any]) -> dict[str, bool]:
    return {f["summary"]: f["ci_counts"] for f in ci_read.facts(record, "claude", "s1")}


class WhatGreenMeans(unittest.TestCase):
    def test_all_checks_passing_on_the_sessions_commit_counts(self) -> None:
        facts = ci_read.facts(record_with(*GREEN), "claude", "s1")
        by_result = {f["result"]: f["ci_counts"] for f in facts}
        self.assertTrue(by_result["passed"])
        self.assertFalse(by_result["skipped"])

    def test_pending_settles_nothing(self) -> None:
        record = record_with(check("lint", "pass"), check("e2e", "pending"))
        self.assertFalse(any(counted(record).values()))

    def test_zero_completed_checks_settle_nothing(self) -> None:
        self.assertEqual([], ci_read.facts(record_with(), "claude", "s1"))
        record = record_with(check("docs", "skipping"), check("e2e", "pending"))
        self.assertFalse(any(counted(record).values()))
        self.assertFalse(ci_read.green(record_with(check("docs", "skipping"))))

    def test_skipped_checks_count_as_neither(self) -> None:
        record = record_with(check("lint", "pass"), check("docs", "skipping"))
        facts = {f["result"]: f["ci_counts"] for f in ci_read.facts(record, "claude", "s1")}
        self.assertEqual({"passed": True, "skipped": False}, facts)

    def test_a_cancelled_check_is_not_a_pass(self) -> None:
        record = record_with(check("lint", "pass"), check("e2e", "cancel"))
        self.assertFalse(any(counted(record).values()))

    def test_a_head_past_the_sessions_commit_settles_nothing_and_says_so(self) -> None:
        record = record_with(*GREEN, head_matches=False)
        facts = ci_read.facts(record, "claude", "s1")
        self.assertFalse(any(f["ci_counts"] for f in facts))
        self.assertTrue(all(ci_read.HEAD_MOVED_TEXT in f["summary"] for f in facts))

    def test_a_failure_counts_only_on_the_sessions_commit(self) -> None:
        record = record_with(check("lint", "pass"), check("e2e", "fail"))
        self.assertEqual(
            [True],
            [
                f["ci_counts"]
                for f in ci_read.facts(record, "claude", "s1")
                if f["result"] == "failed"
            ],
        )
        moved = record_with(check("lint", "pass"), check("e2e", "fail"), head_matches=False)
        self.assertFalse(any(f["ci_counts"] for f in ci_read.facts(moved, "claude", "s1")))

    def test_an_edited_workflow_adds_a_caution_to_every_row_and_still_settles(self) -> None:
        facts = ci_read.facts(record_with(*GREEN, caution=True), "claude", "s1")
        self.assertTrue(all(ci_read.CAUTION_TEXT in f["summary"] for f in facts))
        self.assertTrue(any(f["ci_counts"] for f in facts))

    def test_which_writes_are_ci_configuration(self) -> None:
        self.assertTrue(ci_read.changed_ci_configuration([".github/workflows/ci.yml"]))
        self.assertTrue(ci_read.changed_ci_configuration(["app/.github/workflows/x.yaml"]))
        self.assertTrue(ci_read.changed_ci_configuration(["./.gitlab-ci.yml"]))
        self.assertFalse(ci_read.changed_ci_configuration(["src/app.py", "docs/workflows/a.md"]))

    def test_an_errored_read_has_no_facts(self) -> None:
        self.assertEqual(
            [], ci_read.facts({**record_with(*GREEN), "error": "gh-failed"}, "claude", "s1")
        )
        self.assertEqual([], ci_read.facts(None, "claude", "s1"))


def ci_goal_row(text: str = GOAL_TEXT, verdict_reason: str = "") -> dict[str, Any]:
    row = goal_row(verdict_reason)
    row["session_goal"]["text"] = text
    return row


class ACheckTheModelCitesCanSettleALine(base.AClaudeCodeReadingProducer):
    def _read(
        self, record: dict[str, Any] | None, answer: dict[str, Any], line: str = "CI is green"
    ) -> dict[str, Any]:
        assessment, why, _spent = reading.produce(
            self.config,  # type: ignore[arg-type]
            {"harness": "claude", "sid": "s1", "state": "working", "ended_at": None},
            [{"n": 1, "at": 50.0, "goal": GOAL_TEXT, "lines": [line]}],
            [base.WORDS_FACT],
            now=200.0,
            stamp_text="read at 10:00",
            model=self._model(json.dumps(answer)),
            read_lines=True,
            read_agent_words=True,
            ci=record,
        )
        self.assertEqual("", why)
        return cast("dict[str, Any]", assessment)

    def cite(self, record: dict[str, Any]) -> list[int]:
        facts = [base.WORDS_FACT, *ci_read.facts(record, "claude", "s1")]
        ledger = reading.build_ledger(facts, "claude", "s1")
        return [i + 1 for i, row in enumerate(ledger) if row["type"] == ci_read.FACT_TYPE]

    def consistent(self, record: dict[str, Any]) -> dict[str, Any]:
        cites = self.cite(record)
        answer = {"line_1": {"result": "consistent", "cites": cites, "detail": ""}}
        return cast("dict[str, Any]", self._read(record, answer)["criteria"]["line_1"])

    def test_green_ci_on_the_sessions_commit_reads_consistent_and_cites_the_checks(self) -> None:
        assessment = self._read(
            record_with(*GREEN),
            {
                "line_1": {
                    "result": "consistent",
                    "cites": self.cite(record_with(*GREEN)),
                    "detail": "",
                }
            },
        )
        row = assessment["criteria"]["line_1"]
        self.assertEqual(reading.RESULT_CONSISTENT, row["result"])
        self.assertTrue(row["cites"])
        self.assertTrue(all(c.startswith("ci:12:") for c in row["cites"]))
        self.assertEqual(record_with(*GREEN), assessment["ci"])
        # The checks are on the prompt, quoted, and nothing the CLI said besides.
        self.assertIn('"unit-tests" passed on the pull request', self.prompts[0])

    def test_pending_checks_cannot_carry_a_consistent(self) -> None:
        row = self.consistent(record_with(check("lint", "pass"), check("e2e", "pending")))
        self.assertEqual(reading.RESULT_UNVERIFIABLE, row["result"])

    def test_a_head_past_the_sessions_commit_cannot_carry_a_consistent(self) -> None:
        row = self.consistent(record_with(*GREEN, head_matches=False))
        self.assertEqual(reading.RESULT_UNVERIFIABLE, row["result"])

    def test_skipped_checks_alone_cannot_carry_a_consistent(self) -> None:
        row = self.consistent(record_with(check("docs", "skipping")))
        self.assertEqual(reading.RESULT_UNVERIFIABLE, row["result"])

    def test_a_workflow_edit_adds_a_caution_the_model_reads_and_still_settles(self) -> None:
        record = record_with(*GREEN, caution=True)
        row = self.consistent(record)
        self.assertEqual(reading.RESULT_CONSISTENT, row["result"])
        self.assertIn(ci_read.CAUTION_TEXT, self.prompts[0])

    def test_a_failure_on_the_sessions_commit_carries_a_departure(self) -> None:
        record = record_with(check("lint", "pass"), check("e2e", "fail"))
        failed = [
            n
            for n, row in zip(
                self.cite(record),
                [
                    r
                    for r in reading.build_ledger(
                        [base.WORDS_FACT, *ci_read.facts(record, "claude", "s1")], "claude", "s1"
                    )
                    if r["type"] == ci_read.FACT_TYPE
                ],
                strict=True,
            )
            if row["result"] == "failed"
        ]
        answer = {"line_1": {"result": "departure", "cites": failed, "detail": "e2e failed."}}
        row = self._read(record, answer)["criteria"]["line_1"]
        self.assertEqual(reading.RESULT_DEPARTURE, row["result"])

    def test_a_read_does_not_stand_in_for_a_session_that_did_nothing_since_the_words(self) -> None:
        # The words came at 300, the session's only entry is from before them, and the read is at
        # the press: the reading is still withheld for want of anything in the window.
        record = {**record_with(*GREEN), "read_at": 350.0}
        assessment, why, spent = reading.produce(
            self.config,  # type: ignore[arg-type]
            {"harness": "claude", "sid": "s1", "state": "working", "ended_at": None},
            [{"n": 1, "at": 300.0, "goal": GOAL_TEXT, "lines": ["CI is green"]}],
            [base.WORDS_FACT],
            now=400.0,
            stamp_text="read at 10:00",
            model=self._model("{}"),
            read_lines=True,
            read_agent_words=True,
            ci=record,
        )
        self.assertIsNone(assessment)
        self.assertEqual(reading.WITHHELD_WINDOW_EMPTY, why)
        self.assertFalse(spent)
        self.assertEqual([], self.prompts)

    def test_no_read_leaves_the_assessment_without_the_key(self) -> None:
        assessment = self._read(None, {"line_1": {"result": "unverifiable", "cites": []}})
        self.assertNotIn("ci", assessment)

    def test_the_ci_facts_reach_the_ledger_with_no_tool_output_grant(self) -> None:
        facts = [base.WORDS_FACT, *ci_read.facts(record_with(*GREEN), "claude", "s1")]
        rows = reading.build_ledger(facts, "claude", "s1")
        self.assertEqual(3, len([r for r in rows if r["type"] == ci_read.FACT_TYPE]))
        self.assertTrue(all(r.get("work") is True for r in rows if r["type"] == ci_read.FACT_TYPE))


class TheLevelRestsOnAStoredCiRead(base.AClaudeCodeReadingProducer):
    """DEC-26's 2026-10-27 amendment: a CI fact is a recorded harness fact for None or low."""

    def level(self, record: dict[str, Any]) -> levels.Level:
        facts = [base.WORDS_FACT, *ci_read.facts(record, "claude", "s1")]
        ledger = reading.build_ledger(facts, "claude", "s1")
        cites = [r["id"] for r in ledger if r["type"] == ci_read.FACT_TYPE]
        stored = {
            "revision_read": 1,
            "read_at": 200.0,
            "scope": reading.SCOPE_FINAL,
            "window_start": 50.0,
            "criteria": {
                reading.CONSTRAINT_GOAL: {
                    "result": reading.RESULT_CONSISTENT,
                    "cites": cites,
                    "detail": "",
                    "clause": GOAL_TEXT,
                    "why": reading.WHY_STANDS,
                }
            },
        }
        scan = dict.fromkeys(levels.SCAN_KEYS, 0)
        evidence = levels.Evidence(tuple(facts), scan, 0)
        return levels.analysis_level(stored, evidence, outcome_lines=0, lines=())

    def test_a_cited_green_ci_reaches_none_or_low(self) -> None:
        level = self.level(record_with(*GREEN))
        self.assertEqual(levels.NONE_OR_LOW, level.level, level.reasons)

    def test_a_pending_ci_keeps_the_level_at_not_enough(self) -> None:
        level = self.level(record_with(check("lint", "pass"), check("e2e", "pending")))
        self.assertEqual(levels.NOT_ENOUGH, level.level)

    def test_a_moved_head_keeps_the_level_at_not_enough(self) -> None:
        self.assertEqual(
            levels.NOT_ENOUGH, self.level(record_with(*GREEN, head_matches=False)).level
        )


class TheHarnessVerdictIsTestedAgainstTheChecks(base.AClaudeCodeReadingProducer):
    def checked(self, record: dict[str, Any] | None) -> dict[str, Any]:
        assessment, why, _spent = reading.produce(
            self.config,  # type: ignore[arg-type]
            ci_goal_row(),
            [{"n": 1, "at": 50.0, "goal": GOAL_TEXT, "lines": []}],
            [base.WORDS_FACT],
            now=200.0,
            stamp_text="read at 10:00",
            model=self._model(json.dumps({"goal": {"result": "consistent", "cites": [1]}})),
            read_lines=True,
            read_agent_words=True,
            ci=record,
        )
        self.assertEqual("", why)
        return cast("dict[str, Any]", cast("Any", assessment)["goal_verdict"])

    def test_green_checks_on_the_named_pull_request_agree(self) -> None:
        verdict = self.checked(record_with(*GREEN))
        self.assertEqual(reading.GOAL_VERDICT_AGREES, verdict["check"])
        self.assertEqual(reading.GOAL_VERDICT_CI, verdict["why"])
        self.assertTrue(verdict["cites"])

    def test_a_failing_check_disputes_it(self) -> None:
        verdict = self.checked(record_with(check("lint", "pass"), check("e2e", "fail")))
        self.assertEqual(reading.GOAL_VERDICT_DISPUTED, verdict["check"])

    def test_pending_a_moved_head_or_no_read_leave_it_unconfirmed(self) -> None:
        for record in (
            record_with(check("lint", "pass"), check("e2e", "pending")),
            record_with(*GREEN, head_matches=False),
            None,
        ):
            with self.subTest():
                self.assertEqual(reading.GOAL_VERDICT_UNCONFIRMED, self.checked(record)["check"])

    def test_checks_of_a_pull_request_the_goal_does_not_name_do_not_agree(self) -> None:
        other = {**record_with(*GREEN), "number": 13}
        self.assertEqual(reading.GOAL_VERDICT_UNCONFIRMED, self.checked(other)["check"])


class TheTranscriptRecordsAreScanned(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.config = types.SimpleNamespace(reverse_chunk_bytes=65_536)

    def transcript(self, rows: list[dict[str, Any]]) -> str:
        path = self.dir / "session.jsonl"
        path.write_text("".join(json.dumps(row) + "\n" for row in rows))
        return str(path)

    def test_pr_link_rows_and_pushed_branches_are_read_newest_first(self) -> None:
        path = self.transcript(
            [
                {"type": "pr-link", "prNumber": 3, "prUrl": "u", "prRepository": REPO},
                {
                    "type": "user",
                    "toolUseResult": {"gitOperation": {"push": {"branch": "fix/one"}}},
                },
                {"type": "pr-link", "prNumber": 9, "prUrl": "u", "prRepository": REPO},
                {
                    "type": "user",
                    "toolUseResult": {"gitOperation": {"push": {"branch": "fix/two"}}},
                },
            ]
        )
        links, pushes = ci_read.scan_records(cast("Any", self.config), path)
        self.assertEqual(((REPO, 9), (REPO, 3)), links)
        self.assertEqual(("fix/two", "fix/one"), pushes)

    def test_odd_rows_are_skipped(self) -> None:
        path = self.transcript(
            [
                {"type": "pr-link", "prNumber": "9", "prRepository": REPO},
                {"type": "pr-link", "prNumber": 9, "prRepository": "a b/c"},
                {"type": "pr-link", "prNumber": True, "prRepository": REPO},
                {"type": "user", "toolUseResult": {"gitOperation": {"push": {"branch": "--web"}}}},
                {"type": "assistant", "message": {"text": 'mentions "pr-link" and "gitOperation"'}},
            ]
        )
        self.assertEqual(((), ()), ci_read.scan_records(cast("Any", self.config), path))


class _PressCase(unittest.TestCase):
    """The config, application and hooks a press runs against, and a guard on every subprocess."""

    def setUp(self) -> None:
        # The floor is the process's and the clock here never moves, so a read an earlier test made
        # would answer this one without launching anything.
        ci_read.FLOOR.clear()
        self.addCleanup(ci_read.FLOOR.clear)
        self.stub = StubGh(self)
        self.state = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.state, True)
        self.config = types.SimpleNamespace(
            state_dir=self.state,
            ci_read_enabled=True,
            model_calls_disabled=False,
            git_probe_enabled=True,
            git_probe_timeout_sec=5.0,
            reverse_chunk_bytes=65_536,
        )
        self.application = types.SimpleNamespace(
            config=self.config, state=object(), clock=lambda: 1_000.0
        )
        self.handler = types.SimpleNamespace(
            server=types.SimpleNamespace(application=self.application)
        )
        self.hooks = types.SimpleNamespace(cancelled=lambda: False, ci_spawned=lambda _group: None)

    def boom(self) -> Any:
        return mock.patch.multiple(
            subprocess,
            Popen=mock.Mock(side_effect=AssertionError("a subprocess was started")),
            run=mock.Mock(side_effect=AssertionError("a subprocess was started")),
        )


class NoCommandRunsWithoutAPressABindingAndTheSwitchOn(_PressCase):
    """A test that fails on any subprocess, at every site `ci_read` could launch from."""

    def read_ci(self, goal: str = GOAL_TEXT) -> dict[str, Any] | None:
        row = {"harness": "claude", "sid": "s1", "session_goal": {"text": goal, "at": 1.0}}
        entry = {"revisions": [{"n": 1, "goal": goal}]}
        # A session folder the harness recorded, with no git behind it: the read is then allowed to
        # launch, and the head the session was on is unknown.
        with (
            mock.patch.object(project_context, "session_folder", return_value="/x"),
            mock.patch.object(ci_read, "probe_session", return_value=None),
        ):
            return http_api._read_ci(
                cast("Any", self.application),
                row,
                cast("Any", entry),
                "t.jsonl",
                [],
                cast("Any", self.hooks),
            )

    def test_no_binding_no_launch(self) -> None:
        with self.boom(), mock.patch.object(supervise, "run", side_effect=AssertionError("run")):
            self.assertIsNone(self.read_ci("no pull request is named here"))

    def test_the_page_setting_off_no_launch(self) -> None:
        self.assertTrue(ci_read.set_setting(cast("Any", self.config), on=False))
        self.assertEqual(ci_read.SETTING_OFF, ci_read.setting(cast("Any", self.config)))
        with self.boom(), mock.patch.object(supervise, "run", side_effect=AssertionError("run")):
            self.assertIsNone(self.read_ci())

    def test_the_flag_no_launch_and_the_page_cannot_lift_it(self) -> None:
        self.config.ci_read_enabled = False
        self.assertFalse(ci_read.set_setting(cast("Any", self.config), on=True))
        self.assertEqual(ci_read.SETTING_FLAG, ci_read.setting(cast("Any", self.config)))
        with self.boom(), mock.patch.object(supervise, "run", side_effect=AssertionError("run")):
            self.assertIsNone(self.read_ci())

    def test_no_observer_model_no_launch(self) -> None:
        self.config.model_calls_disabled = True
        with self.boom(), mock.patch.object(supervise, "run", side_effect=AssertionError("run")):
            self.assertIsNone(self.read_ci())

    def test_a_cancelled_job_no_launch(self) -> None:
        self.hooks.cancelled = lambda: True
        with self.boom(), mock.patch.object(supervise, "run", side_effect=AssertionError("run")):
            self.assertIsNone(self.read_ci())

    def test_a_press_with_a_binding_and_the_switch_on_reads_once(self) -> None:
        with mock.patch.dict(os.environ, self.stub.environ, clear=True):
            record = self.read_ci()
        assert record is not None
        self.assertEqual("", record["error"])
        self.assertEqual(4, len(self.stub.calls))
        # No folder was recorded, so no session commit: the read happened and settles nothing.
        self.assertFalse(record["head_matches"])

    def test_every_launch_hands_its_group_to_the_cancel_hook(self) -> None:
        groups: list[Any] = []
        self.hooks.ci_spawned = groups.append
        with mock.patch.dict(os.environ, self.stub.environ, clear=True):
            self.assertIsNotNone(self.read_ci())
        self.assertEqual(4, len(self.stub.calls))
        self.assertEqual(4, len(groups))

    def test_the_route_hands_produce_the_read_unrun(self) -> None:
        # A route that evaluated the read as an argument would launch gh for a press `produce`
        # then withholds; this fails on that.
        launched: list[int] = []
        seen: dict[str, Any] = {}

        def produce(*_args: Any, **kwargs: Any) -> tuple[None, str, bool]:
            seen.update(kwargs)
            return None, reading.WITHHELD_WINDOW_EMPTY, False

        route = types.SimpleNamespace()
        row = {"harness": "claude", "sid": "s1", "state": "working", "ended_at": None}
        entry = {"revisions": [{"n": 1, "at": 50.0, "goal": GOAL_TEXT}]}
        with (
            mock.patch.object(http_api, "_read_ci", side_effect=lambda *_a: launched.append(1)),
            mock.patch.object(reading, "produce", side_effect=produce),
            mock.patch.object(observer, "resolve_transcript", return_value=""),
            mock.patch.object(http_api, "_session_context", return_value={}),
            mock.patch.object(http_api, "_facts_of", return_value=[]),
            self.boom(),
        ):
            self.hooks.phase = lambda *_a: None
            self.handler._reading_arguments = lambda *_a: {}
            result = http_api._RequestHandler._compose_reading(
                cast("Any", self.handler),
                row,
                cast("Any", entry),
                cast("Any", route),
                cast("Any", self.hooks),
            )
            self.assertEqual(reading.WITHHELD_WINDOW_EMPTY, result[1])
            self.assertTrue(callable(seen["ci"]))
            self.assertEqual([], launched)
            seen["ci"]()
            self.assertEqual([1], launched)

    def test_turning_it_back_on_removes_the_marker(self) -> None:
        cfg = cast("Any", self.config)
        ci_read.set_setting(cfg, on=False)
        ci_read.set_setting(cfg, on=True)
        self.assertEqual(ci_read.SETTING_ON, ci_read.setting(cfg))

    def test_reading_without_a_press_never_reaches_the_launcher(self) -> None:
        # `produce` is the other path a reading takes; with no `ci` it runs nothing of its own.
        with self.boom(), mock.patch.object(supervise, "run", side_effect=AssertionError("run")):
            assessment, why, _ = reading.produce(
                cast("Any", base.WhatOnePressActuallyCostsAndProduces._Config()),
                {"harness": "claude", "sid": "s1", "state": "working", "ended_at": None},
                [{"n": 1, "at": 50.0, "goal": GOAL_TEXT, "lines": ["CI is green"]}],
                [base.WORDS_FACT],
                now=200.0,
                stamp_text="t",
                model=lambda _p, **_k: ('{"line_1": {"result": "unverifiable"}}', "ok"),
                read_lines=True,
                read_agent_words=True,
            )
        self.assertEqual("", why)
        self.assertIsNotNone(assessment)


def _real_git() -> str | None:
    return shutil.which("git")


@unittest.skipUnless(_real_git(), "needs a git executable")
class ThePressTimeIdentityReadsTheFolder(unittest.TestCase):
    """`git_status.identity` and `probe_session` against a real temporary repository."""

    def setUp(self) -> None:
        self.folder = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.folder, True)
        self.repo = self.folder / "repo"
        self.repo.mkdir()
        self.git("init", "-q")
        self.git(
            "-c",
            "user.name=T",
            "-c",
            "user.email=t@example.com",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "-q",
            "--allow-empty",
            "-m",
            "x",
        )

    def git(self, *args: str) -> None:
        subprocess.run(
            ["git", *args],  # noqa: S607 - the test's own repository, a real git on PATH
            cwd=self.repo,
            check=True,
            capture_output=True,
        )

    def test_the_head_and_the_origin(self) -> None:
        self.git("remote", "add", "origin", f"https://github.com/{REPO}.git")
        found = git_status.identity(str(self.repo), timeout_sec=5.0)
        assert found is not None
        self.assertEqual(("github.com", REPO), (found.host, found.repository))
        self.assertRegex(found.head, r"^[0-9a-f]{40}$")

    def test_no_origin_keeps_the_head(self) -> None:
        found = git_status.identity(str(self.repo), timeout_sec=5.0)
        assert found is not None
        self.assertEqual(("", ""), (found.host, found.repository))
        self.assertRegex(found.head, r"^[0-9a-f]{40}$")

    def test_a_missing_folder_and_a_non_repository_read_nothing(self) -> None:
        self.assertIsNone(git_status.identity(str(self.folder / "absent"), timeout_sec=5.0))
        plain = self.folder / "plain"
        plain.mkdir()
        self.assertIsNone(git_status.identity(str(plain), timeout_sec=5.0))

    def test_a_failing_or_non_hex_runner_reads_nothing(self) -> None:
        failed = mock.Mock(return_value=types.SimpleNamespace(returncode=1, stdout=b""))
        self.assertIsNone(git_status.identity(str(self.repo), timeout_sec=5.0, runner=failed))
        junk = mock.Mock(return_value=types.SimpleNamespace(returncode=0, stdout=b"not-a-commit"))
        self.assertIsNone(git_status.identity(str(self.repo), timeout_sec=5.0, runner=junk))

    def test_no_git_launches_nothing(self) -> None:
        config = types.SimpleNamespace(git_probe_enabled=False, git_probe_timeout_sec=5.0)
        boom = mock.Mock(side_effect=AssertionError("a subprocess was started"))
        with mock.patch.multiple(subprocess, Popen=boom, run=boom):
            self.assertIsNone(ci_read.probe_session(cast("Any", config), str(self.repo)))
            self.assertIsNone(ci_read.probe_session(cast("Any", config), ""))

    def test_a_press_binds_a_pr_link_record_to_the_folders_own_origin(self) -> None:
        self.git("remote", "add", "origin", f"https://github.com/{REPO}.git")
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"],  # noqa: S607
            cwd=self.repo,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        stub = StubGh(self)
        stub.set(head=head, number=7)
        record = self.press(stub, REPO)
        assert record is not None
        self.assertEqual("", record["error"])
        self.assertEqual(ci_read.SOURCE_RECORD, record["source"])
        self.assertTrue(record["head_matches"])

    def test_a_record_for_another_repository_makes_no_gh_call(self) -> None:
        self.git("remote", "add", "origin", "https://github.com/acme/other.git")
        stub = StubGh(self)
        self.assertIsNone(self.press(stub, REPO))
        self.assertEqual([], stub.calls)

    def press(self, stub: StubGh, linked: str) -> dict[str, Any] | None:
        transcript = self.folder / "session.jsonl"
        rows = [
            {"type": "user", "cwd": str(self.repo)},
            {"type": "pr-link", "prRepository": linked, "prNumber": 7},
        ]
        transcript.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
        config = types.SimpleNamespace(
            state_dir=self.folder,
            ci_read_enabled=True,
            model_calls_disabled=False,
            git_probe_enabled=True,
            git_probe_timeout_sec=5.0,
            reverse_chunk_bytes=65_536,
            claude_cwd_scan_lines=50,
            claude_cwd_line_bytes=65_536,
            max_cache_entries=16,
        )
        state = types.SimpleNamespace(cache_lock=threading.Lock(), cwd_cache={})
        application = types.SimpleNamespace(config=config, state=state, clock=lambda: 1_000.0)
        row = {"harness": "claude", "sid": "s1", "session_goal": {"text": "tidy up", "at": 1.0}}
        entry = {"revisions": [{"n": 1, "goal": "tidy up"}]}
        hooks = types.SimpleNamespace(cancelled=lambda: False, ci_spawned=lambda _group: None)
        git_dir = str(pathlib.Path(cast("str", _real_git())).parent)
        environ = {
            "PATH": os.pathsep.join([str(stub.bin), git_dir]),
            "CI_STUB_DIR": str(stub.folder),
        }
        with mock.patch.dict(os.environ, environ, clear=True):
            return http_api._read_ci(
                cast("Any", application),
                row,
                cast("Any", entry),
                str(transcript),
                [],
                cast("Any", hooks),
            )


class ARecordedCiPollIsReadForWhatItNames(unittest.TestCase):
    """`parse_poll` reads the repository and target of a poll, and `poll_bound` decides whether
    the session's own records bind it. Nothing here runs `gh`."""

    REMOTE = ("github.com", REPO)

    def poll(self, line: str, raw: tuple[str, ...] = ()) -> ci_read.Poll:
        words = line.split()
        kind = "pr_checks" if words[1] == "pr" else "run_view"
        return ci_read.parse_poll(kind, words, raw)

    def test_the_repository_is_read_from_every_spelling_gh_takes(self) -> None:
        for flag in ("--repo other/old", "-R other/old", "--repo=other/old", "-Rother/old"):
            self.assertEqual("other/old", self.poll(f"gh pr checks 4 {flag}").repository, flag)
        self.assertEqual(REPO, self.poll(f"gh pr checks --repo github.com/{REPO}").repository)
        self.assertEqual(
            REPO, self.poll(f"gh pr checks --repo https://github.com/{REPO}.git").repository
        )
        self.assertEqual("", self.poll("gh pr checks 4").repository)

    def test_the_target_is_the_one_positional_word_past_the_options_values(self) -> None:
        self.assertEqual(4, self.poll("gh pr checks --watch --interval 5 4").number)
        self.assertEqual(4, self.poll("gh pr checks 4 --json name,state").number)
        self.assertEqual("fix/widget-guard", self.poll("gh pr checks fix/widget-guard").branch)
        url = self.poll(f"gh pr checks https://github.com/{REPO}/pull/8")
        self.assertEqual((REPO, 8), (url.repository, url.number))
        self.assertEqual(ci_read.Poll(), self.poll("gh pr checks"))
        self.assertEqual(ci_read.Poll(), self.poll("gh run view 123 --exit-status"))

    def test_a_poll_it_cannot_read_binds_to_nothing(self) -> None:
        for line in (
            "gh pr checks 1 2",
            "gh pr checks 0",
            "gh pr checks --repo nowhere",
            "gh pr checks 4 --repo a/b -R c/d",
            f"gh pr checks https://github.com/{REPO}/pull/8 --repo other/old",
            "gh pr checks ../etc",
        ):
            self.assertFalse(self.poll(line).valid, line)

    def test_an_operand_int_cannot_parse_binds_to_nothing_without_raising(self) -> None:
        for operand in ("\u00b2", "\u0663", "9" * 5000):
            self.assertFalse(self.poll(f"gh pr checks {operand}").valid, operand)
            run = ci_read.parse_poll("run_view", ["gh", "run", "view", operand, "--exit-status"])
            self.assertFalse(run.valid, operand)

    def test_an_all_digit_operand_too_long_to_be_a_number_binds_to_nothing(self) -> None:
        for operand in ("9" * 25, "0" * 30):
            poll = self.poll(f"gh pr checks {operand}")
            self.assertEqual((False, ""), (poll.valid, poll.branch), operand)

    def test_a_gh_repo_assignment_is_a_repository_the_poll_names(self) -> None:
        self.assertEqual(
            "other/old", self.poll("gh pr checks 4", raw=("GH_REPO=other/old", "gh")).repository
        )

    def test_a_run_view_names_a_run_id_or_a_run_url_and_nothing_else(self) -> None:
        url = f"https://github.com/{REPO}/actions/runs/5"
        self.assertEqual(REPO, self.poll(f"gh run view {url} --exit-status").repository)
        self.assertEqual(REPO, self.poll(f"gh run view {url}/job/9").repository)
        self.assertEqual(
            "other/old",
            self.poll("gh run view https://github.com/other/old/actions/runs/5").repository,
        )
        self.assertEqual("other/old", self.poll("gh run view 5 -R other/old").repository)
        for line in (
            "gh run view other-url --exit-status",
            "gh run view https://example.com/acme/widgets/actions/runs/5",
            f"gh run view {url} --repo other/old",
            "gh run view 5 6",
            "gh run view 0",
        ):
            self.assertFalse(self.poll(line).valid, line)

    def test_an_environment_pointing_gh_at_another_host_or_repository_binds_nothing(self) -> None:
        for name in ("GH_HOST=ghe.example.com", "GH_ENTERPRISE_TOKEN=FakePass99"):
            self.assertFalse(self.poll("gh pr checks 4", raw=(name, "gh")).valid, name)
        for word in ("GH_REPO=other/old", "GH_HOST=ghe.example.com", "GH_ENTERPRISE_TOKEN=x"):
            poll = ci_read.parse_poll(
                "pr_checks", ["gh", "pr", "checks", "4"], (), ("export", word)
            )
            self.assertFalse(poll.valid, word)
        clean = ci_read.parse_poll("pr_checks", ["gh", "pr", "checks", "4"], (), ("export", "A=1"))
        self.assertTrue(clean.valid)

    def test_a_poll_binds_only_inside_the_folders_own_repository(self) -> None:
        goal = [f"https://github.com/{REPO}/pull/3"]
        bound = ci_read.poll_bound
        self.assertTrue(bound(self.poll("gh pr checks 3"), self.REMOTE, goal, [], []))
        self.assertTrue(
            bound(self.poll(f"gh pr checks 3 -R {REPO.upper()}"), self.REMOTE, goal, [], [])
        )
        self.assertFalse(bound(self.poll("gh pr checks 3 -R other/old"), self.REMOTE, goal, [], []))
        self.assertFalse(bound(self.poll("gh pr checks 4"), self.REMOTE, goal, [], []))
        self.assertTrue(bound(self.poll("gh pr checks 4"), self.REMOTE, [], [(REPO, 4)], []))
        self.assertFalse(
            bound(self.poll("gh pr checks 4"), self.REMOTE, [], [("other/old", 4)], [])
        )
        self.assertTrue(bound(self.poll("gh pr checks fix/one"), self.REMOTE, [], [], ["fix/one"]))
        self.assertFalse(bound(self.poll("gh pr checks fix/two"), self.REMOTE, [], [], ["fix/one"]))
        self.assertTrue(bound(self.poll("gh pr checks"), self.REMOTE, [], [], []))
        self.assertTrue(bound(self.poll("gh run view 9 --exit-status"), self.REMOTE, [], [], []))

    def test_a_goal_url_in_another_repository_does_not_bind_a_poll_here(self) -> None:
        goal = ["https://github.com/other/old/pull/3"]
        self.assertFalse(ci_read.poll_bound(self.poll("gh pr checks 3"), self.REMOTE, goal, [], []))

    def test_no_remote_or_a_foreign_one_binds_nothing(self) -> None:
        for remote in (("", ""), ("gitlab.example.net", REPO), ("github.com", "")):
            self.assertFalse(ci_read.poll_bound(self.poll("gh pr checks"), remote, [], [], []))


class TheLaunchWaitsForTheDecisionToRead(base.AClaudeCodeReadingProducer):
    """Item 2 of the follow-ups: a withheld press launches nothing, and a Cancel kills a call."""

    def produce(self, ci: Any, **over: Any) -> tuple[Any, str, bool]:
        facts = over.pop("facts", [base.WORDS_FACT])
        row = over.pop(
            "row", {"harness": "claude", "sid": "s1", "state": "working", "ended_at": None}
        )
        options: dict[str, Any] = {
            "now": 200.0,
            "stamp_text": "read at 10:00",
            "model": self._model(json.dumps({"line_1": {"result": "unverifiable", "cites": []}})),
            "read_lines": True,
            "read_agent_words": True,
            "ci": ci,
        }
        options.update(over)
        return reading.produce(
            self.config,  # type: ignore[arg-type]
            row,
            [{"n": 1, "at": 50.0, "goal": GOAL_TEXT, "lines": ["CI is green"]}],
            facts,
            **options,
        )

    def test_a_withheld_press_never_calls_the_read(self) -> None:
        calls: list[int] = []

        def lazy() -> dict[str, Any]:
            calls.append(1)
            return record_with(*GREEN)

        assessment, why, spent = self.produce(lazy, record_withheld=reading.WITHHELD_WINDOW_EMPTY)
        self.assertIsNone(assessment)
        self.assertEqual(reading.WITHHELD_WINDOW_EMPTY, why)
        self.assertFalse(spent)
        self.assertEqual([], calls)

    def _counted(self, facts: list[dict[str, Any]], **over: Any) -> tuple[str, list[int]]:
        calls: list[int] = []

        def lazy() -> dict[str, Any]:
            calls.append(1)
            return record_with(*GREEN)

        assessment, why, spent = self.produce(lazy, facts=facts, **over)
        self.assertIsNone(assessment)
        self.assertFalse(spent)
        return why, calls

    def test_a_press_with_nothing_since_the_words_launches_nothing(self) -> None:
        early = {**base.WORDS_FACT, "at": 10.0}
        why, calls = self._counted([early])
        self.assertEqual(reading.WITHHELD_WINDOW_EMPTY, why)
        self.assertEqual([], calls)

    def test_a_press_with_no_facts_launches_nothing(self) -> None:
        why, calls = self._counted([])
        self.assertEqual(reading.WITHHELD_LEDGER_EMPTY, why)
        self.assertEqual([], calls)

    def test_a_press_with_nothing_inside_the_stop_launches_nothing(self) -> None:
        row = {
            "harness": "claude",
            "sid": "s1",
            "state": "idle",
            "acquisition": "event",
            "finished_at": 60.0,
            "ended_at": None,
        }
        why, calls = self._counted([base.WORDS_FACT], row=row, admit_turn_stop=True)
        self.assertEqual(reading.WITHHELD_AFTER_STOP, why)
        self.assertEqual([], calls)

    def test_a_press_that_reads_calls_it_once_and_stores_what_it_returned(self) -> None:
        calls: list[int] = []

        def lazy() -> dict[str, Any]:
            calls.append(1)
            return record_with(*GREEN)

        assessment, why, _ = self.produce(lazy)
        self.assertEqual("", why)
        self.assertEqual([1], calls)
        self.assertEqual(record_with(*GREEN), cast("Any", assessment)["ci"])

    def test_a_read_that_found_nothing_leaves_the_key_off(self) -> None:
        assessment, _, _ = self.produce(lambda: None)
        self.assertNotIn("ci", cast("Any", assessment))


class ACancelKillsACallAlreadyInFlight(unittest.TestCase):
    def setUp(self) -> None:
        self.stub = StubGh(self)

    def test_a_slow_gh_is_killed_when_the_group_is_cancelled(self) -> None:
        self.stub.set(
            view={"sleep": 30, "stdout": json.dumps({"headRefOid": SESSION_HEAD, "number": 12})}
        )
        seen: list[Any] = []
        record: list[dict[str, Any]] = []

        def spawned(group: Any) -> None:
            seen.append(group)
            threading.Timer(0.3, group.cancel).start()

        started = time.monotonic()
        worker = threading.Thread(
            target=lambda: record.append(read(self.stub, on_spawn=spawned)), daemon=True
        )
        worker.start()
        worker.join(15)
        self.assertFalse(worker.is_alive(), "the call outlived its Cancel")
        self.assertLess(time.monotonic() - started, 10)
        self.assertEqual(1, len(seen))
        self.assertTrue(record[0]["error"])

    def test_the_job_hands_each_call_group_to_a_cancel_that_already_came(self) -> None:
        from compass_runtime import reading_jobs  # noqa: PLC0415 - only this test needs it

        job = reading.Job(
            id="j1",
            harness="claude",
            sid="s1",
            provider="claude",
            label="Claude Code",
            phase=reading.PHASE_PREPARING,
            started_at=1.0,
            phase_at=1.0,
        )
        hooks = reading_jobs.Hooks(cast("Any", types.SimpleNamespace()), job)
        group = mock.Mock()
        hooks.ci_spawned(group)
        group.cancel.assert_not_called()
        self.assertIs(group, job.group)
        job.cancelled_at = 2.0
        later = mock.Mock()
        hooks.ci_spawned(later)
        later.cancel.assert_called_once_with()


class TheReadSaysWhatItLeftOut(unittest.TestCase):
    def setUp(self) -> None:
        self.stub = StubGh(self)

    def test_non_required_checks_are_counted_not_listed(self) -> None:
        self.stub.set(
            checks=[
                check("lint", "pass"),
                check("nightly-soak", "fail"),
                check("docs-preview", "pending"),
            ],
            required=[check("lint", "pass")],
        )
        record = read(self.stub)
        self.assertTrue(record["required_only"])
        self.assertEqual(2, record["not_counted"])
        self.assertEqual(["lint"], [row["name"] for row in record["checks"]])
        self.assertEqual(record, ci_read.validate(json.loads(json.dumps(record))))

    def test_no_required_checks_leaves_nothing_out(self) -> None:
        self.assertEqual(0, read(self.stub)["not_counted"])

    def test_a_record_from_before_the_count_reads_as_none_left_out(self) -> None:
        older = record_with(*GREEN, required=True)
        older.pop("not_counted", None)
        self.assertEqual(0, cast("Any", ci_read.validate(older))["not_counted"])

    def test_a_count_with_no_required_set_is_refused(self) -> None:
        self.assertIsNone(ci_read.validate({**record_with(*GREEN), "not_counted": 3}))
        for bad in (-1, True, "2", 1_001):
            with self.subTest(bad=bad):
                self.assertIsNone(
                    ci_read.validate({**record_with(*GREEN, required=True), "not_counted": bad})
                )


class NoGhIsLaunchedForASessionWithNoFolder(_PressCase):
    def press(self, harness: str, transcript: str) -> dict[str, Any] | None:
        row = {"harness": harness, "sid": "s1", "session_goal": {"text": GOAL_TEXT, "at": 1.0}}
        entry = {"revisions": [{"n": 1, "goal": GOAL_TEXT}]}
        return http_api._read_ci(
            cast("Any", self.application),
            row,
            cast("Any", entry),
            transcript,
            [],
            cast("Any", self.hooks),
        )

    def test_a_harness_that_records_no_folder_gets_a_reason_and_no_process(self) -> None:
        for harness, transcript in (("gemini", "t.json"), ("claude", "")):
            with (
                self.subTest(harness=harness),
                self.boom(),
                mock.patch.object(supervise, "run", side_effect=AssertionError("run")),
                mock.patch.dict(os.environ, self.stub.environ, clear=True),
            ):
                record = self.press(harness, transcript)
            assert record is not None
            self.assertEqual(ci_read.ERROR_NO_FOLDER, record["error"])
            self.assertEqual(12, record["number"])
            self.assertIsNotNone(ci_read.validate(record))
            self.assertEqual([], self.stub.calls)
            self.assertEqual([], ci_read.facts(record, harness, "s1"))

    def test_no_binding_and_no_folder_says_nothing(self) -> None:
        row = {"harness": "gemini", "sid": "s1", "session_goal": {"text": "tidy", "at": 1.0}}
        entry = {"revisions": [{"n": 1, "goal": "tidy"}]}
        with self.boom():
            record = http_api._read_ci(
                cast("Any", self.application),
                row,
                cast("Any", entry),
                "t.json",
                [],
                cast("Any", self.hooks),
            )
        self.assertIsNone(record)


class AnSshRemoteBindsAsGithub(unittest.TestCase):
    LINKS: tuple[tuple[str, int], ...] = ((REPO, 7),)

    def bind(self, host: str, links: Any = LINKS, pushes: Any = ()) -> Any:
        return ci_read.bind([""], links, pushes, (host, REPO))

    def test_the_ssh_over_443_host_is_github(self) -> None:
        self.assertEqual(
            ci_read.Binding(REPO, 7, ci_read.SOURCE_RECORD), self.bind("ssh.github.com")
        )
        self.assertEqual(
            ("ssh.github.com", REPO),
            git_status.parse_remote(f"ssh://git@ssh.github.com:443/{REPO}.git"),
        )

    def test_an_alias_binds_when_a_link_names_the_same_repository(self) -> None:
        self.assertEqual(
            ci_read.Binding(REPO, 7, ci_read.SOURCE_RECORD), self.bind("github.com-work")
        )
        self.assertEqual(
            ("github.com-work", REPO), git_status.parse_remote(f"git@github.com-work:{REPO}.git")
        )

    def test_an_alias_binds_nothing_when_no_record_names_its_repository(self) -> None:
        self.assertIsNone(self.bind("github.com-work", links=[("other-org/other", 7)]))
        self.assertIsNone(self.bind("github.com-work", links=[]))

    def test_an_alias_never_binds_a_push_alone(self) -> None:
        self.assertIsNone(self.bind("github.com-work", links=[], pushes=["fix/widget-guard"]))

    def test_a_host_that_only_looks_like_the_alias_binds_nothing(self) -> None:
        for host in (
            "github.com.evil.example",
            "github.com-a.evil.com",
            "notgithub.com-work",
            "github.com-",
            "gitlab.com",
        ):
            with self.subTest(host=host):
                self.assertIsNone(self.bind(host))

    def test_the_goal_url_names_the_repository_for_a_recorded_poll(self) -> None:
        poll = ci_read.parse_poll("pr_checks", ["gh", "pr", "checks", "3"], (), ("export",))
        goal = [f"https://github.com/{REPO}/pull/3"]
        remote = ("github.com-work", REPO)
        self.assertTrue(ci_read.poll_bound(poll, remote, goal, [], []))
        self.assertTrue(ci_read.poll_bound(poll, ("ssh.github.com", REPO), goal, [], []))
        self.assertFalse(ci_read.poll_bound(poll, remote, [], [], []))
        self.assertFalse(ci_read.poll_bound(poll, remote, ["no url"], [("other-org/o", 3)], []))


class AReasonThatNamesOnlyCiJobsReachesTheCiFacts(base.AClaudeCodeReadingProducer):
    def checked(self, reason: str, record: dict[str, Any] | None) -> dict[str, Any]:
        assessment, why, _ = reading.produce(
            self.config,  # type: ignore[arg-type]
            ci_goal_row("Make CI green", reason),
            [{"n": 1, "at": 50.0, "goal": "Make CI green", "lines": []}],
            [base.WORDS_FACT],
            now=200.0,
            stamp_text="read at 10:00",
            model=self._model(json.dumps({"goal": {"result": "consistent", "cites": [1]}})),
            read_lines=True,
            read_agent_words=True,
            ci=record,
        )
        self.assertEqual("", why)
        return cast("dict[str, Any]", cast("Any", assessment)["goal_verdict"])

    def test_a_named_job_that_passed_on_the_bound_pull_request_agrees(self) -> None:
        verdict = self.checked("The unit-tests job passed.", record_with(*GREEN))
        self.assertEqual(reading.GOAL_VERDICT_AGREES, verdict["check"])
        self.assertEqual(reading.GOAL_VERDICT_CI, verdict["why"])
        # Only the job it named is cited, not its siblings.
        self.assertEqual(["ci:12:1"], list(verdict["cites"]))

    def test_a_named_job_that_failed_disputes_it(self) -> None:
        record = record_with(check("lint", "pass"), check("e2e-suite", "fail"))
        verdict = self.checked("Both lint and the e2e-suite job are green.", record)
        self.assertEqual(reading.GOAL_VERDICT_DISPUTED, verdict["check"])

    def test_the_press_read_none_so_nothing_reaches_the_facts(self) -> None:
        verdict = self.checked("The unit-tests job passed.", None)
        self.assertEqual(reading.GOAL_VERDICT_UNCONFIRMED, verdict["check"])
        self.assertEqual(reading.GOAL_VERDICT_NOTHING_CHECKABLE, verdict["why"])

    def test_a_job_the_press_did_not_list_agrees_with_nothing(self) -> None:
        verdict = self.checked("The deploy-staging job passed.", record_with(*GREEN))
        self.assertEqual(reading.GOAL_VERDICT_UNCONFIRMED, verdict["check"])

    def test_a_head_that_moved_settles_nothing(self) -> None:
        verdict = self.checked(
            "The unit-tests job passed.", record_with(*GREEN, head_matches=False)
        )
        self.assertEqual(reading.GOAL_VERDICT_UNCONFIRMED, verdict["check"])

    def test_a_one_word_job_name_must_be_quoted_to_be_named(self) -> None:
        record = record_with(check("lint", "pass"), check("unit-tests", "pass"))
        plain = self.checked("The lint run is clean and nothing else changed.", record)
        self.assertNotEqual(reading.GOAL_VERDICT_CI, plain["why"])
        quoted = self.checked("The `lint` job passed.", record)
        self.assertEqual(reading.GOAL_VERDICT_CI, quoted["why"])

    def test_a_mention_that_claims_no_result_agrees_with_nothing(self) -> None:
        for reason in (
            "Wired the unit-tests job into the release script.",
            "The unit-tests job is not passing yet, I will fix it later.",
            "The unit-tests job will fail until the migration lands.",
            "Skipped the unit-tests job.",
        ):
            with self.subTest(reason=reason):
                verdict = self.checked(reason, record_with(*GREEN))
                self.assertEqual(reading.GOAL_VERDICT_UNCONFIRMED, verdict["check"])
                self.assertNotEqual(reading.GOAL_VERDICT_CI, verdict["why"])

    def test_a_job_that_passes_in_its_own_clause_still_agrees(self) -> None:
        verdict = self.checked(
            "The server-unittest job passes.", record_with(check("server-unittest", "pass"))
        )
        self.assertEqual(reading.GOAL_VERDICT_AGREES, verdict["check"])


if __name__ == "__main__":
    unittest.main()
