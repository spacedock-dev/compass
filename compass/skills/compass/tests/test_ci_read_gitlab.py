"""A merge request's pipeline, read from GitLab when a reader presses Analyze.

The contract is DEC-30 (docs/design-reading-a-session.md). Every launch goes through a stub `glab`:
a real executable on a temporary PATH, so the argv, the working directory and the environment the
child saw are measured, never assumed. The stub is built from GitLab's documented REST shapes and
no real GitLab server answered it: see docs/captures/claude/gitlab-merge-request-read-unmeasured.md.
"""

from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import time
import types
import unittest
from typing import TYPE_CHECKING, Any, cast
from unittest import mock

from compass_runtime import ci_read, http_api, reading, supervise

from . import test_reading as base
from .test_ci_read import SESSION_HEAD, ci_goal_row

if TYPE_CHECKING:
    from collections.abc import Sequence

HOST = "gitlab.example.com"
PROJECT = "acme/widgets"
REPOSITORY = f"{HOST}/{PROJECT}"
MR_URL = f"https://{HOST}/{PROJECT}/-/merge_requests/12"
GOAL_TEXT = f"Make the pipeline pass on {MR_URL}"
OTHER_HEAD = "b" * 40
CONFIG = f"""\
git_protocol: ssh
hosts:
    {HOST}:
        token: !!null FakePass99
        api_host: {HOST}
        git_protocol: https
    gitlab.com:
        api_host: gitlab.com
    10.0.0.5:
        token: FakePass99
    internal.example.com:8443:
        token: FakePass99
editor: vim
"""


def job(
    name: str, status: str, *, allow_failure: bool = False, done: str = "2026-10-27T10:00:00.123Z"
) -> dict[str, Any]:
    """One row as GitLab's `GET /projects/:id/pipelines/:id/jobs` lists it."""
    return {
        "id": 1,
        "name": name,
        "status": status,
        "allow_failure": allow_failure,
        "finished_at": done if status in {"success", "failed", "canceled"} else None,
        "web_url": f"https://{HOST}/{PROJECT}/-/jobs/1",
        "stage": "test",
    }


GREEN = [job("lint", "success"), job("unit-tests", "success"), job("docs", "skipped")]


def merge_request(
    head: str = SESSION_HEAD,
    *,
    iid: int = 12,
    pipeline: int | None = 77,
    status: str = "success",
    pipeline_sha: str | None = None,
) -> dict[str, Any]:
    return {
        "iid": iid,
        "sha": head,
        "state": "opened",
        "head_pipeline": None
        if pipeline is None
        else {"id": pipeline, "status": status, "sha": pipeline_sha or head},
    }


class StubGlab:
    """A `glab` on a temporary PATH that answers from a scenario file and logs what it saw."""

    SCRIPT = """#!{python}
import json, os, sys
folder = os.environ["CI_STUB_DIR"]
args = sys.argv[1:]
seen = {{"args": args, "cwd": os.getcwd(), "env": dict(os.environ)}}
with open(os.path.join(folder, "calls.jsonl"), "a") as log:
    log.write(json.dumps(seen) + "\\n")
scenario = json.load(open(os.path.join(folder, "scenario.json")))
endpoint = args[1]
if endpoint.endswith("/merge_requests/12"):
    seen_mr = sum(
        1 for line in open(os.path.join(folder, "calls.jsonl"))
        if '/merge_requests/12"' in line
    )
    answer = scenario["mr_second"] if seen_mr > 1 and "mr_second" in scenario else scenario["mr"]
else:
    page = endpoint.rsplit("page=", 1)[-1]
    answer = scenario.get("jobs_" + page, scenario["jobs"])
sys.stdout.write(answer.get("stdout", ""))
sys.stderr.write(answer.get("stderr", ""))
sys.exit(answer.get("rc", 0))
"""

    def __init__(self, test: unittest.TestCase) -> None:
        self.folder = pathlib.Path(tempfile.mkdtemp())
        test.addCleanup(shutil.rmtree, self.folder, True)
        self.bin = self.folder / "bin"
        self.bin.mkdir()
        glab = self.bin / "glab"
        glab.write_text(self.SCRIPT.format(python=sys.executable))
        glab.chmod(0o755)
        self.home = self.folder / "home"
        self.configure(CONFIG)
        self.set()

    def configure(self, text: str | None) -> None:
        directory = self.home / ".config" / "glab-cli"
        shutil.rmtree(self.home, ignore_errors=True)
        if text is not None:
            directory.mkdir(parents=True)
            (directory / "config.yml").write_text(text)
        else:
            self.home.mkdir()

    def set(
        self,
        *,
        mr: dict[str, Any] | None = None,
        jobs: Sequence[dict[str, Any]] | None = None,
        mr_raw: dict[str, Any] | None = None,
        jobs_raw: dict[str, Any] | None = None,
        mr_second: dict[str, Any] | None = None,
        pages: dict[int, Sequence[dict[str, Any]]] | None = None,
    ) -> None:
        scenario: dict[str, Any] = {
            "mr": mr_raw or {"stdout": json.dumps(merge_request() if mr is None else mr)},
            "jobs": jobs_raw or {"stdout": json.dumps(list(GREEN if jobs is None else jobs))},
        }
        if mr_second is not None:
            scenario["mr_second"] = {"stdout": json.dumps(mr_second)}
        for number, rows in (pages or {}).items():
            scenario[f"jobs_{number}"] = {"stdout": json.dumps(list(rows))}
        (self.folder / "scenario.json").write_text(json.dumps(scenario))

    @property
    def environ(self) -> dict[str, str]:
        return {"PATH": str(self.bin), "CI_STUB_DIR": str(self.folder), "HOME": str(self.home)}

    @property
    def calls(self) -> list[dict[str, Any]]:
        path = self.folder / "calls.jsonl"
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text().splitlines()]


def binding(number: int = 12, repository: str = REPOSITORY) -> Any:
    return ci_read.Binding(repository, number, ci_read.SOURCE_GOAL)


def read(stub: StubGlab, **over: Any) -> dict[str, Any]:
    options: dict[str, Any] = {
        "session_head": SESSION_HEAD,
        "caution": False,
        "now": 1_000.0,
        "environ": stub.environ,
    }
    options.update(over)
    chosen = options.pop("binding", None) or binding()
    return ci_read.read(chosen, **options)


class TheBindingNamesOneMergeRequest(unittest.TestCase):
    def test_a_goal_url_binds_with_its_host_lowered(self) -> None:
        found = ci_read.bind(
            [f"fix https://GitLab.Example.com/{PROJECT}/-/merge_requests/12"], [], [], ("", "")
        )
        self.assertEqual(ci_read.Binding(REPOSITORY, 12, ci_read.SOURCE_GOAL), found)

    def test_nested_groups_bind(self) -> None:
        url = f"https://{HOST}/acme/platform/widgets/-/merge_requests/3"
        found = ci_read.bind([url], [], [], ("", ""))
        self.assertEqual(f"{HOST}/acme/platform/widgets", found.repository if found else "")
        self.assertEqual(HOST, ci_read.host_of(found.repository if found else ""))

    def test_two_requests_bind_none_even_across_providers(self) -> None:
        two = f"{MR_URL} and https://{HOST}/{PROJECT}/-/merge_requests/13"
        self.assertIsNone(ci_read.bind([two], [], [], ("", "")))
        mixed = f"{MR_URL} and https://github.com/acme/widgets/pull/4"
        self.assertIsNone(
            ci_read.bind([mixed], [("acme/widgets", 4)], [], ("github.com", "acme/widgets"))
        )

    def test_no_record_binds_a_merge_request(self) -> None:
        # What Claude Code writes for a merge request is not measured, so a `pr-link` row and a
        # push naming a GitLab remote bind nothing.
        remote = (HOST, PROJECT)
        self.assertIsNone(ci_read.bind([""], [(PROJECT, 5)], ["fix/widget-guard"], remote))

    def test_urls_a_launch_must_not_be_built_from(self) -> None:
        for url in (
            f"http://{HOST}/{PROJECT}/-/merge_requests/1",
            f"https://{HOST}:8443/{PROJECT}/-/merge_requests/1",
            f"https://10.0.0.5/{PROJECT}/-/merge_requests/1",
            f"https://localhost/{PROJECT}/-/merge_requests/1",
            f"https://{HOST}/{PROJECT}/-/merge_requests/0",
            f"https://{HOST}/{PROJECT}/-/merge_requests/123456789",
            f"https://{HOST}/{PROJECT}/merge_requests/1",
            f"https://{HOST}/acme/../-/merge_requests/1",
            f"https://{HOST}/-/-/merge_requests/1",
            f"https://{HOST}/widgets/-/merge_requests/1",
            f"https://{HOST}/ac me/widgets/-/merge_requests/1",
            f"https://github.com/{PROJECT}/-/merge_requests/1",
        ):
            with self.subTest(url=url):
                self.assertEqual((), ci_read.pull_request_urls(url))

    def test_a_repository_is_one_provider_or_the_other(self) -> None:
        self.assertTrue(ci_read.valid_repository("acme/widgets"))
        self.assertTrue(ci_read.valid_repository(REPOSITORY))
        self.assertEqual("github.com", ci_read.host_of("acme/widgets"))
        self.assertEqual(HOST, ci_read.host_of(REPOSITORY))
        for bad in ("", HOST, f"{HOST}/widgets", f"10.0.0.5/{PROJECT}", f"{HOST}/a/../b"):
            with self.subTest(bad=bad):
                self.assertFalse(ci_read.valid_repository(bad))


class GlabsOwnConfigurationNamesTheHosts(unittest.TestCase):
    def setUp(self) -> None:
        self.stub = StubGlab(self)

    def test_only_the_keys_under_hosts_are_read(self) -> None:
        hosts = ci_read.glab_hosts(self.stub.environ)
        self.assertEqual(frozenset({HOST, "gitlab.com"}), hosts)

    def test_no_file_no_hosts(self) -> None:
        self.stub.configure(None)
        self.assertEqual(frozenset(), ci_read.glab_hosts(self.stub.environ))
        self.assertEqual(frozenset(), ci_read.glab_hosts({}))

    def test_a_relative_config_home_is_never_read(self) -> None:
        self.assertEqual(frozenset(), ci_read.glab_hosts({"XDG_CONFIG_HOME": "relative"}))

    def test_the_xdg_home_wins_over_home(self) -> None:
        other = self.stub.folder / "xdg"
        (other / "glab-cli").mkdir(parents=True)
        (other / "glab-cli" / "config.yml").write_text("hosts:\n  other.example.org:\n    x: 1\n")
        environ = {**self.stub.environ, "XDG_CONFIG_HOME": str(other)}
        self.assertEqual(frozenset({"other.example.org"}), ci_read.glab_hosts(environ))


class AHostWhoseConfigurationRedirectsTheCallIsNotRead(unittest.TestCase):
    """glab resolves `--hostname` through these keys, so the read must not trust a redirected one."""

    def setUp(self) -> None:
        self.stub = StubGlab(self)

    def host_block(self, *lines: str) -> None:
        body = "".join(f"        {line}\n" for line in lines)
        self.stub.configure(f"hosts:\n    {HOST}:\n        token: FakePass99\n{body}")

    def refused(self) -> None:
        self.assertNotIn(HOST, ci_read.glab_hosts(self.stub.environ))
        self.assertEqual(ci_read.ERROR_HOST, read(self.stub)["error"])
        self.assertEqual([], self.stub.calls)

    def test_a_plain_http_protocol_is_refused(self) -> None:
        self.host_block("api_protocol: http")
        self.refused()

    def test_another_api_host_is_refused(self) -> None:
        self.host_block("api_host: 10.0.0.9")
        self.refused()

    def test_skipped_tls_verification_is_refused(self) -> None:
        self.host_block("skip_tls_verify: true")
        self.refused()

    def test_an_https_protocol_and_the_same_api_host_still_read(self) -> None:
        self.host_block("api_protocol: 'HTTPS'", f"api_host: {HOST}", "skip_tls_verify: false")
        self.assertIn(HOST, ci_read.glab_hosts(self.stub.environ))
        self.assertEqual("", read(self.stub)["error"])


class TheLaunchKeepsEverySafeguard(unittest.TestCase):
    def setUp(self) -> None:
        self.stub = StubGlab(self)

    def test_a_green_pipeline_on_the_sessions_commit(self) -> None:
        record = read(self.stub)
        self.assertEqual("", record["error"])
        self.assertTrue(record["head_matches"])
        self.assertEqual(
            {"pass": 2, "fail": 0, "pending": 0, "skipping": 1, "cancel": 0}, record["counts"]
        )
        self.assertEqual(REPOSITORY, record["repository"])
        self.assertIsNotNone(ci_read.validate(record))
        self.assertTrue(ci_read.green(record))

    def test_the_argv_is_a_fixed_get_of_the_merge_request_and_its_jobs(self) -> None:
        read(self.stub)
        first, jobs, last = (call["args"] for call in self.stub.calls)
        mr = "projects/acme%2Fwidgets/merge_requests/12"
        self.assertEqual(["api", mr, "--hostname", HOST, "--method", "GET"], first)
        self.assertEqual(
            [
                "api",
                "projects/acme%2Fwidgets/pipelines/77/jobs?per_page=100&page=1",
                "--hostname",
                HOST,
                "--method",
                "GET",
            ],
            jobs,
        )
        self.assertEqual(first, last)

    def test_a_nested_project_path_is_one_encoded_segment(self) -> None:
        repository = f"{HOST}/acme/platform/widgets"
        read(self.stub, binding=binding(repository=repository))
        self.assertEqual(
            "projects/acme%2Fplatform%2Fwidgets/merge_requests/12", self.stub.calls[0]["args"][1]
        )

    def test_the_child_has_no_token_no_host_override_and_no_prompt(self) -> None:
        hostile = {
            **self.stub.environ,
            "GITLAB_TOKEN": "FakePass99",
            "GITLAB_HOST": "evil.example",
            "GL_HOST": "evil.example",
            "GLAB_CONFIG_DIR": "/tmp/evil",
            "OAUTH_TOKEN": "FakePass99",
            "GH_TOKEN": "FakePass99",
            "KEEP_ME": "yes",
        }
        read(self.stub, environ=hostile)
        for call in self.stub.calls:
            env = call["env"]
            for name in (
                "GITLAB_TOKEN",
                "GITLAB_HOST",
                "GL_HOST",
                "GLAB_CONFIG_DIR",
                "OAUTH_TOKEN",
                "GH_TOKEN",
            ):
                self.assertNotIn(name, env)
            self.assertEqual("1", env["NO_PROMPT"])
            self.assertEqual("false", env["GLAB_SEND_TELEMETRY"])
            self.assertEqual("false", env["GLAB_CHECK_UPDATE"])
            self.assertEqual("yes", env["KEEP_ME"])
            self.assertIn("compass-ci-cwd-", call["cwd"])
            self.assertFalse(os.path.exists(call["cwd"]))

    def test_a_host_glab_does_not_name_launches_nothing(self) -> None:
        other = f"other.example.org/{PROJECT}"
        with (
            mock.patch.object(subprocess, "Popen", side_effect=AssertionError("a subprocess")),
            mock.patch.object(subprocess, "run", side_effect=AssertionError("a subprocess")),
            mock.patch.object(supervise, "run", side_effect=AssertionError("a subprocess")),
        ):
            record = read(self.stub, binding=binding(repository=other))
        self.assertEqual(ci_read.ERROR_HOST, record["error"])
        self.assertEqual([], self.stub.calls)
        self.assertIsNotNone(ci_read.validate(record))

    def test_no_configuration_file_launches_nothing(self) -> None:
        self.stub.configure(None)
        record = read(self.stub)
        self.assertEqual(ci_read.ERROR_HOST, record["error"])
        self.assertEqual([], self.stub.calls)

    def test_an_ip_literal_in_the_configuration_is_never_a_host(self) -> None:
        self.stub.configure("hosts:\n    10.0.0.5:\n        x: 1\n")
        record = read(self.stub, binding=binding(repository="10.0.0.5/acme/widgets"))
        self.assertEqual(ci_read.ERROR_FAILED, record["error"])
        self.assertEqual([], self.stub.calls)

    def test_glab_missing(self) -> None:
        record = read(self.stub, environ={**self.stub.environ, "PATH": "/nonexistent-compass-bin"})
        self.assertEqual(ci_read.ERROR_GLAB_MISSING, record["error"])

    def test_a_relative_path_element_never_supplies_the_binary(self) -> None:
        planted = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, planted, True)
        (planted / "glab").write_text("#!/bin/sh\nexit 0\n")
        (planted / "glab").chmod(0o755)
        previous = os.getcwd()
        os.chdir(planted)
        self.addCleanup(os.chdir, previous)
        record = read(self.stub, environ={**self.stub.environ, "PATH": f".{os.pathsep}bin"})
        self.assertEqual(ci_read.ERROR_GLAB_MISSING, record["error"])

    def test_a_second_press_inside_the_floor_reads_nothing_new(self) -> None:
        floor = ci_read.Floor()
        read(self.stub, floor=floor)
        calls = len(self.stub.calls)
        read(self.stub, floor=floor, now=1_010.0)
        self.assertEqual(calls, len(self.stub.calls))

    def test_a_head_that_moved_while_the_pipeline_was_read_matches_nothing(self) -> None:
        self.stub.set(mr_second=merge_request(OTHER_HEAD))
        record = read(self.stub)
        self.assertFalse(record["head_matches"])
        self.assertEqual(OTHER_HEAD, record["head"])

    def test_a_new_pipeline_on_the_same_head_matches_nothing(self) -> None:
        self.stub.set(mr_second=merge_request(pipeline=78))
        self.assertFalse(read(self.stub)["head_matches"])

    def test_a_pipeline_of_another_commit_than_the_request_head_matches_nothing(self) -> None:
        self.stub.set(mr=merge_request(pipeline_sha=OTHER_HEAD))
        record = read(self.stub)
        self.assertFalse(record["head_matches"])
        facts = ci_read.facts(record, "claude", "s1")
        self.assertTrue(facts)
        self.assertEqual({False}, {f["ci_counts"] for f in facts})

    def test_a_pipeline_whose_commit_changed_between_the_looks_matches_nothing(self) -> None:
        self.stub.set(mr_second=merge_request(pipeline_sha=OTHER_HEAD))
        self.assertFalse(read(self.stub)["head_matches"])

    def test_a_pipeline_with_no_valid_commit_is_unreadable(self) -> None:
        bad = merge_request()
        bad["head_pipeline"]["sha"] = "not-a-sha"
        self.stub.set(mr=bad)
        self.assertEqual(ci_read.ERROR_OUTPUT, read(self.stub)["error"])

    def test_a_head_past_the_session_commit_is_named_and_does_not_match(self) -> None:
        self.stub.set(mr=merge_request(OTHER_HEAD))
        record = read(self.stub)
        self.assertFalse(record["head_matches"])
        self.assertEqual(OTHER_HEAD, record["head"])

    def test_an_unknown_session_head_never_matches(self) -> None:
        self.assertFalse(read(self.stub, session_head="")["head_matches"])

    def test_a_merge_request_with_no_pipeline_is_an_empty_read(self) -> None:
        self.stub.set(mr=merge_request(pipeline=None))
        record = read(self.stub)
        self.assertEqual("", record["error"])
        self.assertEqual(0, sum(record["counts"].values()))
        self.assertFalse(ci_read.green(record))
        self.assertEqual(2, len(self.stub.calls))

    def test_the_nothing_the_cli_said_beyond_the_closed_fields_is_kept(self) -> None:
        noisy = job("lint", "success")
        noisy["web_url"] = "https://evil.example/FakePass99"
        noisy["user"] = {"name": "Jane Doe", "email": "jane@example.com"}
        self.stub.set(jobs=[noisy])
        text = json.dumps(read(self.stub))
        for leaked in ("evil.example", "FakePass99", "Jane", "jane@example.com"):
            self.assertNotIn(leaked, text)


class TheStatusTableIsClosed(unittest.TestCase):
    def setUp(self) -> None:
        self.stub = StubGlab(self)

    def bucket(self, status: str, *, allow_failure: bool = False, pipeline: str = "success") -> str:
        self.stub.set(
            mr=merge_request(status=pipeline),
            jobs=[job("only", status, allow_failure=allow_failure)],
        )
        record = read(self.stub, floor=None)
        self.assertEqual("", record["error"], status)
        return str(record["checks"][0]["bucket"]) if record["checks"] else ""

    def test_each_status_has_one_bucket(self) -> None:
        for status, expected in (
            ("success", "pass"),
            ("failed", "fail"),
            ("canceled", "cancel"),
            ("canceling", "cancel"),
            ("skipped", "skipping"),
            ("created", "pending"),
            ("pending", "pending"),
            ("running", "pending"),
            ("preparing", "pending"),
            ("scheduled", "pending"),
            ("waiting_for_resource", "pending"),
            ("manual", "pending"),
        ):
            with self.subTest(status=status):
                pipeline = {
                    "failed": "failed",
                    "canceled": "canceled",
                    "canceling": "canceled",
                    "success": "success",
                    "skipped": "success",
                }.get(status, "running")
                self.assertEqual(expected, self.bucket(status, pipeline=pipeline))

    def test_a_job_allowed_to_fail_counts_as_neither(self) -> None:
        self.assertEqual("skipping", self.bucket("failed", allow_failure=True))

    def test_a_manual_job_nobody_has_to_run_counts_as_neither(self) -> None:
        self.assertEqual("skipping", self.bucket("manual", allow_failure=True))

    def test_a_status_outside_the_table_is_unreadable(self) -> None:
        self.stub.set(jobs=[job("only", "exploded")])
        self.assertEqual(ci_read.ERROR_OUTPUT, read(self.stub)["error"])
        self.stub.set(mr=merge_request(status="exploded"))
        self.assertEqual(ci_read.ERROR_OUTPUT, read(self.stub, now=2_000.0)["error"])

    def test_a_pipeline_that_disagrees_with_its_own_jobs_is_named_as_a_check(self) -> None:
        # A trigger job's child pipeline failed: every job of this pipeline passed, and the
        # pipeline did not.
        self.stub.set(mr=merge_request(status="failed"), jobs=GREEN)
        record = read(self.stub)
        self.assertEqual(1, record["counts"]["fail"])
        self.assertFalse(ci_read.green(record))
        self.assertEqual("pipeline", record["checks"][0]["name"])

    def test_a_running_pipeline_with_every_job_in_is_still_pending(self) -> None:
        self.stub.set(mr=merge_request(status="running"), jobs=GREEN)
        self.assertFalse(ci_read.green(read(self.stub)))

    def test_a_cancelled_pipeline_is_not_green(self) -> None:
        self.stub.set(mr=merge_request(status="canceled"), jobs=GREEN)
        self.assertFalse(ci_read.green(read(self.stub)))


class TheJobsAreAllRead(unittest.TestCase):
    def setUp(self) -> None:
        self.stub = StubGlab(self)

    def test_a_second_page_is_read_when_the_first_is_full(self) -> None:
        full = [job(f"shard-{i}", "success") for i in range(100)]
        self.stub.set(pages={1: full, 2: [job("late", "failed")]})
        record = read(self.stub)
        self.assertEqual(100, record["counts"]["pass"])
        self.assertEqual(1, record["counts"]["fail"])
        self.assertEqual("late", record["checks"][0]["name"])

    def test_ten_full_pages_are_unreadable_and_never_a_pass(self) -> None:
        full = [job(f"shard-{i}", "success") for i in range(100)]
        self.stub.set(pages=dict.fromkeys(range(1, 11), full))
        self.assertEqual(ci_read.ERROR_OUTPUT, read(self.stub)["error"])

    def test_the_listing_is_capped_failures_first_and_every_check_is_counted(self) -> None:
        rows = [job(f"ok-{i}", "success") for i in range(60)] + [job("broken", "failed")]
        self.stub.set(jobs=rows)
        record = read(self.stub)
        self.assertEqual(ci_read.MAX_LISTED, len(record["checks"]))
        self.assertEqual("broken", record["checks"][0]["name"])
        self.assertEqual(60, record["counts"]["pass"])


class TheClosedErrorTokens(unittest.TestCase):
    def setUp(self) -> None:
        self.stub = StubGlab(self)

    def token(self, *, stderr: str = "", stdout: str = "", rc: int = 1) -> str:
        self.stub.set(mr_raw={"stderr": stderr, "stdout": stdout, "rc": rc})
        return str(read(self.stub, now=float(len(self.stub.calls) + 1))["error"])

    def test_a_refusal_is_a_token_and_its_words_are_dropped(self) -> None:
        self.assertEqual(
            ci_read.ERROR_GLAB_SIGNED_OUT,
            self.token(stdout=json.dumps({"message": "401 Unauthorized"})),
        )
        self.assertEqual(
            ci_read.ERROR_NOT_FOUND, self.token(stdout=json.dumps({"message": "404 Not Found"}))
        )
        self.assertEqual(ci_read.ERROR_NOT_FOUND, self.token(stderr="403 Forbidden", stdout=""))
        self.assertEqual(ci_read.ERROR_RATE_LIMITED, self.token(stderr="429 Too Many Requests"))
        self.assertEqual(ci_read.ERROR_GLAB_FAILED, self.token(stderr="boom FakePass99"))

    def test_a_refusal_body_is_never_read_as_a_merge_request(self) -> None:
        body = json.dumps(merge_request())
        self.assertEqual(ci_read.ERROR_GLAB_FAILED, self.token(stdout=body, rc=1))

    def test_output_that_is_not_the_schema_is_unreadable(self) -> None:
        for raw in ("not json", "[]", json.dumps({"sha": "xyz", "iid": 12}), "{}"):
            with self.subTest(raw=raw):
                self.assertEqual(ci_read.ERROR_OUTPUT, self.token(stdout=raw, rc=0))

    def test_another_merge_requests_number_is_unreadable(self) -> None:
        self.stub.set(mr=merge_request(iid=13))
        self.assertEqual(ci_read.ERROR_OUTPUT, read(self.stub)["error"])

    def test_a_pipeline_id_that_is_not_a_number_is_unreadable(self) -> None:
        for bad in ("77; id", True, -1, 0.5):
            with self.subTest(bad=bad):
                broken = merge_request()
                broken["head_pipeline"]["id"] = bad
                self.stub.set(mr=broken)
                self.assertEqual(ci_read.ERROR_OUTPUT, read(self.stub, now=3_000.0)["error"])

    def test_every_token_has_a_place_in_the_closed_set(self) -> None:
        for token in (
            ci_read.ERROR_GLAB_MISSING,
            ci_read.ERROR_GLAB_SIGNED_OUT,
            ci_read.ERROR_GLAB_FAILED,
            ci_read.ERROR_HOST,
        ):
            self.assertIn(token, ci_read.ERRORS)


class AStoredGitlabReadIsValidatedAndBecomesFacts(unittest.TestCase):
    def setUp(self) -> None:
        self.stub = StubGlab(self)

    def test_the_facts_say_where_they_came_from(self) -> None:
        facts = ci_read.facts(read(self.stub), "claude", "s1")
        self.assertTrue(facts)
        for fact in facts:
            self.assertEqual("gitlab", fact["by"])
            self.assertEqual(ci_read.SOURCE_TEXT_GITLAB, fact["evidence"]["source"])
            self.assertEqual(REPOSITORY, fact["ci_repository"])

    def test_a_pass_counts_only_on_the_sessions_commit(self) -> None:
        facts = ci_read.facts(read(self.stub), "claude", "s1")
        # The skipped job settles nothing; both passes do.
        self.assertEqual(
            {"passed": True, "skipped": False},
            {f["result"] if f["result"] == "skipped" else "passed": f["ci_counts"] for f in facts},
        )
        self.stub.set(mr=merge_request(OTHER_HEAD))
        moved = ci_read.facts(read(self.stub, now=5_000.0), "claude", "s1")
        self.assertEqual({False}, {f["ci_counts"] for f in moved})

    def test_a_repository_that_is_neither_provider_refuses_the_record(self) -> None:
        record = read(self.stub)
        self.assertIsNotNone(ci_read.validate(record))
        self.assertIsNone(ci_read.validate({**record, "repository": f"10.0.0.5/{PROJECT}"}))
        self.assertIsNone(ci_read.validate({**record, "repository": HOST}))


class ADoneMergeRequestSettlesTheGoal(base.AClaudeCodeReadingProducer):
    """The acceptance case: a passed pipeline reads `consistent` on a pipeline goal."""

    def setUp(self) -> None:
        super().setUp()
        self.stub = StubGlab(self)

    def produce(self, record: dict[str, Any], row: dict[str, Any] | None = None) -> dict[str, Any]:
        facts = [base.WORDS_FACT, *ci_read.facts(record, "claude", "s1")]
        ledger = reading.build_ledger(facts, "claude", "s1")
        cites = [i + 1 for i, entry in enumerate(ledger) if entry["type"] == ci_read.FACT_TYPE]
        answer = {"line_1": {"result": "consistent", "cites": cites, "detail": ""}}
        assessment, why, _spent = reading.produce(
            self.config,  # type: ignore[arg-type]
            row or {"harness": "claude", "sid": "s1", "state": "working", "ended_at": None},
            [{"n": 1, "at": 50.0, "goal": GOAL_TEXT, "lines": ["The pipeline passes"]}],
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

    def test_a_passed_pipeline_on_the_sessions_commit_reads_consistent(self) -> None:
        record = read(self.stub)
        assessment = self.produce(record)
        row = assessment["criteria"]["line_1"]
        self.assertEqual(reading.RESULT_CONSISTENT, row["result"])
        self.assertTrue(row["cites"])
        self.assertTrue(all(c.startswith("ci:12:") for c in row["cites"]))
        self.assertIn('"unit-tests" passed on the pull request', self.prompts[0])
        self.assertNotIn("FakePass99", self.prompts[0])

    def test_a_pipeline_still_running_cannot_carry_a_consistent(self) -> None:
        self.stub.set(mr=merge_request(status="running"), jobs=[job("lint", "running")])
        row = self.produce(read(self.stub))["criteria"]["line_1"]
        self.assertNotEqual(reading.RESULT_CONSISTENT, row["result"])

    def test_a_pipeline_of_another_commit_cannot_carry_a_consistent(self) -> None:
        self.stub.set(mr=merge_request(OTHER_HEAD))
        row = self.produce(read(self.stub))["criteria"]["line_1"]
        self.assertNotEqual(reading.RESULT_CONSISTENT, row["result"])

    def test_a_pipeline_that_never_ran_the_session_commit_cannot_carry_a_consistent(self) -> None:
        self.stub.set(mr=merge_request(pipeline_sha=OTHER_HEAD))
        row = self.produce(read(self.stub))["criteria"]["line_1"]
        self.assertNotEqual(reading.RESULT_CONSISTENT, row["result"])

    def test_a_long_dotted_token_in_a_verdict_is_matched_in_linear_time(self) -> None:
        started = time.monotonic()
        self.assertEqual((), reading._verdict_prs("a." * 2000))
        self.assertLess(time.monotonic() - started, 0.5)
        found = reading._verdict_prs(
            f"green on {MR_URL} and on gitlab.com/g/s/p/-/merge_requests/3"
        )
        self.assertEqual(((REPOSITORY, 12), ("gitlab.com/g/s/p", 3)), found)

    def test_the_harness_verdict_naming_the_merge_request_agrees(self) -> None:
        for reason in (
            f"the pipeline passed on {MR_URL}",
            "the pipeline passed on MR !12",
            "merge request 12 is green",
        ):
            with self.subTest(reason=reason):
                row = ci_goal_row(GOAL_TEXT, reason)
                verdict = cast("Any", self.produce(read(self.stub), row))["goal_verdict"]
                self.assertEqual(reading.GOAL_VERDICT_AGREES, verdict["check"])
                self.assertEqual(reading.GOAL_VERDICT_CI, verdict["why"])

    def test_a_verdict_naming_another_projects_request_does_not_agree(self) -> None:
        other = f"https://{HOST}/acme/gadgets/-/merge_requests/12"
        row = ci_goal_row(GOAL_TEXT, f"the pipeline passed on {other}")
        verdict = cast("Any", self.produce(read(self.stub), row))["goal_verdict"]
        self.assertNotEqual(reading.GOAL_VERDICT_CI, verdict.get("why"))


class APressOnAnUnconfiguredHostStartsNothing(unittest.TestCase):
    """`_read_ci` is the press's own path: the host check must hold there too."""

    def setUp(self) -> None:
        self.stub = StubGlab(self)
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
        self.hooks = types.SimpleNamespace(cancelled=lambda: False)

    def press(self, goal: str) -> dict[str, Any] | None:
        row = {"harness": "claude", "sid": "s1", "session_goal": {"text": goal, "at": 1.0}}
        entry = {"revisions": [{"n": 1, "goal": goal}]}
        return http_api._read_ci(
            cast("Any", self.application), row, cast("Any", entry), "", [], cast("Any", self.hooks)
        )

    def test_a_goal_url_on_a_host_not_in_glabs_configuration_launches_nothing(self) -> None:
        goal = f"Make the pipeline pass: https://not-configured.example.org/{PROJECT}/-/merge_requests/12"
        with (
            mock.patch.dict(os.environ, self.stub.environ, clear=True),
            mock.patch.object(subprocess, "Popen", side_effect=AssertionError("a subprocess")),
            mock.patch.object(subprocess, "run", side_effect=AssertionError("a subprocess")),
            mock.patch.object(supervise, "run", side_effect=AssertionError("a subprocess")),
        ):
            record = self.press(goal)
        assert record is not None
        self.assertEqual(ci_read.ERROR_HOST, record["error"])
        self.assertEqual([], self.stub.calls)

    def test_a_goal_url_on_a_configured_host_reads_once_through_glab(self) -> None:
        with mock.patch.dict(os.environ, self.stub.environ, clear=True):
            record = self.press(GOAL_TEXT)
        assert record is not None
        self.assertEqual("", record["error"])
        self.assertEqual(3, len(self.stub.calls))
        self.assertEqual(REPOSITORY, record["repository"])


if __name__ == "__main__":
    unittest.main()
