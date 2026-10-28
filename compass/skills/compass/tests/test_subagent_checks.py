"""DRC-4687 and DRC-4709's subagent item: a subagent's checks and writes are the parent's.

DEC-23's amendment of 2026-09-28 (docs/design-reading-a-session.md) is the ruling. Every
fixture is built from the field shapes in
`docs/captures/claude/subagent-transcript-shapes-2.1.281-macos.jsonl`: a subagent writes its
own transcript at `<session id>/subagents/agent-<id>.jsonl` beside the parent's, every record
in it is a sidechain carrying the parent's `sessionId` and its own `agentId`, and the parent's
Agent result names that id. No text here came from a real transcript.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import heapq
import json
import os
from pathlib import Path
from typing import Any
from unittest import mock

from compass_runtime import http_api, levels, observer, project_context, reading
from compass_runtime import io as runtime_io
from compass_runtime.state import build_runtime_state

from .test_claude_checks import SHORT, SID, START, ClaudeChecksTestCase, Transcript


class Subagent(Transcript):
    """A subagent's own transcript, on the parent's clock, in the recorded shapes."""

    def __init__(self, parent: Transcript, agent_id: str) -> None:
        super().__init__(Path(parent.cwd))
        self.parent = parent
        self.agent_id = agent_id
        # Call ids are disjoint between a parent and its subagents (measured:
        # 245 of 245 sampled subagent files shared none with their parent).
        self.calls = 500 + 100 * len(agent_id)

    def _stamp(self) -> str:
        return self.parent._stamp()

    def _entry(self, kind: str, content: list[dict[str, Any]], **extra: Any) -> dict[str, Any]:
        row = super()._entry(kind, content, **extra)
        row["isSidechain"] = True
        row["agentId"] = self.agent_id
        return row

    def call(self, name: str, tool_input: dict[str, Any], *, sidechain: bool = True) -> str:
        del sidechain
        self.calls += 1
        call_id = f"toolu_sub_{self.agent_id}_{self.calls:03d}"
        self._entry(
            "assistant",
            [
                {
                    "type": "tool_use",
                    "id": call_id,
                    "name": name,
                    "input": tool_input,
                    "caller": {"type": "direct"},
                }
            ],
        )
        return call_id


class SubagentChecksTestCase(ClaudeChecksTestCase):
    NOW = START.timestamp() + 3600

    def setUp(self) -> None:
        super().setUp()
        patcher = mock.patch.object(observer.CodexGoalModel, "__call__", return_value=None)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.subagents: list[tuple[Subagent, Path]] = []

    def delegate(self, agent_id: str = "a1b2c3d4e5f60718", *, layout: str = "") -> Subagent:
        """The parent's Agent call, and the subagent transcript it starts."""
        self.agent_call = self.session.call(
            "Agent", {"description": "Run the tests", "prompt": "Run the tests."}
        )
        sub = Subagent(self.session, agent_id)
        sub.prompt("Run the tests.")
        base = self.path.with_suffix("") / "subagents"
        folder = base / layout if layout else base
        self.subagents.append((sub, folder / f"agent-{agent_id}.jsonl"))
        return sub

    def returns(self, sub: Subagent) -> None:
        """The parent's Agent result, which names the subagent's id."""
        self.session.result(
            self.agent_call,
            [{"type": "text", "text": "Done."}],
            tool_use_result={"agentId": sub.agent_id, "status": "completed"},
        )

    def save_all(self) -> None:
        self.session.save(self.path)
        for sub, path in self.subagents:
            sub.save(path)

    def read(self) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        self.save_all()
        return project_context.claude_tool_reports(self.config, str(self.path), SHORT)

    def collect(self) -> dict[str, Any]:
        """`collect` for the focused parent session, as `WhereTheChecksGoOnceCollected` runs it."""
        self.save_all()
        state = build_runtime_state(self.config, started=self.NOW)
        row = {
            "project": "billing",
            "harness": "claude",
            "sid": SHORT,
            "last_activity": self.NOW,
            "active": True,
        }
        return project_context.collect(
            self.config, state, [row], "billing", now=self.NOW, focus=("claude", SHORT)
        )

    def live(self, *lines: str) -> levels.Level:
        """The live estimate over what `collect` publishes for the session."""
        context = self.collect()
        facts = tuple(f for f in context["semantic"]["facts"] if f.get("type") == "tool_report")
        scan = context["sources"]["work"]["tool_reports"][0]
        return levels.live_level(
            levels.Evidence(facts=facts, scan=scan, unsettled_directions=0, cwd=str(self.cwd)),
            levels.Intent(
                saved=True, goal="Add retry with backoff", lines=lines or ("Tests pass",)
            ),
        )


class ASubagentsCheckIsTheParents(SubagentChecksTestCase):
    def test_clipped_parent_agent_result_withholds_without_claiming_a_paired_child(self) -> None:
        agent = self.session.call("Agent", {"prompt": "Run checks"})
        self.session.result(agent, "Done", tool_use_result={"agentId": "a1b2c3d4"})
        self.session.bash("pytest", "5 passed", is_error=False)
        self.session.save(self.path)
        raw = self.path.read_bytes()
        result = json.dumps(self.session.rows[-3]).encode()
        # Begin one byte before the result: the earlier Agent call is outside
        # the bounded tail, while its result and the passing check remain.
        cap = len(raw) - raw.index(result) + 1
        self.config = dataclasses.replace(self.config, turn_scan_max_bytes=cap)

        events, scan = project_context.claude_tool_reports(self.config, str(self.path), SHORT)
        check = next(row for row in events if row["subject"] == "check")
        self.assertEqual(0, scan["subagent_transcripts_unread"])
        self.assertTrue(check["read_incomplete"])
        press = project_context.claude_check_press(self.config, str(self.path))
        self.assertIn((check["record_id"], check["title"]), press.read_incomplete)
        self.assertEqual(levels.NOT_ENOUGH, self.live().level)

    def test_a_subagents_check_appears_on_the_parent_labelled_as_the_subagents(self) -> None:
        sub = self.delegate()
        sub.bash("pytest", "5 passed in 0.2s", is_error=False)
        self.returns(sub)

        events, scan = self.read()

        checks = [e for e in events if e["subject"] == "check"]
        self.assertEqual(1, len(checks), events)
        self.assertEqual("passed", checks[0]["result"])
        self.assertEqual("subagent", checks[0]["worker_kind"])
        self.assertEqual(("claude", SHORT), (checks[0]["harness"], checks[0]["sid"]))
        self.assertEqual(1, scan["check_runs"])
        self.assertEqual(1, scan["subagent_transcripts"])

    def test_a_named_child_without_a_transcript_withholds_every_parent_pass(self) -> None:
        self.session.bash("pytest", "5 passed", is_error=False)
        missing = self.delegate()
        self.returns(missing)
        self.session.bash("ruff check .", "All checks passed!", is_error=False)
        self.session.save(self.path)
        events, scan = project_context.claude_tool_reports(self.config, str(self.path), SHORT)
        passes = [e for e in events if e["subject"] == "check"]
        self.assertEqual(1, scan["subagent_transcripts_unread"])
        self.assertEqual(2, len(passes))
        self.assertTrue(all(e["read_incomplete"] for e in passes))
        press = project_context.claude_check_press(self.config, str(self.path))
        self.assertEqual({e["record_id"] for e in passes}, {i for i, _ in press.read_incomplete})
        self.save_all = lambda: None  # type: ignore[method-assign]
        self.assertEqual(levels.NOT_ENOUGH, self.live().level)

    def test_a_named_child_without_a_transcript_makes_the_command_counts_a_floor(self) -> None:
        self.session.bash("make deploy", "done", is_error=False)
        self.session.bash("ls -la", "", is_error=False)
        self.returns(self.delegate())
        self.session.save(self.path)
        _events, scan = project_context.claude_tool_reports(self.config, str(self.path), SHORT)
        self.assertEqual(1, scan["subagent_transcripts_unread"])
        # The scan read its whole transcript, so nothing marks it as cut; the child's own commands
        # are what it could not count, which makes the counts a lower bound all the same.
        self.assertNotIn("reads_from", scan)
        context = {
            "sources": {"work": {"tool_reports": [{"harness": "claude", "sid": SHORT, **scan}]}}
        }
        counts = http_api._command_counts_of(context, "claude", SHORT)
        self.assertGreater(counts["other_commands"], 0)
        self.assertIs(True, counts["commands_floor"])
        # With every child read, the same counts stay exact.
        exact = {**scan, "subagent_transcripts_unread": 0}
        whole = {
            "sources": {"work": {"tool_reports": [{"harness": "claude", "sid": SHORT, **exact}]}}
        }
        self.assertNotIn("commands_floor", http_api._command_counts_of(whole, "claude", SHORT))

    def test_repeated_legacy_task_result_counts_one_missing_child(self) -> None:
        self.session.bash("pytest", "5 passed", is_error=False)
        call = self.session.call("Task", {"prompt": "Run checks"})
        for _ in range(2):
            self.session.result(call, "Done", tool_use_result={"agentId": "a1b2c3d4"})
        events, scan = self.read()
        self.assertEqual(1, scan["subagent_transcripts_unread"])
        self.assertTrue(next(e for e in events if e["subject"] == "check")["read_incomplete"])

    def test_unpaired_and_invalid_agent_ids_do_not_invent_missing_work(self) -> None:
        self.session.bash("pytest", "5 passed", is_error=False)
        unrelated = self.session.call("Bash", {"command": "ls"})
        self.session.result(unrelated, "", tool_use_result={"agentId": "a1b2c3d4"})
        agent = self.session.call("Agent", {"prompt": "Run checks"})
        self.session.result(agent, "agentId feedface", tool_use_result={"agentId": "not-hex"})
        events, scan = self.read()
        self.assertEqual(0, scan["subagent_transcripts_unread"])
        self.assertFalse(next(e for e in events if e["subject"] == "check")["read_incomplete"])

    def test_equal_call_and_result_times_keep_the_parent_first(self) -> None:
        parent_id = self.session.bash("pytest", "5 passed", is_error=False)
        sub = self.delegate()
        sub_id = sub.bash("pytest", "1 failed", is_error=True)
        self.returns(sub)
        # The two independent streams can record calls and results at one instant.
        parent_call = next(
            r
            for r in self.session.rows
            if r["type"] == "assistant" and r["message"]["content"][0].get("id") == parent_id
        )
        parent_result = next(
            r
            for r in self.session.rows
            if r["type"] == "user" and r["message"]["content"][0].get("tool_use_id") == parent_id
        )
        sub_call = next(r for r in sub.rows if r["type"] == "assistant")
        sub_result = next(
            r
            for r in sub.rows
            if r["type"] == "user" and r["message"]["content"][0].get("tool_use_id") == sub_id
        )
        sub_call["timestamp"] = parent_call["timestamp"]
        sub_result["timestamp"] = parent_result["timestamp"]
        check = next(e for e in self.read()[0] if e["subject"] == "check")
        self.assertEqual(
            ("failed", sub_id, "subagent"),
            (check["result"], check["record_id"], check["worker_kind"]),
        )
        press = project_context.claude_check_press(self.config, str(self.path))
        self.assertIn(sub_id, press.tails)
        self.assertNotIn(parent_id, press.tails)
        merge = heapq.merge

        def reversed_streams(*streams: Any, **kwargs: Any) -> Any:
            return merge(*reversed(streams), **kwargs)

        with mock.patch.object(heapq, "merge", side_effect=reversed_streams):
            mutant = next(e for e in self.read()[0] if e["subject"] == "check")
        self.assertEqual(parent_id, mutant["record_id"])

    def test_the_parents_own_check_carries_no_subagent_label(self) -> None:
        self.session.bash("pytest", "5 passed", is_error=False)
        sub = self.delegate()
        sub.bash("ruff check .", "All checks passed!", is_error=False)
        self.returns(sub)
        found = {e["title"]: e for e in self.read()[0] if e["subject"] == "check"}
        self.assertNotIn("worker_kind", found["pytest"])
        self.assertEqual("subagent", found["ruff check ."]["worker_kind"])

    def test_a_reader_sees_the_subagent_named_in_the_source_line(self) -> None:
        """The page shows no worker label, so the source line carries it (owner, 2026-09-28)."""
        self.session.bash("pytest", "5 passed", is_error=False)
        sub = self.delegate()
        sub.bash("ruff check .", "All checks passed!", is_error=False)
        sub.edit(self.file("src/retry.py"))
        self.returns(sub)
        found = {e["title"]: e["source"] for e in self.read()[0]}
        self.assertEqual("Claude Bash call and paired result", found["pytest"])
        self.assertEqual("Claude subagent Bash call and paired result", found["ruff check ."])
        self.assertEqual("Claude subagent Edit call", found["src/retry.py"])

    def test_the_label_reaches_the_published_fact(self) -> None:
        sub = self.delegate()
        sub.bash("pytest", "5 passed", is_error=False)
        self.returns(sub)
        facts = [f for f in self.collect()["semantic"]["facts"] if f.get("subject") == "check"]
        self.assertEqual(["subagent"], [f.get("worker_kind") for f in facts])
        self.assertEqual({"harness": "claude", "sid": SHORT}, facts[0]["source_session"])

    def test_a_subagents_failing_check_makes_the_parents_live_level_high(self) -> None:
        self.session.bash("pytest", "5 passed", is_error=False)
        sub = self.delegate()
        sub.bash("npm test", "Tests: 1 failed, 4 passed", is_error=True)
        self.returns(sub)
        got = self.live()
        self.assertEqual(levels.HIGH, got.level, got)
        self.assertIn(levels.REASON_FAILED_CHECK, got.reasons)

    def test_one_check_run_in_both_is_one_check_and_the_latest_result_wins(self) -> None:
        self.session.bash("pytest", "1 failed, 4 passed", is_error=True)
        sub = self.delegate()
        sub.bash("pytest", "5 passed", is_error=False)
        self.returns(sub)
        events, scan = self.read()
        checks = [e for e in events if e["subject"] == "check"]
        self.assertEqual(1, len(checks), checks)
        self.assertEqual("passed", checks[0]["result"])
        self.assertIs(True, checks[0]["earlier_failed"])
        self.assertEqual("subagent", checks[0]["worker_kind"])
        self.assertEqual(2, scan["check_runs"])
        self.assertEqual(1, scan["distinct_checks"])

    def test_a_parent_rerun_after_a_subagents_failure_supersedes_it(self) -> None:
        sub = self.delegate()
        sub.bash("pytest", "1 failed, 4 passed", is_error=True)
        self.returns(sub)
        self.session.bash("pytest", "5 passed", is_error=False)
        check = next(e for e in self.read()[0] if e["subject"] == "check")
        self.assertEqual("passed", check["result"])
        self.assertIs(True, check["earlier_failed"])
        self.assertNotIn("worker_kind", check)

    def test_a_check_delegated_reads_no_higher_than_the_same_check_run_by_the_parent(
        self,
    ) -> None:
        # DRC-4687's third criterion: the same work, delegated or not, reads alike.
        self.session.edit(self.file("src/retry.py"))
        sub = self.delegate()
        sub.bash("pytest", "5 passed", is_error=False)
        self.returns(sub)
        delegated = self.live()

        self.setUp()
        self.session.edit(self.file("src/retry.py"))
        self.session.bash("pytest", "5 passed", is_error=False)
        own = self.live()

        self.assertEqual(own.level, delegated.level)
        self.assertEqual(own.reasons, delegated.reasons)

    def test_a_workflow_agent_under_its_run_is_read_too(self) -> None:
        sub = self.delegate("0f1e2d3c4b5a6978", layout="workflows/wf_0001-abc")
        sub.bash("pytest", "1 failed", is_error=True)
        self.returns(sub)
        check = next(e for e in self.read()[0] if e["subject"] == "check")
        self.assertEqual("failed", check["result"])
        self.assertEqual("subagent", check["worker_kind"])

    def test_a_forked_context_is_not_a_subagent_and_is_not_read_twice(self) -> None:
        # Compaction, an aside question and a prompt suggestion replay the
        # parent's context under the parent's own call ids (measured: 15 of 16
        # aside questions and 21 of 39 compactions with calls shared them).
        self.session.bash("pytest", "5 passed", is_error=False)
        for name in ("acompact-9a8b7c6d5e4f3a2b", "aside_question-1a2b3c4d5e6f7a8b"):
            fork = Subagent(self.session, name)
            fork.bash("pytest", "1 failed", is_error=True)
            fork.edit(self.file("src/retry.py"))
            folder = self.path.with_suffix("") / "subagents"
            self.subagents.append((fork, folder / f"agent-{name}.jsonl"))
        events, scan = self.read()
        check = next(e for e in events if e["subject"] == "check")
        self.assertEqual("passed", check["result"])
        self.assertIs(False, check["before_last_change"])
        self.assertEqual(0, scan["subagent_transcripts"])
        self.assertEqual([], [e for e in events if e["subject"] == "write"])


class ASubagentsWritesAreTheParents(SubagentChecksTestCase):
    def worker_in(self, folder: Path, agent_id: str) -> Subagent:
        """A subagent whose own records carry `folder`, as a worktree checkout does."""
        folder.mkdir(parents=True, exist_ok=True)
        sub = self.delegate(agent_id)
        sub.cwd = str(folder)
        return sub

    def test_two_subagents_writing_one_relative_path_in_their_own_folders_stay_two(self) -> None:
        for name in ("a1b2c3d4e5f60718", "b1c2d3e4f5a60718"):
            sub = self.worker_in(self.cwd / "checkouts" / name[:2], name)
            call_id = sub.call("Edit", {"file_path": "src/main.py", "old_string": "a"})
            sub.result(call_id, "updated")
            self.returns(sub)
        events, scan = self.read()
        self.assertEqual(
            ["checkouts/a1/src/main.py", "checkouts/b1/src/main.py"],
            sorted(e["title"] for e in events if e["subject"] == "write"),
        )
        self.assertEqual(2, scan["written_paths"])

    def test_two_subagents_writing_one_absolute_path_keep_one_file(self) -> None:
        for name in ("a1b2c3d4e5f60718", "b1c2d3e4f5a60718"):
            self.worker_in(self.cwd / "checkouts" / name[:2], name).edit(self.file("src/main.py"))
        events, scan = self.read()
        self.assertEqual(["src/main.py"], [e["title"] for e in events if e["subject"] == "write"])
        self.assertEqual(1, scan["written_paths"])

    def test_a_subagent_checkout_outside_the_session_directory_is_counted_not_listed(self) -> None:
        for name in ("a1b2c3d4e5f60718", "b1c2d3e4f5a60718"):
            sub = self.worker_in(self.root / "elsewhere" / name[:2], name)
            call_id = sub.call("Edit", {"file_path": "src/main.py", "old_string": "a"})
            sub.result(call_id, "updated")
        events, scan = self.read()
        self.assertEqual([], [e for e in events if e["subject"] == "write"])
        self.assertEqual(2, scan["outside_paths"])
        self.assertEqual(0, scan["written_paths"])

    def test_a_subagent_write_after_a_parent_pass_ages_the_pass(self) -> None:
        self.session.bash("pytest", "5 passed", is_error=False)
        sub = self.delegate()
        sub.edit(self.file("src/retry.py"))
        self.returns(sub)
        events, scan = self.read()
        check = next(e for e in events if e["subject"] == "check")
        self.assertIs(True, check["before_last_change"])
        writes = [e for e in events if e["subject"] == "write"]
        self.assertEqual(["src/retry.py"], [w["title"] for w in writes])
        self.assertEqual("subagent", writes[0]["worker_kind"])
        self.assertEqual(1, scan["written_paths"])
        got = self.live()
        self.assertNotEqual(levels.NONE_OR_LOW, got.level)
        self.assertIn(levels.REASON_PASS_THEN_WRITE, got.reasons)

    def test_a_parent_write_after_a_subagent_pass_ages_it(self) -> None:
        sub = self.delegate()
        sub.bash("pytest", "5 passed", is_error=False)
        self.returns(sub)
        self.session.edit(self.file("src/retry.py"))
        check = next(e for e in self.read()[0] if e["subject"] == "check")
        self.assertEqual("subagent", check["worker_kind"])
        self.assertIs(True, check["before_last_change"])
        self.assertIn(levels.REASON_PASS_THEN_WRITE, self.live().reasons)

    def test_a_subagent_write_before_the_parents_pass_does_not_age_it(self) -> None:
        sub = self.delegate()
        sub.edit(self.file("src/retry.py"))
        self.returns(sub)
        self.session.bash("pytest", "5 passed", is_error=False)
        check = next(e for e in self.read()[0] if e["subject"] == "check")
        self.assertIs(False, check["before_last_change"])
        self.assertIs(False, check["changed_after"])
        self.assertEqual(levels.NONE_OR_LOW, self.live().level)

    def test_a_subagents_changing_command_after_a_parent_pass_blocks_the_floor(self) -> None:
        self.session.bash("pytest", "5 passed", is_error=False)
        sub = self.delegate()
        sub.bash("sed -i s/a/b/ src/retry.py", "", is_error=False)
        self.returns(sub)
        check = next(e for e in self.read()[0] if e["subject"] == "check")
        self.assertIs(True, check["changed_after"])
        got = self.live()
        self.assertEqual(levels.NOT_ENOUGH, got.level)
        self.assertIn(levels.REASON_CHANGING_COMMAND, got.reasons)

    def test_a_parents_changing_command_after_a_subagent_pass_blocks_the_floor(self) -> None:
        # Binds the merge by call time: read one transcript after the other and
        # the parent's later command would sort before the subagent's pass.
        sub = self.delegate()
        sub.bash("pytest", "5 passed", is_error=False)
        self.returns(sub)
        self.session.bash("touch src/new.py", "", is_error=False)
        check = next(e for e in self.read()[0] if e["subject"] == "check")
        self.assertIs(True, check["changed_after"])
        self.assertIn(levels.REASON_CHANGING_COMMAND, self.live().reasons)

    def test_the_press_reads_the_subagents_change_and_tail_as_the_page_does(self) -> None:
        passed = self.session.bash("pytest", "5 passed", is_error=False)
        sub = self.delegate()
        mine = sub.bash("ruff check .", "All checks passed!", is_error=False)
        sub.bash("touch src/new.py", "", is_error=False)
        self.returns(sub)
        self.save_all()
        press = project_context.claude_check_press(self.config, str(self.path))
        self.assertEqual({passed, mine}, set(press.tails))
        self.assertEqual(
            frozenset({(passed, "pytest"), (mine, "ruff check .")}), press.changed_after
        )

    def test_a_write_by_one_subagent_ages_a_pass_in_another(self) -> None:
        first = self.delegate("aaaa000011112222")
        first.bash("pytest", "5 passed", is_error=False)
        self.returns(first)
        second = self.delegate("bbbb333344445555")
        second.write(self.file("src/other.py"))
        self.returns(second)
        check = next(e for e in self.read()[0] if e["subject"] == "check")
        self.assertIs(True, check["before_last_change"])


class TheFrozenMomentReadsSubagentsToo(SubagentChecksTestCase):
    def freeze(self, seconds: int) -> list[dict[str, Any]]:
        self.save_all()
        until = (START + dt.timedelta(seconds=seconds)).timestamp()
        facts, _press = project_context.frozen_claude_checks(
            self.config, str(self.path), SID, until=until
        )
        return facts

    def test_a_subagent_check_before_the_moment_is_in_it_and_a_later_write_is_not(self) -> None:
        sub = self.delegate()  # Agent call 10 s, subagent prompt 15 s
        sub.bash("pytest", "5 passed", is_error=False)  # 20 s, result 25 s
        sub.edit(self.file("src/retry.py"))  # 30 s, result 35 s
        self.returns(sub)
        at_the_pass = [f for f in self.freeze(27) if f.get("subject") == "check"]
        self.assertEqual(["passed"], [f["result"] for f in at_the_pass])
        self.assertIs(False, at_the_pass[0]["before_last_change"])
        self.assertEqual("subagent", at_the_pass[0]["worker_kind"])
        later = [f for f in self.freeze(40) if f.get("subject") == "check"]
        self.assertIs(True, later[0]["before_last_change"])


class SubagentTranscriptsShareOneBound(SubagentChecksTestCase):
    def test_the_newest_transcripts_are_read_first_and_the_rest_are_counted(self) -> None:
        old = self.delegate("0000aaaa0000aaaa")
        old.bash("npm test", "Tests: 1 failed", is_error=True)
        self.returns(old)
        new = self.delegate("1111bbbb1111bbbb")
        new.bash("pytest", "5 passed", is_error=False)
        self.returns(new)
        self.save_all()
        old_path, new_path = (path for _sub, path in self.subagents)
        # The older transcript is older on disk too, and the bound holds only the newer.
        stamp = START.timestamp()
        os.utime(old_path, (stamp, stamp))
        # Parent first, then exactly the newer transcript; the older is unread.
        self.config = dataclasses.replace(
            self.config, turn_scan_max_bytes=self.path.stat().st_size + new_path.stat().st_size
        )
        events, scan = project_context.claude_tool_reports(self.config, str(self.path), SHORT)
        self.assertEqual(["pytest"], [e["title"] for e in events if e["subject"] == "check"])
        self.assertEqual(1, scan["subagent_transcripts"])
        self.assertEqual(1, scan["subagent_transcripts_unread"])


PAD = "x" * 400


def _last_stamp(path: Path) -> float:
    """The newest record's time, which is where Claude Code leaves the file's mtime."""
    stamps = [
        dt.datetime.fromisoformat(row["timestamp"]).timestamp()
        for row in map(json.loads, path.read_text().splitlines())
    ]
    return max(stamps)


class APassTheBoundCannotVouchForIsNotCurrent(SubagentChecksTestCase):
    """The reads-from horizon: an incomplete read withholds a pass without claiming a change."""

    def settle(self) -> None:
        """Save every transcript with its mtime at its own last record, then keep them."""
        self.save_all()
        for path in (self.path, *(p for _s, p in self.subagents)):
            stamp = _last_stamp(path)
            os.utime(path, (stamp, stamp))
        self.save_all = lambda: None  # type: ignore[method-assign]

    def older_pass_with_the_parents_write_cut(self) -> None:
        self.session.bash("pytest", "5 passed", is_error=False)
        sub = self.delegate()
        sub.edit(self.file("src/retry.py"))
        self.returns(sub)
        self.save_all()
        self.config = dataclasses.replace(self.config, turn_scan_max_bytes=self.path.stat().st_size)

    def test_unread_read_only_work_withholds_without_claiming_a_later_change(self) -> None:
        self.session.bash("pytest", "5 passed", is_error=False)
        sub = self.delegate()
        sub.bash("ls src", "retry.py", is_error=False)
        self.returns(sub)
        self.save_all()
        self.config = dataclasses.replace(self.config, turn_scan_max_bytes=self.path.stat().st_size)
        context = self.collect()
        facts = tuple(f for f in context["semantic"]["facts"] if f.get("type") == "tool_report")
        check = next(f for f in facts if f["subject"] == "check")
        scan = context["sources"]["work"]["tool_reports"][0]
        self.assertEqual(0, scan["written_paths"])
        self.assertIs(False, check["changed_after"])
        self.assertIs(False, check["before_last_change"])
        self.assertIs(True, check.get("read_incomplete"))
        live = self.live()
        self.assertEqual(levels.NOT_ENOUGH, live.level)
        self.assertIn("pass-older-than-read", live.reasons)
        self.assertNotIn("command-after-pass", live.reasons)
        reading_row = {
            "window_start": START.timestamp(),
            "criteria": {
                "line_1": {"result": reading.RESULT_CONSISTENT, "cites": [check["fact_id"]]}
            },
        }
        analysis = levels.analysis_level(
            reading_row,
            levels.Evidence(facts=facts, scan=scan, unsettled_directions=0),
            outcome_lines=1,
        )
        self.assertEqual(levels.NOT_ENOUGH, analysis.level)
        self.assertNotIn("pass-then-write", analysis.reasons)

    def test_a_parent_pass_with_an_unread_child_does_not_meet_the_floor(self) -> None:
        self.older_pass_with_the_parents_write_cut()
        events, scan = self.read()
        check = next(e for e in events if e["subject"] == "check")
        # Withheld, not dropped: the parent's measured pass is still listed.
        self.assertEqual(("pytest", "passed"), (check["title"], check["result"]))
        self.assertIs(True, check["read_incomplete"])
        self.assertEqual(1, scan["subagent_transcripts_unread"])
        got = self.live()
        self.assertEqual(levels.NOT_ENOUGH, got.level, got)
        self.assertNotIn(levels.REASON_FLOOR_MET, got.reasons)

    def test_a_failure_older_than_the_window_is_kept_and_unmarked(self) -> None:
        # Withholding marks passes only: a failure still reads High, and is
        # not said to have been changed after.
        self.session.bash("pytest", "1 failed, 4 passed", is_error=True)
        sub = self.delegate()
        sub.edit(self.file("src/retry.py"))
        self.returns(sub)
        self.save_all()
        self.config = dataclasses.replace(self.config, turn_scan_max_bytes=self.path.stat().st_size)
        check = next(e for e in self.read()[0] if e["subject"] == "check")
        self.assertEqual("failed", check["result"])
        self.assertIs(False, check["read_incomplete"])
        self.assertEqual(levels.HIGH, self.live().level)

    def test_the_press_carries_the_same_withheld_pass(self) -> None:
        self.older_pass_with_the_parents_write_cut()
        self.save_all()
        press = project_context.claude_check_press(self.config, str(self.path))
        self.assertEqual(["pytest"], [title for _id, title in press.read_incomplete])

    def test_the_frozen_moment_withholds_it_too(self) -> None:
        self.older_pass_with_the_parents_write_cut()
        self.save_all()
        facts, press = project_context.frozen_claude_checks(
            self.config, str(self.path), SID, until=self.NOW
        )
        check = next(f for f in facts if f.get("subject") == "check")
        self.assertEqual("passed", check["result"])
        self.assertIs(True, check["read_incomplete"])
        self.assertEqual(["pytest"], [title for _id, title in press.read_incomplete])

    def test_a_parent_only_window_reads_as_it_did(self) -> None:
        # Every pass the parent's own window holds is at or after its oldest record.
        for i in range(20):
            self.session.bash(f"ls dir{i}", PAD, is_error=False)
        self.session.bash("pytest", "5 passed", is_error=False)
        self.config = dataclasses.replace(self.config, turn_scan_max_bytes=6000)
        events, scan = self.read()
        check = next(e for e in events if e["subject"] == "check")
        self.assertIs(False, check["read_incomplete"])
        self.assertIn("reads_from", scan)
        self.assertEqual(levels.NONE_OR_LOW, self.live().level)

    def test_nothing_cut_publishes_no_horizon(self) -> None:
        self.session.bash("pytest", "5 passed", is_error=False)
        sub = self.delegate()
        sub.bash("ruff check .", "All checks passed!", is_error=False)
        self.returns(sub)
        self.assertNotIn("reads_from", self.read()[1])
        self.assertEqual(levels.NONE_OR_LOW, self.live().level)

    def test_an_unread_subagents_write_after_the_pass_withholds_the_floor(self) -> None:
        self.session.bash("pytest", "5 passed", is_error=False)
        old = self.delegate("0000aaaa0000aaaa")
        old.edit(self.file("src/retry.py"))
        self.returns(old)
        new = self.delegate("1111bbbb1111bbbb")
        for i in range(10):
            new.bash(f"cat f{i}", PAD, is_error=False)
        self.returns(new)
        self.settle()
        old_path, new_path = (p for _s, p in self.subagents)
        self.config = dataclasses.replace(
            self.config, turn_scan_max_bytes=self.path.stat().st_size + new_path.stat().st_size
        )
        events, scan = project_context.claude_tool_reports(self.config, str(self.path), SHORT)
        self.assertEqual(1, scan["subagent_transcripts_unread"])
        self.assertEqual(old_path.stat().st_mtime, scan["reads_from"])
        check = next(e for e in events if e["title"] == "pytest")
        self.assertIs(True, check["read_incomplete"])
        self.assertEqual(levels.NOT_ENOUGH, self.live().level)

    def test_a_transcript_that_grew_past_the_bound_while_read_leaves_a_horizon(self) -> None:
        self.session.bash("pytest", "5 passed", is_error=False)
        sub = self.delegate()
        sub.edit(self.file("src/retry.py"))
        self.returns(sub)
        self.save_all()
        sub_path = self.subagents[0][1]
        self.config = dataclasses.replace(self.config, turn_scan_max_bytes=6000)
        self.assertLess(sub_path.stat().st_size, 6000)
        real = runtime_io.scan_reverse_lines

        def grows_first(config: Any, path: str, budget: Any, **kw: Any) -> Any:
            # Appended between the stat and the read: the window now starts
            # after the subagent's edit, which postdates the parent's pass.
            if path == str(sub_path):
                for i in range(20):
                    sub.bash(f"cat f{i}", PAD, is_error=False)
                sub.save(sub_path)
            return real(config, path, budget, **kw)

        with mock.patch.object(runtime_io, "scan_reverse_lines", side_effect=grows_first):
            events, scan = project_context.claude_tool_reports(self.config, str(self.path), SHORT)
        self.assertEqual(0, scan["written_paths"])
        self.assertIs(True, next(e for e in events if e["title"] == "pytest")["read_incomplete"])


class ATranscriptThatYieldsNothingWasNotRead(SubagentChecksTestCase):
    def pass_then_subagent_edit(self) -> None:
        self.session.bash("pytest", "5 passed", is_error=False)
        sub = self.delegate()
        sub.edit(self.file("src/retry.py"))
        self.returns(sub)
        self.save_all()

    def test_one_that_fails_to_open_is_unread_and_withholds_the_floor(self) -> None:
        self.pass_then_subagent_edit()
        real = runtime_io._open_scan_binary

        def refuse(path: str, **kw: Any) -> Any:
            if "subagents" in str(path):
                raise PermissionError(13, "denied", path)
            return real(path, **kw)

        with mock.patch.object(runtime_io, "_open_scan_binary", side_effect=refuse):
            events, scan = project_context.claude_tool_reports(self.config, str(self.path), SHORT)
        self.assertEqual(
            (0, 1), (scan["subagent_transcripts"], scan["subagent_transcripts_unread"])
        )
        self.assertIn("reads_from", scan)
        self.assertIs(True, next(e for e in events if e["subject"] == "check")["read_incomplete"])

    def test_one_whose_only_line_outgrew_the_bound_is_unread(self) -> None:
        self.session.bash("pytest", "5 passed", is_error=False)
        sub = self.delegate()
        sub.bash("cat big", "y" * 20_000, is_error=False)
        self.returns(sub)
        self.save_all()
        sub_path = self.subagents[0][1]
        # Room for the prompt record alone would still be a read, so the bound
        # sits below the newest line: nothing complete fits.
        self.config = dataclasses.replace(self.config, turn_scan_max_bytes=10_000)
        self.assertGreater(sub_path.stat().st_size, 10_000)
        _events, scan = project_context.claude_tool_reports(self.config, str(self.path), SHORT)
        self.assertEqual(
            (0, 1), (scan["subagent_transcripts"], scan["subagent_transcripts_unread"])
        )

    def test_the_frozen_moment_counts_an_unopenable_one_as_unread(self) -> None:
        self.pass_then_subagent_edit()
        real = runtime_io._open_scan_binary

        def refuse(path: str, **kw: Any) -> Any:
            if "subagents" in str(path):
                raise PermissionError(13, "denied", path)
            return real(path, **kw)

        with mock.patch.object(runtime_io, "_open_scan_binary", side_effect=refuse):
            facts, _press = project_context.frozen_claude_checks(
                self.config, str(self.path), SID, until=self.NOW
            )
        check = next(f for f in facts if f.get("subject") == "check")
        self.assertIs(True, check["read_incomplete"])


class ALinkOutOfTheSessionDirectoryIsNotASubagent(SubagentChecksTestCase):
    def outside(self, folder: Path) -> Path:
        folder.mkdir(parents=True)
        other = Subagent(self.session, "feedfacefeedface")
        other.bash("make test", "all passed", is_error=False)
        other.save(folder / "agent-feedfacefeedface.jsonl")
        return folder

    def titles(self) -> list[str]:
        self.session.save(self.path)
        events, _scan = project_context.claude_tool_reports(self.config, str(self.path), SHORT)
        return [e["title"] for e in events if e["subject"] == "check"]

    def test_a_linked_subagents_directory_is_not_read(self) -> None:
        self.session.bash("pytest", "5 passed", is_error=False)
        out = self.outside(self.root / "elsewhere")
        session_dir = self.path.with_suffix("")
        session_dir.mkdir(parents=True)
        os.symlink(out, session_dir / "subagents")
        self.assertEqual(["pytest"], self.titles())

    def test_a_linked_workflow_run_is_not_read(self) -> None:
        self.session.bash("pytest", "5 passed", is_error=False)
        out = self.outside(self.root / "elsewhere")
        runs = self.path.with_suffix("") / "subagents" / "workflows"
        runs.mkdir(parents=True)
        os.symlink(out, runs / "wf_0001-abc")
        self.assertEqual(["pytest"], self.titles())

    def test_a_linked_session_directory_is_followed_as_the_parent_is(self) -> None:
        self.session.bash("pytest", "5 passed", is_error=False)
        out = self.outside(self.root / "elsewhere" / "subagents")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        os.symlink(out.parent, self.path.with_suffix(""))
        self.assertEqual(["make test", "pytest"], sorted(self.titles()))
