from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest import mock

from compass_runtime import claude_data, notifications, records, spacedock, transcripts
from compass_runtime import io as runtime_io
from compass_runtime import sessions as runtime_sessions
from compass_runtime.collectors import claude as claude_collector

from . import support
from .support import (
    RuntimeTestCase,
    cfg,
    collect,
    collect_claude,
    config_patch,
    make_runtime,
    runtime,
    state_of,
    store_patch,
)


class ClaudeDataBoundTest(unittest.TestCase):
    """Every bounded read stops where the configuration says it does.

    Each fixture puts a usable record immediately before the bound and another
    immediately after it, so a test cannot pass by reading either everything or
    nothing.
    """

    def test_the_cwd_per_line_cap_truncates_a_long_record(self) -> None:
        # A single record longer than the per-line cap is read only up to it, so
        # a cwd hiding past the cap must not be found. Mutation-checked:
        # removing the cap passed the whole suite.
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "long.jsonl"
            padded = {"type": "user", "pad": "x" * 400, "cwd": "/w/beyond"}
            path.write_text(json.dumps(padded) + "\n")
            config, state = make_runtime(claude_cwd_line_bytes=64)

            self.assertEqual("", claude_data.session_cwd(config, state, str(path)))

            wide, wide_state = make_runtime(claude_cwd_line_bytes=100_000)
            self.assertEqual("/w/beyond", claude_data.session_cwd(wide, wide_state, str(path)))

    def test_the_cwd_line_count_cap_stops_at_the_bound(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "many.jsonl"
            filler = json.dumps({"type": "assistant"})
            inside = json.dumps({"type": "user", "cwd": "/w/inside"})
            beyond = json.dumps({"type": "user", "cwd": "/w/beyond"})
            path.write_text(f"{filler}\n{inside}\n{filler}\n{beyond}\n")
            # Two lines reaches the record before the bound, never the one after.
            config, state = make_runtime(claude_cwd_scan_lines=2)

            self.assertEqual("/w/inside", claude_data.session_cwd(config, state, str(path)))

    def test_the_agent_scan_line_cap_stops_at_the_bound(self) -> None:
        # Mutation-checked: dropping the line cap passed the whole suite.
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "agent.jsonl"
            filler = json.dumps({"type": "assistant"})
            beyond = json.dumps({"type": "agent-name", "agentName": "reviewer"})
            path.write_text(f"{filler}\n{filler}\n{beyond}\n")
            capped, capped_state = make_runtime(claude_agent_scan_lines=2)
            wide, wide_state = make_runtime(claude_agent_scan_lines=10)

            self.assertEqual(
                (False, "", ""), claude_data.agent_identity(capped, capped_state, str(path))
            )
            self.assertEqual(
                (False, "reviewer", ""), claude_data.agent_identity(wide, wide_state, str(path))
            )

    def test_a_hook_transcript_outside_the_projects_tree_is_refused(self) -> None:
        # The hook payload names its own transcript path, so containment is what
        # stops it naming an arbitrary file. Mutation-checked: dropping the
        # check passed the whole suite.
        with tempfile.TemporaryDirectory() as tmp:
            projects = Path(tmp) / "projects" / "-w-proj"
            projects.mkdir(parents=True)
            prefix = "abcdef12"
            record = json.dumps({"type": "user", "message": {"role": "user", "content": "hello"}})
            inside = projects / f"{prefix}-0000-0000-0000-000000000000.jsonl"
            inside.write_text(record + "\n")
            outside = Path(tmp) / f"{prefix}-0000-0000-0000-000000000000.jsonl"
            outside.write_text(record + "\n")

            with store_patch(PROJECTS_DIR=str(Path(tmp) / "projects")):
                config, state = runtime()

                self.assertTrue(claude_data.hook_user_event(config, state, str(inside), prefix)[0])
                self.assertEqual(
                    (False, None),
                    claude_data.hook_user_event(config, state, str(outside), prefix),
                )


class ClaudeCollectorTest(RuntimeTestCase):
    def test_the_parent_row_publishes_its_scanned_output_token_totals(self) -> None:
        now = time.time()
        session_id = "12345678-0000-0000-0000-000000000000"
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "projects" / "sample"
            project.mkdir(parents=True)
            transcript = project / f"{session_id}.jsonl"
            transcript.write_text(
                "\n".join(
                    json.dumps(record)
                    for record in (
                        {
                            "type": "user",
                            "sessionId": session_id,
                            "timestamp": datetime.fromtimestamp(now - 3, UTC).isoformat(),
                            "message": {"role": "user", "content": "count this turn"},
                        },
                        {
                            "type": "assistant",
                            "sessionId": session_id,
                            "timestamp": datetime.fromtimestamp(now - 2, UTC).isoformat(),
                            "message": {
                                "role": "assistant",
                                "content": [],
                                "usage": {"output_tokens": 15},
                            },
                        },
                    )
                )
                + "\n"
            )
            with (
                store_patch(PROJECTS_DIR=str(Path(tmp) / "projects")),
                store_patch(TASKS_DIR=str(Path(tmp) / "no-tasks")),
            ):
                session = collect_claude(now, 24, False)[0]

        self.assertEqual(15, session["session_output_tokens"])
        self.assertEqual(15, session["turn_output_tokens"])

    def test_the_row_publishes_the_whole_session_id_the_cli_resume_verb_needs(self) -> None:
        # `sid` is Claude's eight-character transcript prefix, which is its key
        # upstream and stays that way. It is not a session id: `claude --resume
        # 27d10654` answers "Provided value \"27d10654\" is not a UUID and does not
        # match any session title" (2.1.261), so a control built from `sid` would
        # hand the reader a command that cannot work. `resume_id` carries the whole
        # id the verb takes, and nothing else changes.
        now = time.time()
        session_id = "27d10654-1cb5-481e-8194-6ce868b91bb5"
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "projects" / "sample"
            project.mkdir(parents=True)
            (project / f"{session_id}.jsonl").write_text(
                json.dumps(
                    {
                        "type": "user",
                        "sessionId": session_id,
                        "timestamp": datetime.fromtimestamp(now - 3, UTC).isoformat(),
                        "message": {"role": "user", "content": "hello"},
                    }
                )
                + "\n"
            )
            with (
                store_patch(PROJECTS_DIR=str(Path(tmp) / "projects")),
                store_patch(TASKS_DIR=str(Path(tmp) / "no-tasks")),
            ):
                session = collect_claude(now, 24, False)[0]

        self.assertEqual("27d10654", session["sid"])
        self.assertEqual(session_id, session["resume_id"])

    def test_a_row_with_only_a_task_file_behind_it_publishes_no_resume_id(self) -> None:
        # A prefix reaches the registry from the task store as well as from a
        # transcript, and the task file's directory name is that prefix and nothing
        # more. There is no id to publish, so the row publishes None rather than the
        # prefix: a resume command built from a prefix does not work.
        now = time.time()
        with tempfile.TemporaryDirectory() as tmp:
            tasks = Path(tmp) / "tasks" / "session-27d10654"
            tasks.mkdir(parents=True)
            (tasks / "1.json").write_text(
                json.dumps({"id": "1", "subject": "Do it", "status": "pending"})
            )
            os.utime(tasks / "1.json", (now - 5, now - 5))
            with (
                store_patch(PROJECTS_DIR=str(Path(tmp) / "no-projects")),
                store_patch(TASKS_DIR=str(Path(tmp) / "tasks")),
            ):
                rows = collect_claude(now, 24, False)

        self.assertEqual(1, len(rows))
        self.assertEqual("27d10654", rows[0]["sid"])
        self.assertIsNone(rows[0]["resume_id"])

    def test_load_tasks_supports_current_and_legacy_directories(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            current = root / "12345678-abcd-ef00-1234-567890abcdef"
            legacy = root / "session-abcdef12"
            current.mkdir()
            legacy.mkdir()
            (current / "1.json").write_text(
                json.dumps({"id": "1", "subject": "Current", "status": "pending"})
            )
            (legacy / "2.json").write_text(
                json.dumps({"id": "2", "subject": "Legacy", "status": "completed"})
            )

            with store_patch(TASKS_DIR=str(root)):
                tasks = claude_collector.load_tasks(runtime()[0])

        self.assertEqual({"12345678", "abcdef12"}, set(tasks))
        self.assertEqual("Current", tasks["12345678"][0]["subject"])
        self.assertEqual("Legacy", tasks["abcdef12"][0]["subject"])

    def test_hook_user_event_accepts_matching_project_transcript(self) -> None:
        session_id = "12345678-0000-0000-0000-000000000000"
        with tempfile.TemporaryDirectory() as tmp:
            projects = Path(tmp) / "projects"
            project = projects / "sample"
            project.mkdir(parents=True)
            transcript = project / f"{session_id}.jsonl"
            transcript.write_text(
                json.dumps(
                    {
                        "type": "user",
                        "uuid": "user-before-hook",
                        "message": {"content": "run the command"},
                    }
                )
                + "\n"
            )
            with store_patch(PROJECTS_DIR=str(projects)):
                config, state = runtime()
                found, user_event = claude_data.hook_user_event(
                    config, state, str(transcript), session_id[:8]
                )

        self.assertTrue(found)
        self.assertEqual("user-before-hook", user_event)

    def test_new_user_event_clears_hook_without_comparing_clocks(self) -> None:
        _config, state = runtime()
        with state_of().hook_lock:
            state_of().hook_notifications["12345678"] = {
                "ts": 10_000.0,
                "message": "permission",
                "user_event": "before",
            }

        self.assertIsNotNone(notifications.current_hook(state, "12345678", "before", 0.0))
        self.assertIsNone(notifications.current_hook(state, "12345678", "after", 0.0))
        self.assertNotIn("12345678", state_of().hook_notifications)

    def test_untimestamped_user_record_clears_hook_notification(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            transcript = Path(tmp) / "12345678-session.jsonl"
            transcript.write_text(
                json.dumps(
                    {
                        "type": "user",
                        "uuid": "before",
                        "message": {"content": "approve"},
                    }
                )
                + "\n"
            )
            config, state = runtime()
            before = claude_data.analyze_transcript(config, state, str(transcript))[
                "last_user_event"
            ]
            with state_of().hook_lock:
                state_of().hook_notifications["12345678"] = {
                    "ts": 10_000.0,
                    "message": "permission",
                    "user_event": before,
                }
            with transcript.open("a") as output:
                output.write(
                    json.dumps(
                        {
                            "type": "user",
                            "message": {"content": "continue without a timestamp"},
                        }
                    )
                    + "\n"
                )
            config, state = runtime()
            after = claude_data.analyze_transcript(config, state, str(transcript))[
                "last_user_event"
            ]

        self.assertNotEqual(before, after)
        self.assertIsNone(notifications.current_hook(state, "12345678", after, 0.0))

    def test_assistant_only_tail_does_not_change_hook_user_event(self) -> None:
        records = [
            {
                "type": "user",
                "uuid": "user-before-hook",
                "message": {"content": "approve"},
            },
            {
                "type": "assistant",
                "message": {"content": "x" * (cfg().tail_bytes + 100)},
            },
        ]
        with tempfile.TemporaryDirectory() as tmp:
            transcript = Path(tmp) / "12345678-session.jsonl"
            transcript.write_text("\n".join(json.dumps(record) for record in records) + "\n")
            config, state = runtime()
            user_event = claude_data.analyze_transcript(config, state, str(transcript))[
                "last_user_event"
            ]

        self.assertEqual("user-before-hook", user_event)

    def test_answer_result_after_tail_boundary_does_not_leave_question_open(self) -> None:
        question = {
            "type": "assistant",
            "timestamp": "2026-01-01T00:00:00+00:00",
            "message": {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "question-1",
                        "name": "AskUserQuestion",
                        "input": {},
                    }
                ],
            },
        }
        answer = {
            "type": "user",
            "timestamp": "2026-01-01T00:10:00+00:00",
            "message": {
                "role": "user",
                "content": [{"type": "tool_result", "tool_use_id": "question-1"}],
            },
        }
        # The only possible split in append-only JSONL puts the older
        # tool_use outside the tail and its later answer inside it. The answer
        # cannot age out before the question that precedes it.
        filler = {"type": "assistant", "message": {"content": "x" * cfg().tail_bytes}}
        with tempfile.TemporaryDirectory() as tmp:
            transcript = Path(tmp) / "session.jsonl"
            transcript.write_text(
                "\n".join(json.dumps(record) for record in (question, filler, answer)) + "\n"
            )
            config, state = runtime()
            info = claude_data.analyze_transcript(config, state, str(transcript))

        self.assertIsNone(info["pending_input_tool"])

    def test_transcript_mtime_alone_does_not_clear_newer_hook(self) -> None:
        now = time.time()
        event_time = datetime.fromtimestamp(now - 10, UTC).isoformat()
        with tempfile.TemporaryDirectory() as tmp:
            projects = Path(tmp) / "projects"
            tasks = Path(tmp) / "tasks"
            project = projects / "sample"
            project.mkdir(parents=True)
            tasks.mkdir()
            transcript = project / "12345678-session.jsonl"
            transcript.write_text(
                json.dumps(
                    {
                        "type": "assistant",
                        "timestamp": event_time,
                        "message": {"content": []},
                    }
                )
                + "\n"
            )
            with state_of().hook_lock:
                state_of().hook_notifications["12345678"] = {
                    "ts": now - 1,
                    "message": "permission",
                }

            with (
                store_patch(PROJECTS_DIR=str(projects)),
                store_patch(TASKS_DIR=str(tasks)),
                mock.patch.object(notifications, "notify_mac"),
            ):
                sessions = collect_claude(now, 24, False)

        # Fresh activity now takes display precedence (the hook only
        # surfaces once the session goes quiet) — but the property this test
        # protects still holds: mtime alone must NOT clear the stored hook.
        self.assertEqual("working", sessions[0]["state"])
        self.assertIn("12345678", state_of().hook_notifications)

    def test_claude_agent_identity_reads_only_a_bounded_prefix(self) -> None:
        record = json.dumps(
            {
                "type": "user",
                "agentName": "reviewer",
                "teamName": "session-12345678",
            }
        )
        source = mock.mock_open(read_data=(record + "\n" + ("x" * 100_000)).encode())
        runtime_pair = runtime()
        with (
            mock.patch("builtins.open", source),
            mock.patch.object(os.path, "getsize", return_value=1_000_000),
            mock.patch.object(support, "runtime", return_value=runtime_pair),
        ):
            config, state = runtime_pair
            identity = claude_data.agent_identity(config, state, "/fake/transcript.jsonl")

        self.assertEqual((True, "reviewer", "12345678"), identity)
        source().read.assert_called_once_with(runtime_pair[0].claude_agent_scan_bytes)

    def test_claude_agent_identity_drops_a_partial_final_prefix_record(self) -> None:
        apparent_record = b'{"agentName":"reviewer","teamName":"session-badbad00"}'
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "agent.jsonl"
            path.write_bytes(apparent_record + b"-continued-without-newline")
            with (
                config_patch(claude_agent_scan_bytes=len(apparent_record)),
                config_patch(claude_agent_cache_negative_min_bytes=len(apparent_record) * 10),
            ):
                config, state = runtime()
                identity = claude_data.agent_identity(config, state, str(path))

        self.assertEqual((False, "", ""), identity)

    def test_transient_agent_identity_read_failure_is_not_negative_cached(self) -> None:
        record = json.dumps(
            {
                "type": "user",
                "agentName": "reviewer",
                "teamName": "session-12345678",
            }
        )
        source = mock.mock_open(read_data=(record + "\n").encode())
        runtime_pair = runtime()
        path = "/fake/transient-agent.jsonl"
        with (
            mock.patch(
                "builtins.open",
                side_effect=[PermissionError("temporarily locked"), source.return_value],
            ),
            mock.patch.object(
                os.path,
                "getsize",
                return_value=runtime_pair[0].claude_agent_cache_negative_min_bytes,
            ),
            mock.patch.object(support, "runtime", return_value=runtime_pair),
        ):
            config, state = runtime_pair
            self.assertEqual((False, "", ""), claude_data.agent_identity(config, state, path))
            self.assertNotIn(path, state_of().agent_class_cache)
            self.assertEqual(
                (True, "reviewer", "12345678"),
                claude_data.agent_identity(config, state, path),
            )

    def test_transient_agent_setting_read_failure_is_not_negative_cached(self) -> None:
        record = json.dumps({"agentSetting": spacedock.SPACEDOCK_ENSIGN})
        source = mock.mock_open(read_data=(record + "\n").encode())
        runtime_pair = runtime()
        path = "/fake/transient-setting.jsonl"
        with (
            mock.patch(
                "builtins.open",
                side_effect=[PermissionError("temporarily locked"), source.return_value],
            ),
            mock.patch.object(
                os.path,
                "getsize",
                return_value=runtime_pair[0].claude_agent_cache_negative_min_bytes,
            ),
            mock.patch.object(support, "runtime", return_value=runtime_pair),
        ):
            config, state = runtime_pair
            self.assertEqual("", claude_data.agent_setting(config, state, path))
            self.assertNotIn(path, state.spacedock_role_cache)
            self.assertEqual(
                spacedock.SPACEDOCK_ENSIGN,
                claude_data.agent_setting(config, state, path),
            )

    def test_claude_cwd_uses_independent_line_and_count_caps(self) -> None:
        first = json.dumps({"ignored": "x" * 100})
        target = json.dumps({"cwd": "/wanted/project"})
        first_line = (first + "\n").encode()
        payload = first_line + (target + "\n").encode()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "session.jsonl"
            path.write_bytes(payload)
            short_scan = Path(tmp) / "short-scan.jsonl"
            short_scan.write_bytes(payload)
            self.assertEqual(payload, path.read_bytes())
            self.assertEqual(payload, short_scan.read_bytes())
            with (
                config_patch(claude_cwd_scan_lines=2),
                config_patch(claude_cwd_line_bytes=len(first_line)),
            ):
                config, state = runtime()
                self.assertEqual(
                    "/wanted/project", claude_data.session_cwd(config, state, str(path))
                )
            with (
                config_patch(claude_cwd_scan_lines=1),
                config_patch(claude_cwd_line_bytes=len(first_line)),
            ):
                config, state = runtime()
                self.assertEqual("", claude_data.session_cwd(config, state, str(short_scan)))

    def test_configured_agent_transcript_remains_a_top_level_session(self) -> None:
        now = time.time()
        timestamp = datetime.fromtimestamp(now - 5, UTC).isoformat()
        session_id = "c0ffee25-0000-0000-0000-000000000000"
        with tempfile.TemporaryDirectory() as tmp:
            projects = Path(tmp) / "projects"
            project = projects / "sample"
            project.mkdir(parents=True)
            tasks = Path(tmp) / "tasks"
            tasks.mkdir()
            transcript = project / f"{session_id}.jsonl"
            transcript.write_text(
                "\n".join(
                    json.dumps(record)
                    for record in (
                        {
                            "type": "agent-name",
                            "agentName": spacedock.SPACEDOCK_ENSIGN,
                            "agentSetting": spacedock.SPACEDOCK_ENSIGN,
                        },
                        {
                            "type": "user",
                            "sessionId": session_id,
                            "timestamp": timestamp,
                            "message": {"role": "user", "content": "run the workflow"},
                        },
                    )
                )
                + "\n"
            )
            with (
                store_patch(PROJECTS_DIR=str(projects)),
                store_patch(TASKS_DIR=str(tasks)),
            ):
                sessions = collect_claude(now, 24, False)
                config, state = runtime()
                classified_as_subagent = claude_data.prefix_is_agent(config, state, session_id[:8])

        self.assertEqual([session_id[:8]], [session["session"] for session in sessions])
        self.assertFalse(classified_as_subagent)
        self.assertEqual(
            {"role": "ensign", "workflows": []},
            sessions[0]["spacedock"],
        )

    def test_young_agent_identity_can_gain_a_parent_relation(self) -> None:
        config, state = runtime()
        with tempfile.TemporaryDirectory() as tmp:
            transcript = Path(tmp) / "young-agent.jsonl"
            transcript.write_text(
                json.dumps({"type": "agent-name", "agentName": "reviewer"}) + "\n"
            )

            self.assertEqual(
                (False, "reviewer", ""),
                claude_data.agent_identity(config, state, str(transcript)),
            )

            with transcript.open("a") as stream:
                stream.write(
                    json.dumps(
                        {
                            "type": "user",
                            "teamName": "session-12345678",
                        }
                    )
                    + "\n"
                )

            self.assertEqual(
                (True, "reviewer", "12345678"),
                claude_data.agent_identity(config, state, str(transcript)),
            )

    def test_young_agent_identity_can_gain_a_name_after_parent_relation(self) -> None:
        config, state = runtime()
        with tempfile.TemporaryDirectory() as tmp:
            transcript = Path(tmp) / "young-agent.jsonl"
            transcript.write_text(
                json.dumps(
                    {
                        "type": "user",
                        "teamName": "session-12345678",
                    }
                )
                + "\n"
            )

            self.assertEqual(
                (True, "", "12345678"),
                claude_data.agent_identity(config, state, str(transcript)),
            )
            self.assertNotIn(str(transcript), state_of().agent_class_cache)

            with transcript.open("a") as stream:
                stream.write(
                    json.dumps(
                        {
                            "type": "agent-name",
                            "agentName": "reviewer",
                        }
                    )
                    + "\n"
                )

            self.assertEqual(
                (True, "reviewer", "12345678"),
                claude_data.agent_identity(config, state, str(transcript)),
            )

    def test_parent_relation_without_agent_name_is_still_a_subagent(self) -> None:
        config, state = runtime()
        with tempfile.TemporaryDirectory() as tmp:
            transcript = Path(tmp) / "unnamed-agent.jsonl"
            transcript.write_text(
                json.dumps(
                    {
                        "type": "user",
                        "teamName": "session-12345678",
                    }
                )
                + "\n"
            )

            self.assertEqual(
                (True, "", "12345678"),
                claude_data.agent_identity(config, state, str(transcript)),
            )

    def test_claude_agent_negative_cache_waits_for_conclusive_prefix(self) -> None:
        config, state = runtime()
        with tempfile.TemporaryDirectory() as tmp:
            transcript = Path(tmp) / "young.jsonl"
            transcript.write_text("{}\n")
            self.assertEqual(
                (False, "", ""),
                claude_data.agent_identity(config, state, str(transcript)),
            )
            self.assertNotIn(str(transcript), state_of().agent_class_cache)

            transcript.write_text("{}\n" * 50)
            self.assertEqual(
                (False, "", ""),
                claude_data.agent_identity(config, state, str(transcript)),
            )

        self.assertIn(str(transcript), state_of().agent_class_cache)

    def test_claude_title_prefers_newest_ai_title_outside_tail(self) -> None:
        records = [
            {
                "type": "user",
                "timestamp": "2026-01-01T00:00:00Z",
                "message": {"content": "stale first prompt"},
            },
            {"type": "ai-title", "aiTitle": "Older generated title"},
            {"type": "ai-title", "aiTitle": "Current generated title"},
            {
                "type": "assistant",
                "timestamp": "2026-01-01T00:00:01Z",
                "message": {"content": "x" * (cfg().tail_bytes + 100)},
            },
        ]
        with tempfile.TemporaryDirectory() as tmp:
            transcript = Path(tmp) / "session.jsonl"
            transcript.write_text("\n".join(json.dumps(record) for record in records) + "\n")
            config, state = runtime()
            info = claude_data.analyze_transcript(config, state, str(transcript))

        self.assertEqual("Current generated title", info["title"])

    def test_claude_title_falls_back_to_first_user_prompt(self) -> None:
        records = [
            {"type": "system", "timestamp": "2026-01-01T00:00:00Z"},
            {
                "type": "user",
                "timestamp": "2026-01-01T00:00:01Z",
                "message": {"content": "First useful prompt\nwith details"},
            },
            {
                "type": "user",
                "timestamp": "2026-01-01T00:00:02Z",
                "message": {"content": "Later prompt"},
            },
        ]
        with tempfile.TemporaryDirectory() as tmp:
            transcript = Path(tmp) / "session.jsonl"
            transcript.write_text("\n".join(json.dumps(record) for record in records) + "\n")
            config, state = runtime()
            info = claude_data.analyze_transcript(config, state, str(transcript))

        self.assertEqual("First useful prompt", info["title"])

    def test_legacy_claude_agent_files_are_not_top_level_sessions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            projects = Path(tmp) / "projects"
            tasks = Path(tmp) / "tasks"
            project = projects / "sample"
            project.mkdir(parents=True)
            tasks.mkdir()
            (project / "agent-abcd.jsonl").write_text("{}\n")
            (project / "12345678-session.jsonl").write_text("{}\n")

            with (
                store_patch(PROJECTS_DIR=str(projects)),
                store_patch(TASKS_DIR=str(tasks)),
            ):
                sessions = collect_claude(time.time(), 24, True)

        self.assertEqual(["12345678"], [session["session"] for session in sessions])

    def test_a_transcript_of_harness_metadata_alone_is_not_a_session(self) -> None:
        # DRC-4645. Measured 2026-09-23: 438 of 765 transcripts in one project
        # directory were a single `ai-title` record, and 30 of 34 rows under
        # that project were those files. `pr-link` is the other measured shape.
        now = time.time()
        iso = datetime.fromtimestamp(now - 5, UTC).isoformat()
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "projects" / "-Users-test-repo"
            project.mkdir(parents=True)
            (project / "aaaa0001-0000-0000-0000-000000000000.jsonl").write_text(
                json.dumps({"type": "ai-title", "aiTitle": "Work in another repo"}) + "\n"
            )
            (project / "aaaa0002-0000-0000-0000-000000000000.jsonl").write_text(
                json.dumps({"type": "pr-link", "url": "https://example.invalid/pr/1"})
                + "\n"
                + json.dumps({"type": "ai-title", "aiTitle": "Also elsewhere"})
                + "\n"
            )
            (project / "bbbb0001-0000-0000-0000-000000000000.jsonl").write_text(
                json.dumps({"type": "ai-title", "aiTitle": "The real session"})
                + "\n"
                + json.dumps({"type": "user", "timestamp": iso, "message": {"content": "build it"}})
                + "\n"
            )
            with store_patch(PROJECTS_DIR=str(Path(tmp) / "projects")):
                sessions = collect_claude(now, 24, True)

        self.assertEqual(["bbbb0001"], [session["session"] for session in sessions])
        self.assertEqual("The real session", sessions[0]["title"])

    def test_a_metadata_transcript_larger_than_the_scan_is_still_counted(self) -> None:
        # The check reads a bounded prefix. A file longer than that prefix is
        # never hidden on a guess about what the unread part holds.
        # Records are sized to divide the scan exactly, so the prefix ends on a
        # record boundary and parses clean: a torn last line would keep the file
        # counted on its own and leave the bound untested.
        now = time.time()
        scan = cfg().claude_agent_scan_bytes
        stem = json.dumps({"type": "ai-title", "aiTitle": ""})
        record = stem.replace('""', '"' + "x" * (64 - len(stem) - 1) + '"') + "\n"
        self.assertEqual(0, scan % len(record))
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "projects" / "-Users-test-repo"
            project.mkdir(parents=True)
            big = project / "cccc0001-0000-0000-0000-000000000000.jsonl"
            big.write_text(record * (scan // len(record) + 4))
            with store_patch(PROJECTS_DIR=str(Path(tmp) / "projects")):
                sessions = collect_claude(now, 24, True)

        self.assertEqual(["cccc0001"], [session["session"] for session in sessions])

    def test_a_session_opened_but_not_yet_prompted_keeps_its_row(self) -> None:
        # Claude Code writes these before the first user record, for up to 85
        # minutes in the 2026-09-23 sweep. Hiding them would drop a live row.
        now = time.time()
        records = [
            {"type": "attachment", "attachment": {"type": "hook_success"}},
            {"type": "last-prompt"},
            {"type": "mode"},
            {"type": "permission-mode"},
            {"type": "file-history-snapshot"},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "projects" / "-Users-test-repo"
            project.mkdir(parents=True)
            (project / "dddd0001-0000-0000-0000-000000000000.jsonl").write_text(
                "".join(json.dumps(record) + "\n" for record in records)
            )
            with store_patch(PROJECTS_DIR=str(Path(tmp) / "projects")):
                sessions = collect_claude(now, 24, True)

        self.assertEqual(["dddd0001"], [session["session"] for session in sessions])

    def test_a_record_with_a_non_string_type_keeps_the_file_and_the_harness_up(self) -> None:
        now = time.time()
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "projects" / "-Users-test-repo"
            project.mkdir(parents=True)
            (project / "eeee0001-0000-0000-0000-000000000000.jsonl").write_text(
                json.dumps({"type": ["ai-title"]}) + "\n"
            )
            with store_patch(PROJECTS_DIR=str(Path(tmp) / "projects")):
                sessions = collect_claude(now, 24, True)

        self.assertEqual(["eeee0001"], [session["session"] for session in sessions])

    def test_a_torn_metadata_file_is_decided_again_once_it_is_complete(self) -> None:
        # A mid-write read is shown rather than hidden and is not cached, so
        # the completed file is classified on the next pass.
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ffff0001-0000-0000-0000-000000000000.jsonl"
            path.write_text('{"type": "ai-ti')
            config, state = runtime()
            self.assertTrue(claude_data.has_conversation(config, state, str(path)))
            self.assertNotIn(str(path), state.conversation_cache)
            path.write_text(json.dumps({"type": "ai-title", "aiTitle": "x"}) + "\n")
            self.assertFalse(claude_data.has_conversation(config, state, str(path)))
            with path.open("a") as handle:
                handle.write(json.dumps({"type": "user", "message": {"content": "go"}}) + "\n")
            self.assertTrue(claude_data.has_conversation(config, state, str(path)))

    def test_modern_subagent_transcripts_fold_into_parent_session(self) -> None:
        # Harness >= 2.x writes subagent transcripts as ordinary top-level
        # <uuid>.jsonl files whose records carry agentName and
        # teamName "session-<parent prefix>". They must NOT surface as
        # standalone sessions; they attach to the parent as named running
        # subagents, keep it working, and contribute to its output rate.
        now = time.time()
        iso = datetime.fromtimestamp(now - 5, UTC).isoformat()
        stale_iso = datetime.fromtimestamp(now - 600, UTC).isoformat()
        parent_id = "aaaa1111-0000-0000-0000-000000000000"
        child_id = "bbbb2222-0000-0000-0000-000000000000"
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp) / "projects" / "-Users-test-repo"
            proj.mkdir(parents=True)
            parent_fp = proj / f"{parent_id}.jsonl"
            parent_fp.write_text(
                json.dumps(
                    {
                        "type": "user",
                        "sessionId": parent_id,
                        "timestamp": stale_iso,
                        "message": {"role": "user", "content": "build the feature"},
                    }
                )
                + "\n"
            )
            child_fp = proj / f"{child_id}.jsonl"
            child_fp.write_text(
                json.dumps(
                    {
                        "type": "user",
                        "sessionId": child_id,
                        "agentName": "spark-reviewer",
                        "teamName": f"session-{parent_id[:8]}",
                        "timestamp": iso,
                        "message": {"role": "user", "content": "review the sparkline"},
                    }
                )
                + "\n"
                + json.dumps(
                    {
                        "type": "assistant",
                        "sessionId": child_id,
                        "agentName": "spark-reviewer",
                        "teamName": f"session-{parent_id[:8]}",
                        "timestamp": iso,
                        "message": {
                            "role": "assistant",
                            "content": [],
                            "usage": {"output_tokens": 500},
                        },
                    }
                )
                + "\n"
            )
            # Parent quiet for 10 minutes; child fresh.
            old = now - 600
            os.utime(parent_fp, (old, old))
            with (
                store_patch(PROJECTS_DIR=str(Path(tmp) / "projects")),
                store_patch(TASKS_DIR=str(Path(tmp) / "no-tasks")),
            ):
                sessions = collect_claude(now, 24, False)

        self.assertEqual(1, len(sessions))
        parent = sessions[0]
        self.assertEqual(parent_id[:8], parent["session"])
        self.assertEqual("working", parent["state"])
        self.assertEqual(
            [
                {
                    "name": "spark-reviewer",
                    "model": None,
                    "started_at": records.parse_ts(iso),
                    "active": True,
                    "parent": None,
                }
            ],
            parent["subagents"],
        )
        self.assertEqual(records.parse_ts(stale_iso), parent["started_at"])
        self.assertGreater(parent["rate_per_min"], 0)

    def test_a_quiet_child_transcript_stops_counting_as_a_running_subagent(self) -> None:
        # A child that has gone quiet is finished work, not running work: it must
        # drop off the parent's subagent pills and stop holding it in Working.
        # The parent still stays in the window, because a child write is real
        # activity even when it is too old to read as running.
        # Mutation-checked: dropping the child freshness filter passed the suite.
        now = time.time()
        stale_iso = datetime.fromtimestamp(now - 600, UTC).isoformat()
        parent_id = "aaaa1111-0000-0000-0000-000000000000"
        child_id = "bbbb2222-0000-0000-0000-000000000000"
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp) / "projects" / "-Users-test-repo"
            proj.mkdir(parents=True)
            parent_fp = proj / f"{parent_id}.jsonl"
            parent_fp.write_text(
                json.dumps(
                    {
                        "type": "user",
                        "sessionId": parent_id,
                        "timestamp": stale_iso,
                        "message": {"role": "user", "content": "build the feature"},
                    }
                )
                + "\n"
            )
            child_fp = proj / f"{child_id}.jsonl"
            child_fp.write_text(
                json.dumps(
                    {
                        "type": "user",
                        "sessionId": child_id,
                        "agentName": "spark-reviewer",
                        "teamName": f"session-{parent_id[:8]}",
                        "timestamp": stale_iso,
                        "message": {"role": "user", "content": "review the sparkline"},
                    }
                )
                + "\n"
            )
            old = now - 600
            os.utime(parent_fp, (old, old))
            os.utime(child_fp, (old, old))
            with (
                store_patch(PROJECTS_DIR=str(Path(tmp) / "projects")),
                store_patch(TASKS_DIR=str(Path(tmp) / "no-tasks")),
            ):
                sessions = collect_claude(now, 24, False)

        self.assertEqual(1, len(sessions), "the child must still not be a standalone session")
        parent = sessions[0]
        self.assertEqual(parent_id[:8], parent["session"])
        # DRC-4344 changed what "stops counting" means, and only that. The child
        # stays on the published row, because vanishing is how a live teammate
        # blocked on its own subagents disappeared for minutes at a time; what it
        # no longer does is read as running. The state assertions below are the
        # ones this case was written for and are untouched.
        self.assertEqual(
            [
                {
                    "name": "spark-reviewer",
                    "model": None,
                    "started_at": records.parse_ts(stale_iso),
                    "active": False,
                    "parent": None,
                }
            ],
            parent["subagents"],
        )
        self.assertEqual("idle", parent["state"])
        self.assertTrue(parent["active"], "a child write keeps the session in the window")

    def test_load_tasks_coerces_malformed_field_types(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "12345678-abcd-ef00-1234-567890abcdef"
            root.mkdir(parents=True)
            (root / "1.json").write_text(
                json.dumps({"id": "1", "subject": {"nested": True}, "activeForm": 42, "status": 7})
            )
            (root / "2.json").write_text(json.dumps(["not", "a", "task"]))

            with store_patch(TASKS_DIR=str(tmp)):
                tasks = claude_collector.load_tasks(runtime()[0])

        rows = tasks["12345678"]
        self.assertEqual(1, len(rows))  # the non-dict record is skipped
        task = rows[0]
        self.assertEqual("(untitled)", task["subject"])
        self.assertEqual("", task["activeForm"])
        self.assertEqual("pending", task["status"])
        # The concatenation that previously raised TypeError must work.
        self.assertEqual("(untitled)…", (task["activeForm"] or task["subject"]) + "…")

    def test_claude_subagents_tolerate_malformed_meta(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sess = Path(tmp) / "abc.jsonl"
            sess.write_text("{}\n")
            sub = Path(tmp) / "abc" / "subagents"
            sub.mkdir(parents=True)
            (sub / "agent-1.jsonl").write_text("{}\n")
            (sub / "agent-1.meta.json").write_text('{"name":42,"description":7}')
            (sub / "agent-2.jsonl").write_text("{}\n")
            (sub / "agent-2.meta.json").write_text("42")  # non-dict meta

            agents = claude_collector.load_subagents(runtime()[0], str(sess), time.time())

        # Both agents survive with the fallback label instead of TypeError.
        self.assertEqual(["subagent", "subagent"], [a["label"] for a in agents])
        self.assertEqual([None, None], [a["started_at"] for a in agents])

    def test_a_subagent_start_comes_from_its_first_record(self) -> None:
        stamp = "2026-01-01T00:00:00Z"
        with tempfile.TemporaryDirectory() as tmp:
            sess = Path(tmp) / "abc.jsonl"
            sess.write_text("{}\n")
            sub = Path(tmp) / "abc" / "subagents"
            sub.mkdir(parents=True)
            child = sub / "agent-1.jsonl"
            child.write_text(json.dumps({"type": "user", "timestamp": stamp, "message": {}}) + "\n")

            agents = claude_collector.load_subagents(runtime()[0], str(sess), time.time())

        self.assertEqual(records.parse_ts(stamp), agents[0]["started_at"])

    def test_a_quiet_subagent_transcript_is_not_a_running_subagent(self) -> None:
        # "Running" is inferred from mtime, and a subagent pill is the reason a
        # parent session reads Working. Without the freshness filter a session
        # would list every subagent it ever ran and never leave Working.
        # Mutation-checked: dropping the filter passed the whole suite.
        now = 1_700_000_000.0
        config = runtime()[0]
        with tempfile.TemporaryDirectory() as tmp:
            sess = Path(tmp) / "abc.jsonl"
            sess.write_text("{}\n")
            sub = Path(tmp) / "abc" / "subagents"
            sub.mkdir(parents=True)
            for name, age in (("agent-live", 5.0), ("agent-quiet", 600.0)):
                path = sub / f"{name}.jsonl"
                path.write_text("{}\n")
                (sub / f"{name}.meta.json").write_text(json.dumps({"name": name}))
                os.utime(path, (now - age, now - age))

            agents = claude_collector.load_subagents(config, str(sess), now)

        self.assertGreater(600.0, config.working_threshold_sec, "the quiet agent must be stale")
        self.assertEqual(["agent-live"], [a["label"] for a in agents])

    def test_workflow_subagents_count_as_running_subagents(self) -> None:
        # Workflow fan-outs write one directory deeper than a plain Task
        # subagent: subagents/workflows/<run-id>/agent-*.jsonl. Both layouts
        # are the same thing to the dashboard — work the session is doing.
        with tempfile.TemporaryDirectory() as tmp:
            sess = Path(tmp) / "abc.jsonl"
            sess.write_text("{}\n")
            plain = Path(tmp) / "abc" / "subagents"
            plain.mkdir(parents=True)
            (plain / "agent-1.jsonl").write_text("{}\n")
            (plain / "agent-1.meta.json").write_text('{"name":"plain-task"}')
            run = plain / "workflows" / "wf_506d8d41-ba5"
            run.mkdir(parents=True)
            (run / "agent-2.jsonl").write_text("{}\n")
            (run / "agent-2.meta.json").write_text('{"name":"review:bugs"}')
            # The run's bookkeeping file sits beside its agents and is not one.
            (run / "journal.jsonl").write_text("{}\n")

            agents = claude_collector.load_subagents(runtime()[0], str(sess), time.time())

        self.assertEqual({"plain-task", "review:bugs"}, {a["label"] for a in agents})

    def test_workflow_agents_keep_a_quiet_parent_working(self) -> None:
        # The live 5cb7c95e case: the main loop is parked awaiting a background
        # workflow, so its transcript goes quiet while ten workflow agents burn
        # tokens. The session read Idle with its task list hidden.
        now = time.time()
        session_id = "5cb7c95e-0000-0000-0000-000000000000"
        stale = now - 400  # well past working_threshold_sec
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "projects" / "sample"
            project.mkdir(parents=True)
            transcript = project / f"{session_id}.jsonl"
            transcript.write_text(
                json.dumps(
                    {
                        "type": "user",
                        "timestamp": datetime.fromtimestamp(stale, UTC).isoformat(),
                        "message": {"role": "user", "content": "fan the detectors out"},
                    }
                )
                + "\n"
            )
            os.utime(transcript, (stale, stale))
            run = project / session_id / "subagents" / "workflows" / "wf_506d8d41-ba5"
            run.mkdir(parents=True)
            agent = run / "agent-a88a43dd9.jsonl"
            agent.write_text(
                json.dumps(
                    {
                        "type": "assistant",
                        "timestamp": datetime.fromtimestamp(now - 5, UTC).isoformat(),
                        "message": {
                            "role": "assistant",
                            "content": [],
                            "usage": {"output_tokens": 3000},
                        },
                    }
                )
                + "\n"
            )
            (run / "agent-a88a43dd9.meta.json").write_text('{"name":"detect:backend"}')
            with (
                store_patch(PROJECTS_DIR=str(Path(tmp) / "projects")),
                store_patch(TASKS_DIR=str(Path(tmp) / "no-tasks")),
            ):
                session = collect_claude(now, 24, False)[0]

        self.assertEqual("working", session["state"])
        self.assertEqual(
            [
                {
                    "name": "detect:backend",
                    "model": None,
                    "started_at": records.parse_ts(
                        datetime.fromtimestamp(now - 5, UTC).isoformat()
                    ),
                    "active": True,
                    "parent": None,
                }
            ],
            session["subagents"],
        )
        # The agent's output is the session's output — a parent that reads
        # Working at 0 tok/min is the same blind spot in the rate panel.
        self.assertGreater(session["rate_per_min"], 0)

    def test_a_finished_loop_is_still_published_after_the_session_goes_quiet(self) -> None:
        # The whole point of the top-level field. `turn` is None for anything
        # that is not working, so a loop signal carried there would vanish the
        # moment the failures stopped — which is when the human walks back to
        # the machine and asks what happened.
        now = time.time()
        session_id = "10000000-0000-0000-0000-000000000000"
        quiet = now - 600  # past the working threshold, inside the 24h window
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "projects" / "sample"
            project.mkdir(parents=True)
            transcript = project / f"{session_id}.jsonl"
            lines = [
                {
                    "type": "user",
                    "timestamp": datetime.fromtimestamp(quiet - 60, UTC).isoformat(),
                    "message": {"role": "user", "content": "run the suite"},
                }
            ]
            for i in range(4):
                lines.append(
                    {
                        "type": "assistant",
                        "timestamp": datetime.fromtimestamp(quiet - 50 + i * 10, UTC).isoformat(),
                        "message": {
                            "role": "assistant",
                            "content": [{"type": "tool_use", "id": f"t{i}", "name": "Bash"}],
                        },
                    }
                )
                lines.append(
                    {
                        "type": "user",
                        "timestamp": datetime.fromtimestamp(quiet - 45 + i * 10, UTC).isoformat(),
                        "message": {
                            "role": "user",
                            "content": [
                                {"type": "tool_result", "tool_use_id": f"t{i}", "is_error": True}
                            ],
                        },
                    }
                )
            transcript.write_text("\n".join(json.dumps(line) for line in lines) + "\n")
            os.utime(transcript, (quiet, quiet))
            with (
                store_patch(PROJECTS_DIR=str(Path(tmp) / "projects")),
                store_patch(TASKS_DIR=str(Path(tmp) / "no-tasks")),
            ):
                session = collect_claude(now, 24, False)[0]

        self.assertNotEqual("working", session["state"])
        self.assertIsNone(session["turn"])
        # Four failures and no successful call, so the turn is barren as well
        # as a run of four. Both readings are published; neither replaces the
        # other (DRC-4021).
        self.assertEqual(
            {"errors": 4, "failures": 4, "barren": True, "tool": "Bash"}, session["loop"]
        )

    def test_workflow_agent_activity_holds_a_session_in_the_window(self) -> None:
        # last_activity drives both the freshness window and the "idle 23h"
        # age. A stale parent whose workflow agents wrote a minute ago has to
        # count as a minute old, or a long run ages out of the dashboard.
        now = time.time()
        session_id = "d0d0d0d0-0000-0000-0000-000000000000"
        ancient = now - 30 * 3600  # older than the 24h window
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "projects" / "sample"
            project.mkdir(parents=True)
            transcript = project / f"{session_id}.jsonl"
            transcript.write_text("{}\n")
            os.utime(transcript, (ancient, ancient))
            run = project / session_id / "subagents" / "workflows" / "wf_1"
            run.mkdir(parents=True)
            agent = run / "agent-1.jsonl"
            agent.write_text("{}\n")
            recent = now - 300  # quiet enough not to read Working
            os.utime(agent, (recent, recent))
            with (
                store_patch(PROJECTS_DIR=str(Path(tmp) / "projects")),
                store_patch(TASKS_DIR=str(Path(tmp) / "no-tasks")),
            ):
                sessions = collect_claude(now, 24, False)

        self.assertEqual(1, len(sessions))
        self.assertAlmostEqual(recent, sessions[0]["last_activity"], delta=2)

    def test_claude_session_cwd_reads_the_head_and_retries_when_absent(self) -> None:
        # The cwd drives every Claude project label.
        with tempfile.TemporaryDirectory() as tmp:
            late = Path(tmp) / "late.jsonl"
            filler = "\n".join(json.dumps({"type": "x", "n": i}) for i in range(60))
            late.write_text(filler + "\n" + json.dumps({"type": "user", "cwd": "/w/late"}) + "\n")
            # Past the 50-line scan bound: not found, and not cached as a miss.
            config, state = runtime()
            self.assertEqual("", claude_data.session_cwd(config, state, str(late)))
            self.assertNotIn(str(late), state_of().cwd_cache)

            early = Path(tmp) / "early.jsonl"
            early.write_text("{}\n")
            config, state = runtime()
            self.assertEqual("", claude_data.session_cwd(config, state, str(early)))
            # A miss must not be cached, or a transcript whose head is written
            # before its first cwd record keeps the fallback label forever.
            early.write_text(json.dumps({"type": "user", "cwd": "/w/early"}) + "\n")
            config, state = runtime()
            self.assertEqual("/w/early", claude_data.session_cwd(config, state, str(early)))

            missing = Path(tmp) / "gone.jsonl"
            config, state = runtime()
            self.assertEqual("", claude_data.session_cwd(config, state, str(missing)))

    def test_claude_project_falls_back_when_transcript_has_no_cwd(self) -> None:
        # A transcript head can be written before any record carries cwd. The
        # encoded directory name is lossy: Claude replaces every separator with
        # "-", so it cannot be split back apart. It is capped at the last two
        # segments rather than published whole, which is the one thing that can
        # be said about it here without guessing, and it is what makes this row
        # and the history store hold the same label. It does not make this row
        # group with the same directory's cwd-derived rows: grouping is on the
        # exact string, so `spacedock/subspace` and `spacedock-subspace` are
        # still two groups. What the cap buys is that neither of them is a path.
        now = time.time()
        home = "/Users/cl"
        encoded = f"{runtime_sessions.encoded_home_prefix(home)}-git-spacedock-subspace"
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp) / "projects" / encoded
            project_dir.mkdir(parents=True)
            (project_dir / "bbbb2222-0000-0000-0000-000000000000.jsonl").write_text("{}\n")
            with (
                store_patch(PROJECTS_DIR=str(Path(tmp) / "projects")),
                store_patch(TASKS_DIR=str(Path(tmp) / "no-tasks")),
                config_patch(home=home),
            ):
                sessions = collect_claude(now, 24, False)

        self.assertEqual("spacedock-subspace", sessions[0]["project"])


class StartStampCacheTest(RuntimeTestCase):
    """The memo behind every roster element's start stamp.

    The roster reaches past the freshness gate, so a quiet agent's head is read
    on every collection unless something remembers it. What it remembers has to
    be invalidated on the file, not on the path alone: a transcript's start
    stamp is immutable only once the file HAS one.
    """

    @staticmethod
    def transcript(tmp: str, *, body: str) -> str:
        fp = Path(tmp) / "agent-x.jsonl"
        fp.write_text(body)
        return str(fp)

    def test_a_stampless_head_is_read_once_and_not_once_per_pass(self) -> None:
        # A transcript whose head carries no timestamp is exactly the case the
        # memo was added for, and it was the one case the memo missed: only a
        # FOUND stamp was cached, so every pass paid the bounded head read AND
        # the one-line fallback again, forever. Keying on the file's own
        # (mtime, size) is what makes remembering a null answer safe.
        # Falsified by: caching only a found stamp, which doubles both counts.
        with tempfile.TemporaryDirectory() as tmp:
            path = self.transcript(tmp, body=json.dumps({"type": "mode"}) + "\n")
            config, state = runtime()
            heads, firsts = {"n": 0}, {"n": 0}
            real_head, real_first = runtime_io.read_prefix_bytes, runtime_io.read_first_json

            def head(target: str, *, max_bytes: int) -> bytes:
                heads["n"] += 1
                return real_head(target, max_bytes=max_bytes)

            def first(conf: Any, target: str) -> dict[str, Any]:
                firsts["n"] += 1
                return real_first(conf, target)

            with (
                mock.patch.object(runtime_io, "read_prefix_bytes", head),
                mock.patch.object(runtime_io, "read_first_json", first),
            ):
                for _ in range(3):
                    self.assertIsNone(claude_data.transcript_started_at(config, path, state=state))

        self.assertEqual(1, heads["n"], "the bounded head read must happen once")
        self.assertEqual(1, firsts["n"], "so must the one-line fallback")

    def test_a_transcript_that_gains_a_stamp_stops_reading_as_unstarted(self) -> None:
        # The reason the memo cannot be keyed on the path alone. A teammate
        # parked on a permission prompt has a head with no timestamp in it; the
        # moment it takes its first turn the file grows one, and a remembered
        # null would freeze the pill at "no start measured" for the rest of the
        # session.
        # Falsified by: dropping the (mtime, size) key, which returns the
        # remembered null after the file has moved.
        now = time.time()
        stamp = datetime.fromtimestamp(now - 5, UTC).isoformat()
        with tempfile.TemporaryDirectory() as tmp:
            path = self.transcript(tmp, body=json.dumps({"type": "mode"}) + "\n")
            config, state = runtime()
            self.assertIsNone(claude_data.transcript_started_at(config, path, state=state))
            Path(path).write_text(
                json.dumps({"type": "mode"})
                + "\n"
                + json.dumps({"type": "user", "timestamp": stamp})
                + "\n"
            )
            os.utime(path, (now, now))

            self.assertEqual(
                records.parse_ts(stamp),
                claude_data.transcript_started_at(config, path, state=state),
            )

    def test_a_rewritten_transcript_does_not_serve_the_old_start(self) -> None:
        # The same invalidation from the other side: a found stamp was cached on
        # the path forever, so a rotated or replaced transcript at a reused path
        # kept reporting the previous file's start.
        # Falsified by: keying the memo on the path alone.
        now = time.time()
        first_stamp = datetime.fromtimestamp(now - 3600, UTC).isoformat()
        second_stamp = datetime.fromtimestamp(now - 10, UTC).isoformat()
        with tempfile.TemporaryDirectory() as tmp:
            path = self.transcript(
                tmp, body=json.dumps({"type": "user", "timestamp": first_stamp}) + "\n"
            )
            config, state = runtime()
            self.assertEqual(
                records.parse_ts(first_stamp),
                claude_data.transcript_started_at(config, path, state=state),
            )
            Path(path).write_text(
                json.dumps({"type": "user", "timestamp": second_stamp, "pad": "x" * 40}) + "\n"
            )
            os.utime(path, (now, now))

            self.assertEqual(
                records.parse_ts(second_stamp),
                claude_data.transcript_started_at(config, path, state=state),
            )


class ClaudeModelTest(RuntimeTestCase):
    """The model a Claude session and its subagents report.

    Three states, never two: a measured model, and no model reported, are
    different facts and stay distinguishable all the way to the page. Nothing
    here may infer a model from anything other than an assistant record that
    names one.
    """

    PARENT = "aaaa1111-0000-0000-0000-000000000000"
    CHILD = "bbbb2222-0000-0000-0000-000000000000"

    @staticmethod
    def _write(path: Path, records_out: list[dict[str, Any]]) -> None:
        path.write_text("\n".join(json.dumps(r) for r in records_out) + "\n")

    def _assistant(self, **fields: Any) -> dict[str, Any]:
        message: dict[str, Any] = {"role": "assistant", "content": []}
        for key in ("model", "usage"):
            if key in fields:
                message[key] = fields.pop(key)
        return {"type": "assistant", "message": message, **fields}

    def _analyze(self, records_out: list[dict[str, Any]]) -> dict[str, Any]:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "t.jsonl"
            self._write(path, records_out)
            config, state = runtime()
            return claude_data.analyze_transcript(config, state, str(path))

    def test_the_synthetic_sentinel_is_never_published_as_a_model(self) -> None:
        # One top-level transcript in five has "<synthetic>" as its newest
        # assistant model: Claude's marker for a record it wrote locally, without
        # the request reaching the API. Published, it renders exactly like a real
        # model name. Rejected by VALUE, because the isApiErrorMessage flag that
        # sits beside it is falsy on some synthetic records — a flag gate leaks
        # the sentinel. When it is all a transcript has, the answer is None.
        info = self._analyze(
            [
                self._assistant(model="<synthetic>", isApiErrorMessage=True),
                self._assistant(model="<synthetic>", isApiErrorMessage=False),
                self._assistant(model="<synthetic>"),
            ]
        )

        self.assertIsNone(info["model"])
        self.assertIsNone(info["model_sidechain"])

    def test_a_synthetic_tail_does_not_withdraw_a_measured_model(self) -> None:
        # A cancellation or an error banner lands after the last real turn. It
        # says nothing about which model the session is on, so it must not
        # overwrite the reading the turns before it earned.
        info = self._analyze(
            [
                self._assistant(model="claude-opus-5"),
                self._assistant(model="<synthetic>", isApiErrorMessage=False),
            ]
        )

        self.assertEqual("claude-opus-5", info["model"])

    def test_the_newest_assistant_model_wins_a_mid_session_switch(self) -> None:
        # Newest-wins, not first-wins: a session that switched plan mid-run is
        # on the model of its most recent turn. Transcripts do not carry stray
        # background models, so the newest value is the session's own.
        info = self._analyze(
            [
                self._assistant(model="claude-fable-5"),
                self._assistant(model="claude-opus-5"),
            ]
        )

        self.assertEqual("claude-opus-5", info["model"])

    def test_a_sidechain_record_lands_in_the_sidechain_half(self) -> None:
        # isSidechain INVERTS between a session and its children: a subagent's
        # own transcript flags every assistant record as a sidechain, so its
        # model lands in `model_sidechain` and the session half stays empty.
        # `child_model` reads the two in that order, which is why a child is
        # measured at all.
        info = self._analyze([self._assistant(model="claude-fable-5", isSidechain=True)])

        self.assertIsNone(info["model"])
        self.assertEqual("claude-fable-5", info["model_sidechain"])
        self.assertEqual("claude-fable-5", claude_collector.child_model(info))

    def test_child_model_never_falls_back_to_the_parent(self) -> None:
        # An unread child publishes None. Borrowing the parent's model would make
        # "the same model as its parent" indistinguishable from "not measured",
        # which is the one distinction this ticket exists to keep.
        self.assertIsNone(claude_collector.child_model(None))
        self.assertIsNone(claude_collector.child_model({}))
        self.assertIsNone(claude_collector.child_model({"model": None, "model_sidechain": None}))
        self.assertEqual("claude-opus-5", claude_collector.child_model({"model": "claude-opus-5"}))

    def test_a_model_string_is_bounded_and_stripped_of_control_characters(self) -> None:
        # Untrusted vendor text on its way to the DOM. Bounded at the only door
        # it comes through, so no caller can forget.
        cap = runtime_sessions.MODEL_CAP_CHARS
        info = self._analyze([self._assistant(model="m\u0007odel" + "x" * (cap * 3))])

        model = info["model"]
        assert model is not None
        self.assertEqual(cap, len(model))
        self.assertTrue(model.startswith("m odel"), model)

    def test_a_non_string_model_field_reports_no_model(self) -> None:
        # Untyped JSON: a number, an object or an empty string is not a reading.
        for value in (42, {"name": "opus"}, ["opus"], "", "   ", None):
            with self.subTest(value=value):
                self.assertIsNone(claude_data.model_reported(value))

    def test_a_session_and_its_subagent_publish_their_own_models(self) -> None:
        # End to end, on the modern layout: the parent's model comes from its own
        # non-sidechain records, the child's from its own sidechain ones, and the
        # child's rides beside its label rather than replacing it.
        now = time.time()
        iso = datetime.fromtimestamp(now - 5, UTC).isoformat()
        stale_iso = datetime.fromtimestamp(now - 600, UTC).isoformat()
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp) / "projects" / "-Users-test-repo"
            proj.mkdir(parents=True)
            parent_fp = proj / f"{self.PARENT}.jsonl"
            self._write(
                parent_fp,
                [
                    {
                        "type": "user",
                        "sessionId": self.PARENT,
                        "timestamp": stale_iso,
                        "message": {"role": "user", "content": "build the feature"},
                    },
                    self._assistant(
                        model="claude-opus-5",
                        sessionId=self.PARENT,
                        timestamp=stale_iso,
                    ),
                ],
            )
            child_fp = proj / f"{self.CHILD}.jsonl"
            self._write(
                child_fp,
                [
                    {
                        "type": "user",
                        "sessionId": self.CHILD,
                        "agentName": "spark-reviewer",
                        "teamName": f"session-{self.PARENT[:8]}",
                        "timestamp": iso,
                        "message": {"role": "user", "content": "review the sparkline"},
                    },
                    self._assistant(
                        model="claude-fable-5",
                        isSidechain=True,
                        sessionId=self.CHILD,
                        agentName="spark-reviewer",
                        teamName=f"session-{self.PARENT[:8]}",
                        timestamp=iso,
                        usage={"output_tokens": 500},
                    ),
                ],
            )
            old = now - 600
            os.utime(parent_fp, (old, old))
            with (
                store_patch(PROJECTS_DIR=str(Path(tmp) / "projects")),
                store_patch(TASKS_DIR=str(Path(tmp) / "no-tasks")),
            ):
                sessions = collect_claude(now, 24, False)

        self.assertEqual(1, len(sessions))
        parent = sessions[0]
        self.assertEqual("claude-opus-5", parent["model"])
        self.assertEqual(
            [
                {
                    "name": "spark-reviewer",
                    "model": "claude-fable-5",
                    "started_at": records.parse_ts(iso),
                    "active": True,
                    "parent": None,
                }
            ],
            parent["subagents"],
        )

    def test_a_legacy_workflow_agent_publishes_the_model_from_its_own_file(self) -> None:
        # The other layout: agent-*.jsonl beneath the session directory, named by
        # a sibling .meta.json. Same rule, and a session whose own transcript
        # names no model still reports None rather than borrowing the child's.
        now = time.time()
        iso = datetime.fromtimestamp(now - 5, UTC).isoformat()
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp) / "projects" / "-Users-test-repo"
            run = proj / self.PARENT / "subagents"
            run.mkdir(parents=True)
            self._write(
                proj / f"{self.PARENT}.jsonl",
                [
                    {
                        "type": "user",
                        "sessionId": self.PARENT,
                        "timestamp": iso,
                        "message": {"role": "user", "content": "detect the backend"},
                    }
                ],
            )
            agent_fp = run / "agent-a88a43dd9.jsonl"
            self._write(
                agent_fp,
                [
                    self._assistant(
                        model="claude-fable-5",
                        isSidechain=True,
                        timestamp=iso,
                        usage={"output_tokens": 500},
                    )
                ],
            )
            (run / "agent-a88a43dd9.meta.json").write_text('{"name":"detect:backend"}')
            with (
                store_patch(PROJECTS_DIR=str(Path(tmp) / "projects")),
                store_patch(TASKS_DIR=str(Path(tmp) / "no-tasks")),
            ):
                session = collect_claude(now, 24, False)[0]

        self.assertIsNone(session["model"], "the parent named no model of its own")
        self.assertEqual(
            [
                {
                    "name": "detect:backend",
                    "model": "claude-fable-5",
                    "started_at": records.parse_ts(iso),
                    "active": True,
                    "parent": None,
                }
            ],
            session["subagents"],
        )

    def test_an_unmeasured_subagent_publishes_a_null_model_beside_its_name(self) -> None:
        # `model` is always present on a subagent element, null meaning not read.
        # A missing key would leave the page unable to tell the two apart.
        now = time.time()
        iso = datetime.fromtimestamp(now - 5, UTC).isoformat()
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp) / "projects" / "-Users-test-repo"
            run = proj / self.PARENT / "subagents"
            run.mkdir(parents=True)
            self._write(
                proj / f"{self.PARENT}.jsonl",
                [
                    {
                        "type": "user",
                        "sessionId": self.PARENT,
                        "timestamp": iso,
                        "message": {"role": "user", "content": "detect the backend"},
                    }
                ],
            )
            self._write(
                run / "agent-a88a43dd9.jsonl",
                [self._assistant(model="<synthetic>", isSidechain=True, timestamp=iso)],
            )
            (run / "agent-a88a43dd9.meta.json").write_text('{"name":"detect:backend"}')
            with (
                store_patch(PROJECTS_DIR=str(Path(tmp) / "projects")),
                store_patch(TASKS_DIR=str(Path(tmp) / "no-tasks")),
            ):
                session = collect_claude(now, 24, False)[0]

        self.assertEqual(
            [
                {
                    "name": "detect:backend",
                    "model": None,
                    "started_at": records.parse_ts(iso),
                    "active": True,
                    "parent": None,
                }
            ],
            session["subagents"],
        )

    def test_load_subagents_without_analyses_publishes_no_model(self) -> None:
        # The callers outside a collection hand no `models` map over. They must
        # get an explicit null rather than a missing key or a guess.
        now = time.time()
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp) / self.PARENT / "subagents"
            run.mkdir(parents=True)
            transcript = Path(tmp) / f"{self.PARENT}.jsonl"
            transcript.write_text("{}\n")
            (run / "agent-1.jsonl").write_text("{}\n")
            config, _state = runtime()

            agents = claude_collector.load_subagents(config, str(transcript), now)

        self.assertEqual([None], [a["model"] for a in agents])


class ClaudeReviewFixTest(unittest.TestCase):
    def test_a_non_dict_message_does_not_kill_the_claude_collector(self) -> None:
        # {"type":"user","message":"a string"} is valid JSON, and the string is
        # truthy — so `record.get("message") or {}` returned it and the next
        # .get() raised, taking the whole collector down for that refresh.
        # Exercised end to end: the helpers alone missed analyze_transcript,
        # which is the path every active session goes through.
        now = 1_700_000_000.0
        malformed = [
            {"type": "user", "message": "not-an-object"},
            {"type": "assistant", "message": 42},
            {"type": "user", "message": ["a", "list"]},
            {"type": "message", "message": "droid-shaped"},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "projects" / "-w-proj"
            project.mkdir(parents=True)
            transcript = project / "abcdef12-0000-0000-0000-000000000000.jsonl"
            transcript.write_text("\n".join(json.dumps(r) for r in malformed) + "\n")
            os.utime(transcript, (now, now))

            config, state = runtime()
            self.assertIsNone(claude_data.session_title(config, state, str(transcript)))
            self.assertEqual({}, records.message_dict({"message": "str"}))
            self.assertEqual({}, records.message_dict("not-a-record"))
            self.assertEqual({"a": 1}, records.message_dict({"message": {"a": 1}}))

            with (
                store_patch(PROJECTS_DIR=str(Path(tmp) / "projects")),
                store_patch(TASKS_DIR=str(Path(tmp) / "tasks")),
            ):
                sessions = collect_claude(now, 24, False)  # must not raise
                everything = collect(24, True)

        self.assertEqual(1, len(sessions))
        claude = next(h for h in everything["harnesses"] if h["key"] == "claude")
        self.assertIsNone(claude["error"], "collector errored on a malformed record")


class ClaudeGlobTest(unittest.TestCase):
    HOSTILE = "A [Contractor]"

    def test_claude_sessions_survive_a_metacharacter_in_the_projects_root(self) -> None:
        now = 1_700_000_000.0
        session_id = "abcdef12-3456-7890-abcd-ef1234567890"
        with tempfile.TemporaryDirectory() as tmp:
            projects = Path(tmp) / self.HOSTILE / "projects"
            project = projects / "-w-proj"
            project.mkdir(parents=True)
            transcript = project / f"{session_id}.jsonl"
            transcript.write_text(
                json.dumps(
                    {
                        "type": "user",
                        "uuid": "u1",
                        "timestamp": "2023-11-14T22:13:20+00:00",
                        "message": {"content": "hostile path prompt"},
                    }
                )
                + "\n"
            )
            os.utime(transcript, (now, now))
            with (
                store_patch(PROJECTS_DIR=str(projects)),
                store_patch(TASKS_DIR=str(Path(tmp) / "tasks")),
            ):
                sessions = collect_claude(now, 24, False)

        self.assertEqual(1, len(sessions))
        self.assertEqual("hostile path prompt", sessions[0]["title"])


class SubagentGlobCostTest(RuntimeTestCase):
    """One subagent scan per session, not two.

    The parent transcript and the subagent transcripts are all real files, so
    these fail if handing the listing over changes which subagents are found.
    """

    def _fixture(self, root: str, *names: str) -> str:
        """A parent transcript plus ``names`` under its ``subagents/`` layout."""
        parent = Path(root) / "abcd1234-session.jsonl"
        parent.write_text("{}\n", encoding="utf-8")
        sub = Path(root) / "abcd1234-session" / "subagents"
        sub.mkdir(parents=True, exist_ok=True)
        for name in names:
            (sub / name).write_text("{}\n", encoding="utf-8")
        return str(parent)

    def test_load_subagents_accepts_a_precomputed_listing(self) -> None:
        config = runtime()[0]
        now = time.time()
        with tempfile.TemporaryDirectory() as root:
            parent = self._fixture(root, "agent-worker.jsonl")

            found = claude_collector.agent_transcripts(parent)
            self.assertTrue(found, "fixture must produce at least one subagent transcript")

            with mock.patch.object(
                claude_collector,
                "agent_transcripts",
                side_effect=AssertionError("globbed again"),
            ):
                agents = claude_collector.load_subagents(config, parent, now, found=found)

            self.assertEqual(["subagent"], [a["label"] for a in agents])

    def test_precomputed_and_self_scanned_results_are_identical(self) -> None:
        config = runtime()[0]
        now = time.time()
        with tempfile.TemporaryDirectory() as root:
            parent = self._fixture(root, "agent-a.jsonl", "agent-b.jsonl")

            self.assertEqual(
                claude_collector.load_subagents(config, parent, now),
                claude_collector.load_subagents(
                    config, parent, now, found=claude_collector.agent_transcripts(parent)
                ),
            )

    def test_absent_session_directory_is_not_globbed(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            parent = Path(root) / "abcd1234-session.jsonl"
            parent.write_text("{}\n", encoding="utf-8")
            # No sibling "abcd1234-session/" directory: the common case for a
            # historical session that never ran a subagent.
            with mock.patch.object(
                runtime_io,
                "glob_under",
                side_effect=AssertionError("globbed a directory that does not exist"),
            ):
                self.assertEqual([], claude_collector.agent_transcripts(str(parent)))

    def test_present_session_directory_is_still_globbed(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            parent = self._fixture(root, "agent-a.jsonl")
            found = claude_collector.agent_transcripts(parent)
            self.assertEqual(["agent-a.jsonl"], [os.path.basename(p) for p, _ in found])


class SubagentListingCacheTest(RuntimeTestCase):
    """A session directory whose subagent tree has not moved is listed once.

    Keyed on directory mtimes rather than on a freshness window, because a
    workflow that runs for hours parks its parent transcript and keeps writing
    only to subagent files. Dropping old prefixes would lose those sessions.
    """

    def _fixture(self, root: str, *names: str) -> str:
        """A parent transcript plus ``names`` under its ``subagents/`` layout."""
        parent = os.path.join(root, "abcd1234-session.jsonl")
        Path(parent).write_text("{}\n", encoding="utf-8")
        sub = os.path.join(root, "abcd1234-session", "subagents")
        os.makedirs(sub, exist_ok=True)
        for name in names:
            Path(os.path.join(sub, name)).write_text("{}\n", encoding="utf-8")
        return parent

    def test_second_call_with_unchanged_mtime_does_not_glob(self) -> None:
        config, state = runtime()
        with tempfile.TemporaryDirectory() as root:
            parent = self._fixture(root, "agent-a.jsonl")
            first = claude_collector.agent_transcripts(parent, config=config, state=state)
            self.assertTrue(first)
            with mock.patch.object(
                runtime_io,
                "glob_under",
                side_effect=AssertionError("re-globbed an unchanged directory"),
            ):
                second = claude_collector.agent_transcripts(parent, config=config, state=state)
            self.assertEqual(first, second)

    def test_a_new_subagent_file_invalidates_the_entry(self) -> None:
        config, state = runtime()
        with tempfile.TemporaryDirectory() as root:
            parent = self._fixture(root, "agent-a.jsonl")
            first = claude_collector.agent_transcripts(parent, config=config, state=state)
            sub = os.path.join(root, "abcd1234-session", "subagents")
            # Force a distinct directory mtime: a coarse filesystem timestamp
            # would otherwise make this test pass or fail on timing alone.
            Path(os.path.join(sub, "agent-b.jsonl")).write_text("{}\n", encoding="utf-8")
            os.utime(sub, (time.time() + 5, time.time() + 5))
            second = claude_collector.agent_transcripts(parent, config=config, state=state)
            self.assertEqual(len(first), 1)
            self.assertEqual(len(second), 2)

    def test_a_reused_listing_carries_the_current_file_mtime(self) -> None:
        """A cache hit restates the mtimes; only the glob is skipped.

        Appending to a subagent transcript moves no directory mtime, so an
        entry that served cached mtimes would freeze a running subagent at the
        moment it was first seen and read Idle from then on.
        """
        config, state = runtime()
        with tempfile.TemporaryDirectory() as root:
            parent = self._fixture(root, "agent-a.jsonl")
            claude_collector.agent_transcripts(parent, config=config, state=state)
            agent = os.path.join(root, "abcd1234-session", "subagents", "agent-a.jsonl")
            moved = time.time() + 30
            os.utime(agent, (moved, moved))
            with mock.patch.object(
                runtime_io,
                "glob_under",
                side_effect=AssertionError("re-globbed an unchanged directory"),
            ):
                again = claude_collector.agent_transcripts(parent, config=config, state=state)
            self.assertEqual([(agent, moved)], again)

    def test_without_state_the_behaviour_is_uncached(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            parent = self._fixture(root, "agent-a.jsonl")
            self.assertEqual(
                claude_collector.agent_transcripts(parent),
                claude_collector.agent_transcripts(parent),
            )

    def test_a_parked_parent_keeps_its_subagent_activity(self) -> None:
        """The regression this cache design exists to avoid.

        The parent transcript is hours old; only the subagent file is fresh. The
        session must still report its subagent activity.
        """
        config, state = runtime()
        with tempfile.TemporaryDirectory() as root:
            parent = self._fixture(root, "agent-a.jsonl")
            stale = time.time() - 6 * 3600
            os.utime(parent, (stale, stale))
            found = claude_collector.agent_transcripts(parent, config=config, state=state)
            self.assertEqual(len(found), 1)
            self.assertGreater(found[0][1], stale)


class SubagentWorkflowCacheTest(RuntimeTestCase):
    """The nested layout invalidates too, from the moment a run exists.

    A workflow run directory is created a beat before its first agent
    transcript, and a file appearing inside it moves no other directory's
    mtime. An entry cached in that window has to expire anyway, or every agent
    of that run stays invisible for the life of the process and its parked
    parent ages out of the window entirely.
    """

    def _fixture(self, root: str) -> tuple[str, str]:
        """A parent transcript and one empty workflow run directory."""
        parent = os.path.join(root, "abcd1234-session.jsonl")
        Path(parent).write_text("{}\n", encoding="utf-8")
        run = os.path.join(root, "abcd1234-session", "subagents", "workflows", "wf_1")
        os.makedirs(run)
        # Every real run directory holds a journal, which no glob pattern
        # matches: the directory is non-empty and the listing is still empty.
        Path(os.path.join(run, "journal.jsonl")).write_text("{}\n", encoding="utf-8")
        return parent, run

    def _names(self, found: list[tuple[str, float]]) -> list[str]:
        return sorted(os.path.basename(path) for path, _ in found)

    def _park(self, directory: str) -> None:
        """Age a directory's mtime before it is first listed.

        The signal under test is a real file creation moving a real directory
        mtime, so nothing here forges the change itself. Parking the starting
        value a minute back is only what keeps a filesystem with coarse
        timestamps from reporting the before and after as the same instant.
        """
        parked = time.time() - 60
        os.utime(directory, (parked, parked))

    def test_the_first_agent_in_a_known_empty_run_directory_is_seen(self) -> None:
        config, state = runtime()
        with tempfile.TemporaryDirectory() as root:
            parent, run = self._fixture(root)
            self._park(run)
            self.assertEqual(
                [], claude_collector.agent_transcripts(parent, config=config, state=state)
            )

            Path(os.path.join(run, "agent-alpha.jsonl")).write_text("{}\n", encoding="utf-8")

            self.assertEqual(
                ["agent-alpha.jsonl"],
                self._names(claude_collector.agent_transcripts(parent, config=config, state=state)),
            )

    def test_a_replacement_agent_in_a_known_run_directory_is_seen(self) -> None:
        config, state = runtime()
        with tempfile.TemporaryDirectory() as root:
            parent, run = self._fixture(root)
            first = os.path.join(run, "agent-alpha.jsonl")
            Path(first).write_text("{}\n", encoding="utf-8")
            self._park(run)
            self.assertEqual(
                ["agent-alpha.jsonl"],
                self._names(claude_collector.agent_transcripts(parent, config=config, state=state)),
            )

            os.remove(first)
            Path(os.path.join(run, "agent-beta.jsonl")).write_text("{}\n", encoding="utf-8")

            self.assertEqual(
                ["agent-beta.jsonl"],
                self._names(claude_collector.agent_transcripts(parent, config=config, state=state)),
            )

    def test_a_run_directory_created_after_the_first_listing_is_seen(self) -> None:
        config, state = runtime()
        with tempfile.TemporaryDirectory() as root:
            parent = os.path.join(root, "abcd1234-session.jsonl")
            Path(parent).write_text("{}\n", encoding="utf-8")
            os.makedirs(os.path.join(root, "abcd1234-session", "subagents"))
            self.assertEqual(
                [], claude_collector.agent_transcripts(parent, config=config, state=state)
            )

            run = os.path.join(root, "abcd1234-session", "subagents", "workflows", "wf_2")
            os.makedirs(run)
            Path(os.path.join(run, "agent-alpha.jsonl")).write_text("{}\n", encoding="utf-8")

            self.assertEqual(
                ["agent-alpha.jsonl"],
                self._names(claude_collector.agent_transcripts(parent, config=config, state=state)),
            )

    def test_a_transcript_written_during_the_glob_is_not_cached_away(self) -> None:
        """The stamp has to be taken before the listing, never after it.

        A stamp taken after the glob records the directory move the new
        transcript caused as already accounted for, so the listing that missed
        it looks current and is served for the life of the process.
        """
        config, state = runtime()
        with tempfile.TemporaryDirectory() as root:
            parent = os.path.join(root, "abcd1234-session.jsonl")
            Path(parent).write_text("{}\n", encoding="utf-8")
            sub = os.path.join(root, "abcd1234-session", "subagents")
            os.makedirs(sub)
            Path(os.path.join(sub, "agent-a.jsonl")).write_text("{}\n", encoding="utf-8")
            self._park(sub)
            late = os.path.join(sub, "agent-b.jsonl")
            real_glob = runtime_io.glob_under

            def racing(base: str, *pattern: str) -> list[str]:
                listed = real_glob(base, *pattern)
                if not os.path.exists(late):
                    Path(late).write_text("{}\n", encoding="utf-8")
                return listed

            with mock.patch.object(runtime_io, "glob_under", side_effect=racing):
                claude_collector.agent_transcripts(parent, config=config, state=state)

            self.assertEqual(
                ["agent-a.jsonl", "agent-b.jsonl"],
                self._names(claude_collector.agent_transcripts(parent, config=config, state=state)),
            )


class SubagentScanCountTest(RuntimeTestCase):
    """The collector itself scans a session's subagents once per collection.

    Both of the call site's guarantees are load-bearing and neither is visible
    from ``agent_transcripts`` alone: handing the listing to
    ``load_subagents`` is what makes it one scan instead of two, and passing
    the runtime is what lets the second collection skip the glob.
    """

    def test_one_collection_costs_one_scan_and_the_next_costs_none(self) -> None:
        now = time.time()
        with tempfile.TemporaryDirectory() as tmp:
            projects = Path(tmp) / "projects"
            project = projects / "-w-proj"
            project.mkdir(parents=True)
            transcript = project / "abcd1234-3456-7890-abcd-ef1234567890.jsonl"
            transcript.write_text("{}\n", encoding="utf-8")
            sess_dir = project / "abcd1234-3456-7890-abcd-ef1234567890"
            (sess_dir / "subagents").mkdir(parents=True)
            (sess_dir / "subagents" / "agent-a.jsonl").write_text("{}\n", encoding="utf-8")
            real_glob = runtime_io.glob_under
            scans: list[str] = []

            def counting(base: str, *pattern: str) -> list[str]:
                if base == str(sess_dir):
                    scans.append(os.path.join(base, *pattern))
                return real_glob(base, *pattern)

            with (
                store_patch(PROJECTS_DIR=str(projects)),
                store_patch(TASKS_DIR=str(Path(tmp) / "tasks")),
                mock.patch.object(runtime_io, "glob_under", side_effect=counting),
            ):
                first = collect_claude(now, 24, False)
                after_one = len(scans)
                second = collect_claude(now, 24, False)

        self.assertEqual(1, len(first), "fixture must produce exactly one session")
        self.assertEqual(1, len(second))
        self.assertEqual(
            len(claude_collector.SUBAGENT_GLOBS),
            after_one,
            f"one collection should list the subagent tree once, listed: {scans}",
        )
        self.assertEqual(after_one, len(scans), "an unchanged tree was listed again")


class OwnActivityTest(RuntimeTestCase):
    """`own_activity` is the session's own transcript and nothing below it.

    `last_activity` folds in every subagent and task write on purpose, so a
    parent parked on a long workflow does not age out of the window. That makes
    it useless for the one question the overlay reducer asks: has the human
    answered, or is a background agent simply writing while the prompt is still
    open (DRC-4097). The two fields must come apart here, or the reducer's guard
    is reading the subtree under another name.
    """

    def _store(self, root: Path, *, parent_at: float, agent_at: float) -> Path:
        projects = root / "projects"
        project = projects / "-w-proj"
        project.mkdir(parents=True)
        parent = project / "12345678-1111-2222-3333-444444444444.jsonl"
        parent.write_text(
            json.dumps(
                {
                    "type": "assistant",
                    "timestamp": datetime.fromtimestamp(parent_at, UTC).isoformat(),
                    "message": {"content": []},
                }
            )
            + "\n"
        )
        os.utime(parent, (parent_at, parent_at))
        agent = project / "99999999-1111-2222-3333-444444444444.jsonl"
        agent.write_text(
            json.dumps(
                {
                    "type": "user",
                    "agentName": "reviewer",
                    "teamName": "session-12345678",
                    "timestamp": datetime.fromtimestamp(agent_at, UTC).isoformat(),
                    "message": {"content": "x"},
                }
            )
            + "\n"
        )
        os.utime(agent, (agent_at, agent_at))
        return projects

    def test_a_fresh_subagent_moves_last_activity_and_leaves_own_activity_alone(self) -> None:
        now = time.time()
        with tempfile.TemporaryDirectory() as tmp:
            projects = self._store(Path(tmp), parent_at=now - 600, agent_at=now - 5)
            with (
                store_patch(PROJECTS_DIR=str(projects)),
                store_patch(TASKS_DIR=str(Path(tmp) / "tasks")),
                mock.patch.object(notifications, "notify_mac"),
            ):
                sessions = collect_claude(now, 24, False)

        parent = next(s for s in sessions if s["sid"].startswith("12345678"))
        self.assertAlmostEqual(now - 5, parent["last_activity"], delta=1.0)
        self.assertAlmostEqual(now - 600, parent["own_activity"], delta=1.0)
        self.assertLess(parent["own_activity"], parent["last_activity"])

    def test_own_activity_follows_the_parent_transcript_when_it_is_the_fresher(self) -> None:
        now = time.time()
        with tempfile.TemporaryDirectory() as tmp:
            projects = self._store(Path(tmp), parent_at=now - 5, agent_at=now - 600)
            with (
                store_patch(PROJECTS_DIR=str(projects)),
                store_patch(TASKS_DIR=str(Path(tmp) / "tasks")),
                mock.patch.object(notifications, "notify_mac"),
            ):
                sessions = collect_claude(now, 24, False)

        parent = next(s for s in sessions if s["sid"].startswith("12345678"))
        self.assertAlmostEqual(now - 5, parent["own_activity"], delta=1.0)

    def _store_with_trailing_bookkeeping(
        self, root: Path, *, assistant_at: float, bookkeeping_at: float
    ) -> Path:
        """A parent transcript whose newest record is not the agent speaking."""
        projects = root / "projects"
        project = projects / "-w-proj"
        project.mkdir(parents=True)
        parent = project / "12345678-1111-2222-3333-444444444444.jsonl"
        parent.write_text(
            json.dumps(
                {
                    "type": "assistant",
                    "timestamp": datetime.fromtimestamp(assistant_at, UTC).isoformat(),
                    "message": {"content": []},
                }
            )
            + "\n"
            + json.dumps(
                {
                    "type": "queue-operation",
                    "timestamp": datetime.fromtimestamp(bookkeeping_at, UTC).isoformat(),
                }
            )
            + "\n"
        )
        os.utime(parent, (bookkeeping_at, bookkeeping_at))
        return projects

    def test_a_bookkeeping_write_does_not_move_own_activity(self) -> None:
        """Only the agent speaking moves `own_activity`, not any write at all.

        A background task completing appends `queue-operation` and `attachment`
        records to the *parent* transcript while a question is still open on
        screen. Those are not the human answering, but they move the file's
        mtime, and the reducer's wait guard reads `own_activity` as "the agent
        resumed, so the wait is over". Keyed on mtime, one background task
        completing retired a live gate for the whole rest of its life — the
        session read `working` while it sat blocked, and `Needs you` said 0.
        """
        now = time.time()
        with tempfile.TemporaryDirectory() as tmp:
            projects = self._store_with_trailing_bookkeeping(
                Path(tmp), assistant_at=now - 600, bookkeeping_at=now - 5
            )
            with (
                store_patch(PROJECTS_DIR=str(projects)),
                store_patch(TASKS_DIR=str(Path(tmp) / "tasks")),
                mock.patch.object(notifications, "notify_mac"),
            ):
                sessions = collect_claude(now, 24, False)

        parent = next(s for s in sessions if s["sid"].startswith("12345678"))
        self.assertAlmostEqual(now - 600, parent["own_activity"], delta=1.0)


class LastConversationTest(unittest.TestCase):
    """`last_conversation_ts` reads conversation records alone (DRC-4770).

    The stop guard reads it, so every record type Claude Code appends while a
    session sits parked has to be invisible to it, while a tool result (a
    `user` record) is not.
    """

    def _info(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        with tempfile.TemporaryDirectory() as tmp:
            transcript = Path(tmp) / "session.jsonl"
            transcript.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
            config, state = runtime()
            return claude_data.analyze_transcript(config, state, str(transcript))

    def test_bookkeeping_records_after_the_turn_do_not_move_it(self) -> None:
        info = self._info(
            [
                {"type": "user", "timestamp": "2026-01-01T00:00:00Z", "message": {"content": "go"}},
                {
                    "type": "assistant",
                    "timestamp": "2026-01-01T00:00:05Z",
                    "message": {"content": []},
                },
                {"type": "system", "subtype": "away_summary", "timestamp": "2026-01-01T00:03:00Z"},
                {"type": "attachment", "timestamp": "2026-01-01T00:03:01Z"},
                {"type": "queue-operation", "timestamp": "2026-01-01T00:03:02Z"},
                {"type": "last-prompt", "lastPrompt": "go", "timestamp": "2026-01-01T00:03:03Z"},
            ]
        )
        self.assertEqual(records.parse_ts("2026-01-01T00:00:05Z"), info["last_conversation_ts"])
        self.assertEqual(records.parse_ts("2026-01-01T00:03:03Z"), info["last_event_ts"])

    def test_a_tool_result_is_conversation(self) -> None:
        info = self._info(
            [
                {
                    "type": "assistant",
                    "timestamp": "2026-01-01T00:00:05Z",
                    "message": {"content": []},
                },
                {
                    "type": "user",
                    "timestamp": "2026-01-01T00:00:09Z",
                    "message": {"content": [{"type": "tool_result", "tool_use_id": "t"}]},
                },
            ]
        )
        self.assertEqual(records.parse_ts("2026-01-01T00:00:09Z"), info["last_conversation_ts"])

    def test_a_tail_with_no_conversation_reports_zero(self) -> None:
        info = self._info([{"type": "system", "timestamp": "2026-01-01T00:03:00Z"}])
        self.assertEqual(0, info["last_conversation_ts"])


class InputSummaryTest(unittest.TestCase):
    """What an open gate is asking, reduced to one bounded line. DRC-4015."""

    @staticmethod
    def _block(name: str, payload: Any) -> dict[str, Any]:
        return {"type": "tool_use", "id": "q-1", "name": name, "input": payload}

    def test_a_question_is_summarised_as_the_question(self) -> None:
        summary = claude_data.input_summary(
            self._block(
                "AskUserQuestion",
                {"questions": [{"header": "Auth", "question": "Which auth method?"}]},
            ),
            limit=160,
        )
        self.assertEqual("Which auth method?", summary)

    def test_several_questions_name_the_first_and_count_the_rest(self) -> None:
        summary = claude_data.input_summary(
            self._block(
                "AskUserQuestion",
                {"questions": [{"question": "Which one?"}, {"question": "And then?"}]},
            ),
            limit=160,
        )
        self.assertEqual("Which one? (+1 more)", summary)

    def test_a_plan_is_reduced_to_its_first_line(self) -> None:
        # Option B of three: a plan runs to thousands of words, and its first
        # line is its title in practice. A row is not where a document goes.
        plan = "# Rewrite the collector\n\nStep one, do the thing.\n" + ("x" * 5_000)
        summary = claude_data.input_summary(self._block("ExitPlanMode", {"plan": plan}), limit=160)
        self.assertEqual("Rewrite the collector", summary)

    def test_a_plan_that_opens_with_furniture_skips_to_the_line_that_names_it(self) -> None:
        # A plan can open with a blank line, a fence or a bullet, and none of
        # those name it. "```, waiting 2m" is a worse row than the tool's name.
        for opening in ("\n\n# Real title\nbody", "```\nReal title\nbody", "- Real title\nbody"):
            with self.subTest(opening=opening.split("\n")[0] or "(blank)"):
                summary = claude_data.input_summary(
                    self._block("ExitPlanMode", {"plan": opening}), limit=160
                )
                self.assertEqual("Real title", summary)

    def test_every_summary_is_capped(self) -> None:
        long_question = "y" * 400
        for block in (
            self._block("AskUserQuestion", {"questions": [{"question": long_question}]}),
            self._block("ExitPlanMode", {"plan": long_question}),
        ):
            self.assertEqual(40, len(claude_data.input_summary(block, limit=40)))

    def test_control_characters_do_not_reach_a_row(self) -> None:
        # A transcript is a file Compass does not write, and this text lands in
        # the DOM.
        summary = claude_data.input_summary(
            self._block("AskUserQuestion", {"questions": [{"question": "we\x00ird\nthing"}]}),
            limit=160,
        )
        self.assertNotIn("\x00", summary)
        self.assertNotIn("\n", summary)

    def test_a_shape_that_is_not_there_summarises_to_nothing(self) -> None:
        # The record reaches disk on no schedule and its shape is Claude Code's
        # rather than something this repo pins, so absent has to be ordinary.
        payloads: list[dict[str, Any]] = [
            {},
            {"questions": []},
            {"questions": "not a list"},
            {"plan": None},
        ]
        for payload in payloads:
            for name in ("AskUserQuestion", "ExitPlanMode"):
                self.assertEqual(
                    "", claude_data.input_summary(self._block(name, payload), limit=160)
                )

    def test_a_pending_question_carries_its_text_through_the_transcript_read(self) -> None:
        record = {
            "type": "assistant",
            "timestamp": "2026-01-01T00:00:00+00:00",
            "message": {
                "role": "assistant",
                "content": [
                    self._block(
                        "AskUserQuestion", {"questions": [{"question": "Force push to main?"}]}
                    )
                ],
            },
        }
        with tempfile.TemporaryDirectory() as tmp:
            transcript = Path(tmp) / "session.jsonl"
            transcript.write_text(json.dumps(record) + "\n")
            config, state = runtime()
            info = claude_data.analyze_transcript(config, state, str(transcript))
        self.assertEqual("Force push to main?", info["pending_input_tool"]["asks"])


class QuestionOnTheRowTest(RuntimeTestCase):
    """The seam between the parse and the row, which nothing else covers."""

    def _row(self, tmp: str, payload: Any) -> dict[str, Any]:
        projects = Path(tmp) / "projects"
        project = projects / "-w-proj"
        project.mkdir(parents=True)
        transcript = project / "abcdef12-0000-0000-0000-000000000000.jsonl"
        transcript.write_text(
            json.dumps(
                {
                    "type": "assistant",
                    "timestamp": datetime.fromtimestamp(time.time() - 120, UTC).isoformat(),
                    "message": {
                        "role": "assistant",
                        "content": [
                            {
                                "type": "tool_use",
                                "id": "q-1",
                                "name": "AskUserQuestion",
                                "input": payload,
                            }
                        ],
                    },
                }
            )
            + "\n"
        )
        with (
            store_patch(PROJECTS_DIR=str(projects)),
            store_patch(TASKS_DIR=str(projects / "tasks")),
        ):
            sessions = collect()["sessions"]
        return next(s for s in sessions if s["sid"].startswith("abcdef12"))

    def test_the_question_reaches_the_row(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            row = self._row(tmp, {"questions": [{"question": "Force push to main?"}]})
        self.assertEqual("needs_input", row["state"])
        self.assertTrue(
            row["state_detail"].startswith("Force push to main?, waiting"),
            row["state_detail"],
        )

    def test_a_record_carrying_no_question_keeps_the_old_wording(self) -> None:
        # The record reaches disk on no schedule and its shape is Claude Code's,
        # so absent has to read as ordinary rather than as an empty row.
        with tempfile.TemporaryDirectory() as tmp:
            row = self._row(tmp, {})
        self.assertEqual("needs_input", row["state"])
        self.assertTrue(
            row["state_detail"].startswith("open question (AskUserQuestion), waiting"),
            row["state_detail"],
        )


class ClaudeInstructionTest(unittest.TestCase):
    """The line beneath a Claude session title: what it is doing NOW.

    Line 1 is the `ai-title`, which is generated once from the opening prompt and
    never refreshed — 424 of the 425 transcripts carrying two or more of those
    records carry one distinct value — so on a long session it names finished
    work. These fixtures pin the second line that says otherwise.
    """

    @staticmethod
    def _at(offset: float) -> str:
        return (
            datetime.fromtimestamp(1_780_000_000 + offset, UTC).strftime("%Y-%m-%dT%H:%M:%S")
            + ".000Z"
        )

    @classmethod
    def _prompt(cls, offset: float, text: str, **extra: Any) -> dict[str, Any]:
        return {
            "type": "user",
            "timestamp": cls._at(offset),
            "message": {"role": "user", "content": text},
            **extra,
        }

    def read(self, *entries: dict[str, Any]) -> dict[str, Any] | None:
        config, state = make_runtime()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "abcdef12-0000-0000-0000-000000000000.jsonl"
            path.write_text("".join(json.dumps(e) + "\n" for e in entries), encoding="utf-8")
            return claude_data.session_instruction(config, state, str(path))

    def test_the_newest_real_prompt_is_the_line_and_the_opener_is_not(self) -> None:
        # Anchor A from DRC-4266, the strictest of the four readings: the NEWEST
        # real prompt. On the 204-session cohort the title is off-subject against
        # it on 112 of 152 decidable sessions (73.7%), which is exactly the gap
        # this line closes.
        line = self.read(
            self._prompt(0, "Improve the write wall repository discoverability"),
            self._prompt(60, "Now reconcile the harness registry with the docs"),
        )

        assert line is not None
        self.assertEqual("asked", line["label"])
        self.assertEqual("Now reconcile the harness registry with the docs", line["text"])
        self.assertEqual(records.parse_ts(self._at(60)), line["at"])

    def test_a_bare_continuation_falls_back_to_a_labelled_older_prompt(self) -> None:
        # 60 of the 204 cohort (29.4%) have a newest real prompt of six words or
        # fewer. "proceed" published as the current instruction is true and
        # useless; the older line is labelled so it cannot pass for the newest.
        line = self.read(
            self._prompt(0, "Reconcile the harness registry with the docs"),
            self._prompt(60, "proceed"),
        )

        assert line is not None
        self.assertEqual("earlier", line["label"])
        self.assertEqual("Reconcile the harness registry with the docs", line["text"])
        self.assertEqual(records.parse_ts(self._at(0)), line["at"])

    def test_an_injected_shape_is_not_an_instruction(self) -> None:
        # Tag rejection alone is not enough: after it, 306 of 2,868 files (10.7%)
        # still have a newest "prompt" that is not an instruction, and the
        # dominant contaminants — the compaction preamble and the interrupt
        # notice — carry no XML wrapper at all.
        for text in (
            "<task-notification>agent finished</task-notification>",
            "This session is being continued from a previous conversation",
            "[Request interrupted by user]",
            "Another Claude session sent a message: hello",
            "Analyze this conversation and determine the next step",
            "Warmup",
        ):
            with self.subTest(text=text):
                line = self.read(
                    self._prompt(0, "Reconcile the harness registry with the docs"),
                    self._prompt(60, text),
                )

                assert line is not None
                self.assertEqual("Reconcile the harness registry with the docs", line["text"])
                self.assertEqual("asked", line["label"])

    def test_nothing_is_published_when_no_real_prompt_exists(self) -> None:
        self.assertIsNone(
            self.read(
                self._prompt(0, "<task-notification>done</task-notification>"),
                self._prompt(60, "[Request interrupted by user]"),
            )
        )
        self.assertIsNone(self.read())

    def test_a_compaction_boundary_stops_an_older_prompt_being_quoted(self) -> None:
        # Behind the boundary is context the session no longer holds.
        line = self.read(
            self._prompt(0, "Reconcile the harness registry with the docs"),
            self._prompt(30, "compaction summary", isCompactSummary=True),
            self._prompt(60, "proceed"),
        )

        self.assertIsNone(line)

    def test_a_prompt_newer_than_the_boundary_still_reads(self) -> None:
        # The boundary only blocks what is BEHIND it. A compacted session that
        # has since been given real work must still show that work.
        line = self.read(
            self._prompt(0, "Old work from before the compaction"),
            self._prompt(30, "compaction summary", isCompactSummary=True),
            self._prompt(60, "Reconcile the harness registry with the docs"),
        )

        assert line is not None
        self.assertEqual("Reconcile the harness registry with the docs", line["text"])

    def test_a_slash_command_renders_as_the_command_it_was(self) -> None:
        # `prompt_title` already owns this rendering, and routing through it is
        # why line 2 grows no tag-stripping code of its own.
        line = self.read(
            self._prompt(
                0,
                "<command-message>burndown is running</command-message>"
                "<command-name>/burndown</command-name>"
                "<command-args>DRC-4266 and the board</command-args>",
            )
        )

        assert line is not None
        self.assertEqual("asked", line["label"])
        self.assertEqual("/burndown DRC-4266 and the board", line["text"])

    def test_a_bare_slash_command_is_an_instruction_and_not_a_continuation(self) -> None:
        # The word count is the wrong instrument for the one prompt shape that is
        # already explicit: `/release` renders to two words and means a whole
        # workflow. Counting it as a continuation buries what the operator
        # deliberately invoked and shows an older line in its place.
        line = self.read(
            self._prompt(0, "Reconcile the harness registry with the docs"),
            self._prompt(
                60,
                "<command-message>release</command-message>\n<command-name>/release</command-name>",
            ),
        )

        assert line is not None
        self.assertEqual("asked", line["label"])
        self.assertEqual("/release", line["text"])

    def test_a_short_opener_over_a_real_body_is_not_a_continuation(self) -> None:
        # The word count belongs on the BODY, not on `prompt_title`'s line 1.
        # Counting line 1 called 97 of 2,066 local newest prompts bare when the
        # operator had written an instruction, and quoted an older prompt in
        # place of the one they had just sent.
        line = self.read(
            self._prompt(0, "Reconcile the harness registry with the docs"),
            self._prompt(
                60,
                "a backend python test is failing:\n\n"
                "tests/test_quota.py::test_receipt_floor times out on the socket read.\n"
                "Reproduce it, find the cause, and fix it without touching config.py.",
            ),
        )

        assert line is not None
        self.assertEqual("asked", line["label"])
        self.assertTrue(line["text"].startswith("a backend python test is failing:"))

    def test_a_prompt_that_is_mostly_a_pasted_url_is_not_a_continuation(self) -> None:
        # The other half of the same defect, and a one-LINE case, so it is the
        # 140-character clip doing the damage rather than a line break.
        # `shorten_paths` deliberately leaves a URL whole — the repo and issue
        # number in it are the informative part — so a long one eats the whole
        # title budget. The word-count approach would have misclassified the
        # rendered line as a continuation (5 words), but the vocabulary approach
        # correctly identifies it as NOT a continuation (tokens like "open",
        # "reconcile", "every" are not in the continuation vocabulary).
        #
        # What matters is that the FULL prompt still results in "asked" because
        # it contains real work ("reconcile every harness row..."), which the
        # states_work check correctly identifies.
        url = (
            "https://app.notion.com/p/infuseai/The-overview-of-all-your-agents"
            "-work-in-your-head-3b279451d357816e9f2bc7d1a4e0"
        )
        prompt = (
            f"Open {url} and reconcile every harness row in the registry against "
            "what the collectors actually publish, then write up the drift you find."
        )
        probe_config, _probe_state = make_runtime()
        rendered = transcripts.prompt_title(probe_config, prompt, records.INSTRUCTION_CAP_CHARS)
        assert rendered is not None
        # The rendered text contains tokens like "open", "reconcile", "every" that
        # are not in the continuation vocabulary, so it's NOT classified as a bare
        # continuation. This is more accurate than the old word-count approach.
        self.assertFalse(records.bare_continuation(rendered), rendered)

        line = self.read(
            self._prompt(0, "Reconcile the harness registry with the docs"),
            self._prompt(60, prompt),
        )

        assert line is not None
        self.assertEqual("asked", line["label"])
        self.assertTrue(line["text"].startswith("Open "), line["text"])

    def test_a_bare_harness_control_is_refused_and_leaves_the_line_beneath_it(self) -> None:
        # 202 of 1,906 published lines on the local Claude corpus were a bare
        # `/clear`, `/login`, `/plugin` or `/mcp` sitting in the labelled slot,
        # indistinguishable from an instruction. Refusing one leaves the real
        # instruction beneath it standing rather than erasing it — the same
        # behaviour `observer.py` ships for the goal slot (DRC-4265).
        for control in ("/clear", "/login", "/mcp", "/plugin", "/reload-plugins"):
            with self.subTest(control=control):
                line = self.read(
                    self._prompt(0, "Reconcile the harness registry with the docs"),
                    self._prompt(60, f"<command-name>{control}</command-name>"),
                )

                assert line is not None
                self.assertEqual("earlier", line["label"])
                self.assertEqual("Reconcile the harness registry with the docs", line["text"])

    def test_a_bare_skill_invocation_is_the_operators_intent_and_survives(self) -> None:
        # The carve-out #222 measured and this must not undo. The structural rule
        # "a bare command carries no arguments, so it carries no goal" was checked
        # against the same corpus and is wrong: a skill invoked with no arguments
        # is exactly what the operator asked for. Only the measured control names
        # are refused.
        for skill in ("/create-pr", "/compass:compass", "/security-review"):
            with self.subTest(skill=skill):
                line = self.read(
                    self._prompt(0, "Reconcile the harness registry with the docs"),
                    # The recorded shape: a prompt command opens with `<command-message>`.
                    self._prompt(
                        60,
                        f"<command-message>{skill[1:]}</command-message>\n"
                        f"<command-name>{skill}</command-name>",
                    ),
                )

                assert line is not None
                self.assertEqual("asked", line["label"])
                self.assertEqual(skill, line["text"])

    def test_a_local_command_carrying_arguments_is_still_a_control(self) -> None:
        # Reversed by the owner's ruling on DRC-4764, 2026-10-01. This once
        # asserted that `/model opus for the rest` publishes, because the bare-token
        # shape never matches a rendered `/name args`. But a record opening with
        # `<command-name>` is a local command the harness ran itself, with
        # arguments or none: `/compact keep notes` was published as work that way.
        # No `/model` record in the local store carried arguments (0 of 40).
        line = self.read(
            self._prompt(0, "Reconcile the harness registry with the docs"),
            self._prompt(
                60,
                "<command-name>/model</command-name><command-args>opus for the rest</command-args>",
            ),
        )

        assert line is not None
        self.assertEqual("earlier", line["label"])
        self.assertEqual("Reconcile the harness registry with the docs", line["text"])

    def test_the_prompt_is_found_behind_a_bounded_tail(self) -> None:
        # The newest real prompt sits a median 40 KB from EOF but p95 650 KB, so
        # a tail read is not a substitute for the backward walk.
        config, state = make_runtime()
        entries = [self._prompt(0, "Reconcile the harness registry with the docs")]
        entries += [
            {"type": "assistant", "timestamp": self._at(1), "message": {"content": "z" * 900}}
            for _ in range(700)
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "abcdef12-0000-0000-0000-000000000000.jsonl"
            path.write_text("".join(json.dumps(e) + "\n" for e in entries), encoding="utf-8")
            blob = path.read_bytes()
            self.assertNotIn(b"Reconcile the harness", blob[-config.tail_bytes :])
            line = claude_data.session_instruction(config, state, str(path))

        assert line is not None
        self.assertEqual("Reconcile the harness registry with the docs", line["text"])

    def test_a_malformed_transcript_reads_as_nothing_rather_than_raising(self) -> None:
        hostile: list[Any] = [5, "str", [1, 2], {"k": "v"}, None, True]
        for value in hostile:
            with self.subTest(value=repr(value)):
                self.read({"type": "user", "message": value, "timestamp": value})

    def test_a_missing_file_reads_as_nothing(self) -> None:
        config, state = make_runtime()

        self.assertIsNone(
            claude_data.session_instruction(config, state, "/nonexistent/transcript.jsonl")
        )


class ClaudeTitleBoundTest(unittest.TestCase):
    def test_the_generated_title_is_bounded_and_scrubbed_like_every_vendor_string(self) -> None:
        # It reached the payload with no cap and no scrub, the only untrusted
        # vendor string in the runtime that did. Measured harmless on the local
        # corpus, which is why this is hardening rather than a fix — but a row
        # that renders a bidi override says something it does not say.
        config, state = make_runtime()
        hostile = "Improve\u202e the\x07 write wall " + "z" * 300
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "abcdef12-0000-0000-0000-000000000000.jsonl"
            path.write_text(
                json.dumps({"type": "ai-title", "aiTitle": hostile}) + "\n", encoding="utf-8"
            )
            title = claude_data.session_title(config, state, str(path))

        assert title is not None
        self.assertLessEqual(len(title), records.PROMPT_TITLE_CAP_CHARS)
        self.assertNotIn("\u202e", title)
        self.assertNotIn("\x07", title)


class TeamRosterTest(RuntimeTestCase):
    """A member registered in the teams registry that never wrote a transcript.

    The observation behind DRC-4263: three subagents parked on a startup
    permission prompt for 22 minutes, alive in their panes, with no transcript
    between them. Their lead read Working while the operator's message was
    fresh, then Idle, and the project panel then said nothing was going on at
    all. The registry entry is the only thing on disk that knows they exist.
    """

    PARENT = "aaaa1111-0000-0000-0000-000000000000"

    def build(
        self,
        tmp: str,
        members: list[dict[str, Any]],
        *,
        now: float,
        parent_age: float = 600,
    ) -> tuple[Path, Path]:
        proj = Path(tmp) / "projects" / "-Users-test-repo"
        proj.mkdir(parents=True)
        parent_fp = proj / f"{self.PARENT}.jsonl"
        parent_fp.write_text(
            json.dumps(
                {
                    "type": "user",
                    "sessionId": self.PARENT,
                    "timestamp": datetime.fromtimestamp(now - parent_age, UTC).isoformat(),
                    "message": {"role": "user", "content": "build the feature"},
                }
            )
            + "\n"
        )
        os.utime(parent_fp, (now - parent_age, now - parent_age))
        teams = Path(tmp) / "teams" / f"session-{self.PARENT[:8]}"
        teams.mkdir(parents=True)
        (teams / "config.json").write_text(
            json.dumps(
                {
                    "name": f"session-{self.PARENT[:8]}",
                    "leadSessionId": self.PARENT,
                    "members": [
                        {
                            "agentId": f"team-lead@session-{self.PARENT[:8]}",
                            "name": "team-lead",
                            "backendType": "in-process",
                        },
                        *members,
                    ],
                }
            )
        )
        return proj, Path(tmp) / "teams"

    def member(self, name: str, joined_ms: float) -> dict[str, Any]:
        # `int`, and it is load-bearing rather than tidiness (DRC-4332). Callers
        # write `(now - 300) * 1000`, and `claude.py` reads that back with
        # `joined / 1000`. That round trip is lossy at epoch magnitudes -- one
        # ULP of a float near 1.7e9 is about 0.24 microseconds -- so for 1.17%
        # of wall-clock values it yields 299.9999997 rather than 300, and
        # `fmt_duration` floors a five-minute wait to "4m".
        #
        # Truncating here is one-directional: `int` rounds the join DOWN, so the
        # measured wait is never SHORTER than the interval the fixture asked
        # for, and the floor cannot slip a minute at any offset. Widening the
        # fixture off the boundary would have fixed the one assertion; this
        # fixes the shape, which is latent at every exact-minute offset in this
        # file. It is also what a real registry writes: whole milliseconds, not
        # a float.
        #
        # Three unrelated PRs paid for this before anyone reproduced it: the
        # Windows platform test and the Ubuntu coverage job of #256 on
        # 2026-09-02, and the Ubuntu platform test of #267 on 2026-09-05.
        return {
            "agentId": f"{name}@session-{self.PARENT[:8]}",
            "name": name,
            "agentType": "general-purpose",
            "joinedAt": int(joined_ms),
            "backendType": "tmux",
        }

    def collect_one(self, tmp: str, teams: Path, now: float) -> dict[str, Any]:
        with (
            store_patch(PROJECTS_DIR=str(Path(tmp) / "projects")),
            store_patch(TASKS_DIR=str(Path(tmp) / "no-tasks")),
            store_patch(TEAMS_DIR=str(teams)),
        ):
            sessions = collect_claude(now, 24, False)
        self.assertEqual(1, len(sessions))
        return sessions[0]

    def test_a_registered_member_that_never_started_reports_needs_input(self) -> None:
        # The whole defect in one case: two members on the roster, no transcript
        # for either, a lead quiet for ten minutes. Removing the roster read
        # leaves this session idle and unnamed, which is what the dashboard
        # showed.
        now = time.time()
        joined = (now - 1320) * 1000  # 22 minutes ago, in epoch milliseconds
        members = [self.member("evidence-skeptic", joined), self.member("design-skeptic", joined)]
        # Read back from the fixture rather than from `joined`, which is the
        # value BEFORE `member` truncates it to whole milliseconds. Comparing a
        # published number against an intermediate the fixture did not write is
        # how a rounding change reads as a collector defect (DRC-4332).
        written = members[0]["joinedAt"]
        with tempfile.TemporaryDirectory() as tmp:
            _, teams = self.build(tmp, members, now=now)
            session = self.collect_one(tmp, teams, now)

        self.assertEqual("needs_input", session["state"])
        self.assertIn("2 subagents have not started", session["state_detail"])
        self.assertEqual(
            ["design-skeptic", "evidence-skeptic"],
            sorted(agent["name"] for agent in session["subagents"]),
        )
        self.assertEqual(written / 1000, session["blocked_since"])

    def test_one_unstarted_member_is_named_on_the_row(self) -> None:
        # "2 subagents" is not actionable; the name is. A single pending member
        # says which one, and its wait is measured from the join.
        now = time.time()
        with tempfile.TemporaryDirectory() as tmp:
            _, teams = self.build(
                tmp, [self.member("steering-analyst", (now - 300) * 1000)], now=now
            )
            session = self.collect_one(tmp, teams, now)

        self.assertEqual("needs_input", session["state"])
        self.assertEqual("steering-analyst has not started, waiting 5m", session["state_detail"])

    def test_the_wait_label_reads_the_same_at_every_wall_clock_value(self) -> None:
        # The falsifier for DRC-4332, and the reason the fixture truncates.
        #
        # The test above takes ONE reading of `time.time()`, so it exercises one
        # wall-clock fraction out of the whole space and passes on about 98.8%
        # of them. It cannot see the defect it was failing on; only a sweep can.
        # So this drives the production expression -- the fixture's `joinedAt`,
        # the magnitude-scaled conversion in `claude.py`, `age`, and
        # `fmt_duration` -- across a deterministic range of clock values and
        # asserts the label never moves.
        #
        # The sweep is fixed rather than random so a failure is reproducible.
        # Against a float `joinedAt` this range fails at indices 75, 226, 377,
        # 528 and 531, which is what makes it a falsifier rather than a
        # restatement: revert the `int` in `member` and this goes red.
        #
        # Deliberately NOT an end-to-end collect. Six hundred temporary stores
        # would cost more than the whole module does today, and every step
        # between the registry read and the label is shared with the test above,
        # which does run the collector.
        config = cfg()
        for index in range(600):
            now = 1788600000.0 + index * 0.000173
            joined = self.member("steering-analyst", (now - 300) * 1000)["joinedAt"]
            when = joined / 1000 if joined > 1e11 else float(joined)
            label = runtime_sessions.fmt_duration(runtime_sessions.age(config, now, when))
            self.assertEqual("5m", label, f"clock {now!r} (index {index}) read {label}")

    def test_a_member_that_has_written_a_transcript_is_not_pending(self) -> None:
        # The join in its normal form: the child's agentName plus its teamName
        # reassemble the roster's agentId. A member that started is running work
        # and must keep the session Working rather than turn the row red.
        now = time.time()
        iso = datetime.fromtimestamp(now - 5, UTC).isoformat()
        child_id = "bbbb2222-0000-0000-0000-000000000000"
        with tempfile.TemporaryDirectory() as tmp:
            proj, teams = self.build(
                tmp, [self.member("evidence-skeptic", (now - 600) * 1000)], now=now
            )
            (proj / f"{child_id}.jsonl").write_text(
                json.dumps(
                    {
                        "type": "user",
                        "sessionId": child_id,
                        "agentName": "evidence-skeptic",
                        "teamName": f"session-{self.PARENT[:8]}",
                        "timestamp": iso,
                        "message": {"role": "user", "content": "read the evidence"},
                    }
                )
                + "\n"
            )
            session = self.collect_one(tmp, teams, now)

        self.assertEqual("working", session["state"])
        self.assertEqual(["evidence-skeptic"], [a["name"] for a in session["subagents"]])

    def test_a_legacy_hex_member_joins_through_its_own_transcript(self) -> None:
        # Historical members carry a hex agentId and no name at all, and their
        # transcript is agent-<id>.jsonl under the session's subagents/. A join
        # keyed on agentName alone would report every one of them as unstarted.
        now = time.time()
        agent_id = "a1e621a43b4af4fbc"
        with tempfile.TemporaryDirectory() as tmp:
            proj, teams = self.build(
                tmp,
                # Whole milliseconds, for the reason `member` gives above.
                [{"agentId": agent_id, "joinedAt": int((now - 600) * 1000)}],
                now=now,
            )
            subagents = proj / self.PARENT / "subagents"
            subagents.mkdir(parents=True)
            fp = subagents / f"agent-{agent_id}.jsonl"
            fp.write_text(json.dumps({"type": "user", "timestamp": "2026-01-01T00:00:00Z"}) + "\n")
            os.utime(fp, (now - 600, now - 600))
            session = self.collect_one(tmp, teams, now)

        self.assertEqual("idle", session["state"])
        # The member is published as a STARTED agent gone quiet, never as an
        # unstarted one. Asserted on the shape rather than on an empty list
        # because captain-ruling[2026-09-03] gave the lead's own agents the same
        # 24-hour retention its children already had, so a quiet one is now
        # retained and inactive. The join is what this case owns, and a broken
        # join is still loud: it would publish a PENDING element carrying the
        # hex agentId as its name and the join stamp as its start.
        published = session["subagents"]
        self.assertEqual(1, len(published))
        self.assertIs(False, published[0]["active"])
        self.assertNotEqual(agent_id, published[0]["name"])
        self.assertNotEqual((now - 600) * 1000, published[0]["started_at"])

    def test_a_member_that_has_only_just_joined_is_not_reported_yet(self) -> None:
        # Every healthy fan-out passes through this window on its way to a first
        # transcript byte. Without the floor a normal dispatch flashes a red band
        # for a few seconds each time.
        now = time.time()
        with tempfile.TemporaryDirectory() as tmp:
            _, teams = self.build(
                tmp, [self.member("evidence-skeptic", (now - 10) * 1000)], now=now
            )
            session = self.collect_one(tmp, teams, now)

        self.assertEqual("idle", session["state"])
        self.assertEqual([], session["subagents"])

    def test_an_old_roster_does_not_resurrect_a_stale_session(self) -> None:
        # The registry stamps a join and never ages it, so nothing in the file
        # says this team stopped mattering. The display window has to, or a lead
        # that died mid-dispatch holds a red row for as long as it is on the
        # board. Mutation-checked: dropping the upper bound passed the suite.
        now = time.time()
        with tempfile.TemporaryDirectory() as tmp:
            _, teams = self.build(
                tmp,
                [self.member("evidence-skeptic", (now - 40 * 3600) * 1000)],
                now=now,
                parent_age=40 * 3600,
            )
            with (
                store_patch(PROJECTS_DIR=str(Path(tmp) / "projects")),
                store_patch(TASKS_DIR=str(Path(tmp) / "no-tasks")),
                store_patch(TEAMS_DIR=str(teams)),
            ):
                sessions = collect_claude(now, 24, True)

        self.assertEqual(1, len(sessions))
        self.assertEqual("idle", sessions[0]["state"])
        self.assertEqual([], sessions[0]["subagents"])

    def test_the_lead_is_never_a_subagent_of_itself(self) -> None:
        # The lead has no joinedAt and no transcript beyond the session's own,
        # so a roster read that did not exclude it would report every team
        # session as blocked on itself.
        now = time.time()
        with tempfile.TemporaryDirectory() as tmp:
            _, teams = self.build(tmp, [], now=now)
            session = self.collect_one(tmp, teams, now)

        self.assertEqual("idle", session["state"])
        self.assertEqual([], session["subagents"])

    def test_a_broken_registry_is_skipped_rather_than_fatal(self) -> None:
        # Untrusted JSON from a store nothing validates: a truncated file, a
        # members list that is not a list, and a member that is not a dict all
        # arrive from the same directory as the good one. The older layout keeps
        # inboxes with no config.json at all.
        now = time.time()
        with tempfile.TemporaryDirectory() as tmp:
            _, teams = self.build(
                tmp, [self.member("evidence-skeptic", (now - 600) * 1000)], now=now
            )
            (teams / "session-deadbeef").mkdir()
            (teams / "session-deadbeef" / "config.json").write_text("{not json")
            (teams / "session-cafe0000").mkdir()
            (teams / "session-cafe0000" / "config.json").write_text(
                json.dumps({"members": "team-lead"})
            )
            (teams / "session-feed0000").mkdir()
            (teams / "session-feed0000" / "config.json").write_text(
                json.dumps({"members": [42, {"name": "no-id"}]})
            )
            (teams / "5929bca9-740a-498a-ac5f-087ca9f22121" / "inboxes").mkdir(parents=True)
            session = self.collect_one(tmp, teams, now)

        self.assertEqual("needs_input", session["state"])
        self.assertEqual(["evidence-skeptic"], [a["name"] for a in session["subagents"]])

    def test_a_long_member_name_cannot_grow_the_state_line(self) -> None:
        # `state_detail` is the one place a registry label reaches the payload
        # outside `published_agent`, which redacts and then bounds at 70. This
        # round removed the upstream `label[:70]` on the strength of that bound
        # and left this interpolation with none, so an untrusted name of any
        # length went out on `/api/data`, every SSE snapshot and the
        # notification body. Two runs differing only in name length must give
        # the same line length, because both names bound to the same 70.
        # Falsified by: interpolating the raw label, which puts the 200-
        # character arm 130 characters past the 70-character one.
        now = time.time()
        joined = (now - 300) * 1000
        lengths = []
        for size in (70, 200):
            with tempfile.TemporaryDirectory() as tmp:
                _, teams = self.build(tmp, [self.member("n" * size, joined)], now=now)
                lengths.append(len(self.collect_one(tmp, teams, now)["state_detail"]))

        self.assertEqual(lengths[0], lengths[1])
        self.assertEqual(70 + len(" has not started, waiting 5m"), lengths[0])


class DispatchedTeammateTest(RuntimeTestCase):
    """A teammate dispatched into its own pane, as the board must report it.

    The fixtures here are the measured Claude Code 2.1.259 shapes rather than
    invented ones: a top-level transcript opens with untimestamped control
    records, and a teammate's own subagents live under its own session
    directory. Both were read off live stores before these cases were written.
    """

    PARENT = "aaaa1111-0000-0000-0000-000000000000"

    @staticmethod
    def stamp(when: float) -> str:
        return datetime.fromtimestamp(when, UTC).isoformat()

    def project(self, tmp: str, *, now: float, parent_age: float = 600) -> Path:
        proj = Path(tmp) / "projects" / "-Users-test-repo"
        proj.mkdir(parents=True)
        parent_fp = proj / f"{self.PARENT}.jsonl"
        parent_fp.write_text(
            json.dumps(
                {
                    "type": "user",
                    "sessionId": self.PARENT,
                    "timestamp": datetime.fromtimestamp(now - parent_age, UTC).isoformat(),
                    "message": {"role": "user", "content": "build the feature"},
                }
            )
            + "\n"
        )
        os.utime(parent_fp, (now - parent_age, now - parent_age))
        return proj

    def teammate(
        self,
        proj: Path,
        *,
        sid: str,
        name: str,
        stamp: str,
        age: float,
        now: float,
        preamble: bool = False,
        parent_prefix: str | None = None,
    ) -> Path:
        """One classified top-level teammate transcript.

        With ``preamble``, the file opens with the three untimestamped control
        records the harness writes before any turn — the shape that made
        ``started_at`` null for every teammate — so the first usable stamp is at
        record index 3.
        """
        lines: list[str] = []
        if preamble:
            lines += [
                json.dumps({"type": "agent-setting", "agentSetting": "spacedock:ensign"}),
                json.dumps({"type": "mode", "mode": "default"}),
                json.dumps({"type": "permission-mode", "permissionMode": "acceptEdits"}),
            ]
        pref = parent_prefix if parent_prefix is not None else self.PARENT[:8]
        lines.append(
            json.dumps(
                {
                    "type": "user",
                    "sessionId": sid,
                    "agentName": name,
                    "teamName": f"session-{pref}",
                    "timestamp": stamp,
                    "message": {"role": "user", "content": "do the work"},
                }
            )
        )
        fp = proj / f"{sid}.jsonl"
        fp.write_text("\n".join(lines) + "\n")
        os.utime(fp, (now - age, now - age))
        return fp

    def registry(self, tmp: str, members: list[dict[str, Any]]) -> Path:
        teams = Path(tmp) / "teams" / f"session-{self.PARENT[:8]}"
        teams.mkdir(parents=True)
        (teams / "config.json").write_text(
            json.dumps(
                {
                    "name": f"session-{self.PARENT[:8]}",
                    "leadSessionId": self.PARENT,
                    "members": [
                        {
                            "agentId": f"team-lead@session-{self.PARENT[:8]}",
                            "name": "team-lead",
                            "backendType": "in-process",
                        },
                        *members,
                    ],
                }
            )
        )
        return Path(tmp) / "teams"

    def member(
        self, name: str, joined_ms: float, *, is_active: bool | None = None
    ) -> dict[str, Any]:
        entry: dict[str, Any] = {
            "agentId": f"{name}@session-{self.PARENT[:8]}",
            "name": name,
            "agentType": "general-purpose",
            # Whole milliseconds, for the reason `TeamRosterTest.member` gives.
            "joinedAt": int(joined_ms),
            "backendType": "tmux",
        }
        if is_active is not None:
            entry["isActive"] = is_active
        return entry

    def own_agent(self, proj: Path, *, label: str, age: float, now: float) -> Path:
        """One agent the LEAD dispatched itself, under the lead's own directory.

        The same `agent-*.jsonl` plus `.meta.json` pair a teammate's own workers
        use, one level up: this is the population `load_subagents` reads.
        """
        agents = proj / self.PARENT / "subagents"
        agents.mkdir(parents=True, exist_ok=True)
        fp = agents / f"agent-{label}.jsonl"
        fp.write_text(
            json.dumps({"type": "user", "timestamp": self.stamp(now - age), "message": {}}) + "\n"
        )
        (agents / f"agent-{label}.meta.json").write_text(json.dumps({"name": f"{label}-lens"}))
        os.utime(fp, (now - age, now - age))
        return fp

    def collect_one(self, tmp: str, teams: Path | None, now: float) -> dict[str, Any]:
        patches = [
            store_patch(PROJECTS_DIR=str(Path(tmp) / "projects")),
            store_patch(TASKS_DIR=str(Path(tmp) / "no-tasks")),
            store_patch(TEAMS_DIR=str(teams or Path(tmp) / "no-teams")),
        ]
        with patches[0], patches[1], patches[2]:
            sessions = collect_claude(now, 24, False)
        self.assertEqual(1, len(sessions), "a teammate is folded, never a standalone row")
        return sessions[0]

    def test_a_teammate_start_comes_from_the_first_timestamped_record(self) -> None:
        # AC-1. The harness opens a top-level transcript with three
        # untimestamped control records, so reading record 0 alone returned None
        # for every dispatched teammate and the pill rendered no elapsed at all.
        # The expected value is the fixture's own fourth record, not a runtime
        # constant, so the assertion cannot pass by agreeing with the code.
        # Falsified by: restoring the one-line read in transcript_started_at.
        now = time.time()
        stamp = datetime.fromtimestamp(now - 120, UTC).isoformat()
        with tempfile.TemporaryDirectory() as tmp:
            proj = self.project(tmp, now=now)
            self.teammate(
                proj,
                sid="bbbb2222-0000-0000-0000-000000000000",
                name="ensign-one",
                stamp=stamp,
                age=5,
                now=now,
                preamble=True,
            )
            session = self.collect_one(tmp, None, now)

        published = session["subagents"]
        self.assertEqual(["ensign-one"], [a["name"] for a in published])
        self.assertEqual(records.parse_ts(stamp), published[0]["started_at"])

    def test_a_quiet_teammate_stays_published_and_reads_as_not_running(self) -> None:
        # AC-2. The published roster and the state derivation are two different
        # lists. A teammate blocked on its own subagents writes nothing for
        # minutes and must stay on the row; the lead must still read as running
        # exactly one subagent, because DRC-4118 and DRC-4263's AC-3 both forbid
        # a parked child from inflating the parent's state detail.
        # Falsified by: appending the stale child to the fresh-gated list, which
        # flips state_detail to "running 2 subagents".
        now = time.time()
        fresh_stamp = datetime.fromtimestamp(now - 30, UTC).isoformat()
        stale_stamp = datetime.fromtimestamp(now - 3600, UTC).isoformat()
        with tempfile.TemporaryDirectory() as tmp:
            proj = self.project(tmp, now=now)
            self.teammate(
                proj,
                sid="bbbb2222-0000-0000-0000-000000000000",
                name="ensign-live",
                stamp=fresh_stamp,
                age=5,
                now=now,
            )
            self.teammate(
                proj,
                sid="cccc3333-0000-0000-0000-000000000000",
                name="ensign-quiet",
                stamp=stale_stamp,
                age=3600,
                now=now,
            )
            teams = self.registry(
                tmp,
                [
                    self.member("ensign-live", (now - 300) * 1000),
                    self.member("ensign-quiet", (now - 4000) * 1000),
                ],
            )
            session = self.collect_one(tmp, teams, now)

        published = {a["name"]: a for a in session["subagents"]}
        self.assertEqual({"ensign-live", "ensign-quiet"}, set(published))
        self.assertIs(True, published["ensign-live"]["active"])
        self.assertIs(False, published["ensign-quiet"]["active"])
        # Both members have written a transcript, so neither is pending and the
        # roster contributes no extra element.
        self.assertEqual(2, len(session["subagents"]))
        self.assertEqual("working", session["state"])
        self.assertEqual("running 1 subagent", session["state_detail"])

    def test_a_teammates_own_subagents_are_published_under_it(self) -> None:
        # AC-3. The lenses a reviewer spawns live under the reviewer's own
        # session directory, which no call site ever handed to the directory
        # walk. Flattened onto the roster with the teammate named as parent —
        # nesting would let a grandchild orphan into a peer row, which is the
        # rule DRC-4118 settled for Cursor.
        # Falsified by: walking only the lead's transcript, which yields zero
        # grandchildren.
        now = time.time()
        stamp = datetime.fromtimestamp(now - 60, UTC).isoformat()
        lens_stamp = datetime.fromtimestamp(now - 45, UTC).isoformat()
        child_sid = "bbbb2222-0000-0000-0000-000000000000"
        with tempfile.TemporaryDirectory() as tmp:
            proj = self.project(tmp, now=now)
            self.teammate(proj, sid=child_sid, name="ensign-review", stamp=stamp, age=5, now=now)
            lenses = proj / child_sid / "subagents"
            lenses.mkdir(parents=True)
            for label in ("evidence", "design"):
                fp = lenses / f"agent-{label}.jsonl"
                fp.write_text(
                    json.dumps({"type": "user", "timestamp": lens_stamp, "message": {}}) + "\n"
                )
                (lenses / f"agent-{label}.meta.json").write_text(
                    json.dumps({"name": f"{label}-lens"})
                )
                os.utime(fp, (now - 10, now - 10))
            session = self.collect_one(tmp, None, now)

        published = {a["name"]: a for a in session["subagents"]}
        self.assertEqual({"ensign-review", "design-lens", "evidence-lens"}, set(published))
        self.assertIsNone(published["ensign-review"]["parent"])
        self.assertEqual("ensign-review", published["design-lens"]["parent"])
        self.assertEqual("ensign-review", published["evidence-lens"]["parent"])
        self.assertEqual(records.parse_ts(lens_stamp), published["design-lens"]["started_at"])
        # A grandchild is published, never counted into the parent's state: the
        # lead is running one teammate, whatever that teammate is running.
        self.assertEqual("running 1 subagent", session["state_detail"])

    def test_nested_teammate_with_child_parent_prefix_is_published_under_lead(self) -> None:
        # DRC-4347 AC-1, AC-2, AC-3. A teammate whose transcript specifies a
        # teamName pointing to an intermediate child rather than the lead
        # session is resolved to the lead session and published under it,
        # with parent set to the intermediate teammate, and its own subagents
        # flattened beneath it.
        now = time.time()
        stamp = datetime.fromtimestamp(now - 60, UTC).isoformat()
        nested_stamp = datetime.fromtimestamp(now - 50, UTC).isoformat()
        worker_stamp = datetime.fromtimestamp(now - 40, UTC).isoformat()
        child_sid = "bbbb2222-0000-0000-0000-000000000000"
        nested_sid = "cccc3333-0000-0000-0000-000000000000"
        with tempfile.TemporaryDirectory() as tmp:
            proj = self.project(tmp, now=now)
            # Direct teammate of lead (parent = aaaa1111)
            self.teammate(proj, sid=child_sid, name="ensign-review", stamp=stamp, age=5, now=now)
            # Nested teammate dispatched by ensign-review (parent = bbbb2222)
            self.teammate(
                proj,
                sid=nested_sid,
                name="ensign-nested",
                stamp=nested_stamp,
                age=4,
                now=now,
                parent_prefix=child_sid[:8],
            )
            # Nested teammate's own workers
            workers = proj / nested_sid / "subagents"
            workers.mkdir(parents=True)
            wfp = workers / "agent-worker.jsonl"
            wfp.write_text(
                json.dumps({"type": "user", "timestamp": worker_stamp, "message": {}}) + "\n"
            )
            (workers / "agent-worker.meta.json").write_text(json.dumps({"name": "worker-lens"}))
            os.utime(wfp, (now - 10, now - 10))

            session = self.collect_one(tmp, None, now)

        published = {a["name"]: a for a in session["subagents"]}
        self.assertEqual({"ensign-review", "ensign-nested", "worker-lens"}, set(published))
        self.assertIsNone(published["ensign-review"]["parent"])
        self.assertEqual("ensign-review", published["ensign-nested"]["parent"])
        self.assertEqual("ensign-nested", published["worker-lens"]["parent"])
        self.assertEqual(records.parse_ts(nested_stamp), published["ensign-nested"]["started_at"])
        self.assertIs(True, published["ensign-nested"]["active"])

    def test_teammates_sharing_harness_lead_team_name_are_published_under_lead(self) -> None:
        # DRC-4347 AC-4. Claude Code coordinates agent teams under the team
        # coordinator's identifier `teamName: session-<lead-prefix>`. Multiple
        # teammates sharing this teamName all bucket under the lead session.
        now = time.time()
        stamp = datetime.fromtimestamp(now - 60, UTC).isoformat()
        t1_sid = "bbbb2222-0000-0000-0000-000000000000"
        t2_sid = "cccc3333-0000-0000-0000-000000000000"
        with tempfile.TemporaryDirectory() as tmp:
            proj = self.project(tmp, now=now)
            self.teammate(proj, sid=t1_sid, name="ensign-review", stamp=stamp, age=5, now=now)
            self.teammate(proj, sid=t2_sid, name="ensign-build", stamp=stamp, age=4, now=now)
            session = self.collect_one(tmp, None, now)

        published = {a["name"]: a for a in session["subagents"]}
        self.assertEqual({"ensign-review", "ensign-build"}, set(published))
        self.assertIsNone(published["ensign-review"]["parent"])
        self.assertIsNone(published["ensign-build"]["parent"])

    def test_a_quiet_agent_the_lead_dispatched_itself_stays_published(self) -> None:
        # captain-ruling[2026-09-03]. The window gate reached children and
        # grandchildren and left the lead's OWN agents fresh-gated at 90 s, so a
        # lens the lead dispatched directly still vanished the moment it went
        # quiet — the commonest population on this board. All three now share
        # one retention rule: published inside `window_hours`, `active` from
        # `working_threshold_sec`.
        # The fresh-gated list that drives state is untouched, which is the half
        # AC-4 froze: one running lens, so `state_detail` reads one subagent
        # however many quiet ones are retained beside it.
        # Falsified by: restoring the freshness gate on the roster's own-agent
        # arm (the quiet lens disappears), or feeding the retained list into the
        # state derivation ("running 2 subagents", which also fires DRC-4263's
        # pre-existing guard).
        now = time.time()
        with tempfile.TemporaryDirectory() as tmp:
            proj = self.project(tmp, now=now)
            self.own_agent(proj, label="live", age=10, now=now)
            self.own_agent(proj, label="quiet", age=3600, now=now)
            self.own_agent(proj, label="ancient", age=25 * 3600, now=now)
            session = self.collect_one(tmp, None, now)

        published = {a["name"]: a for a in session["subagents"]}
        self.assertEqual({"live-lens", "quiet-lens"}, set(published))
        self.assertIs(True, published["live-lens"]["active"])
        self.assertIs(False, published["quiet-lens"]["active"])
        # An agent the lead ran itself belongs to no teammate.
        self.assertIsNone(published["live-lens"]["parent"])
        self.assertIsNone(published["quiet-lens"]["parent"])
        self.assertEqual("working", session["state"])
        self.assertEqual("running 1 subagent", session["state_detail"])

    def test_the_registry_inactive_flag_demotes_but_never_promotes(self) -> None:
        # Gap 4. Claude Code 2.1.259 retains a finished member and marks it
        # isActive false rather than pruning it. That flag may take a fresh
        # child out of "running"; it may never put a stale one back in, because
        # DRC-4229 keeps transcript freshness authoritative and whether a
        # hard-killed pane clears the flag is unmeasured.
        # Falsified by: reading isActive as the liveness signal in either
        # direction, which flips one of the two assertions below.
        now = time.time()
        fresh_stamp = datetime.fromtimestamp(now - 30, UTC).isoformat()
        stale_stamp = datetime.fromtimestamp(now - 3600, UTC).isoformat()
        with tempfile.TemporaryDirectory() as tmp:
            proj = self.project(tmp, now=now)
            self.teammate(
                proj,
                sid="bbbb2222-0000-0000-0000-000000000000",
                name="ensign-retained",
                stamp=fresh_stamp,
                age=5,
                now=now,
            )
            self.teammate(
                proj,
                sid="cccc3333-0000-0000-0000-000000000000",
                name="ensign-claimed-live",
                stamp=stale_stamp,
                age=3600,
                now=now,
            )
            teams = self.registry(
                tmp,
                [
                    self.member("ensign-retained", (now - 300) * 1000, is_active=False),
                    self.member("ensign-claimed-live", (now - 4000) * 1000, is_active=True),
                ],
            )
            session = self.collect_one(tmp, teams, now)

        published = {a["name"]: a for a in session["subagents"]}
        self.assertIs(
            False, published["ensign-retained"]["active"], "the flag demotes a fresh child"
        )
        self.assertIs(
            False, published["ensign-claimed-live"]["active"], "the flag cannot promote a stale one"
        )

    def steady_state_head_reads(self, tmp: str, *, lenses: int, now: float) -> int:
        """Head reads on the SECOND collection, with `lenses` grandchildren."""
        proj = self.project(tmp, now=now)
        child_sid = "bbbb2222-0000-0000-0000-000000000000"
        self.teammate(
            proj,
            sid=child_sid,
            name="ensign-done",
            stamp=self.stamp(now - 3600),
            age=3600,
            now=now,
        )
        directory = proj / child_sid / "subagents"
        directory.mkdir(parents=True)
        for index in range(lenses):
            fp = directory / f"agent-{index}.jsonl"
            fp.write_text(json.dumps({"type": "user", "timestamp": self.stamp(now - 3600)}) + "\n")
            os.utime(fp, (now - 3600, now - 3600))

        counted = {"reads": 0}
        real = runtime_io.read_prefix_bytes

        def counting(path: str, *, max_bytes: int) -> bytes:
            counted["reads"] += 1
            return real(path, max_bytes=max_bytes)

        with (
            store_patch(PROJECTS_DIR=str(Path(tmp) / "projects")),
            store_patch(TASKS_DIR=str(Path(tmp) / "no-tasks")),
            store_patch(TEAMS_DIR=str(Path(tmp) / "no-teams")),
        ):
            config, state = runtime()
            with mock.patch.object(runtime_io, "read_prefix_bytes", counting):
                claude_collector.collect(config, state, now, 24.0, False)
                counted["reads"] = 0
                rows = claude_collector.collect(config, state, now, 24.0, False)
        self.assertEqual(lenses + 1, len(rows[0]["subagents"]))
        return counted["reads"]

    def test_the_roster_does_not_cost_a_head_read_per_pass(self) -> None:
        # The published roster reaches past the freshness gate, so before the
        # memo it re-read a bounded head per child and per grandchild on every
        # collection: measured at 178 reads a pass on a store of 8 finished
        # teammates of 20 workers each, for a roster that was entirely inactive.
        # Asserted as "does not scale with the roster" rather than as a fixed
        # count, because a few reads recur for an unrelated reason -- a tiny
        # transcript's inconclusive classification is deliberately not cached --
        # and pinning the constant would pin that instead of this.
        # Falsified by: dropping the `state=` argument at either roster call
        # site, which makes the wider roster cost proportionally more.
        now = time.time()
        with tempfile.TemporaryDirectory() as small:
            few = self.steady_state_head_reads(small, lenses=2, now=now)
        with tempfile.TemporaryDirectory() as large:
            many = self.steady_state_head_reads(large, lenses=12, now=now)

        self.assertEqual(few, many, "steady-state head reads must not grow with the roster's size")

    def test_every_published_element_declares_both_new_keys(self) -> None:
        # DRC-4223's rule for this element: always present, null meaning not
        # measured. A pending member has demonstrably not started, so its
        # liveness is measured False rather than unknown.
        now = time.time()
        with tempfile.TemporaryDirectory() as tmp:
            self.project(tmp, now=now)
            teams = self.registry(tmp, [self.member("ensign-pending", (now - 300) * 1000)])
            session = self.collect_one(tmp, teams, now)

        for agent in session["subagents"]:
            self.assertEqual({"name", "model", "started_at", "active", "parent"}, set(agent))
        self.assertEqual(["ensign-pending"], [a["name"] for a in session["subagents"]])
        self.assertIs(False, session["subagents"][0]["active"])
        self.assertIsNone(session["subagents"][0]["parent"])

    def test_a_teammate_blocked_on_live_workers_reads_as_running_and_keeps_lead_working(
        self,
    ) -> None:
        # DRC-4346. A teammate quiet for 300 seconds whose grandchild worker
        # is actively writing reads as running, attributes the worker, and keeps
        # the lead session working with its last activity absorbed.
        now = time.time()
        teammate_stamp = datetime.fromtimestamp(now - 300, UTC).isoformat()
        lens_stamp = datetime.fromtimestamp(now - 5, UTC).isoformat()
        child_sid = "bbbb2222-0000-0000-0000-000000000000"
        with tempfile.TemporaryDirectory() as tmp:
            proj = self.project(tmp, now=now)
            self.teammate(
                proj, sid=child_sid, name="ensign-review", stamp=teammate_stamp, age=300, now=now
            )
            lenses = proj / child_sid / "subagents"
            lenses.mkdir(parents=True)
            lens_fp = lenses / "agent-lens.jsonl"
            lens_fp.write_text(
                json.dumps({"type": "user", "timestamp": lens_stamp, "message": {}}) + "\n"
            )
            (lenses / "agent-lens.meta.json").write_text(json.dumps({"name": "lens-worker"}))
            os.utime(lens_fp, (now - 5, now - 5))
            session = self.collect_one(tmp, None, now)

        published = {a["name"]: a for a in session["subagents"]}
        self.assertEqual({"ensign-review", "lens-worker"}, set(published))
        self.assertIs(True, published["ensign-review"]["active"])
        self.assertIs(True, published["lens-worker"]["active"])
        self.assertEqual("ensign-review", published["lens-worker"]["parent"])
        self.assertEqual("working", session["state"])
        self.assertEqual("running 1 subagent", session["state_detail"])
        self.assertEqual(now - 5, session["last_activity"])

    def test_a_teammate_with_only_stale_workers_reads_as_not_running(self) -> None:
        # DRC-4346. When both teammate and its workers are quiet, the teammate
        # still reads as not running, and does not make the lead read as working.
        now = time.time()
        stale_stamp = datetime.fromtimestamp(now - 300, UTC).isoformat()
        child_sid = "bbbb2222-0000-0000-0000-000000000000"
        with tempfile.TemporaryDirectory() as tmp:
            proj = self.project(tmp, now=now)
            self.teammate(
                proj, sid=child_sid, name="ensign-review", stamp=stale_stamp, age=300, now=now
            )
            lenses = proj / child_sid / "subagents"
            lenses.mkdir(parents=True)
            lens_fp = lenses / "agent-lens.jsonl"
            lens_fp.write_text(
                json.dumps({"type": "user", "timestamp": stale_stamp, "message": {}}) + "\n"
            )
            (lenses / "agent-lens.meta.json").write_text(json.dumps({"name": "lens-worker"}))
            os.utime(lens_fp, (now - 300, now - 300))
            session = self.collect_one(tmp, None, now)

        published = {a["name"]: a for a in session["subagents"]}
        self.assertEqual({"ensign-review", "lens-worker"}, set(published))
        self.assertIs(False, published["ensign-review"]["active"])
        self.assertIs(False, published["lens-worker"]["active"])
        self.assertEqual("idle", session["state"])
        # The lead's fixture transcript records no turn stop, so it does not claim to await you.
        self.assertEqual("last turn not recorded as finished", session["state_detail"])

    def test_published_subagent_roster_is_capped_at_configured_bound(self) -> None:
        # DRC-4348. When a lead runs many workers (294 seen in practice), the
        # published roster is capped at SUBAGENTS_ROSTER_CAP (60) with live
        # workers preserved first, and the excess reported in subagents_omitted.
        now = time.time()
        with tempfile.TemporaryDirectory() as tmp:
            proj = self.project(tmp, now=now)
            # Create 5 live agents (age=10s) and 65 finished agents (age=300s to 1000s)
            for i in range(5):
                self.own_agent(proj, label=f"live-{i}", age=10, now=now)
            for i in range(65):
                # Older agents have larger ages, so smaller started_at
                self.own_agent(proj, label=f"finished-{i}", age=200 + i * 10, now=now)
            session = self.collect_one(tmp, None, now)

        self.assertEqual(runtime_sessions.SUBAGENTS_ROSTER_CAP, len(session["subagents"]))
        self.assertEqual(10, session["subagents_omitted"])
        published_names = {a["name"] for a in session["subagents"]}
        # All 5 live agents must be retained
        for i in range(5):
            self.assertIn(f"live-{i}-lens", published_names)
        # The newest finished agents must be retained over the oldest
        self.assertIn("finished-0-lens", published_names)
        self.assertNotIn("finished-64-lens", published_names)


# The recorded shape of Claude Code's own turn stop: a top-level `system` record with subtype
# `stop_hook_summary`, written when its Stop hooks run, the event a hook stop is stamped from
# (docs/design-reading-a-session.md, "Amended 2026-10-01: a reader's correction and a transcript
# stop", item 2; the scorer's `_transcript_stop` reads the same keys). Fixtures only: every record
# here is written by the test.
TURN_SID = "abcdef12-0000-4000-8000-000000000000"


def _turn_records(stop: float, *after: dict[str, Any], **summary: Any) -> list[dict[str, Any]]:
    def stamp(at: float) -> str:
        return datetime.fromtimestamp(at, UTC).isoformat()

    rows: list[dict[str, Any]] = [
        {
            "type": "user",
            "sessionId": TURN_SID,
            "timestamp": stamp(stop - 40),
            "message": {"role": "user", "content": "add retry to the webhook"},
        },
        {
            "type": "assistant",
            "sessionId": TURN_SID,
            "timestamp": stamp(stop - 0.2),
            "message": {"role": "assistant", "content": [{"type": "text", "text": "Done."}]},
        },
        {
            "type": "system",
            "subtype": "stop_hook_summary",
            "isSidechain": False,
            "preventedContinuation": False,
            "sessionId": TURN_SID,
            "timestamp": stamp(stop),
            **summary,
        },
    ]
    rows.extend(
        {"sessionId": TURN_SID, **row, "timestamp": stamp(row["timestamp"])} for row in after
    )
    return rows


class ClaudeTranscriptTurnStopTest(RuntimeTestCase):
    """A Claude Code turn stop read from the transcript on a board no hook reaches (ui3)."""

    STOP = 0.0

    def setUp(self) -> None:
        super().setUp()
        self.STOP = float(int(time.time()) - 600)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.project = Path(self.tmp.name) / "projects" / "sample"
        self.project.mkdir(parents=True)

    def row_at(self, now: float, rows: list[dict[str, Any]]) -> dict[str, Any]:
        transcript = self.project / f"{TURN_SID}.jsonl"
        transcript.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
        newest = max(records.parse_ts(row["timestamp"]) or 0.0 for row in rows)
        os.utime(transcript, (newest, newest))
        with (
            store_patch(PROJECTS_DIR=str(Path(self.tmp.name) / "projects")),
            store_patch(TASKS_DIR=str(Path(self.tmp.name) / "no-tasks")),
        ):
            return collect_claude(now, 24, False)[0]

    def press(self, row: dict[str, Any], now: float) -> Any:
        from compass_runtime import reading  # noqa: PLC0415 - the press reads the row

        return reading.press_eligibility(row, [], now=now, settle_sec=8.0)

    def test_a_reader_whose_claude_code_session_finished_its_turn_on_a_board_no_hook_reaches_sees_it_idle_and_can_analyze_its_last_turn_once_it_settles(
        self,
    ) -> None:
        from compass_runtime import reading  # noqa: PLC0415 - the press reads the row

        stop = self.STOP
        early = self.row_at(stop + 2, _turn_records(stop))
        self.assertEqual("idle", early["state"])
        self.assertEqual(stop, early["turn_end_at"])
        self.assertIsNone(early["finished_at"])
        settling = self.press(self.row_at(stop + 3, _turn_records(stop)), stop + 3)
        self.assertEqual(reading.WITHHELD_STOP_SETTLING, settling["reason"])
        self.assertEqual(stop + 8.0, settling["until"])
        for later in (stop + 9, stop + 300):
            with self.subTest(at=later - stop):
                row = self.row_at(later, _turn_records(stop))
                self.assertTrue(self.press(row, later)["ok"])
                self.assertEqual(
                    (reading.SCOPE_LAST_TURN, ""),
                    reading.eligibility(
                        row,
                        latest_revision_at=0.0,
                        now=later,
                        settle_sec=8.0,
                        admit_turn_stop=True,
                    ),
                )

    def test_a_reader_whose_session_is_waiting_on_a_permission_is_not_told_its_turn_finished(
        self,
    ) -> None:
        from compass_runtime import reading  # noqa: PLC0415 - the press reads the row

        stop = self.STOP
        rows = _turn_records(stop)[:2]
        rows[1] = {
            **rows[1],
            "message": {
                "role": "assistant",
                "content": [{"type": "tool_use", "id": "t1", "name": "Bash", "input": {}}],
            },
        }
        row = self.row_at(stop + 120, rows)
        self.assertIsNone(row["turn_end_at"])
        # Owner, 2026-10-20: pressable, read up to its last entry as a running session is, and
        # never as a turn that finished.
        self.assertIs(True, self.press(row, stop + 120)["ok"])
        self.assertEqual(
            (reading.SCOPE_MID_FLIGHT, ""),
            reading.eligibility(
                row,
                latest_revision_at=0.0,
                now=stop + 120,
                settle_sec=8.0,
                admit_turn_stop=True,
            ),
        )

    def test_a_summary_written_for_pre_tool_use_hooks_is_not_a_turn_stop(self) -> None:
        """Verifier S2 (ui3): Claude Code 2.1.287's own reader knows a `stop_hook_summary` with
        `hookLabel: "PreToolUse"`, written mid-turn after a tool call and before the tool runs.
        Read as a stop, a long Bash showed Idle and opened a last-turn reading. Only the Stop
        hooks' summary is a stop: the 2.1.287 Stop path writes no `hookLabel`, so an absent
        label and `"Stop"` are admitted and every other label is refused."""
        from compass_runtime import reading  # noqa: PLC0415 - the press reads the row

        stop = self.STOP
        rows = _turn_records(stop, hookLabel="PreToolUse")
        rows[1] = {
            **rows[1],
            "message": {
                "role": "assistant",
                "content": [{"type": "tool_use", "id": "t1", "name": "Bash", "input": {}}],
            },
        }
        for later in (stop + 9, stop + 60):
            with self.subTest(at=later - stop):
                row = self.row_at(later, rows)
                self.assertIsNone(row["turn_end_at"])
                self.assertNotEqual(
                    reading.SCOPE_LAST_TURN,
                    reading.eligibility(
                        row,
                        latest_revision_at=0.0,
                        now=later,
                        settle_sec=8.0,
                        admit_turn_stop=True,
                    )[0],
                )
        self.assertEqual("working", self.row_at(stop + 9, rows)["state"])
        labelled = self.row_at(stop + 9, _turn_records(stop, hookLabel="Stop"))
        self.assertEqual(stop, labelled["turn_end_at"])

    def test_an_interrupted_turn_is_not_a_turn_stop(self) -> None:
        stop = self.STOP
        rows = [
            *_turn_records(stop)[:2],
            {
                "type": "user",
                "sessionId": TURN_SID,
                "timestamp": datetime.fromtimestamp(stop, UTC).isoformat(),
                "message": {
                    "role": "user",
                    "content": [{"type": "text", "text": "[Request interrupted by user]"}],
                },
            },
        ]
        self.assertIsNone(self.row_at(stop + 120, rows)["turn_end_at"])

    def test_an_idle_session_whose_turn_is_not_recorded_as_finished_does_not_say_it_awaits_you(
        self,
    ) -> None:
        # Verifier F3: the header said "awaiting your message" while Drift said the last turn
        # isn't recorded as finished, on the owner's own session. One surface must not claim the
        # session waits on the reader while the other says its turn may still be running.
        stop = self.STOP
        interrupted = [
            *_turn_records(stop)[:2],
            {
                "type": "user",
                "sessionId": TURN_SID,
                "timestamp": datetime.fromtimestamp(stop, UTC).isoformat(),
                "message": {
                    "role": "user",
                    "content": [{"type": "text", "text": "[Request interrupted by user]"}],
                },
            },
        ]
        row = self.row_at(stop + 120, interrupted)
        self.assertEqual("idle", row["state"])
        self.assertIsNone(row["turn_end_at"])
        self.assertEqual("last turn not recorded as finished", row["state_detail"])
        finished = self.row_at(stop + 120, _turn_records(stop))
        self.assertEqual("awaiting your message", finished["state_detail"])

    def kept_going(self, stop: float, **summary: Any) -> list[dict[str, Any]]:
        """A Stop hook that blocked the stop, as Claude Code 2.1.287 writes it.

        Its reason lands as an `isMeta` user record before the summary, the summary says
        `preventedContinuation: false`, and the turn goes on: the model is still generating, so
        no assistant record follows yet (verifier S1, read from the installed bundle).
        """
        rows = _turn_records(stop, **summary)
        meta = {
            "type": "user",
            "isMeta": True,
            "sessionId": TURN_SID,
            "timestamp": datetime.fromtimestamp(stop - 0.05, UTC).isoformat(),
            "message": {"role": "user", "content": "Stop hook feedback: tests still fail"},
        }
        return [*rows[:2], meta, rows[2]]

    def test_a_stop_hook_that_kept_the_turn_going_does_not_open_analyze(self) -> None:
        from compass_runtime import reading  # noqa: PLC0415 - the press reads the row

        stop = self.STOP
        cases: dict[str, dict[str, Any]] = {
            "a blocking hook": {"hookErrors": ["tests still fail"]},
            "a goal not met": {"hookErrors": []},
        }
        for name, summary in cases.items():
            for later in (stop + 9, stop + 40):
                with self.subTest(case=name, at=later - stop):
                    row = self.row_at(later, self.kept_going(stop, **summary))
                    self.assertIsNone(row["turn_end_at"])
                    scope, _ = reading.eligibility(
                        row, latest_revision_at=0.0, now=later, settle_sec=8.0,
                        admit_turn_stop=True,
                    )  # fmt: skip
                    self.assertNotEqual(reading.SCOPE_LAST_TURN, scope)

    def test_a_stop_hook_that_stopped_the_turn_is_a_turn_stop(self) -> None:
        # `preventedContinuation: true` is a hook ending the turn ("Stop hook prevented
        # continuation"), which is a stop, not a turn kept going.
        stop = self.STOP
        row = self.row_at(stop + 120, _turn_records(stop, preventedContinuation=True))
        self.assertEqual(stop, row["turn_end_at"])

    def test_a_new_prompt_after_the_stop_closes_the_last_turn_reading(self) -> None:
        stop = self.STOP
        prompt = {"type": "user", "timestamp": stop + 30, "message": {"content": "and logging"}}
        row = self.row_at(stop + 120, _turn_records(stop, prompt))
        self.assertIsNone(row["turn_end_at"])

    def test_a_subagents_stop_summary_is_not_the_sessions(self) -> None:
        stop = self.STOP
        row = self.row_at(stop + 120, _turn_records(stop, isSidechain=True))
        self.assertIsNone(row["turn_end_at"])

    def test_a_summary_for_another_session_id_is_not_this_sessions_stop(self) -> None:
        stop = self.STOP
        other = "abcdef12-0000-4000-8000-ffffffffffff"
        row = self.row_at(stop + 120, _turn_records(stop, sessionId=other))
        self.assertIsNone(row["turn_end_at"])

    def test_an_away_summary_after_the_stop_leaves_it_standing(self) -> None:
        stop = self.STOP
        away = {"type": "system", "subtype": "away_summary", "timestamp": stop + 200}
        row = self.row_at(stop + 230, _turn_records(stop, away))
        self.assertEqual(stop, row["turn_end_at"])
        # The away_summary wrote the file 30 s ago, which used to turn the row Working.
        self.assertEqual("idle", row["state"])

    def test_a_prompt_inside_the_activity_grace_still_withdraws_it(self) -> None:
        stop = self.STOP
        prompt = {"type": "user", "timestamp": stop + 3, "message": {"content": "and logging"}}
        self.assertIsNone(self.row_at(stop + 120, _turn_records(stop, prompt))["turn_end_at"])

    def test_a_session_a_hook_says_is_waiting_on_you_keeps_its_question(self) -> None:
        # A permission prompt raised after the stop summary: the turn is held, not finished.
        stop = self.STOP
        state_of().hook_notifications[TURN_SID[:8]] = {
            "ts": stop + 50,
            "message": "Claude needs your permission to use Bash",
        }
        row = self.row_at(stop + 120, _turn_records(stop))
        self.assertEqual("needs_input", row["state"])
        self.assertIsNone(row["turn_end_at"])

    def test_work_written_after_the_stop_withdraws_it(self) -> None:
        # A task file the session updated a minute after the summary: the turn
        # did not end there, so the summary does not stand for it.
        stop = self.STOP
        tasks = Path(self.tmp.name) / "no-tasks" / TURN_SID
        tasks.mkdir(parents=True)
        task = tasks / "1.json"
        task.write_text(json.dumps({"id": "1", "subject": "Do it", "status": "pending"}))
        os.utime(task, (stop + 60, stop + 60))
        self.assertIsNone(self.row_at(stop + 120, _turn_records(stop))["turn_end_at"])
        os.utime(task, (stop + 5, stop + 5))
        self.assertEqual(stop, self.row_at(stop + 120, _turn_records(stop))["turn_end_at"])

    def test_a_record_with_no_stamp_or_the_wrong_shape_is_not_a_turn_stop(self) -> None:
        stop = self.STOP
        for change in ({"subtype": "away_summary"}, {"type": "assistant"}, {"sessionId": 7}):
            with self.subTest(change=change):
                row = self.row_at(stop + 120, _turn_records(stop, **change))
                self.assertIsNone(row["turn_end_at"])


class TheTurnStopRecordIsTheScorersRecordTest(unittest.TestCase):
    """`claude_data.is_turn_stop_record` and the scorer's `_transcript_stop`, over one table."""

    # Each row: a change to the summary, the conversation records before it, and the verdict.
    # A `user` record between the last reply and the summary is a hook's or a goal's feedback,
    # which keeps the turn going (verifier S1); a summary with no reply before it vouches for
    # nothing.
    TABLE: tuple[tuple[dict[str, Any], tuple[str, ...], bool], ...] = (
        ({}, ("user", "assistant"), True),
        ({"preventedContinuation": True}, ("user", "assistant"), True),
        ({}, ("user", "assistant", "user"), False),
        ({}, ("assistant", "user"), False),
        ({}, (), False),
        ({"isSidechain": True}, ("assistant",), False),
        ({"subtype": "away_summary"}, ("assistant",), False),
        ({"type": "user"}, ("assistant",), False),
        ({"isSidechain": None}, ("assistant",), False),
        ({"preventedContinuation": None}, ("assistant",), False),
        ({"sessionId": None}, ("assistant",), False),
        # Verifier S2: only the Stop hooks' summary is a stop. 2.1.287's Stop path writes no
        # `hookLabel`; its reader knows a PreToolUse one, written mid-turn.
        ({"hookLabel": "Stop"}, ("user", "assistant"), True),
        ({"hookLabel": "PreToolUse"}, ("user", "assistant"), False),
        ({"hookLabel": "SubagentStop"}, ("user", "assistant"), False),
        ({"hookLabel": None}, ("user", "assistant"), False),
    )

    def test_both_readers_agree_on_every_shape(self) -> None:
        import sys  # noqa: PLC0415 - the scorer is only imported here

        scripts = str(Path(__file__).parents[4] / "scripts")
        if scripts not in sys.path:
            sys.path.insert(0, scripts)
        import mark_abstention  # noqa: PLC0415 - the scorer is only measured here

        stamp = "2026-01-01T00:00:05Z"
        for change, before, expected in self.TABLE:
            replies = [
                {"type": kind, "sessionId": TURN_SID, "timestamp": "2026-01-01T00:00:04Z",
                 "message": {"role": kind, "content": "x"}}
                for kind in before
            ]  # fmt: skip
            record = {
                "type": "system",
                "subtype": "stop_hook_summary",
                "isSidechain": False,
                "preventedContinuation": False,
                "sessionId": TURN_SID,
                "timestamp": stamp,
                **change,
            }
            with self.subTest(change=change, before=before), tempfile.TemporaryDirectory() as tmp:
                after = before[-1] if before else None
                self.assertIs(expected, claude_data.is_turn_stop_record(record, after))
                path = Path(tmp) / "t.jsonl"
                path.write_text("".join(json.dumps(row) + "\n" for row in [*replies, record]))
                scored = mark_abstention._transcript_stop(
                    str(path), TURN_SID[:8], records.parse_ts(stamp) or 0.0
                )
                self.assertIs(expected, scored)
