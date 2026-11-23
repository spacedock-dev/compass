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

from compass_runtime import terminal_client, terminal_project, terminal_sessions
from compass_runtime.terminal_sessions import _owner

from .support import SERVER_PATH
from .test_terminal_client import ClockedDashboard, FakeDashboard

FIXTURES = Path(__file__).resolve().parents[4] / "frontend/test/fixtures"


def recorded(name: str) -> dict[str, Any]:
    body: dict[str, Any] = json.loads(
        (FIXTURES / "client-contract" / (name + ".json")).read_text()
    )["response"]["body"]
    return body


class ProjectTest(unittest.TestCase):
    def test_inferred_layout_discloses_one_unknown_without_another_measured_location(self) -> None:
        for key in ("main-key", "other-key"):
            rows = [
                {
                    "harness": "claude",
                    "sid": "main",
                    "project": "audits",
                    "project_key": "main-key",
                    "project_identity_source": "git common directory",
                },
                {
                    "harness": "claude",
                    "sid": "gone",
                    "project": "audits",
                    "project_key": key,
                    "project_identity_source": "inferred Claude worktree layout",
                    "worktree": "gone",
                },
            ]
            output = "\n".join(
                terminal_project.render(
                    terminal_project.derive({"sessions": rows}, {}, label="audits"),
                    caller=("claude", "main"),
                )
            )
            self.assertIn("Location not measured for 1 session with this display label", output)
            self.assertNotIn("2 measured locations", output)

    def test_project_location_warning_survives_the_real_terminal_projection(self) -> None:
        for source in ("working directory path", "git common directory"):
            for case in ("same", "unknown", "different"):
                with self.subTest(source=source, case=case):
                    rows = [
                        {
                            "harness": "claude",
                            "sid": f"audit-{i}",
                            "project": "audits",
                            "project_key": "measured-key",
                            "project_identity_source": source,
                            "state": "idle",
                        }
                        for i in range(9)
                    ]
                    warning = ""
                    if case == "unknown":
                        rows[-1]["project_identity_source"] = "collector project label"
                        warning = "Location not measured for 1 session with this display label"
                    if case == "different":
                        rows[-1]["project_key"] = "different-key"
                        warning = "9 sessions share this display label across 2 measured locations"
                    payload = {"sessions": rows}
                    projected = terminal_sessions.list_payload(payload)
                    brief = terminal_project.derive(projected, {}, label="audits")
                    self.assertEqual(warning, brief["warning"])
                    output = "\n".join(terminal_project.render(brief, caller=("claude", "audit-0")))
                    raw = terminal_project.derive(payload, {}, label="audits")
                    self.assertEqual(
                        output,
                        "\n".join(terminal_project.render(raw, caller=("claude", "audit-0"))),
                    )
                    if warning:
                        self.assertIn(warning, output.splitlines())
                    else:
                        self.assertNotIn("Location not measured", output)
                        self.assertNotIn("measured locations", output)
                    self.assertEqual(9, len(brief["members"]))

    def test_singleton_and_absent_keys_keep_exact_rendered_location_disclosures(self) -> None:
        measured = {
            "harness": "claude",
            "sid": "main",
            "project": "audits",
            "project_key": "measured",
            "project_identity_source": "git common directory",
        }
        unknown = {**measured, "sid": "peer"}
        for missing in (True, False):
            for value in (None, "", "   "):
                with self.subTest(missing=missing, value=value):
                    peer = {**unknown, "project_key": value}
                    if missing:
                        del peer["project_key"]
                    for rows, warning in (
                        ([peer], ""),
                        (
                            [measured, peer],
                            "Location not measured for 1 session with this display label",
                        ),
                        (
                            [peer, {**peer, "sid": "third"}],
                            "Location not measured for 2 sessions with this display label",
                        ),
                    ):
                        brief = terminal_project.derive(
                            terminal_sessions.list_payload({"sessions": rows}), {}, label="audits"
                        )
                        self.assertEqual(warning, brief["warning"])
                        output = "\n".join(
                            terminal_project.render(brief, caller=("claude", "main"))
                        )
                        if warning:
                            self.assertIn(warning, output.splitlines())
                        else:
                            self.assertNotIn("Location not measured", output)
                        self.assertNotIn("measured locations", output)

    def test_mixed_location_count_only_counts_measured_members(self) -> None:
        rows = [
            {
                "harness": "claude",
                "sid": str(i),
                "project": "audits",
                "project_key": f"key-{i}",
                "project_identity_source": source,
            }
            for i, source in enumerate(
                (
                    "working directory path",
                    "git common directory",
                    "inferred Claude worktree layout",
                )
            )
        ]
        expected = (
            "2 sessions share this display label across 2 measured locations. "
            "Location not measured for 1 session with this display label"
        )
        brief = terminal_project.derive(
            terminal_sessions.list_payload({"sessions": rows}), {}, label="audits"
        )
        self.assertEqual(expected, brief["warning"])
        output = "\n".join(terminal_project.render(brief, caller=("claude", "0")))
        self.assertIn(expected, output.splitlines())
        self.assertEqual(
            1, output.count("Location not measured for 1 session with this display label")
        )
        self.assertEqual(3, len(brief["members"]))

    def test_a_person_reads_the_board_members_counts_order_and_brief(self) -> None:
        for fixture in ("terminal-project", "terminal-project-fo"):
            expected = json.loads((FIXTURES / (fixture + ".json")).read_text())
            if attention := expected.pop("terminal_attention", None):
                expected["attention_heading"] = attention[0].strip()
                expected["attention_truth"] = attention[1].strip()
            for name in ("data-" + fixture, "sessions-" + fixture):
                with self.subTest(fixture=fixture, name=name):
                    self.assertEqual(
                        expected,
                        terminal_project.derive(
                            recorded(name), recorded("context-" + fixture), label="terminal-project"
                        ),
                    )

    def test_a_person_reads_workflow_authority_in_plain_words_before_the_technical_line(
        self,
    ) -> None:
        expected = json.loads((FIXTURES / "terminal-project-fo.json").read_text())
        brief = terminal_project.derive(
            recorded("data-terminal-project-fo"),
            recorded("context-terminal-project-fo"),
            label="terminal-project",
        )
        lines = terminal_project.render(brief, caller=("claude", "a1b2c3d4"))
        attention = lines[lines.index("Needs you:") + 1 :]
        self.assertEqual(expected["terminal_attention"], attention[:4] + attention[-1:])
        self.assertNotRegex("\n".join(attention[:-1]), r"\b(FO|Captain|CAPTAIN)\b")

    def test_only_an_observed_turn_end_counts_as_quiet(self) -> None:
        rows = [
            {"harness": "claude", "sid": "unknown", "project": "p", "state": "idle"},
            {"harness": "claude", "sid": "stop", "project": "p", "state": "idle", "finished_at": 2},
            {"harness": "codex", "sid": "run", "project": "p", "state": "idle", "turn_end_at": 2},
            {"harness": "gemini", "sid": "scan", "project": "p", "state": "idle", "turn_end_at": 2},
        ]
        brief = terminal_project.derive({"sessions": rows}, {}, label="p")
        self.assertEqual("4 sessions · 2 quiet · 2 in no counted state", brief["counts"])

    def test_an_open_request_and_a_child_wait_take_precedence_over_a_turn_stop(self) -> None:
        rows = [
            {"harness": "claude", "sid": "ask", "project": "p", "state": "idle", "finished_at": 2},
            {
                "harness": "claude",
                "sid": "child-wait",
                "project": "p",
                "state": "working",
                "waiting_on_child": {"harness": "codex", "sid": "child"},
                "finished_at": 2,
            },
            {"harness": "codex", "sid": "child", "project": "p", "state": "working"},
        ]
        payload = {
            "sessions": rows,
            "ask": True,
            "asks": [
                {
                    "harness": "claude",
                    "session_id": "ask",
                    "project": "p",
                    "question": "Review the result?",
                }
            ],
        }
        brief = terminal_project.derive(payload, {}, label="p")
        self.assertEqual(
            "3 sessions · 1 working · 1 waiting on you · 1 in no counted state", brief["counts"]
        )
        lines = terminal_project.render(brief, caller=("claude", "ask"))
        self.assertTrue(
            any(
                line.startswith("  claude:ask ") and " · Waiting on you · " in line
                for line in lines
            )
        )
        self.assertIn('    Waiting on child "child"', lines)

    def test_a_person_can_see_that_working_was_read_by_scanning(self) -> None:
        row = {
            "harness": "gemini",
            "sid": "scan",
            "project": "p",
            "state": "working",
            "acquisition": "scan-only",
        }
        brief = terminal_project.derive({"sessions": [row]}, {}, label="p")
        lines = terminal_project.render(brief, caller=("claude", "other"))
        member = next(line for line in lines if "gemini:scan" in line)
        self.assertIn(" · Working · ", member)
        self.assertEqual(
            "    Read by scanning: no turn end can be observed here", lines[lines.index(member) + 1]
        )

    def test_a_person_sees_the_servers_cut_task_in_the_terminal(self) -> None:
        brief = terminal_project.derive(
            recorded("data-terminal-project"),
            recorded("context-terminal-project"),
            label="terminal-project",
        )
        expected = (
            "Build the parser with bounded input and preserve every reader-facing "
            "explanation and preserve every reader-facin…"
        )
        self.assertEqual(expected, brief["task"])
        self.assertIn(
            expected, "\n".join(terminal_project.render(brief, caller=("claude", "a1b2c3d4")))
        )

    def test_a_person_sees_when_the_parser_cut_a_task_after_skipped_xml(self) -> None:
        sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "scripts"))
        try:
            recorder = importlib.import_module("regen_client_fixtures")
        finally:
            sys.path.pop(0)
        captures = recorder.Recorder()
        scratch = recorder.Scratch()
        try:
            with recorder.guarded():
                recorder.task_preview_scenario(captures, scratch)
        finally:
            scratch.close()
        for case, expected in (("xml", "Build the parser…"), ("whole", "Build the parser")):
            with self.subTest(case=case):
                payload = captures.scenarios["data-task-preview-" + case]["response"]["body"]
                context = captures.scenarios["context-task-preview-" + case]["response"]["body"]
                fact = next(f for f in context["semantic"]["facts"] if f["type"] == "user_message")
                self.assertEqual(expected, fact["summary"])
                brief = terminal_project.derive(payload, context, label="task-preview")
                self.assertEqual(expected, brief["task"])
                self.assertIn(
                    expected,
                    "\n".join(terminal_project.render(brief, caller=("claude", "a1b2c3d4"))),
                )

    def test_a_person_is_not_needed_when_only_the_first_officer_has_follow_ups(self) -> None:
        payload = recorded("data-terminal-project")
        for row in payload["sessions"]:
            if row["state"] == "needs_input":
                row["state"] = "idle"
        payload["sessions"][0]["spacedock"] = {"role": "first-officer"}
        brief = terminal_project.derive(
            payload, recorded("context-terminal-project"), label="terminal-project"
        )
        output = "\n".join(terminal_project.render(brief, caller=("claude", "a1b2c3d4")))
        self.assertIn("CHECKING", output)
        self.assertIn("You are not needed", output)
        self.assertIn("AGENT · REFRESH · refresh workflow discovery", output)
        self.assertIn(
            "FO is the first officer, the agent driving this workflow; Captain is you.", output
        )
        self.assertNotIn("Follow-up ·", output)
        self.assertNotIn("CAPTAIN NEEDED", output)

    def test_a_persons_attention_is_not_cleared_past_a_wait_question_or_incomplete_scan(
        self,
    ) -> None:
        for workflow in (False, True):
            for state in ("incomplete", "unavailable", "wait", "question"):
                with self.subTest(workflow=workflow, state=state):
                    payload = recorded("data-terminal-project-fo")
                    if not workflow:
                        for row in payload["sessions"]:
                            row["spacedock"] = None
                    context = recorded("context-terminal-project-fo")
                    projections = context["semantic"]["projections"]
                    if state in ("incomplete", "unavailable"):
                        projections["command_attention_coverage"]["state"] = state
                    if state == "wait":
                        next(row for row in payload["sessions"] if row["sid"] == "a1b2c3d4")[
                            "state"
                        ] = "needs_input"
                    if state == "question":
                        projections["command_attention"] = [
                            {"owner": "CAPTAIN", "question": "Approve the parser?"}
                        ]
                    output = "\n".join(
                        terminal_project.render(
                            terminal_project.derive(payload, context, label="terminal-project"),
                            caller=("claude", "a1b2c3d4"),
                        )
                    )
                    not_needed = "You are not needed"
                    self.assertNotIn(not_needed, output)
                    if state in ("incomplete", "unavailable"):
                        self.assertIn(
                            "Your attention is unknown",
                            output,
                        )
                    if state == "question":
                        self.assertIn("NEEDS YOU", output)
                        self.assertIn(
                            "YOU" + " · ANSWER · Approve the parser?",
                            output,
                        )

    def test_a_person_reads_the_first_published_handoff_when_return_times_tie(self) -> None:
        payload = {
            "generated": 1000,
            "sessions": [
                {
                    "harness": "claude",
                    "sid": "first",
                    "project": "p",
                    "state": "idle",
                    "last_activity": 900,
                    "subagent_events": [{"kind": "subagent_complete", "name": "First", "at": 800}],
                },
                {
                    "harness": "claude",
                    "sid": "second",
                    "project": "p",
                    "state": "working",
                    "last_activity": 950,
                    "subagent_events": [{"kind": "subagent_complete", "name": "Second", "at": 800}],
                },
            ],
        }
        output = "\n".join(
            terminal_project.render(
                terminal_project.derive(payload, {}, label="p"), caller=("claude", "first")
            )
        )
        self.assertIn("recover First handoff", output)
        self.assertNotIn("recover Second handoff", output)

    def test_a_person_reads_indented_members_execution_and_attention(self) -> None:
        brief = terminal_project.derive(
            recorded("data-terminal-project"),
            recorded("context-terminal-project"),
            label="terminal-project",
        )
        lines = terminal_project.render(brief, caller=("claude", "a1b2c3d4"))
        self.assertTrue(any(line.startswith("  claude:a1b2c3d4 [this session]") for line in lines))
        for heading in ("Running now:", "Needs you:"):
            self.assertTrue(lines[lines.index(heading) + 1].startswith("  "), lines)
        self.assertTrue(any(line.startswith("  Reader · active") for line in lines))

    def test_a_person_keeps_same_label_members_when_repository_keys_disagree(self) -> None:
        payload = recorded("data-terminal-project")
        payload["sessions"][0]["project_key"] = "other-key"
        brief = terminal_project.derive(payload, {}, label="terminal-project")
        self.assertEqual(
            "terminal-project", terminal_project.project_key(payload, "terminal-project")
        )
        self.assertEqual(4, len(brief["members"]))
        self.assertIn("Location not measured for 4 sessions", brief["warning"])

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
        self.assertIn("2 waiting on you", brief["counts"])
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
    # Measures a cold project read against a real response beyond the ordinary request budget.
    REAL_TIME_TESTS = True

    def run_project(
        self, fake: FakeDashboard | ClockedDashboard, **kwargs: Any
    ) -> tuple[int, str, str]:
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

    def test_a_person_is_not_marked_as_a_peer_with_the_same_short_session_id(self) -> None:
        answers = self.answers()
        payload = recorded("sessions-terminal-project")
        peer = next(row for row in payload["sessions"] if row["sid"] == "a1b2c3d4")
        peer["resume_id"] = "a1b2c3d4-9999-2222-3333-444455556666"
        answers["/api/sessions"] = (200, {}, json.dumps(payload).encode())
        with FakeDashboard(answers=answers) as fake:
            code, out, err = self.run_project(fake)
        self.assertEqual((1, ""), (code, out))
        self.assertIn("outside the current board", err)
        self.assertNotIn("[this session]", out)
        self.assertFalse(any(path.startswith("/api/project-context") for _, path in fake.requests))

    def test_a_person_reads_their_project_when_the_cold_session_list_takes_six_seconds(
        self,
    ) -> None:
        # Scale the ordinary/list budgets and the cold reply by ten, retaining real I/O.
        with (
            mock.patch.object(terminal_client, "REQUEST_TIMEOUT_SEC", 0.5),
            mock.patch.object(terminal_client, "LIST_REQUEST_TIMEOUT_SEC", 3.0),
            mock.patch.dict(terminal_client.request.__kwdefaults__, timeout=0.5),
            mock.patch.dict(terminal_client.get.__kwdefaults__, timeout=0.5),
            mock.patch.dict(terminal_client.read_sessions.__kwdefaults__, timeout=3.0),
            FakeDashboard(answers=self.answers(), delays={"/api/sessions": 0.6}) as fake,
        ):
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
            ClockedDashboard(
                answers=self.answers(),
                delays={
                    "/api/session?harness=claude&sid=a1b2c3d4-1111-2222-3333-444455556666": 0.08,
                    "/api/sessions": 0.49,
                    "/api/project-context?project=key-terminal-project": 0.08,
                },
            ) as fake,
        ):
            code, out, err = self.run_project(fake)

        self.assertEqual((0, ""), (code, err))
        self.assertEqual(1, out.count("[this session]"))

    def test_a_person_gets_no_partial_brief_when_the_project_list_exceeds_its_allowance(
        self,
    ) -> None:
        with (
            mock.patch.object(terminal_client, "REQUEST_TIMEOUT_SEC", 0.1),
            mock.patch.object(terminal_client, "LIST_REQUEST_TIMEOUT_SEC", 0.5),
            ClockedDashboard(answers=self.answers(), delays={"/api/sessions": 0.51}) as fake,
        ):
            result = self.run_project(fake)

        self.assertEqual(
            (1, "", "Compass answered, but its session list could not be read.\n"), result
        )
        self.assertIn(("GET", "/api/sessions"), fake.requests)
        self.assertFalse(any(path.startswith("/api/project-context") for _, path in fake.requests))
        self.assertNotIn(("GET", "/api/data"), fake.requests)

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
