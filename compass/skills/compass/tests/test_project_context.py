"""Real-source project observer and gate/steering history."""

from __future__ import annotations

import dataclasses
import json
import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from compass_runtime import (
    observer,
    project_context,
    reading_route,
    semantic_history,
    sessions,
    spacedock,
)
from compass_runtime.config import build_runtime_config
from compass_runtime.state import build_runtime_state


def message(msg_id: str, text: str, timestamp: str) -> str:
    return json.dumps(
        {
            "type": "message",
            "id": msg_id,
            "timestamp": timestamp,
            "message": {"role": "user", "content": text},
        }
    )


def codex_message(text: str, timestamp: str) -> dict[str, object]:
    return {
        "timestamp": timestamp,
        "type": "response_item",
        "payload": {"type": "message", "role": "user", "content": text},
    }


class ProjectContextTest(unittest.TestCase):
    NOW = 1_800_000_000.0
    SID = "project-session"

    def test_a_reader_using_a_project_label_and_key_gets_one_history(self) -> None:
        row = {
            "project": "recce/example",
            "project_key": "git:example",
            "harness": "codex",
            "sid": "root",
        }
        with mock.patch.object(observer, "resolve_transcript", return_value=None):
            project_context.collect(
                self.config,
                build_runtime_state(self.config, started=1),
                [row],
                "recce/example",
                now=self.NOW,
            )
            project_context.collect(
                self.config,
                build_runtime_state(self.config, started=1),
                [row],
                "git:example",
                now=self.NOW,
            )
        stored = json.loads(Path(semantic_history.store_path(self.config)).read_text())
        self.assertEqual({"git:example"}, set(stored["projects"]))

    def test_a_reader_keeps_legacy_label_history_when_the_key_is_unambiguous(self) -> None:
        state = build_runtime_state(self.config, started=1)
        fact = {
            "fact_id": "old",
            "type": "user_message",
            "at": self.NOW,
            "summary": "Build synthetic work",
            "source_session": {"harness": "codex", "sid": "root"},
        }
        semantic_history.update(self.config, state, "recce/example", {"facts": [fact]}, [])
        row = {
            "project": "recce/example",
            "project_key": "git:example",
            "harness": "codex",
            "sid": "root",
        }
        with mock.patch.object(observer, "resolve_transcript", return_value=None):
            result = project_context.collect(self.config, state, [row], "git:example", now=self.NOW)
        self.assertIn("old", [f["fact_id"] for f in result["semantic"]["facts"]])
        self.assertEqual(
            ["old"],
            [
                e["event_id"]
                for e in semantic_history.read(self.config, state, "git:example")["events"]
            ],
        )

    def test_a_reader_never_joins_repositories_that_share_a_display_label(self) -> None:
        rows = [{"project": "example", "project_key": key} for key in ("git:first", "git:second")]
        self.assertEqual(("example", ()), project_context._history_identity(rows, "example"))
        self.assertEqual(("git:first", ()), project_context._history_identity(rows, "git:first"))

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.workflow = self.root / "workflow"
        self.entity_dir = self.workflow / ".spacedock-state"
        self.workflow.mkdir()
        self.entity_dir.mkdir()
        (self.workflow / "README.md").write_text(
            "---\ncommissioned-by: spacedock@0.27.0\ntitle: Ship project cockpit\n"
            "stages:\n  states:\n    - name: shaping\n    - name: review\n---\n",
            encoding="utf-8",
        )
        self.transcript = self.root / "session.jsonl"
        self._write_transcript("Follow the captain revision", "2026-08-24T20:00:00Z")
        self.entity = self.entity_dir / "project-cockpit.md"
        self._write_gate("2026-08-24T20:05:00Z", "approve")
        os.utime(self.entity, (self.NOW, self.NOW))
        self.config = build_runtime_config(
            environ={"HOME": str(self.root), "COMPASS_HOME": str(self.root / "state")},
            platform_name="linux",
            os_name="posix",
            launcher_path=self.root / "server.py",
            store_root_overrides={"pi.sessions": str(self.root)},
        )
        self.model = mock.patch.object(
            observer.CodexGoalModel,
            "__call__",
            return_value=None,
        )
        self.model.start()

    def tearDown(self) -> None:
        self.model.stop()
        self.temp.cleanup()

    def _write_transcript(self, text: str | None, timestamp: str) -> None:
        envelope = json.dumps(
            {
                "command": "boot",
                "definition_dir": str(self.workflow),
                "entity_dir": str(self.entity_dir),
            }
        )
        boot = json.dumps(
            {
                "type": "message",
                "id": "boot",
                "message": {
                    "role": "user",
                    "content": [{"type": "tool_result", "content": envelope}],
                },
            }
        )
        lines = [json.dumps({"type": "session", "id": self.SID, "cwd": str(self.root)}), boot]
        if text is not None:
            lines.append(message("captain-1", text, timestamp))
        self.transcript.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _write_gate(self, timestamp: str, decision: str) -> None:
        self.entity.write_text(
            "---\ntitle: Project cockpit\nstatus: shaping\ngates:\n  version: 1\n"
            "  records:\n    - id: gate:project-cockpit:shaping\n"
            "      stage: shaping\n      attempts:\n"
            "        - id: gate-attempt:project-cockpit-shaping-1\n"
            "          briefing:\n            id: briefing:one\n"
            "          resolution:\n            by: person:captain\n"
            f'            at: "{timestamp}"\n            decision: {decision}\n'
            "            reason: 'ready to continue'\n"
            "          application:\n            target-stage: review\n"
            "            state: consumed\n---\n",
            encoding="utf-8",
        )

    def collect(
        self, *, refresh: bool = True, focused: bool = True, model_consent: bool = False
    ) -> dict[str, Any]:
        state = build_runtime_state(self.config, started=self.NOW)
        sessions = [
            {
                "project": "repo/proj",
                "harness": "pi",
                "sid": self.SID,
                "last_activity": self.NOW,
                "active": True,
                "spacedock": {
                    "role": "first-officer",
                    "workflows": [
                        {
                            "workflow": "workflow",
                            "entities": [{"slug": "project-cockpit"}],
                        }
                    ],
                },
            }
        ]
        return project_context.collect(
            self.config,
            state,
            sessions,
            "repo/proj",
            now=self.NOW,
            refresh=refresh,
            model_consent=model_consent,
            focus=("pi", self.SID) if focused else None,
        )

    def test_real_transcript_and_gate_frontmatter_supply_the_context(self) -> None:
        focused = self.collect()
        result = self.collect(focused=False)

        observer = focused["observers"][0]
        events = result["events"]
        self.assertEqual("Follow the captain revision", observer["goal"])
        self.assertEqual("shaping", observer["stage"])
        self.assertEqual(["gate", "steer"], [event["kind"] for event in events])
        self.assertEqual("application consumed", events[0]["phase"].split(" · ")[-1])

    def test_project_workflows_are_discovered_without_session_attachment_metadata(self) -> None:
        # Given: a checkout contains dev and explore workflow definitions.
        repository = self.root / "repository"
        (repository / ".git").mkdir(parents=True)
        workflow_dirs = [repository / ".spacedock" / name for name in ("dev", "explore")]
        for workflow_dir in workflow_dirs:
            workflow_dir.mkdir(parents=True)
            (workflow_dir / "README.md").write_text(
                "---\ncommissioned-by: spacedock@0.28.0-pre0\n"
                f"title: Shape {workflow_dir.name}\n"
                "stages:\n  states:\n    - name: shaping\n    - name: review\n---\n",
                encoding="utf-8",
            )
        calls: list[dict[str, object]] = []

        def runner(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
            calls.append({"argv": argv, **kwargs})
            return subprocess.CompletedProcess(
                argv,
                0,
                stdout="\n".join(str(path) for path in workflow_dirs) + "\n",
                stderr="",
            )

        state = build_runtime_state(self.config, started=self.NOW)
        with mock.patch.dict(os.environ, {"SPACEDOCK_BIN": "/opt/bin/spacedock"}):
            # When: discover workflows with the bounded runner.
            result = project_context.discover_project_workflows(
                self.config,
                state,
                str(repository),
                now=self.NOW,
                runner=runner,
            )

        # Then
        self.assertEqual("observed", result["state"])
        self.assertEqual(["dev", "explore"], [row["workflow"] for row in result["workflows"]])
        self.assertEqual(["shaping", "review"], result["workflows"][0]["stages"])
        self.assertEqual(
            [["/opt/bin/spacedock", "status", "--discover"]], [call["argv"] for call in calls]
        )
        self.assertEqual(os.path.realpath(repository), calls[0]["cwd"])
        self.assertFalse(calls[0].get("shell", False))

    @mock.patch.dict(os.environ, {"SPACEDOCK_BIN": ""})
    def test_project_workflow_discovery_caches_the_bounded_result(self) -> None:
        # Given: the first discovery has cached an empty result.
        repository = self.root / "repository"
        (repository / ".git").mkdir(parents=True)
        calls = 0

        def runner(argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
            nonlocal calls
            calls += 1
            return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

        state = build_runtime_state(self.config, started=self.NOW)
        first = project_context.discover_project_workflows(
            self.config,
            state,
            str(repository),
            now=self.NOW,
            runner=runner,
            binary_resolver=lambda _name: str(self.root / "spacedock"),
        )

        # When: discover again one second later.
        second = project_context.discover_project_workflows(
            self.config,
            state,
            str(repository),
            now=self.NOW + 1,
            runner=runner,
            binary_resolver=lambda _name: str(self.root / "spacedock"),
        )

        # Then
        self.assertEqual("none", first["state"])
        self.assertEqual(first, second)
        self.assertEqual(1, calls)

    @mock.patch.dict(os.environ, {"SPACEDOCK_BIN": ""})
    def test_project_workflow_discovery_reports_unavailable_and_error_honestly(self) -> None:
        repository = self.root / "repository"
        (repository / ".git").mkdir(parents=True)

        def missing(_argv: list[str], **_kwargs: object) -> None:
            raise FileNotFoundError

        def timeout(argv: list[str], **_kwargs: object) -> None:
            raise subprocess.TimeoutExpired(argv, timeout=2)

        missing_result = project_context.discover_project_workflows(
            self.config,
            build_runtime_state(self.config, started=self.NOW),
            str(repository),
            now=self.NOW,
            runner=missing,
            binary_resolver=lambda _name: str(self.root / "spacedock"),
        )
        timeout_result = project_context.discover_project_workflows(
            self.config,
            build_runtime_state(self.config, started=self.NOW),
            str(repository),
            now=self.NOW,
            runner=timeout,
            binary_resolver=lambda _name: str(self.root / "spacedock"),
        )

        self.assertEqual("unavailable", missing_result["state"])
        self.assertIn("command", missing_result["reason"])
        self.assertEqual("error", timeout_result["state"])
        self.assertIn("timed out", timeout_result["reason"])

    @mock.patch.dict(os.environ, {"SPACEDOCK_BIN": ""})
    def test_project_workflow_discovery_rejects_missing_or_relative_resolution(self) -> None:
        # Given: the resolver returns a missing or relative binary path.
        for binary in (None, "spacedock", "bin/spacedock"):
            with self.subTest(binary=binary):
                runner = mock.Mock()
                resolver = mock.Mock(return_value=binary)

                # When: attempt workflow discovery for that resolution.
                result = project_context.discover_project_workflows(
                    self.config,
                    build_runtime_state(self.config, started=self.NOW),
                    str(self.root),
                    now=self.NOW,
                    runner=runner,
                    binary_resolver=resolver,
                )

                # Then
                self.assertEqual("unavailable", result["state"])
                self.assertIn("requires an absolute path", result["reason"])
                resolver.assert_called_once_with("spacedock")
                runner.assert_not_called()

    @mock.patch.dict(os.environ, {"SPACEDOCK_BIN": ""})
    def test_linked_worktree_session_discovers_from_the_canonical_checkout(self) -> None:
        # Given: a session transcript points to a linked worktree.
        checkout = self.root / "checkout"
        git_dir = checkout / ".git"
        worktree = checkout / ".worktrees" / "prototype"
        worktree_git_dir = git_dir / "worktrees" / "prototype"
        worktree.mkdir(parents=True)
        worktree_git_dir.mkdir(parents=True)
        (worktree / ".git").write_text(
            f"gitdir: {worktree_git_dir}\n",
            encoding="utf-8",
        )
        (worktree_git_dir / "commondir").write_text("../..\n", encoding="utf-8")
        workflow_dirs = [checkout / ".spacedock" / name for name in ("dev", "explore")]
        for workflow_dir in workflow_dirs:
            workflow_dir.mkdir(parents=True)
            (workflow_dir / "README.md").write_text(
                "---\ncommissioned-by: spacedock@0.28.0-pre0\n"
                f"title: Shape {workflow_dir.name}\n"
                "stages:\n  states:\n    - name: shaping\n---\n",
                encoding="utf-8",
            )
        sid = "linked-worktree"
        transcript = self.root / "linked-worktree.jsonl"
        transcript.write_text(
            json.dumps({"type": "session", "id": sid, "cwd": str(worktree)}) + "\n",
            encoding="utf-8",
        )
        project_key = sessions.project_identity(self.config, str(worktree))["key"]
        calls: list[str] = []

        def runner(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
            calls.append(str(kwargs["cwd"]))
            return subprocess.CompletedProcess(
                argv,
                0,
                stdout="\n".join(str(path) for path in workflow_dirs) + "\n",
                stderr="",
            )

        # When: discover its workflows from the project identity.
        result = project_context._project_workflow_discovery(
            self.config,
            build_runtime_state(self.config, started=self.NOW),
            [
                {
                    "project": "checkout/prototype",
                    "project_key": project_key,
                    "harness": "pi",
                    "sid": sid,
                }
            ],
            project_key,
            now=self.NOW,
            refresh=False,
            runner=runner,
            binary_resolver=lambda _name: str(self.root / "spacedock"),
        )

        # Then
        self.assertEqual([os.path.realpath(checkout)], calls)
        self.assertEqual("observed", result["state"])
        self.assertEqual(["dev", "explore"], [row["workflow"] for row in result["workflows"]])

    @unittest.skipUnless(hasattr(os, "symlink"), "platform has no symlink")
    @mock.patch.dict(os.environ, {"SPACEDOCK_BIN": ""})
    def test_discovery_reads_only_project_local_linked_definitions(self) -> None:
        repository = self.root / "repository"
        definition_root = repository / ".spacedock"
        workflow = definition_root / "dev"
        shared = definition_root / "repo"
        workflow.mkdir(parents=True)
        shared.mkdir()
        target = shared / "README.md"
        target.write_text(
            "---\ncommissioned-by: spacedock@0.28.0-pre0\n"
            "title: Linked project definition\n"
            "stages:\n  states:\n    - name: shaping\n---\n",
            encoding="utf-8",
        )
        try:
            (workflow / "README.md").symlink_to(target)
        except OSError:  # pragma: no cover - Windows without the privilege
            self.skipTest("symlink creation not permitted")

        def runner(argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(argv, 0, stdout=f"{workflow}\n", stderr="")

        result = project_context.discover_project_workflows(
            self.config,
            build_runtime_state(self.config, started=self.NOW),
            str(repository),
            now=self.NOW,
            runner=runner,
            binary_resolver=lambda _name: str(self.root / "spacedock"),
        )

        self.assertEqual("observed", result["state"])
        self.assertEqual("Linked project definition", result["workflows"][0]["goal"])
        self.assertEqual(["shaping"], result["workflows"][0]["stages"])

    def test_source_changes_move_events_and_source_removal_does_not_leave_rows(self) -> None:
        before = self.collect(focused=False)
        self._write_gate("2026-08-24T20:15:00Z", "revise")
        moved = self.collect(focused=False)
        self.entity.unlink()
        no_gate = self.collect(focused=False)
        self._write_transcript(None, "2026-08-24T20:00:00Z")
        empty = self.collect(focused=False)

        self.assertNotEqual(before["events"][0]["at"], moved["events"][0]["at"])
        self.assertEqual(0, no_gate["sources"]["gate"]["live"])
        self.assertEqual(["steer"], [event["kind"] for event in no_gate["events"]])
        self.assertEqual([], empty["events"])
        self.assertEqual(0, empty["sources"]["steer"]["live"])

    def test_bound_omissions_are_not_reported_as_unreadable_transcripts(self) -> None:
        # Given: active sessions exceed the observer cap and have missing transcripts.
        state = build_runtime_state(self.config, started=self.NOW)
        sessions = [
            {
                "project": "repo/proj",
                "harness": "pi",
                "sid": f"missing-{index}",
                "last_activity": self.NOW - index,
                "active": True,
            }
            for index in range(project_context.MAX_PROJECT_OBSERVERS + 1)
        ]

        # When: collect project context.
        result = project_context.collect(
            self.config,
            state,
            sessions,
            "repo/proj",
            now=self.NOW,
        )

        # Then
        self.assertEqual(
            project_context.MAX_PROJECT_OBSERVERS, len(result["sources"]["observer"]["unavailable"])
        )
        self.assertEqual(1, len(result["sources"]["observer"]["omitted"]))

    def test_attention_scan_includes_fourth_active_session_beyond_observer_cap(self) -> None:
        # Given: a fourth active session has an exact authorization request.
        state = build_runtime_state(self.config, started=self.NOW)
        sessions = [
            {
                "project": "repo/proj",
                "harness": "pi",
                "sid": f"newer-{index}",
                "state": "working",
                "last_activity": self.NOW - index,
                "active": True,
            }
            for index in range(project_context.MAX_PROJECT_OBSERVERS)
        ]
        sessions.append(
            {
                "project": "repo/proj",
                "harness": "codex",
                "sid": "fourth-auth",
                "title": "Exact fourth-session authorization",
                "state": "idle",
                "last_activity": self.NOW - 10,
                "last_output": (
                    "A separate authorization is required to push and create the PR.\n"
                    "Approve pushing this candidate and creating the PR?"
                ),
                "active": True,
            }
        )

        # When: collect automatic project context.
        result = project_context.collect(
            self.config, state, sessions, "repo/proj", now=self.NOW, refresh=False
        )

        attention = result["semantic"]["projections"]["command_attention"]
        coverage = result["semantic"]["projections"]["command_attention_coverage"]

        # Then
        self.assertEqual(1, len(attention))
        self.assertEqual("Exact fourth-session authorization", attention[0]["label"])
        self.assertEqual("complete", coverage["state"])
        self.assertEqual(4, coverage["scanned"])

    def test_attention_scan_reports_incomplete_bounded_coverage(self) -> None:
        # Given: active sessions exceed the attention-scan cap by one.
        state = build_runtime_state(self.config, started=self.NOW)
        sessions = [
            {
                "project": "repo/proj",
                "harness": "pi",
                "sid": f"session-{index}",
                "state": "working",
                "last_activity": self.NOW - index,
                "active": True,
            }
            for index in range(project_context.MAX_PROJECT_ATTENTION_SESSIONS + 1)
        ]

        # When: collect automatic project context.
        result = project_context.collect(
            self.config, state, sessions, "repo/proj", now=self.NOW, refresh=False
        )

        coverage = result["semantic"]["projections"]["command_attention_coverage"]

        # Then
        self.assertEqual("incomplete", coverage["state"])
        self.assertEqual(project_context.MAX_PROJECT_ATTENTION_SESSIONS, coverage["scanned"])
        self.assertEqual(1, coverage["omitted"])

    def test_focus_identity_excludes_surrounding_sessions_from_analysis(self) -> None:
        # Given: the selected session is older than surrounding active sessions.
        state = build_runtime_state(self.config, started=self.NOW)
        sessions = [
            {
                "project": "repo/proj",
                "harness": "pi",
                "sid": f"newer-{index}",
                "last_activity": self.NOW + index,
                "active": True,
            }
            for index in range(project_context.MAX_PROJECT_OBSERVERS)
        ]
        sessions.append(
            {
                "project": "repo/proj",
                "harness": "pi",
                "sid": self.SID,
                "last_activity": self.NOW - 100,
                "active": True,
            }
        )

        # When: collect context focused on its exact identity.
        result = project_context.collect(
            self.config,
            state,
            sessions,
            "repo/proj",
            now=self.NOW,
            refresh=True,
            focus=("pi", self.SID),
        )

        # Then
        self.assertEqual(self.SID, result["observers"][0]["sid"])
        self.assertTrue(result["focus"]["observed"])
        self.assertEqual([], result["sources"]["observer"]["omitted"])
        self.assertEqual("focused session", result["sources"]["scope"])
        self.assertEqual(
            project_context.MAX_PROJECT_OBSERVERS,
            result["sources"]["surrounding_active"],
        )

    def test_focused_goal_refresh_honors_off_and_publishes_the_notice(self) -> None:
        self.model.stop()
        from compass_runtime import reading_policy  # noqa: PLC0415

        reading_policy.set_consent(self.config, False, now=self.NOW)
        with mock.patch.object(observer, "codex_exec") as execute:
            off = self.collect(model_consent=True)
        execute.assert_not_called()
        self.assertEqual("model-calls-paused", off["observers"][0]["model"]["status"])
        self.assertNotIn("notice", off["observer_model"])
        reading_policy.set_consent(self.config, True, now=self.NOW + 1)

        def execute_goal(*_args: Any, **kwargs: Any) -> tuple[str, str]:
            kwargs["before_call"]()
            return "ship the parser", "ok"

        with mock.patch.object(observer, "codex_exec", side_effect=execute_goal):
            on = self.collect(model_consent=True)
            again = self.collect(model_consent=True)
        self.assertTrue(on["observer_model"]["enabled"])
        self.assertEqual("goal", on["observer_model"]["notice"]["kind"])
        self.assertEqual(
            reading_route.destination(reading_route.CODEX),
            on["observer_model"]["notice"]["destination"],
        )
        self.assertNotIn("notice", again["observer_model"])
        self.assertNotIn("?", on["observer_model"]["disclosure"])
        self.assertIn("Pause model calls", on["observer_model"]["disclosure"])

    def test_a_childs_goal_call_publishes_the_notice_it_recorded(self) -> None:
        # The child is observed before its parent, so its call is the one that
        # records the notice; the parent then finds none due.
        from compass_runtime import reading_policy  # noqa: PLC0415

        reading_policy.store_path(self.config).unlink(missing_ok=True)
        state = build_runtime_state(self.config, started=self.NOW)
        parent = {
            "project": "repo/proj",
            "harness": "codex",
            "sid": "parent-thread",
            "last_activity": self.NOW,
            "active": True,
            "subagent_hierarchy": [
                {"name": "Volta", "depth": 1, "parent_name": None, "observer_sid": "child"}
            ],
        }
        for goal in ("Improve the assignment roster", observer.NO_GOAL):
            with self.subTest(goal=goal):
                reading_policy.set_consent(self.config, False, now=self.NOW)
                reading_policy.set_consent(self.config, True, now=self.NOW)

                def observe_child(*_args: Any, child_goal: str = goal, **_kwargs: Any) -> Any:
                    notice = reading_policy.note(
                        self.config,
                        kind="goal",
                        provider="codex",
                        destination="OpenAI",
                        content=reading_policy.CONTENT_VERSION,
                        tool_output="",
                        now=self.NOW,
                    )
                    return {
                        "goal": child_goal,
                        "observed_at": self.NOW,
                        "snapshot_status": "refreshed",
                        "notice": notice,
                    }

                with (
                    mock.patch.object(
                        observer,
                        "resolve_transcript",
                        side_effect=lambda _c, _s, _h, sid: (
                            "/tmp/child.jsonl" if sid == "child" else None
                        ),
                    ),
                    mock.patch.object(
                        project_context, "_observe_session", side_effect=observe_child
                    ),
                ):
                    result = project_context.collect(
                        self.config,
                        state,
                        [parent],
                        "repo/proj",
                        now=self.NOW,
                        refresh=True,
                        model_consent=True,
                        focus=("codex", "parent-thread"),
                    )
                notice = result["observer_model"]["notice"]
                self.assertEqual("goal", notice["kind"])
                self.assertEqual("OpenAI", notice["destination"])
                self.assertNotIn("notice", result["child_assignments"][0])

    def test_refresh_without_model_consent_uses_local_analysis(self) -> None:
        # Given: model analysis is enabled but no consent was supplied.
        self.config = dataclasses.replace(self.config, observer_model_enabled=True)
        with mock.patch.object(observer.CodexGoalModel, "__call__") as model:
            # When: refresh project context.
            result = self.collect()

        # Then
        model.assert_not_called()
        self.assertEqual("Follow the captain revision", result["observers"][0]["goal"])
        self.assertEqual("consent-required", result["observers"][0]["model"]["status"])
        self.assertTrue(result["observer_model"]["enabled"])
        self.assertEqual(16384, result["observer_model"]["max_prompt_bytes"])
        self.assertIn("transcript", result["observer_model"]["disclosure"])

    def test_automatic_context_uses_stale_cache_without_model_wait(self) -> None:
        # Given: a cached observation predates a changed transcript.
        refreshed = self.collect()
        observed_at = refreshed["observers"][0]["observed_at"]
        self._write_transcript("A newer steering record", "2026-08-24T20:20:00Z")

        with mock.patch.object(observer.CodexGoalModel, "__call__") as model:
            # When: collect automatic context without refresh.
            automatic = self.collect(refresh=False)

        # Then
        model.assert_not_called()
        self.assertEqual(observed_at, automatic["observers"][0]["observed_at"])
        self.assertEqual("cached-stale", automatic["observers"][0]["snapshot_status"])
        self.assertEqual("A newer steering record", automatic["events"][0]["title"])

    def test_automatic_context_without_cache_returns_timeline_only(self) -> None:
        # Given: the observer sidecar is absent.
        path = observer.sidecar_path(self.config, "pi", self.SID)
        if path is not None:
            Path(path).unlink(missing_ok=True)

        with mock.patch.object(observer.CodexGoalModel, "__call__") as model:
            # When: collect automatic project context without refresh.
            automatic = self.collect(refresh=False, focused=False)

        # Then
        model.assert_not_called()
        self.assertEqual([], automatic["observers"])
        self.assertEqual(["gate", "steer"], [event["kind"] for event in automatic["events"]])

    def test_codex_response_item_is_a_timestamped_instruction(self) -> None:
        event = project_context._instruction_event(
            self.config,
            codex_message("Captain changed the shape", "2026-08-24T20:10:00Z"),
            "codex",
            self.SID,
        )

        self.assertIsNotNone(event)
        assert event is not None
        self.assertEqual("Captain changed the shape", event["title"])
        self.assertEqual("user-role instruction", event["phase"])
        self.assertNotIn("detail", event)
        self.assertEqual("timestamped non-meta user-role record", event["source"])

    def test_instruction_is_condensed_and_tagged_only_by_explicit_wording(self) -> None:
        # Given: a user message includes explicit clarification and trailing prose.
        record = codex_message(
            "Captain clarification: Keep the graph concise.\n"
            "Infrastructure prose that must not become the directive.",
            "2026-08-24T20:10:00Z",
        )

        # When: extract the instruction event.
        event = project_context._instruction_event(
            self.config,
            record,
            "codex",
            self.SID,
        )

        # Then
        self.assertIsNotNone(event)
        assert event is not None
        self.assertEqual("Keep the graph concise.", event["title"])
        self.assertEqual("reframed", event["steering_tag"])
        self.assertEqual("explicit user-role wording", event["tag_source"])
        self.assertNotIn("Infrastructure prose", event["title"])

    def test_pi_work_events_normalize_dispatch_and_subagent_results(self) -> None:
        # Given: the transcript contains dispatch, subagent, status, and result records.
        records = [
            {
                "type": "message",
                "timestamp": "2026-08-24T20:00:00Z",
                "message": {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "toolCall",
                            "id": "raw-build-id",
                            "name": "bash",
                            "arguments": {
                                "command": "echo preparing\n"
                                "spacedock dispatch build --workflow-dir /work task-one "
                                "--stage shaping\n"
                            },
                        },
                        {
                            "type": "toolCall",
                            "id": "raw-batch-id",
                            "name": "subagent",
                            "arguments": {
                                "tasks": [
                                    {"task": "Inspect architecture", "agent": "one"},
                                    {"task": "Inspect interaction", "agent": "two"},
                                ]
                            },
                        },
                        {
                            "type": "toolCall",
                            "id": "raw-status-id",
                            "name": "subagent",
                            "arguments": {"action": "status"},
                        },
                        {
                            "type": "toolCall",
                            "id": "raw-open-id",
                            "name": "subagent",
                            "arguments": {"task": "Check the unresolved edge"},
                        },
                    ],
                },
            },
            {
                "type": "message",
                "timestamp": "2026-08-24T20:01:00Z",
                "message": {
                    "role": "toolResult",
                    "toolCallId": "raw-build-id",
                    "isError": False,
                    "content": [{"type": "text", "text": "built"}],
                },
            },
            {
                "type": "message",
                "timestamp": "2026-08-24T20:02:00Z",
                "message": {
                    "role": "toolResult",
                    "toolCallId": "raw-batch-id",
                    "isError": False,
                    "content": [{"type": "text", "text": "done"}],
                },
            },
        ]
        self.transcript.write_text(
            "\n".join(json.dumps(record) for record in records) + "\n", encoding="utf-8"
        )

        # When: read normalized work events.
        events = project_context.work_events(self.config, str(self.transcript), "pi", self.SID)

        # Then
        self.assertEqual(
            [
                "prepared_dispatch",
                "task_started",
                "task_started",
                "task_result",
                "task_result",
                "task_started",
            ],
            [event["kind"] for event in events],
        )
        self.assertEqual("task-one → shaping", events[0]["title"])
        self.assertEqual("Inspect architecture", events[1]["title"])
        self.assertEqual("Review call returned", events[3]["title"])
        self.assertNotIn("raw-status-id", json.dumps(events))
        self.assertNotIn("preparing", json.dumps(events))

    def test_semantic_layers_keep_work_items_distinct_from_contributors(self) -> None:
        # Given: two contributors share work and one also has a separate request.
        events = [
            {
                "at": 1.0,
                "kind": "steer",
                "title": "Change course",
                "source": "user row",
            },
            {
                "at": 2.0,
                "kind": "prepared_dispatch",
                "title": "workflow-task → shaping",
                "source": "build call",
                "entity": "workflow-task",
                "stage": "shaping",
            },
            {
                "at": 3.0,
                "kind": "task_started",
                "title": "Shared implementation",
                "source": "subagent call",
                "lineage": "call-one:0",
                "work_item_binding": "shared-work",
                "contributor_ref": "worker-a",
            },
            {
                "at": 4.0,
                "kind": "task_started",
                "title": "Shared implementation handoff",
                "source": "subagent call",
                "lineage": "call-two:0",
                "work_item_binding": "shared-work",
                "contributor_ref": "worker-b",
            },
            {
                "at": 5.0,
                "kind": "task_started",
                "title": "One-off investigation",
                "source": "subagent call",
                "lineage": "call-three:0",
                "contributor_ref": "worker-a",
            },
        ]

        # When: build the semantic model.
        model = project_context._semantic_model(events, [])
        shared = next(
            item
            for item in model["work_items"]
            if {"source": "explicit task binding", "value": "shared-work"}
            in item["source_bindings"]
        )
        one_off = next(
            item for item in model["work_items"] if item["label"] == "One-off investigation"
        )
        prepared = next(item for item in model["work_items"] if item["label"] == "workflow-task")
        contributors = {item["source_label"]: item for item in model["contributors"]}

        # Then
        self.assertEqual(
            [
                contributors["worker-a"]["contributor_id"],
                contributors["worker-b"]["contributor_id"],
            ],
            shared["contributor_refs"],
        )
        self.assertEqual("one_off", one_off["kind"])
        self.assertNotIn("head_event", shared)
        self.assertFalse(
            any(
                fact["type"] == "work_birth" and fact["work_item_id"] == prepared["work_item_id"]
                for fact in model["facts"]
            )
        )
        worker_a_links = [
            relation
            for relation in model["relations"]
            if relation["from"] == contributors["worker-a"]["contributor_id"]
            and relation["type"] == "contributes_to"
        ]
        self.assertEqual(2, len(worker_a_links))
        self.assertTrue(all(link["confidence"] == "source-labeled" for link in worker_a_links))
        self.assertEqual("unverified source label", contributors["worker-a"]["identity_status"])
        self.assertEqual([], model["projections"]["steering_episodes"])
        self.assertEqual([], model["projections"]["candidate_goal_shifts"])

    def test_dispatch_topology_is_separate_from_membership_and_counts_attempts(self) -> None:
        # Given: three exact dispatch attempts target the same workflow task.
        common = {
            "kind": "prepared_dispatch",
            "title": "project-cockpit → shaping",
            "source": "exact dispatch artifact",
            "harness": "codex",
            "sid": self.SID,
            "entity": "project-cockpit",
            "stage": "shaping",
            "workflow_binding": "/repo/.spacedock/explore",
        }
        events = [{**common, "at": float(at)} for at in (1, 2, 3)]

        # When: build the semantic model.
        model = project_context._semantic_model(events, [])
        work_item = model["work_items"][0]
        work_item_id = work_item["work_item_id"]
        relations = model["relations"]
        branches = [row for row in relations if row["type"] == "dispatches_to"]
        memberships = [row for row in relations if row["type"] == "binds_to"]

        # Then
        self.assertEqual(3, len(memberships))
        self.assertEqual(3, len(branches))
        self.assertEqual({f"fo:codex:{self.SID}"}, {row["from"] for row in branches})
        self.assertEqual({f"task:{work_item_id}"}, {row["to"] for row in branches})
        self.assertTrue(all(row.get("evidence_ref") for row in branches))
        head = model["projections"]["trail_heads"][0]
        self.assertEqual(3, head["dispatch_count"])

    def test_task_state_fact_not_contributor_supplies_stage(self) -> None:
        # Given: a task has a prepared dispatch and a later stage-transition fact.
        task_id = "workflow:task"

        facts_by_task = {
            task_id: [
                {
                    "fact_id": "dispatch",
                    "at": 1,
                    "type": "prepared_dispatch",
                    "source_kind": "prepared_dispatch",
                },
                {
                    "fact_id": "state",
                    "at": 2,
                    "type": "stage_transition",
                    "source_kind": "child_assignment",
                    "stage": "shaping",
                },
            ]
        }

        # When: derive its trail head.
        heads = project_context._semantic_trail_heads(
            facts_by_task,
            [],
        )

        # Then
        self.assertEqual("shaping", heads[0]["stage"])
        self.assertEqual("state", heads[0]["state_fact"])
        self.assertEqual("current stage", heads[0]["status"])
        self.assertEqual(1, heads[0]["dispatch_count"])

    def test_birth_only_is_requested_history_not_demonstrated_current_work(self) -> None:
        # Given: a historical task-start label claims that the task is done.
        events = [
            {
                "at": 2.0,
                "kind": "task_started",
                "title": "task is DONE",
                "source": "historical subagent call",
                "lineage": "old-call:0",
            }
        ]

        # When: build the semantic model.
        model = project_context._semantic_model(
            events,
            [],
        )

        # Then
        self.assertEqual("requested", model["projections"]["trail_heads"][0]["status"])
        self.assertFalse(
            any(
                head["status"] in {"started", "working"}
                for head in model["projections"]["trail_heads"]
            )
        )

    def test_only_explicitly_eligible_directive_promotes_and_links_a_reaction(self) -> None:
        model = project_context._semantic_model(
            [
                {
                    "at": 1.0,
                    "kind": "steer",
                    "title": "redispatch",
                    "source": "Pi user record",
                    "intent_promotable": False,
                    "harness": "pi",
                    "sid": self.SID,
                    "record_id": "user-redispatch",
                    "parent_id": "previous-assistant",
                    "turn_id": "user-redispatch",
                    "branch_id": "user-redispatch",
                },
                {
                    "at": 2.0,
                    "kind": "task_started",
                    "title": "Fix causal encoder",
                    "source": "Pi subagent task label",
                    "harness": "pi",
                    "sid": self.SID,
                    "lineage": "call-fix:0",
                    "record_id": "assistant-dispatch",
                    "parent_id": "tool-preflight",
                    "turn_id": "user-redispatch",
                    "branch_id": "assistant-preflight",
                },
                {
                    "at": 3.0,
                    "kind": "steer",
                    "title": "and do the comparison at the same time",
                    "source": "Pi user record",
                    "intent_promotable": True,
                    "harness": "pi",
                    "sid": self.SID,
                    "record_id": "user-compare",
                    "parent_id": "assistant-dispatch",
                    "turn_id": "user-compare",
                    "branch_id": "user-compare",
                },
            ],
            [],
            now=3.0,
        )

        intents = model["projections"]["operator_intents"]
        episodes = model["projections"]["steering_episodes"]
        self.assertEqual(
            ["and do the comparison at the same time"],
            [intent["summary"] for intent in intents],
        )
        self.assertEqual([], episodes)
        self.assertEqual(
            [False, True],
            [
                fact["intent_promoted"]
                for fact in sorted(
                    (fact for fact in model["facts"] if fact["type"] == "user_message"),
                    key=lambda fact: fact["at"],
                )
            ],
        )
        self.assertFalse(any(relation["type"] == "elicits" for relation in model["relations"]))

    def test_pi_turn_identity_reaches_a_descendant_subagent_call(self) -> None:
        # Given: the transcript links a user turn through preflight to a descendant call.
        rows = [
            {"type": "session", "id": self.SID, "cwd": str(self.root)},
            {
                "type": "message",
                "id": "user-redispatch",
                "parentId": None,
                "timestamp": "2026-08-24T20:00:00Z",
                "message": {"role": "user", "content": "redispatch"},
            },
            {
                "type": "message",
                "id": "assistant-preflight",
                "parentId": "user-redispatch",
                "timestamp": "2026-08-24T20:00:01Z",
                "message": {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "toolCall",
                            "id": "call-preflight",
                            "name": "bash",
                            "arguments": {"command": "pwd"},
                        }
                    ],
                },
            },
            {
                "type": "message",
                "id": "preflight-result",
                "parentId": "assistant-preflight",
                "timestamp": "2026-08-24T20:00:02Z",
                "message": {
                    "role": "toolResult",
                    "toolCallId": "call-preflight",
                    "content": str(self.root),
                },
            },
            {
                "type": "message",
                "id": "assistant-dispatch",
                "parentId": "preflight-result",
                "timestamp": "2026-08-24T20:00:03Z",
                "message": {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "toolCall",
                            "id": "call-fix",
                            "name": "subagent",
                            "arguments": {"task": "Fix causal encoder"},
                        }
                    ],
                },
            },
        ]
        self.transcript.write_text(
            "\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8"
        )

        instructions = project_context.instruction_events(
            self.config, str(self.transcript), "pi", self.SID
        )

        # When: read the work evidence for that transcript.
        work, _stats = project_context._work_evidence(
            self.config, str(self.transcript), "pi", self.SID
        )

        # Then
        self.assertEqual("user-redispatch", instructions[0]["record_id"])
        started = next(event for event in work if event["kind"] == "task_started")
        self.assertEqual("assistant-dispatch", started["record_id"])
        self.assertEqual("preflight-result", started["parent_id"])
        self.assertEqual("user-redispatch", started["turn_id"])
        self.assertEqual("assistant-preflight", started["branch_id"])

    def test_activity_floor_uses_collection_time_not_newest_work(self) -> None:
        # Given: an unmatched dispatch is older than the current-work horizon.
        events = [
            {
                "at": self.NOW - (42 * 60),
                "kind": "task_started",
                "title": "Stale unmatched ASR dispatch",
                "source": "Pi subagent task label",
                "lineage": "old-call:0",
            }
        ]

        # When: build the semantic model at collection time.
        model = project_context._semantic_model(
            events,
            [],
            now=self.NOW,
        )

        activity = model["projections"]["activity"]

        # Then
        self.assertEqual([], activity["nodes"])
        self.assertEqual(1, activity["historical_unresolved"])
        self.assertEqual(
            self.NOW - project_context.SEMANTIC_CURRENT_HORIZON_SEC, activity["current_after"]
        )

    def test_primary_activity_collapses_dispatch_burst_and_old_retry(self) -> None:
        # Given: old dispatches precede a retry burst and later conversation.
        events = [
            {
                "at": 1.0,
                "kind": "task_started",
                "title": "Fix causal encoder",
                "source": "old task call",
                "harness": "pi",
                "sid": self.SID,
                "lineage": "old-call:0",
            },
            {
                "at": 2.0,
                "kind": "task_started",
                "title": "Historical unrelated request",
                "source": "old task call",
                "harness": "pi",
                "sid": self.SID,
                "lineage": "older-call:0",
            },
        ]
        events.extend(
            {
                "at": 4_500.0,
                "kind": "task_started",
                "title": "Fix causal encoder" if index == 0 else f"Entity {index}",
                "source": "batch task call",
                "harness": "pi",
                "sid": self.SID,
                "lineage": f"batch-call:{index}",
            }
            for index in range(8)
        )
        events.append(
            {
                "at": 5_000.0,
                "kind": "steer",
                "title": "Later conversation must not erase work",
                "source": "user row",
                "intent_promotable": True,
            }
        )

        # When: derive current activity from the semantic model.
        activity = project_context._semantic_model(events, [])["projections"]["activity"]

        # Then
        self.assertEqual(1, len(activity["nodes"]))
        self.assertEqual("burst", activity["nodes"][0]["kind"])
        self.assertEqual(8, activity["nodes"][0]["count"])
        self.assertEqual(1, activity["historical_unresolved"])
        self.assertEqual(2, activity["historical_dispatches"])

    def test_intent_promotion_rejects_output_code_and_path_rows(self) -> None:
        rejected = (
            ", mode, buffering, encoding, errors, newline)",
            'raise RuntimeError("no benchmark samples selected")',
            "find ~/.cache/whisperlivekit/benchmark_data",
            "Saved metadata to /Users/example/long_samples.json",
        )

        for text in rejected:
            with self.subTest(text=text):
                self.assertFalse(project_context._intent_promotable(text, text))
        self.assertTrue(
            project_context._intent_promotable(
                "redispatch the causal bug fix worker",
                "redispatch the causal bug fix worker",
            )
        )

    def test_primary_steering_prefers_directives_to_recent_questions(self) -> None:
        # Given: directives are followed by newer questions and a repeated directive.
        intents = [
            {"at": 1.0, "summary": "before running benchmark, validate model size"},
            {"at": 2.0, "summary": "redispatch the causal bug fix worker"},
            {"at": 2.5, "summary": "please redispatch the causal bug fix worker again"},
            {"at": 3.0, "summary": "how far are we?"},
            {"at": 4.0, "summary": "is this a raw subagent?"},
        ]

        # When: select recent steering nodes.
        steering = project_context._recent_steering_nodes(intents)

        # Then
        self.assertEqual(
            [
                "please redispatch the causal bug fix worker again",
                "before running benchmark, validate model size",
            ],
            [item["summary"] for item in steering],
        )

    def test_primary_steering_keeps_questions_as_evidence_not_diamonds(self) -> None:
        intents = [
            {"at": 1.0, "summary": "how far are we?"},
            {"at": 2.0, "summary": "why is there also audio alignment?"},
            {"at": 3.0, "summary": "where is the attention head shipped?"},
        ]

        steering = project_context._recent_steering_nodes(intents)

        self.assertEqual([], steering)

    def test_exact_dispatch_artifact_binds_spawn_and_result_to_workflow_item(self) -> None:
        # Given: an exact artifact connects prepared dispatch, spawn, and result records.
        artifact = "/tmp/spacedock-dispatch/spacedock-ensign-search-review.md"

        events = [
            {
                "at": 1.0,
                "kind": "prepared_dispatch",
                "title": "search → review",
                "source": "build call",
                "workflow_binding": "/workflow/asr",
                "entity": "search",
                "stage": "",
                "dispatch_artifact": "",
                "dispatch_artifact_prefix": ("/tmp/spacedock-dispatch/spacedock-ensign-search-"),
            },
            {
                "at": 2.0,
                "kind": "task_started",
                "title": f"Read {artifact} and treat its content as your assignment.",
                "source": "Pi subagent task label",
                "lineage": "spawn:0",
                "dispatch_artifact": artifact,
            },
            {
                "at": 3.0,
                "kind": "task_result",
                "title": "Dispatch result returned",
                "source": "Pi subagent paired result",
                "lineage": "spawn:0",
                "dispatch_artifact": artifact,
            },
        ]

        # When: build the semantic model.
        model = project_context._semantic_model(
            events,
            [],
        )

        # Then
        self.assertEqual(1, len(model["work_items"]))
        self.assertEqual("workflow_item", model["work_items"][0]["kind"])
        self.assertEqual("search · review", model["work_items"][0]["label"])
        self.assertEqual("outcome", model["projections"]["trail_heads"][0]["status"])
        summaries = {fact["summary"] for fact in model["facts"]}
        self.assertIn("search · review dispatched", summaries)
        self.assertIn("search · review result returned", summaries)
        self.assertFalse(any("/tmp/spacedock-dispatch" in str(value) for value in summaries))

    def test_dispatch_artifact_binding_rejects_ambiguous_or_similar_labels(self) -> None:
        # Given: two workflows share an artifact and another task has only a similar label.
        artifact = "/tmp/spacedock-dispatch/spacedock-ensign-shared-review.md"
        events = [
            {
                "at": float(index),
                "kind": "prepared_dispatch",
                "title": "shared → review",
                "source": "build call",
                "workflow_binding": f"/workflow/{index}",
                "entity": "shared",
                "stage": "review",
                "dispatch_artifact": artifact,
            }
            for index in (1, 2)
        ]
        events.extend(
            [
                {
                    "at": 3.0,
                    "kind": "task_started",
                    "title": f"Read {artifact}",
                    "source": "subagent call",
                    "lineage": "ambiguous:0",
                    "dispatch_artifact": artifact,
                },
                {
                    "at": 4.0,
                    "kind": "task_started",
                    "title": "Review shared task",
                    "source": "subagent call",
                    "lineage": "similar-only:0",
                },
            ]
        )

        # When: build the semantic model.
        model = project_context._semantic_model(events, [])

        # Then
        self.assertEqual(4, len(model["work_items"]))
        self.assertEqual(1, sum(item["kind"] == "one_off" for item in model["work_items"]))

    def test_async_dispatch_ack_is_birth_only_and_artifact_supplies_identity(self) -> None:
        artifact = "/tmp/spacedock-dispatch/spacedock-ensign-search-review.md"
        events = project_context._subagent_events(
            {"task": f"Read {artifact} and treat its content as your assignment."},
            call_key="chatcmpl-tool-b27704648c9029bc",
            at=2.0,
            result={
                "succeeded": True,
                "at": 3.0,
                "text": "Async: worker [...] The async run is detached and running in the background.",
            },
            harness="pi",
            sid=self.SID,
        )

        self.assertEqual(["task_started"], [event["kind"] for event in events])
        model = project_context._semantic_model(events, [])
        work_item = model["work_items"][0]
        self.assertEqual("workflow_item", work_item["kind"])
        self.assertEqual("search · review", work_item["label"])
        self.assertIn(
            {"source": "structured Spacedock dispatch artifact", "value": artifact},
            work_item["source_bindings"],
        )
        self.assertEqual("requested", model["projections"]["trail_heads"][0]["status"])
        self.assertFalse(any(fact["type"] == "work_result" for fact in model["facts"]))

    @unittest.skipUnless(
        hasattr(os, "O_NOFOLLOW") and hasattr(os, "getuid"), "requires POSIX file ownership"
    )
    def test_dispatch_artifact_title_supplies_assignment_without_claiming_result(self) -> None:
        directory = self.root / "spacedock-dispatch"
        directory.mkdir(mode=0o700)
        artifact = directory / "spacedock-ensign-search-review.md"
        artifact.write_text(
            "You are working on: Review the search release evidence\nStage: review\n",
            encoding="utf-8",
        )
        artifact.chmod(0o600)
        with mock.patch.dict(os.environ, {"XDG_RUNTIME_DIR": str(self.root)}):
            assignment = project_context._dispatch_file_assignment(str(artifact))

        self.assertEqual("Review the search release evidence", assignment)
        self.assertEqual("", project_context._dispatch_file_assignment("/tmp/unrelated.md"))

    def test_codex_backfill_keeps_exact_spacedock_spawn_and_omits_followup(self) -> None:
        rows = [
            {
                "timestamp": "2027-01-15T08:00:00Z",
                "type": "response_item",
                "payload": {
                    "type": "function_call",
                    "id": "spawn-call",
                    "name": "spawn_agent",
                    "arguments": json.dumps(
                        {"task_name": "spacedock_ensign_project_cockpit_shaping_cycle2"}
                    ),
                },
            },
            {
                "timestamp": "2027-01-15T08:01:00Z",
                "type": "response_item",
                "payload": {
                    "type": "function_call",
                    "id": "follow-call",
                    "name": "followup_task",
                    "arguments": json.dumps(
                        {"target": "/root/spacedock_ensign_project_cockpit_shaping_cycle2"}
                    ),
                },
            },
        ]
        self.transcript.write_text(
            "\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8"
        )
        artifact = "/tmp/spacedock-dispatch/spacedock-ensign-project-cockpit-shaping.md"
        with (
            mock.patch.object(
                project_context,
                "_codex_dispatch_artifact",
                return_value=(artifact, "/repo/.spacedock/explore", "project-cockpit", "shaping"),
            ),
            mock.patch.object(
                project_context,
                "_dispatch_file_assignment",
                return_value="Project cockpit and remembered goal",
            ),
        ):
            events = project_context.codex_dispatch_events(
                self.config,
                str(self.transcript),
                "codex",
                self.SID,
                since=1_800_000_000.0 - project_context.SEMANTIC_HISTORY_HORIZON_SEC,
            )

        self.assertEqual(1, len(events))
        self.assertEqual("prepared_dispatch", events[0]["kind"])
        self.assertEqual("spawn-call", events[0]["record_id"])
        self.assertEqual("/repo/.spacedock/explore", events[0]["workflow_binding"])
        model = project_context._semantic_model(events, [])
        self.assertEqual("binds_to", model["relations"][0]["type"])

    def test_active_child_assignment_uses_refreshable_snapshot_or_unavailable(self) -> None:
        session = {
            "subagent_hierarchy": [
                {
                    "name": "Volta",
                    "depth": 1,
                    "parent_name": None,
                    "observer_sid": "child-thread",
                    "assignment": None,
                    "assignment_status": "unavailable",
                    "workflow_entity": "project-cockpit",
                    "workflow_stage": "shaping",
                    "workflow_binding": "/repo/.spacedock/explore",
                }
            ]
        }
        with (
            mock.patch.object(observer, "resolve_transcript", return_value="/tmp/child.jsonl"),
            mock.patch.object(
                project_context,
                "_observe_session",
                return_value={
                    "goal": "Improve the assignment roster",
                    "observed_at": 12.0,
                    "snapshot_status": "refreshed",
                },
            ) as observe,
        ):
            refreshed = project_context._active_child_assignments(
                self.config,
                mock.Mock(),
                session,
                now=self.NOW,
                refresh=True,
            )

        self.assertEqual("Improve the assignment roster", refreshed[0]["assignment"])
        self.assertEqual("derived", refreshed[0]["confidence"])
        self.assertEqual("project-cockpit", refreshed[0]["workflow_entity"])
        self.assertEqual("shaping", refreshed[0]["workflow_stage"])
        self.assertEqual("/repo/.spacedock/explore", refreshed[0]["workflow_binding"])
        self.assertEqual(
            semantic_history.workflow_work_item_id("/repo/.spacedock/explore", "project-cockpit"),
            refreshed[0]["work_item_id"],
        )
        self.assertTrue(observe.call_args.kwargs["refresh"])

        with (
            mock.patch.object(observer, "resolve_transcript", return_value="/tmp/child.jsonl"),
            mock.patch.object(
                project_context,
                "_observe_session",
                return_value={
                    "goal": "Earlier assignment",
                    "observed_at": 10.0,
                    "snapshot_status": "cached-stale",
                },
            ),
        ):
            stale = project_context._active_child_assignments(
                self.config,
                mock.Mock(),
                session,
                now=self.NOW,
                refresh=False,
            )
        self.assertEqual("cached-stale", stale[0]["snapshot_status"])

        with mock.patch.object(observer, "resolve_transcript", return_value=None):
            unavailable = project_context._active_child_assignments(
                self.config,
                mock.Mock(),
                session,
                now=self.NOW,
                refresh=False,
            )
        self.assertIsNone(unavailable[0]["assignment"])
        self.assertEqual("unavailable", unavailable[0]["confidence"])

    def test_subagent_result_category_uses_directive_and_rejects_unavailable_review(self) -> None:
        succeeded = {"succeeded": True, "text": "A substantive result was returned."}
        substantive_review = {
            "succeeded": True,
            "text": "Review changed the course:\n- Preserve the exact project boundary.",
        }
        empty_review = {"succeeded": True, "text": ""}
        contributor_count_only = {"succeeded": True, "text": "Children: 2 completed."}
        unavailable = {
            "succeeded": True,
            "text": "Acceptance cannot be requested explicitly; no reviewer result was supplied.",
        }

        self.assertEqual(
            "Implementation pass completed",
            project_context._subagent_result_title(
                ["Implement the reviewed design after reading its corrections."], succeeded
            ),
        )
        self.assertEqual(
            "Review call returned",
            project_context._subagent_result_title(
                ["Review the implementation for correctness."], succeeded
            ),
        )
        self.assertEqual(
            "Review call returned",
            project_context._subagent_result_title(
                ["Review the implementation for correctness."], empty_review
            ),
        )
        self.assertEqual(
            "Review call returned",
            project_context._subagent_result_title(
                ["Review the implementation for correctness."], contributor_count_only
            ),
        )
        self.assertEqual(
            "Implementation review completed",
            project_context._subagent_result_title(
                ["Review the implementation for correctness."], substantive_review
            ),
        )
        self.assertEqual(
            "",
            project_context._subagent_result_title(
                ["Review the implementation for correctness."], unavailable
            ),
        )

    def test_only_context_sufficient_user_rows_become_intent_projections(self) -> None:
        rows = [
            ("do it", False),
            ("why do we need that?", False),
            ("Error: command returned an internal failure\nraw stack row", False),
            (".venv/bin/python scripts/check.py --verbose", False),
            ("Keep the selected project as the context boundary.", True),
        ]
        events = []
        for index, (text, expected) in enumerate(rows):
            event = project_context._instruction_event(
                self.config,
                codex_message(text, f"2026-08-24T20:1{index}:00Z"),
                "codex",
                self.SID,
            )
            self.assertIsNotNone(event)
            assert event is not None
            self.assertIs(expected, event["intent_promotable"])
            events.append(event)

        model = project_context._semantic_model(events, [])

        self.assertEqual(
            5, len([fact for fact in model["facts"] if fact["type"] == "user_message"])
        )
        self.assertEqual(1, len(model["projections"]["operator_intents"]))
        self.assertEqual(
            "Keep the selected project as the context boundary.",
            model["projections"]["operator_intents"][0]["summary"],
        )

    def test_persisted_intent_flag_survives_restart_without_promoting_envelopes(self) -> None:
        # Given: human, rejected, and collaboration facts have been persisted.
        human = {
            "at": 10.0,
            "kind": "steer",
            "title": "Keep exact workflow identity in the focused view.",
            "source": "timestamped non-meta user-role record",
            "harness": "codex",
            "sid": self.SID,
            "intent_promotable": True,
        }
        rejected = {
            "at": 11.0,
            "kind": "steer",
            "title": "do it",
            "source": "timestamped non-meta user-role record",
            "harness": "codex",
            "sid": self.SID,
            "intent_promotable": False,
        }
        collaboration = {
            "at": 12.0,
            "kind": "steer",
            "title": (
                "Message Type: MESSAGE Task name: /root/worker Sender: /root Payload: keep working"
            ),
            "source": "Codex injected agent_message collaboration envelope",
            "harness": "codex",
            "sid": self.SID,
            "intent_promotable": False,
        }
        state = build_runtime_state(self.config, started=1)
        model = project_context._semantic_model([human, rejected, collaboration], [])
        persisted = semantic_history.update(
            self.config,
            state,
            "git:project",
            model,
            [],
            now=20.0,
        )

        # When: reload and merge history into an empty semantic model.
        replay = project_context._merge_semantic_history(
            project_context._semantic_model([], []),
            semantic_history.read(
                self.config, build_runtime_state(self.config, started=2), "git:project"
            ),
            now=20.0,
        )

        # Then
        self.assertTrue(persisted["persisted"])
        self.assertEqual(3, len(replay["facts"]))
        self.assertEqual(
            ["Keep exact workflow identity in the focused view."],
            [row["summary"] for row in replay["projections"]["operator_intents"]],
        )
        by_summary = {fact["summary"]: fact for fact in replay["facts"]}
        self.assertFalse(by_summary["do it"]["intent_promoted"])
        self.assertFalse(by_summary[collaboration["title"]]["intent_promoted"])

    def test_semantic_ids_include_workflow_and_survive_order_changes(self) -> None:
        # Given: a model contains two workflows with the same entity slug.
        first = {
            "at": 2.0,
            "kind": "gate",
            "title": "shared · review · approve",
            "source": "entity record",
            "workflow_binding": "/workflows/one",
            "entity": "shared",
            "decision": "approve",
        }
        second = {
            "at": 3.0,
            "kind": "gate",
            "title": "shared · review · revise",
            "source": "entity record",
            "workflow_binding": "/workflows/two",
            "entity": "shared",
            "decision": "revise",
        }
        model = project_context._semantic_model([first, second], [])

        # When: rebuild after reordering the gates and adding an earlier steer.
        reordered = project_context._semantic_model(
            [second, {"at": 1.0, "kind": "steer", "title": "Earlier", "source": "row"}, first],
            [],
        )

        # Then
        self.assertEqual(2, len(model["work_items"]))
        self.assertTrue(all(fact["scope"] == "project" for fact in model["facts"]))
        fact_ids = {fact["fact_id"] for fact in model["facts"]}
        reordered_ids = {fact["fact_id"] for fact in reordered["facts"]}
        self.assertTrue(fact_ids.issubset(reordered_ids))
        node_ids = fact_ids | {item["work_item_id"] for item in model["work_items"]}
        node_ids |= {item["contributor_id"] for item in model["contributors"]}
        projections = model["projections"]
        node_ids |= {item["projection_id"] for item in projections["operator_intents"]}
        self.assertTrue(
            all(
                relation["from"] in node_ids and relation["to"] in node_ids
                for relation in model["relations"]
            )
        )

    def test_two_records_that_say_the_same_thing_at_the_same_moment_are_two_facts(self) -> None:
        """DRC-4544 item 2: a fact id must be as unique as the record behind it.

        `_dedupe_project_events` keeps two events that differ only in
        `record_id`, so both are real. Hashed without it they shared one
        `fact_id`; the ledger then emitted two rows under one citation handle
        and the page's `Map` kept whichever came last.
        """
        base = {
            "at": 5.0,
            "kind": "steer",
            "title": "Ship it",
            "source": "row",
            "harness": "claude",
            "sid": "s1",
        }
        first = {**base, "record_id": "rec-a"}
        second = {**base, "record_id": "rec-b"}
        self.assertEqual(2, len(project_context._dedupe_project_events([first, second])))

        model = project_context._semantic_model([first, second], [])

        self.assertEqual(2, len(model["facts"]))
        self.assertEqual(2, len({fact["fact_id"] for fact in model["facts"]}))

    def test_a_fact_with_no_record_behind_it_keeps_the_id_it_had(self) -> None:
        """The other half of item 2: only record-bearing ids move.

        Stored citations and departure evidence name these ids, so an id that
        moves demotes a stored departure to UNCITED on the page. The literal
        was measured at 08c07ad before `record_id` joined the hash; adding it
        unconditionally (`str(None)`) moves this id too, and this test says so.
        """
        event = {
            "at": 5.0,
            "kind": "steer",
            "title": "Ship it",
            "source": "row",
            "harness": "claude",
            "sid": "s1",
        }
        model = project_context._semantic_model([event], [])
        self.assertEqual(["fact:6e475aaa4bbb3580"], [fact["fact_id"] for fact in model["facts"]])

    def test_transcript_facts_keep_source_session_without_branch_records(self) -> None:
        # Given: a Codex user fact has exact session identity but no branch records.
        events = [
            {
                "at": 2.0,
                "kind": "steer",
                "title": "Keep the selected project as the context boundary.",
                "source": "Codex user message",
                "harness": "codex",
                "sid": "codex-root",
                "intent_promotable": True,
            }
        ]

        # When: build the semantic model.
        model = project_context._semantic_model(
            events,
            [],
        )

        fact = model["facts"][0]

        # Then
        self.assertEqual({"harness": "codex", "sid": "codex-root"}, fact["source_session"])
        self.assertNotIn("branch", fact)

    def test_gate_metadata_credentials_never_reach_semantic_publication(self) -> None:
        # Given: each gate metadata field contains a synthetic credential in turn.
        secret = "sk-ant-api03-" + "a" * 93
        for field in ("stage", "decision", "target-stage", "by", "state"):
            with self.subTest(field=field):
                values = {
                    "stage": "review",
                    "decision": "approve",
                    "target-stage": "shaping",
                    "by": "person:captain",
                    "state": "consumed",
                }
                values[field] = secret
                lines = [
                    "id: gate-entity",
                    "title: Synthetic gate",
                    "- id: gate:review",
                    f"  stage: {values['stage']}",
                    "  resolution:",
                    "    at: 1970-01-01T00:01:40Z",
                    f"    decision: {values['decision']}",
                    f"    by: {values['by']}",
                    "  application:",
                    f"    state: {values['state']}",
                    f"    target-stage: {values['target-stage']}",
                ]

                # When: parse the gate and build its semantic publication.
                events, _ = project_context.gate_events(
                    self.config, lines, "synthetic", "/workflow", "codex", self.SID
                )
                model = project_context._semantic_model(events, [], now=105)

                # Then
                self.assertEqual(1, len(model["facts"]))
                self.assertNotIn(secret, json.dumps(events))
                self.assertNotIn(secret, json.dumps(model))

    def test_gate_facts_are_project_scoped_without_invented_session_origin(self) -> None:
        lines = [
            "id: abcdefghjkmnpqrstvwxyz23",
            "title: Project cockpit",
            "- id: gate:review",
            "  stage: review",
            "  resolution:",
            "    at: 2026-08-24T20:10:00Z",
            "    decision: approve",
            "    by: person:captain",
            "  application:",
            "    state: applied",
            "    target-stage: shaping",
        ]
        events, _briefings = project_context.gate_events(
            self.config,
            lines,
            "project-cockpit",
            "explore",
            "codex",
            self.SID,
            workflow_binding="/repo/.spacedock/explore",
        )
        fact = project_context._semantic_model(events, [])["facts"][0]

        self.assertEqual("project", fact["scope"])
        self.assertEqual("person:captain", fact["by"])
        self.assertEqual("shaping", fact["target_stage"])
        self.assertEqual("applied", fact["application_state"])
        self.assertEqual("review", fact["stage"])
        self.assertEqual("abcdefghjk", fact["workflow_entity"])
        self.assertNotIn("source_session", fact)
        self.assertNotIn("harness", events[0])
        self.assertNotIn("sid", events[0])

        dispatch = {
            "at": 3.0,
            "kind": "prepared_dispatch",
            "title": "Project cockpit",
            "source": "structured dispatch artifact",
            "workflow_binding": "/repo/.spacedock/explore",
            "entity": "abcdefghjk",
            "stage": "shaping",
        }
        combined = project_context._semantic_model([*events, dispatch], [])
        self.assertEqual(1, len(combined["work_items"]))
        self.assertEqual("Project cockpit", combined["work_items"][0]["label"])

    def test_exact_gate_entity_binds_artifact_only_start_to_canonical_title(self) -> None:
        # Given: a gate and artifact-only start refer to the same exact entity.
        gate = {
            "at": 1.0,
            "kind": "gate",
            "title": "task-slug · ideation · approve",
            "source": "entity gate",
            "workflow_binding": "/repo/docs/dev",
            "entity": "abcdefghjk",
            "entity_slug": "task-slug",
            "entity_title": "Human task title",
            "stage": "ideation",
            "decision": "approve",
            "by": "person:captain",
            "target_stage": "implementation",
        }
        started = {
            "at": 2.0,
            "kind": "task_started",
            "title": "started",
            "source": "subagent call",
            "harness": "pi",
            "sid": self.SID,
            "dispatch_artifact": "/tmp/spacedock-dispatch/spacedock-ensign-abcdefghjk-implementation.md",
        }

        # When: build the semantic model.
        model = project_context._semantic_model([gate, started], [])

        # Then
        self.assertEqual(1, len(model["work_items"]))
        self.assertEqual("Human task title", model["work_items"][0]["label"])
        self.assertEqual(
            {model["work_items"][0]["work_item_id"]},
            {fact["work_item_id"] for fact in model["facts"]},
        )

    def test_focused_history_keeps_exact_session_and_project_facts_only(self) -> None:
        # Given: history contains the selected session, a peer, and a project fact.
        history = {
            "events": [
                {
                    "event_id": "codex",
                    "fact": {
                        "fact_id": "codex",
                        "scope": "session",
                        "source_session": {"harness": "codex", "sid": "root"},
                    },
                },
                {
                    "event_id": "pi",
                    "fact": {
                        "fact_id": "pi",
                        "scope": "session",
                        "source_session": {"harness": "pi", "sid": "other"},
                    },
                },
                {
                    "event_id": "gate",
                    "fact": {"fact_id": "gate", "scope": "project"},
                },
            ],
            "cursors": {"codex:root": {}, "pi:other": {}},
        }

        # When: filter history to the exact session and bound work.
        focused = project_context._focused_semantic_history(
            history,
            ("codex", "root"),
            {"workflow:kept"},
        )

        # Then
        self.assertEqual(["codex", "gate"], [row["event_id"] for row in focused["events"]])
        self.assertEqual(history["cursors"], focused["cursors"])

    def test_focused_history_excludes_unrelated_project_gate(self) -> None:
        # Given: project gates belong to selected and unrelated work items.
        history = {
            "events": [
                {
                    "event_id": "kept",
                    "fact": {
                        "fact_id": "kept",
                        "scope": "project",
                        "type": "gate_decision",
                        "work_item_id": "workflow:kept",
                    },
                },
                {
                    "event_id": "peer",
                    "fact": {
                        "fact_id": "peer",
                        "scope": "project",
                        "type": "gate_decision",
                        "work_item_id": "workflow:peer",
                    },
                },
            ]
        }

        # When: filter history to the selected work binding.
        focused = project_context._focused_semantic_history(
            history,
            ("codex", "root"),
            {"workflow:kept"},
        )

        # Then
        self.assertEqual(["kept"], [row["event_id"] for row in focused["events"]])

    def test_focused_semantic_graph_keeps_exact_owner_children_and_bound_project_facts(
        self,
    ) -> None:
        # Given: the semantic graph contains a root, its exact child, and peer work.
        root = {"harness": "codex", "sid": self.SID}
        child = {"harness": "codex", "sid": "child-thread"}
        peer = {"harness": "pi", "sid": "peer-thread"}
        root_work = "workflow:root"
        peer_work = "workflow:peer"
        semantic = {
            "facts": [
                {
                    "fact_id": "root-direction",
                    "type": "user_message",
                    "scope": "session",
                    "source_session": root,
                    "work_item_id": None,
                    "at": 5.0,
                },
                {
                    "fact_id": "child-result",
                    "type": "work_result",
                    "scope": "session",
                    "source_session": child,
                    "work_item_id": root_work,
                    "at": 4.0,
                },
                {
                    "fact_id": "root-gate",
                    "type": "gate_decision",
                    "scope": "project",
                    "work_item_id": root_work,
                    "at": 3.0,
                },
                {
                    "fact_id": "peer-direction",
                    "type": "user_message",
                    "scope": "session",
                    "source_session": peer,
                    "work_item_id": peer_work,
                    "at": 2.0,
                },
                {
                    "fact_id": "peer-gate",
                    "type": "gate_decision",
                    "scope": "project",
                    "work_item_id": peer_work,
                    "at": 1.0,
                },
            ],
            "work_items": [
                {"work_item_id": root_work, "label": "root"},
                {"work_item_id": peer_work, "label": "peer"},
            ],
            "contributors": [],
            "relations": [],
            "projections": {
                "operator_intents": [
                    {"projection_id": "intent-root", "derived_from": "root-direction"},
                    {"projection_id": "intent-peer", "derived_from": "peer-direction"},
                ],
                "trail_heads": [],
                "assignments": [],
                "activity": {"nodes": [], "history_nodes": [], "steering": []},
                "steering_episodes": [],
            },
            "history": {"events": []},
        }

        # When: focus the graph on the root and its child binding.
        focused = project_context._focused_semantic_graph(
            semantic,
            ("codex", self.SID),
            [
                {
                    "observer_sid": "child-thread",
                    "confidence": "exact",
                    "work_item_id": root_work,
                    "parent_session": root,
                }
            ],
            now=6.0,
        )

        # Then
        self.assertEqual(
            {"root-direction", "child-result", "root-gate"},
            {row["fact_id"] for row in focused["facts"]},
        )
        self.assertEqual([root_work], [row["work_item_id"] for row in focused["work_items"]])
        self.assertEqual(
            ["intent-root"],
            [row["projection_id"] for row in focused["projections"]["operator_intents"]],
        )

    def test_command_attention_keeps_exact_authorization_open_until_direct_resolution(
        self,
    ) -> None:
        request = {
            "fact_id": "request",
            "at": 10.0,
            "type": "result",
            "work_item_id": "workflow:task",
            "source_session": {"harness": "codex", "sid": "root"},
            "authorization_request": {
                "kind": "push_pr",
                "question": "Approve pushing this candidate and creating the PR?",
                "status": "open",
            },
            "evidence": {"source": "assistant final_answer", "confidence": "exact"},
        }
        semantic: dict[str, Any] = {
            "facts": [request],
            "work_items": [{"work_item_id": "workflow:task", "label": "Completion guard"}],
            "projections": {},
        }

        open_projection = project_context._command_attention_projection(semantic)
        self.assertEqual("CAPTAIN", open_projection[0]["owner"])
        self.assertEqual("push_pr", open_projection[0]["kind"])
        self.assertEqual("exact", open_projection[0]["evidence"]["confidence"])

        semantic["facts"].insert(
            0,
            {
                "fact_id": "answer",
                "at": 11.0,
                "type": "user_message",
                "summary": "I authorize pushing this candidate and creating the PR.",
                "source_session": {"harness": "codex", "sid": "root"},
                "evidence": {"source": "captain message", "confidence": "exact"},
            },
        )
        self.assertEqual([], project_context._command_attention_projection(semantic))

    def test_bound_result_makes_one_task_returned_not_simultaneously_unreturned(self) -> None:
        # Given: a prepared dispatch has a later result on the same work item.
        work_item_id = "workflow:task"
        dispatch = {
            "fact_id": "dispatch",
            "at": 10.0,
            "type": "prepared_dispatch",
            "source_kind": "prepared_dispatch",
            "work_item_id": work_item_id,
        }
        result = {
            "fact_id": "result",
            "at": 11.0,
            "type": "result",
            "work_item_id": work_item_id,
        }

        # When: derive the trail heads.
        trails = project_context._semantic_trail_heads(
            {work_item_id: [dispatch, result]}, [dispatch, result]
        )

        # Then
        self.assertEqual(1, len(trails))
        self.assertEqual("returned", trails[0]["status"])
        self.assertEqual("result", trails[0]["latest_meaningful_event"])

    def test_focused_gates_require_exact_current_child_or_persisted_identity(self) -> None:
        # Given: gates have current, child, persisted, peer, and cross-workflow identities.
        workflow = "/repo/docs/dev"

        def gate(entity: str, slug: str, binding: str = workflow) -> dict[str, str]:
            return {
                "kind": "gate",
                "workflow": Path(binding).name,
                "workflow_binding": binding,
                "entity": entity,
                "entity_slug": slug,
            }

        transcript = [
            {
                "kind": "prepared_dispatch",
                "workflow_binding": workflow,
                "entity": "session-id",
            },
            {
                "kind": "prepared_dispatch",
                "workflow_binding": workflow,
                "entity": "shared-slug",
            },
        ]
        children = [{"work_item_id": semantic_history.workflow_work_item_id(workflow, "child-id")}]
        persisted = {
            "events": [
                {
                    "fact": {
                        "scope": "session",
                        "source_session": {"harness": "codex", "sid": "root"},
                        "work_item_id": semantic_history.workflow_work_item_id(
                            workflow, "persisted-id"
                        ),
                        "workflow_binding": workflow,
                        "workflow_entity": "persisted-id",
                    }
                },
                {
                    "fact": {
                        "scope": "session",
                        "source_session": {"harness": "codex", "sid": "peer"},
                        "work_item_id": semantic_history.workflow_work_item_id(workflow, "peer-id"),
                        "workflow_binding": workflow,
                        "workflow_entity": "peer-id",
                    }
                },
            ]
        }
        gates = [
            gate("session-id", "session-slug"),
            gate("child-id", "child-slug"),
            gate("persisted-id", "persisted-slug"),
            gate("peer-id", "peer-slug"),
            gate("dev-alias-id", "shared-slug"),
            gate("explore-alias-id", "shared-slug", "/repo/docs/explore"),
        ]

        # When: select gates for the exact focused session.
        kept, work_items = project_context._focused_gate_events(
            transcript,
            gates,
            children,
            persisted,
            ("codex", "root"),
        )

        # Then
        self.assertEqual(
            ["session-id", "child-id", "persisted-id", "dev-alias-id"],
            [row["entity"] for row in kept],
        )
        self.assertNotIn(
            semantic_history.workflow_work_item_id(workflow, "peer-id"),
            work_items,
        )

    def test_focused_gate_context_reads_project_peer_without_foreign_transcript_facts(self) -> None:
        # Given: a project peer exposes a gate through its transcript context.
        focused = {
            "harness": "codex",
            "sid": "root",
            "project_key": "git:project",
            "active": True,
        }
        peer = {
            "harness": "claude",
            "sid": "peer",
            "project_key": "git:project",
            "active": True,
        }
        gate = {"kind": "gate", "scope": "project", "title": "task · review · approve"}
        with (
            mock.patch.object(observer, "resolve_transcript", return_value="/tmp/peer.jsonl"),
            mock.patch.object(project_context, "_gate_context", return_value=([gate], 2)) as read,
        ):
            # When: read peer gate context for the focused root.
            rows, briefings = project_context._project_peer_gate_context(
                self.config,
                mock.Mock(),
                [focused, peer],
                "git:project",
                ("codex", "root"),
            )

        # Then
        self.assertEqual([gate], rows)
        self.assertEqual(2, briefings)
        read.assert_called_once_with(self.config, mock.ANY, "/tmp/peer.jsonl", "claude", "peer")

    def test_environment_context_is_not_steering(self) -> None:
        # Given: the user record contains an environment-context envelope.
        record = codex_message(
            "<environment_context>\n  <cwd>/private/project</cwd>\n</environment_context>",
            "2026-08-24T20:10:00Z",
        )

        # When: attempt to extract an instruction event.
        event = project_context._instruction_event(
            self.config,
            record,
            "codex",
            self.SID,
        )

        # Then
        self.assertIsNone(event)

    def test_codex_function_output_can_supply_boot_provenance(self) -> None:
        envelope = (
            '{"command":"boot","id_style":"slug",'
            '"definition_dir":"/w/one","entity_dir":"/w/one",'
            '"dispatchable":[]}'
        )
        record = json.dumps(
            {
                "type": "response_item",
                "payload": {
                    "type": "function_call_output",
                    "output": "=== BOOT ===\n" + envelope,
                },
            }
        ).encode()
        pasted = json.dumps(codex_message(envelope, "2026-08-24T20:10:00Z")).encode()

        self.assertEqual(1, len(spacedock.boot_records(self.config, record)))
        self.assertEqual([], spacedock.boot_records(self.config, pasted))

    def test_codex_custom_output_blocks_can_supply_boot_provenance(self) -> None:
        envelope = (
            '{"command":"boot","id_style":"slug",'
            '"definition_dir":"/w/one","entity_dir":"/w/one",'
            '"dispatchable":[]}'
        )
        record = json.dumps(
            {
                "type": "response_item",
                "payload": {
                    "type": "custom_tool_call_output",
                    "output": [{"type": "input_text", "text": "=== BOOT ===\n" + envelope}],
                },
            }
        ).encode()

        self.assertEqual(1, len(spacedock.boot_records(self.config, record)))

    def test_a_cached_goal_says_which_arm_wrote_it_and_never_guesses(self) -> None:
        """A sidecar written before goal provenance existed reads back as
        unknown, not as the harness talking.

        The cached branch published `goal` with no source at all, so a model
        paraphrase and a transcript line were one indistinguishable string.
        Defaulting the missing field to "deterministic" would be worse than
        omitting it: it relabels every already-cached model goal as something a
        source published, which is the substitution DRC-4509 forbids.
        """
        state = build_runtime_state(self.config, started=self.NOW)
        identity = ("pi", "cached-provenance")

        # A sidecar from before the field existed.
        observer.write_sidecar(
            self.config,
            *identity,
            {"goal": "Ship the cockpit", "observed_at": 10.0, "transcript": "sig"},
        )
        legacy = project_context._observe_session(
            self.config, state, str(self.transcript), identity, now=self.NOW, refresh=False
        )
        assert legacy is not None
        self.assertEqual("unknown", legacy["goal_source"])

        # A sidecar that recorded the model arm keeps that attribution, and the
        # deterministic line it displaced stays reachable beside it.
        observer.write_sidecar(
            self.config,
            *identity,
            {
                "goal": "Ship the cockpit, reworded",
                "deterministic_goal": "Ship the cockpit",
                "goal_source": "model",
                "observed_at": 11.0,
                "transcript": "sig",
            },
        )
        remembered = project_context._observe_session(
            self.config, state, str(self.transcript), identity, now=self.NOW, refresh=False
        )
        assert remembered is not None
        self.assertEqual("model", remembered["goal_source"])
        self.assertEqual("Ship the cockpit", remembered["deterministic_goal"])


@unittest.skipUnless(
    hasattr(os, "O_NOFOLLOW") and hasattr(os, "getuid"), "requires POSIX file ownership"
)
class DispatchSecurityTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.directory = self.root / "spacedock-dispatch"
        self.directory.mkdir(mode=0o700)
        self.artifact = self.directory / "spacedock-ensign-test-review.md"
        self.artifact.write_text("You are working on: Safe assignment\n", encoding="utf-8")
        self.artifact.chmod(0o600)
        patch = mock.patch.dict(os.environ, {"XDG_RUNTIME_DIR": str(self.root)})
        patch.start()
        self.addCleanup(patch.stop)

    def test_private_runtime_directory_is_preferred_and_readable(self) -> None:
        self.assertEqual(
            "Safe assignment", project_context._dispatch_file_assignment(str(self.artifact))
        )
        self.assertEqual(str(self.artifact), project_context._dispatch_artifact(str(self.artifact)))

    def test_real_symlink_cannot_redirect_the_read(self) -> None:
        target = self.root / "private.md"
        self.artifact.replace(target)
        self.artifact.symlink_to(target)
        self.assertTrue(self.artifact.is_symlink())
        self.assertEqual("", project_context._dispatch_file_assignment(str(self.artifact)))

    def test_symlinked_dispatch_directory_is_refused(self) -> None:
        target = self.root / "elsewhere"
        self.directory.rename(target)
        self.directory.symlink_to(target, target_is_directory=True)
        self.assertEqual("", project_context._dispatch_file_assignment(str(self.artifact)))

    def test_group_and_world_writable_files_are_refused(self) -> None:
        for mode in (0o620, 0o602, 0o666):
            with self.subTest(mode=mode):
                self.artifact.chmod(mode)
                self.assertEqual("", project_context._dispatch_file_assignment(str(self.artifact)))

    def test_wrong_uid_is_refused(self) -> None:
        fstat = os.fstat

        def foreign_file(descriptor: int) -> os.stat_result:
            info = fstat(descriptor)
            if stat.S_ISREG(info.st_mode):
                fields = list(info)
                fields[4] = os.getuid() + 1
                return os.stat_result(fields)
            return info

        with mock.patch.object(os, "fstat", side_effect=foreign_file):
            self.assertEqual("", project_context._dispatch_file_assignment(str(self.artifact)))

    def test_symlink_inside_directory_is_refused_by_no_follow(self) -> None:
        target = self.directory / "another.md"
        self.artifact.replace(target)
        self.artifact.symlink_to(target)
        self.assertEqual(self.directory.resolve(), self.artifact.resolve().parent)
        self.assertEqual("", project_context._dispatch_file_assignment(str(self.artifact)))

    def test_symlink_swap_after_realpath_is_refused(self) -> None:
        target = self.directory / "another.md"
        target.write_text("You are working on: Planted title\n", encoding="utf-8")
        target.chmod(0o600)
        open_file = os.open

        def swap(path: Any, flags: int, *args: Any, **kwargs: Any) -> int:
            if path == self.artifact.name:
                self.artifact.unlink()
                self.artifact.symlink_to(target)
            return open_file(path, flags, *args, **kwargs)

        with mock.patch.object(os, "open", side_effect=swap):
            self.assertEqual("", project_context._dispatch_file_assignment(str(self.artifact)))
        self.assertTrue(self.artifact.is_symlink())

    def test_checked_fallback_works_without_xdg_runtime_directory(self) -> None:
        with (
            mock.patch.dict(os.environ, {"XDG_RUNTIME_DIR": ""}),
            mock.patch.object(project_context, "_DISPATCH_DIRECTORY", str(self.directory)),
        ):
            self.assertEqual(
                "Safe assignment", project_context._dispatch_file_assignment(str(self.artifact))
            )
            self.artifact.chmod(0o666)
            self.assertEqual("", project_context._dispatch_file_assignment(str(self.artifact)))

    def test_growth_after_stat_cannot_exceed_read_cap(self) -> None:
        with self.artifact.open("a", encoding="utf-8") as handle:
            handle.write("x" * 65536)
        fstat = os.fstat

        def small_stat(descriptor: int) -> os.stat_result:
            info = fstat(descriptor)
            fields = list(info)
            fields[6] = 20
            return os.stat_result(fields)

        with mock.patch.object(os, "fstat", side_effect=small_stat):
            self.assertEqual("", project_context._dispatch_file_assignment(str(self.artifact)))

    def test_realpath_escape_is_refused_before_open(self) -> None:
        realpath = os.path.realpath

        def resolve(path: Any) -> str:
            return (
                str(self.root / "escape.md") if str(path) == str(self.artifact) else realpath(path)
            )

        with mock.patch.object(os.path, "realpath", side_effect=resolve):
            self.assertEqual("", project_context._dispatch_file_assignment(str(self.artifact)))

    def test_oversized_dispatch_is_refused_even_with_title_at_start(self) -> None:
        with self.artifact.open("a", encoding="utf-8") as handle:
            handle.write("x" * 65536)
        self.assertEqual("", project_context._dispatch_file_assignment(str(self.artifact)))

    def test_fifo_is_refused_without_blocking(self) -> None:
        self.artifact.unlink()
        os.mkfifo(self.artifact, 0o600)
        self.assertEqual("", project_context._dispatch_file_assignment(str(self.artifact)))


class SpacedockExecutableSecurityTest(unittest.TestCase):
    def test_relative_override_is_refused_without_running(self) -> None:
        # Given: the configured executable override is relative.
        config = build_runtime_config(
            environ={}, platform_name="linux", os_name="posix", launcher_path=Path("/server.py")
        )
        state = build_runtime_state(config, started=0)
        for value in ("spacedock", "./spacedock", "bin/spacedock"):
            runner = mock.Mock()
            with mock.patch.dict(os.environ, {"SPACEDOCK_BIN": value}):
                # When: attempt bounded workflow discovery.
                result = project_context._run_project_workflow_discovery(config, state, "/", runner)

            # Then
            runner.assert_not_called()
            self.assertEqual("unavailable", result["state"])

    def test_absolute_override_uses_minimal_environment_and_existing_bounds(self) -> None:
        # Given: an absolute executable override accompanies untrusted environment values.
        config = build_runtime_config(
            environ={}, platform_name="linux", os_name="posix", launcher_path=Path("/server.py")
        )
        state = build_runtime_state(config, started=0)
        runner = mock.Mock(return_value=subprocess.CompletedProcess([], 0, stdout=""))
        with mock.patch.dict(
            os.environ,
            {
                "SPACEDOCK_BIN": "/opt/bin/spacedock",
                "PLANTED_SECRET": "private",
                "PYTHONPATH": "/evil",
            },
        ):
            # When: run bounded workflow discovery.
            project_context._run_project_workflow_discovery(config, state, "/", runner)

        # Then
        self.assertEqual(["/opt/bin/spacedock", "status", "--discover"], runner.call_args.args[0])
        options = runner.call_args.kwargs
        self.assertEqual(2, options["timeout"])
        self.assertFalse(options["shell"])
        self.assertNotIn("PLANTED_SECRET", options["env"])
        self.assertNotIn("PYTHONPATH", options["env"])
        self.assertEqual(os.defpath, options["env"]["PATH"])
        self.assertEqual(65536, project_context.WORKFLOW_DISCOVERY_MAX_BYTES)


if __name__ == "__main__":
    unittest.main()
