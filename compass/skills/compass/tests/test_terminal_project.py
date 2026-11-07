"""A person reads the same project brief as the board, through passive bounded requests."""

from __future__ import annotations

import contextlib
import importlib
import io
import json
import subprocess
import sys
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from compass_runtime import terminal_client, terminal_project
from compass_runtime.terminal_sessions import _owner

from .support import SERVER_PATH
from .test_terminal_client import FakeDashboard

FIXTURES = Path(__file__).resolve().parents[4] / "frontend/test/fixtures"
# A cold project read exercises the session list's real six-second response time.
REAL_TIME_TESTS = True


def recorded(name: str) -> dict[str, Any]:
    body: dict[str, Any] = json.loads(
        (FIXTURES / "client-contract" / (name + ".json")).read_text()
    )["response"]["body"]
    return body


class ProjectTest(unittest.TestCase):
    def test_a_person_reads_the_board_members_counts_order_and_brief(self) -> None:
        expected = json.loads((FIXTURES / "terminal-project.json").read_text())
        for name in ("data-terminal-project", "sessions-terminal-project"):
            self.assertEqual(
                expected,
                terminal_project.derive(
                    recorded(name), recorded("context-terminal-project"), label="terminal-project"
                ),
            )

    def test_a_person_keeps_same_label_members_when_repository_keys_disagree(self) -> None:
        payload = recorded("data-terminal-project")
        payload["sessions"][0]["project_key"] = "other-key"
        brief = terminal_project.derive(payload, {}, label="terminal-project")
        self.assertEqual(
            "terminal-project", terminal_project.project_key(payload, "terminal-project")
        )
        self.assertEqual(4, len(brief["members"]))
        self.assertIn("shared location is not established", brief["warning"])

    def test_a_person_is_not_told_attention_is_clear_without_complete_evidence(self) -> None:
        for context in (
            None,
            {},
            {
                "semantic": {
                    "projections": {
                        "command_attention_coverage": {
                            "state": "incomplete",
                            "scanned": 0,
                            "total": 4,
                            "omitted": 4,
                        }
                    }
                }
            },
        ):
            brief = terminal_project.derive({"sessions": []}, context, label="p")
            output = "\n".join(terminal_project.render(brief, caller=("claude", "a")))
            self.assertNotIn("You are not needed", output)
            self.assertNotIn("nobody", output)
            self.assertTrue("unavailable" in output or "incomplete" in output)
            self.assertTrue("REFRESH" in output or "COMPLETE" in output)

    def test_a_person_reads_one_bounded_line_per_prose_field_and_every_member(self) -> None:
        payload = recorded("data-terminal-project")
        for row in payload["sessions"]:
            row["title"] = "\x1b]52;c;clipboard\x07\u202e" + "word\n" * 1000
        brief = terminal_project.derive(payload, {}, label="terminal-project")
        output = "\n".join(terminal_project.render(brief, caller=("claude", "a1b2c3d4")))
        self.assertNotIn("clipboard", output)
        self.assertNotIn("\u202e", output)
        self.assertEqual(1, output.count("[this session]"))
        self.assertTrue(all(len(line) < 600 for line in output.splitlines()))
        self.assertEqual(4, len(brief["members"]))

    def test_a_person_reads_redacted_peer_credentials_from_real_publication(self) -> None:
        output = "\n".join(
            terminal_project.render(
                terminal_project.derive(
                    recorded("sessions-terminal-project"),
                    recorded("context-terminal-project"),
                    label="terminal-project",
                ),
                caller=("claude", "a1b2c3d4"),
            )
        )
        self.assertNotIn("sk-abcdefghijklmnopqrstuvwxyz123456", output)
        self.assertIn("REDACTED", output)

    def test_a_person_sees_a_workflow_task_only_when_its_id_label_and_stage_join(self) -> None:
        context: dict[str, Any] = {
            "semantic": {
                "work_items": [{"work_item_id": "item", "label": "parser_work"}],
                "projections": {
                    "trail_heads": [
                        {"status": "current stage", "work_item_id": "item", "stage": "code_review"}
                    ]
                },
            }
        }
        brief = terminal_project.derive({"sessions": []}, context, label="p")
        self.assertEqual(
            ("Parser work", "Code review", "Exact workflow state"),
            (brief["task"], brief["task_stage"], brief["task_source"]),
        )
        context["semantic"]["work_items"][0]["work_item_id"] = "unrelated"
        self.assertEqual(
            "Not observed", terminal_project.derive({"sessions": []}, context, label="p")["task"]
        )

    def test_a_person_does_not_read_copied_or_status_requests_as_the_current_task(self) -> None:
        payload = recorded("data-terminal-project")
        context = recorded("context-terminal-project")
        fact = context["semantic"]["facts"][0]
        for changes in (
            {"copied": True},
            {"intent_promoted": False},
            {"summary": "Thanks!"},
            {"summary": "Please report the current status"},
            {"evidence": {"confidence": "inferred"}},
        ):
            changed = {
                **context,
                "semantic": {**context["semantic"], "facts": [{**fact, **changes}]},
            }
            self.assertEqual(
                "Not observed",
                terminal_project.derive(payload, changed, label="terminal-project")["task"],
            )

    def test_a_person_reads_instruction_time_rather_than_session_activity(self) -> None:
        payload = recorded("data-terminal-project")
        rows = payload["sessions"]
        for row in rows:
            row["instruction"] = None
        rows[0]["instruction"] = {
            "label": "asked",
            "text": "Older activity, later instruction",
            "at": 200,
        }
        rows[1]["instruction"] = {
            "label": "asked",
            "text": "Newer activity, older instruction",
            "at": 100,
        }
        rows[1]["last_activity"] = 9999999999
        brief = terminal_project.derive(payload, {}, label="terminal-project")
        self.assertEqual("Older activity, later instruction", brief["instruction"])
        self.assertEqual("Latest instruction", brief["instruction_heading"])
        rows[1]["instruction"]["at"] = None
        self.assertEqual(
            "Published instruction",
            terminal_project.derive(payload, {}, label="terminal-project")["instruction_heading"],
        )

    def test_a_person_sees_an_exact_ask_without_inventing_a_native_wait(self) -> None:
        payload = recorded("data-terminal-project")
        payload["ask"] = True
        payload["asks"] = [
            {
                "id": "ask-one",
                "harness": "codex",
                "session_id": payload["sessions"][-1]["sid"],
                "project": "terminal-project",
                "question": "Which parser format?",
            }
        ]
        brief = terminal_project.derive(payload, {}, label="terminal-project")
        self.assertIn("1 waiting on you", brief["counts"])
        self.assertEqual("Which parser format?", brief["attention"][0]["label"])
        self.assertEqual("CAPTAIN", brief["attention"][0]["owner"])

    def test_a_person_reading_a_large_project_pays_for_each_ask_owner_lookup_once(self) -> None:
        payload = recorded("data-terminal-project")
        peer = next(row for row in payload["sessions"] if row["harness"] == "codex")
        payload["sessions"].extend({**peer, "sid": f"other-{i}"} for i in range(1000))
        payload["ask"] = True
        payload["asks"] = [
            {
                "id": "ask",
                "harness": "codex",
                "session_id": peer["sid"],
                "project": "terminal-project",
                "question": "Which parser format?",
            }
        ]
        with mock.patch.object(terminal_project, "ask_owner", wraps=_owner) as owner:
            brief = terminal_project.derive(payload, {}, label="terminal-project")
        self.assertEqual("Which parser format?", brief["attention"][0]["label"])
        self.assertEqual(1, owner.call_count)

    def test_a_person_sees_the_latest_return_owner_even_after_that_session_ended(self) -> None:
        brief = terminal_project.derive(
            recorded("sessions-terminal-project"), {}, label="terminal-project"
        )
        self.assertEqual(["claude:a1b2c3d4", "claude:deadbeef"], brief["running"])
        self.assertEqual(
            ["active", "returned"], [child["lifecycle"] for child in brief["children"]]
        )
        self.assertTrue(brief["children"][-1]["stale"])

    def test_a_persons_peer_words_are_redacted_by_publication_before_the_terminal_prints(
        self,
    ) -> None:
        sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "scripts"))
        try:
            recorder = importlib.import_module("regen_client_fixtures")
        finally:
            sys.path.pop(0)

        captures = recorder.Recorder()
        scratch = recorder.Scratch()
        try:
            with recorder.guarded():
                recorder.terminal_project_scenario(captures, scratch)
        finally:
            scratch.close()
        payload = captures.scenarios["sessions-terminal-project"]["response"]["body"]
        context = captures.scenarios["context-terminal-project"]["response"]["body"]
        text = "\n".join(
            terminal_project.render(
                terminal_project.derive(payload, context, label="terminal-project"),
                caller=("claude", "a1b2c3d4"),
            )
        )
        self.assertNotIn("sk-abcdefghijklmnopqrstuvwxyz123456", text)
        self.assertIn("REDACTED", text)


class ProjectCommandTest(unittest.TestCase):
    def run_project(self, fake: FakeDashboard, **kwargs: Any) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = terminal_client.run_project(
                port=fake.port,
                environ={},
                session="claude:a1b2c3d4-1111-2222-3333-444455556666",
                **kwargs,
            )
        return code, out.getvalue(), err.getvalue()

    def answers(self) -> dict[str, tuple[int, dict[str, str], bytes]]:
        payload = recorded("sessions-terminal-project")
        caller = next(row for row in payload["sessions"] if row["sid"] == "a1b2c3d4")
        bodies = {
            "/api/session?harness=claude&sid=a1b2c3d4-1111-2222-3333-444455556666": {
                "session": caller
            },
            "/api/sessions": payload,
            "/api/project-context?project=key-terminal-project": recorded(
                "context-terminal-project"
            ),
        }
        return {
            path: (200, {"Content-Type": "application/json"}, json.dumps(body).encode())
            for path, body in bodies.items()
        }

    def test_a_person_reads_only_passive_gets_and_preserves_the_full_caller_id(self) -> None:
        with FakeDashboard(answers=self.answers()) as fake:
            code, out, err = self.run_project(fake)
        self.assertEqual((0, ""), (code, err))
        self.assertEqual(1, out.count("[this session]"))
        self.assertEqual(
            [
                "/api/health",
                "/api/session?harness=claude&sid=a1b2c3d4-1111-2222-3333-444455556666",
                "/api/sessions",
                "/api/project-context?project=key-terminal-project",
            ],
            [path for _, path in fake.requests],
        )
        for method, path in fake.requests:
            self.assertEqual("GET", method)
            for forbidden in ("refresh", "observer_model", "/api/data"):
                self.assertNotIn(forbidden, path)

    def test_a_person_reads_their_project_when_the_cold_session_list_takes_six_seconds(
        self,
    ) -> None:
        with FakeDashboard(answers=self.answers(), delays={"/api/sessions": 6}) as fake:
            code, out, err = self.run_project(fake)

        self.assertEqual((0, ""), (code, err))
        self.assertEqual(1, out.count("[this session]"))
        self.assertNotIn("could not be read", out)

    def test_a_person_with_an_older_dashboard_reads_the_same_project_brief(self) -> None:
        answers = self.answers()
        answers["/api/data"] = (200, {}, json.dumps(recorded("data-terminal-project")).encode())
        with FakeDashboard(version="0.0.1", answers=answers) as fake:
            expected = self.run_project(fake)
            self.assertEqual((0, ""), (expected[0], expected[2]))
            fake.requests.clear()
            answers["/api/sessions"] = (404, {}, b"{}")

            actual = self.run_project(fake)

        self.assertEqual(expected, actual)
        self.assertEqual(1, actual[1].count("[this session]"))
        self.assertIn(("GET", "/api/data"), fake.requests)
        self.assertTrue(all(method == "GET" for method, _path in fake.requests))

    def test_a_person_gets_the_full_list_allowance_when_reading_their_project(self) -> None:
        with (
            mock.patch.object(terminal_client, "REQUEST_TIMEOUT_SEC", 0.1),
            mock.patch.object(terminal_client, "LIST_REQUEST_TIMEOUT_SEC", 0.5),
            FakeDashboard(answers=self.answers(), delays={"/api/sessions": 0.4}) as fake,
        ):
            code, out, err = self.run_project(fake)

        self.assertEqual((0, ""), (code, err))
        self.assertEqual(1, out.count("[this session]"))

    def test_a_person_gets_no_project_brief_from_a_fallback_after_another_read_failure(
        self,
    ) -> None:
        replies: list[tuple[int, dict[str, str], bytes]] = [
            (500, {}, b"{}"),
            (200, {}, b"{"),
        ]
        for reply in replies:
            answers = self.answers()
            answers["/api/sessions"] = reply
            answers["/api/data"] = (
                200,
                {},
                json.dumps(recorded("data-terminal-project")).encode(),
            )
            with self.subTest(reply=reply), FakeDashboard(answers=answers) as fake:
                self.assertEqual(
                    (1, "", "Compass answered, but its session list could not be read.\n"),
                    self.run_project(fake),
                )
                self.assertNotIn(("GET", "/api/data"), fake.requests)

    def test_a_person_without_a_project_label_reads_no_peers(self) -> None:
        answers = self.answers()
        path = next(path for path in answers if path.startswith("/api/session?"))
        answers[path] = (200, {}, b'{"session":{"harness":"claude","sid":"a1b2c3d4","project":""}}')
        with FakeDashboard(answers=answers) as fake:
            code, out, err = self.run_project(fake)
        self.assertEqual((0, ""), (code, err))
        self.assertIn("no project label", out)
        self.assertEqual(2, len(fake.requests))

    def test_a_person_gets_no_partial_brief_when_membership_changes_or_a_read_fails(self) -> None:
        for path in ("/api/sessions", "/api/project-context?project=key-terminal-project"):
            answers = self.answers()
            answers[path] = (200, {}, b'{"sessions":[]}')
            with FakeDashboard(answers=answers) as fake:
                code, out, err = self.run_project(fake)
            self.assertEqual((1, ""), (code, out))
            self.assertTrue(err)

    def test_a_person_with_no_dashboard_starts_nothing(self) -> None:
        out, err = io.StringIO(), io.StringIO()
        with (
            mock.patch.object(terminal_client, "find_dashboard", return_value=None),
            mock.patch.object(subprocess, "Popen") as launch,
            contextlib.redirect_stdout(out),
            contextlib.redirect_stderr(err),
        ):
            code = terminal_client.run_project(session="claude:abc", environ={})
        self.assertEqual(1, code)
        self.assertEqual("", out.getvalue())
        self.assertIn("not running", err.getvalue())
        launch.assert_not_called()

    def test_a_person_gets_no_partial_output_from_a_refused_ambiguous_or_oversize_reply(
        self,
    ) -> None:
        for route in self.answers():
            for status, body in (
                (409, b"{}"),
                (200, b"{"),
                (200, b'{"padding":"' + b"x" * 3000 + b'"}'),
            ):
                answers = self.answers()
                answers[route] = (status, {}, body)
                with (
                    mock.patch.object(terminal_client, "DATA_CAP_BYTES", 2000),
                    mock.patch.object(terminal_client, "REPLY_CAP_BYTES", 2000),
                    FakeDashboard(answers=answers) as fake,
                ):
                    code, out, err = self.run_project(fake)
                self.assertEqual((1, ""), (code, out))
                self.assertTrue(err)

    def test_a_person_reads_from_the_environment_without_reading_standard_input(self) -> None:
        answers = self.answers()
        out = io.StringIO()
        with (
            FakeDashboard(answers=answers) as fake,
            mock.patch.object(sys, "stdin") as stdin,
            contextlib.redirect_stdout(out),
        ):
            code = terminal_client.run_project(
                port=fake.port,
                environ={"CLAUDE_CODE_SESSION_ID": "a1b2c3d4-1111-2222-3333-444455556666"},
            )
        self.assertEqual(0, code)
        stdin.read.assert_not_called()

    def test_a_person_reads_the_project_without_importing_collectors(self) -> None:

        for argv in (["--project"], ["--project", "--session", "claude:abc"]):
            # Valid caller dispatch must never probe the desk's default dashboard.
            script = (
                "import runpy,sys;"
                f"sys.path.insert(0,{str(SERVER_PATH.parent)!r});"
                "from compass_runtime import terminal_client;"
                "terminal_client.ensure_dashboard=lambda *a,**k:terminal_client.Refusal('isolated');"
                f"sys.argv={[str(SERVER_PATH), *argv]!r};"
                f"runpy.run_path({str(SERVER_PATH)!r},run_name='__main__')"
            )
            done = subprocess.run(
                [sys.executable, "-X", "importtime", "-c", script],
                env={"PATH": str(Path(sys.executable).parent), "CODEX_THREAD_ID": "other"},
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            self.assertEqual(1, done.returncode)
            for module in (
                "compass_runtime.cli",
                "compass_runtime.http_api",
                "compass_runtime.aggregate",
            ):
                self.assertNotIn(" " + module + "\n", done.stderr)

    def test_a_person_uses_the_light_dispatch_with_an_explicit_session(self) -> None:
        with mock.patch.object(terminal_client, "run_project", return_value=7) as run:
            self.assertTrue(terminal_client.handles(["--project", "--session", "claude:abc"]))
            self.assertEqual(7, terminal_client.run(["--project", "--session", "claude:abc"]))
        run.assert_called_once_with(session="claude:abc")
