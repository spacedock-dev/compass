"""Restart, dedupe, and replacement contracts for semantic work history."""

from __future__ import annotations

import dataclasses
import json
import os
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from compass_runtime import semantic_history
from compass_runtime.config import build_runtime_config
from compass_runtime.state import build_runtime_state


class SemanticHistoryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.config = build_runtime_config(
            environ={"HOME": str(self.root), "COMPASS_HOME": str(self.root / "state")},
            platform_name="linux",
            os_name="posix",
            launcher_path=self.root / "server.py",
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    @staticmethod
    def _fact(
        fact_id: str,
        at: float,
        fact_type: str,
        source_kind: str,
        summary: str,
        work_item_id: str | None,
    ) -> dict[str, object]:
        return {
            "fact_id": fact_id,
            "at": at,
            "type": fact_type,
            "source_kind": source_kind,
            "summary": summary,
            "scope": "session",
            "work_item_id": work_item_id,
            "stage": "shaping",
            "branch": {"harness": "codex", "sid": "root", "record_id": fact_id},
            "evidence": {"source": "structured rollout record", "confidence": "exact"},
        }

    def test_nested_gate_credentials_are_redacted_on_write_and_legacy_reload(self) -> None:
        secret = "cfg_ghp_" + "D" * 36
        fact = self._fact("gate", 100, "gate_decision", "gate", "Approval", "workflow:gate")
        fact.update(stage=secret, decision=secret, target_stage=secret, by="person:captain")
        model = {"facts": [fact], "work_items": []}
        result = semantic_history.update(
            self.config, build_runtime_state(self.config, started=1), "project", model, [], now=105
        )
        with self.subTest(boundary="publication"):
            self.assertNotIn(secret, json.dumps(result))
        path = Path(semantic_history.store_path(self.config))
        with self.subTest(boundary="disk"):
            self.assertNotIn(secret, path.read_text())
        legacy = json.loads(path.read_text())
        legacy["projects"]["project"]["events"][0]["fact"] = fact
        path.write_text(json.dumps(legacy))
        restarted = semantic_history.read(
            self.config, build_runtime_state(self.config, started=106), "project"
        )
        with self.subTest(boundary="legacy reload"):
            self.assertNotIn(secret, json.dumps(restarted))
        with self.subTest(boundary="legacy disk after read alone"):
            self.assertNotIn(secret, path.read_text())
        rewritten = semantic_history.update(
            self.config, build_runtime_state(self.config, started=107), "project", {}, [], now=108
        )
        with self.subTest(boundary="legacy rewrite"):
            self.assertNotIn(secret, path.read_text())
            self.assertEqual("person:captain", rewritten["events"][0]["fact"]["by"])

    def test_a_reader_who_restarts_finds_no_check_or_written_path_in_history(self) -> None:
        # DEC-23 item 6: the checks a Claude Code session ran live in the
        # observed record only. `collect` never hands them to the history
        # source; this is the second wall, should a fact reach `update` anyway.
        check = self._fact("check", 100, "tool_report", "check_run", "pytest -q", None)
        write = self._fact("write", 101, "tool_report", "path_written", "src/retry.py", None)
        person = self._fact("steer", 102, "user_message", "steer", "add retry", None)
        model = {"facts": [check, write, person], "work_items": []}
        result = semantic_history.update(
            self.config, build_runtime_state(self.config, started=1), "project", model, [], now=105
        )
        restarted = semantic_history.read(
            self.config, build_runtime_state(self.config, started=106), "project"
        )
        stored = json.dumps(result) + json.dumps(restarted)
        stored += Path(semantic_history.store_path(self.config)).read_text()
        self.assertIn("add retry", stored)
        self.assertNotIn("pytest", stored)
        self.assertNotIn("src/retry.py", stored)
        self.assertNotIn("tool_report", semantic_history._FACT_EVENT_TYPES)

    def test_a_failed_read_repair_retries_and_cleans_other_projects_too(self) -> None:
        secret = "sk-ant-api03-" + "b" * 93
        path = Path(semantic_history.store_path(self.config))
        path.parent.mkdir(parents=True, exist_ok=True)
        legacy = {
            "v": 1,
            "projects": {
                "project": {"events": [{"summary": secret}], "cursors": {"source": 100}},
                "other": {"events": [{"fact": {"stage": secret}}]},
            },
        }
        path.write_text(json.dumps(legacy))
        state = build_runtime_state(self.config, started=106)

        with (
            patch("compass_runtime.semantic_history.os.replace", side_effect=PermissionError),
            self.assertLogs(semantic_history.__name__, level="WARNING") as logs,
        ):
            result = semantic_history.read(self.config, state, "project")
        self.assertNotIn(secret, json.dumps(result))
        self.assertNotIn(secret, " ".join(logs.output))
        self.assertEqual(legacy, json.loads(path.read_text()))
        self.assertEqual([], list(path.parent.glob("*.tmp")))

        repaired = semantic_history.read(self.config, state, "project")
        self.assertNotIn(secret, path.read_text())
        self.assertEqual({"source": 100}, repaired["cursors"])
        self.assertIn("other", json.loads(path.read_text())["projects"])
        clean_stat = path.stat()
        semantic_history.read(self.config, state, "other")
        self.assertEqual(clean_stat.st_mtime_ns, path.stat().st_mtime_ns)
        self.assertEqual(clean_stat.st_ino, path.stat().st_ino)

    def test_restart_dedupes_replaces_progress_and_suppresses_lifecycle_only(self) -> None:
        # Given: history already contains assignments, progress, a checkpoint, and final output.
        work_item_id = "workflow:project-cockpit"
        facts = [
            self._fact("assign", 10, "work_birth", "task_started", "Shape cockpit", work_item_id),
            self._fact("progress-1", 11, "work_result", "task_result", "First draft", work_item_id),
            self._fact(
                "progress-2", 12, "work_result", "task_result", "Graph visible", work_item_id
            ),
            self._fact("checkpoint", 13, "result", "checkpoint", "Checkpoint fb056", work_item_id),
            self._fact("lifecycle", 14, "task_complete", "task_complete", "worker stopped", None),
        ]
        semantic: dict[str, Any] = {
            "facts": facts,
            "work_items": [
                {
                    "work_item_id": work_item_id,
                    "label": "Project cockpit",
                    "kind": "workflow_item",
                    "source_bindings": [
                        {"source": "structured dispatch artifact", "value": "project-cockpit"}
                    ],
                    "contributor_refs": [],
                }
            ],
        }
        session = {
            "harness": "codex",
            "sid": "root",
            "state": "idle",
            "last_activity": 15.0,
            "title": "Cockpit shaping",
            "last_output": "Ready for review.\nExact bounded final output.",
        }
        first = semantic_history.update(
            self.config,
            build_runtime_state(self.config, started=1),
            "git:project",
            semantic,
            [session],
        )

        # When: update the same project from a restarted runtime.
        restarted = semantic_history.update(
            self.config,
            build_runtime_state(self.config, started=2),
            "git:project",
            semantic,
            [session],
        )

        # Then
        self.assertEqual(first["events"], restarted["events"])
        event_types = [event["event_type"] for event in restarted["events"]]
        self.assertNotIn("task_complete", event_types)
        self.assertEqual(1, event_types.count("progress_head"))
        self.assertIn("checkpoint", event_types)
        self.assertIn("final_output", event_types)
        assignment = next(
            event for event in restarted["events"] if event["event_type"] == "assignment"
        )
        self.assertEqual("shaping", assignment["fact"]["stage"])
        checkpoint = next(
            event for event in restarted["events"] if event["event_type"] == "checkpoint"
        )
        self.assertEqual(work_item_id, checkpoint["work_binding"])
        final = next(
            event for event in restarted["events"] if event["event_type"] == "final_output"
        )
        self.assertEqual("session:codex:root", final["work_binding"])
        self.assertEqual("Ready for review.\nExact bounded final output.", final["fact"]["detail"])
        self.assertTrue(restarted["persisted"])
        self.assertEqual(final["event_id"], restarted["cursors"]["codex:root"]["event_id"])

    def test_final_output_binds_only_through_unique_exact_workflow_alias_and_title(self) -> None:
        work_item_id = semantic_history.workflow_work_item_id("/repo/docs/dev", "9xnaq83nry")
        dispatch = self._fact(
            "dispatch",
            10,
            "prepared_dispatch",
            "prepared_dispatch",
            "The completion-guard error names the failing sub-check",
            work_item_id,
        )
        dispatch["source_session"] = {"harness": "codex", "sid": "root"}
        gate = self._fact(
            "gate",
            11,
            "gate_decision",
            "gate",
            "validation approved",
            work_item_id,
        )
        gate["workflow_entity"] = "9xnaq83nry"
        semantic: dict[str, Any] = {
            "facts": [dispatch, gate],
            "work_items": [
                {
                    "work_item_id": work_item_id,
                    "label": "The completion-guard error names the failing sub-check",
                    "kind": "workflow_item",
                }
            ],
        }
        output = (
            "`9xn` passed validation. A separate authorization is required to push and create "
            "the PR.\n- Title: The completion-guard error names the failing sub-check\n"
            "- Candidate: `d24e90a`\n[9xn](/repo/blob/sha/task.md)\n"
            "Approve pushing this candidate and creating the PR?"
        )
        session = {
            "harness": "codex",
            "sid": "root",
            "state": "idle",
            "last_activity": 12.0,
            "last_output": output,
        }

        result = semantic_history.update(
            self.config,
            build_runtime_state(self.config, started=1),
            "git:project",
            semantic,
            [session],
        )
        final = next(row for row in result["events"] if row["event_type"] == "final_output")

        self.assertEqual(work_item_id, final["work_binding"])
        self.assertEqual(work_item_id, final["fact"]["work_item_id"])
        self.assertEqual("push_pr", final["fact"]["authorization_request"]["kind"])
        self.assertEqual("exact", final["fact"]["result_binding"]["confidence"])

        duplicate = dict(semantic["work_items"][0])
        duplicate["work_item_id"] = semantic_history.workflow_work_item_id(
            "/repo/docs/explore", "9xnother"
        )
        duplicate_dispatch = dict(dispatch)
        duplicate_dispatch["fact_id"] = "dispatch-other"
        duplicate_dispatch["work_item_id"] = duplicate["work_item_id"]
        duplicate_gate = dict(gate)
        duplicate_gate["fact_id"] = "gate-other"
        duplicate_gate["work_item_id"] = duplicate["work_item_id"]
        duplicate_gate["workflow_entity"] = "9xnother"
        ambiguous = semantic_history.update(
            self.config,
            build_runtime_state(self.config, started=2),
            "git:ambiguous",
            {
                "facts": [dispatch, gate, duplicate_dispatch, duplicate_gate],
                "work_items": [semantic["work_items"][0], duplicate],
            },
            [session],
        )
        ambiguous_final = next(
            row for row in ambiguous["events"] if row["event_type"] == "final_output"
        )
        self.assertEqual("session:codex:root", ambiguous_final["work_binding"])

    def test_unchanged_observer_refresh_replaces_freshness_and_change_records_shift(self) -> None:
        state = build_runtime_state(self.config, started=1)

        def model(fact_id: str, at: float, goal: str) -> dict[str, object]:
            return {
                "facts": [self._fact(fact_id, at, "observer_snapshot", "observer", goal, None)],
                "work_items": [],
            }

        first = semantic_history.update(
            self.config, state, "git:project", model("g1", 10, "Ship"), []
        )
        same = semantic_history.update(
            self.config, state, "git:project", model("g2", 20, "Ship"), []
        )
        changed = semantic_history.update(
            self.config, state, "git:project", model("g3", 30, "Review"), []
        )
        self.assertEqual(1, len(first["events"]))
        self.assertEqual(["observed_goal"], [event["event_type"] for event in same["events"]])
        self.assertEqual(
            ["goal_shift", "observed_goal"],
            [event["event_type"] for event in changed["events"]],
        )
        self.assertTrue(all(len(event["summary"]) <= 240 for event in changed["events"]))

    def test_current_workflow_and_generic_children_share_assignment_vocabulary(self) -> None:
        # Given: one exact child has a workflow stage and another has a generic assignment.
        assignments = [
            {
                "name": "Einstein",
                "observer_sid": "child-one",
                "assignment": "Shape cockpit",
                "confidence": "exact",
                "source": "structured dispatch artifact",
                "workflow_entity": "project-cockpit",
                "workflow_stage": "shaping",
                "workflow_binding": "/repo/.spacedock/explore",
            },
            {
                "name": "James",
                "observer_sid": "child-two",
                "assignment": "Review navigation",
                "confidence": "exact",
                "source": "exact parent dispatch",
            },
        ]

        # When: publish both child assignments to semantic history.
        result = semantic_history.update(
            self.config,
            build_runtime_state(self.config, started=1),
            "git:project",
            {"facts": [], "work_items": []},
            [],
            assignments,
            now=100,
        )
        events = result["events"]

        # Then
        self.assertEqual(
            ["stage_transition", "assignment"],
            [event["event_type"] for event in events],
        )
        workflow = next(
            event for event in events if event["work_binding"].endswith(":project-cockpit")
        )
        generic = next(event for event in events if event is not workflow)
        self.assertEqual("shaping", workflow["fact"]["stage"])
        self.assertNotIn("stage", generic["fact"])
        self.assertEqual("one_off", generic["work_item"]["kind"])

    def test_child_assignment_keeps_verified_child_parent_and_task_identity(self) -> None:
        # Given: an exact child assignment names its parent and workflow task.
        assignments = [
            {
                "name": "Banach",
                "observer_sid": "child-one",
                "parent_session": {"harness": "codex", "sid": "root"},
                "assignment": "Shape cockpit",
                "confidence": "exact",
                "source": "structured dispatch artifact",
                "workflow_entity": "project-cockpit",
                "workflow_stage": "shaping",
                "workflow_binding": "/repo/.spacedock/explore",
                "work_item_id": semantic_history.workflow_work_item_id(
                    "/repo/.spacedock/explore", "project-cockpit"
                ),
            }
        ]

        # When: publish the assignment to semantic history.
        result = semantic_history.update(
            self.config,
            build_runtime_state(self.config, started=1),
            "git:project",
            {"facts": [], "work_items": []},
            [],
            assignments,
            now=100,
        )

        fact = result["events"][0]["fact"]

        # Then
        self.assertEqual({"harness": "codex", "sid": "child-one"}, fact["source_session"])
        self.assertEqual({"harness": "codex", "sid": "root"}, fact["parent_session"])
        self.assertEqual(
            {"harness": "codex", "sid": "child-one", "label": "Banach", "verified": True},
            fact["contributor"],
        )
        self.assertEqual(
            semantic_history.workflow_work_item_id("/repo/.spacedock/explore", "project-cockpit"),
            fact["work_item_id"],
        )

    def test_same_entity_slug_in_two_workflows_retains_distinct_exact_bindings(self) -> None:
        # Given: two workflow directories share the same entity slug.
        assignments = [
            {
                "name": name,
                "observer_sid": sid,
                "assignment": f"Shape {workflow}",
                "confidence": "exact",
                "source": "structured dispatch artifact",
                "workflow_entity": "project-cockpit",
                "workflow_stage": "shaping",
                "workflow_binding": f"/repo/.spacedock/{workflow}",
            }
            for name, sid, workflow in (
                ("Einstein", "explore-child", "explore"),
                ("Legacy", "dev-child", "dev"),
            )
        ]

        # When: publish both assignments to semantic history.
        result = semantic_history.update(
            self.config,
            build_runtime_state(self.config, started=1),
            "git:project",
            {"facts": [], "work_items": []},
            [],
            assignments,
            now=100,
        )
        bindings = {event["work_binding"] for event in result["events"]}

        # Then
        self.assertEqual(2, len(bindings))
        self.assertTrue(all(binding.endswith(":project-cockpit") for binding in bindings))
        sources = {event["work_item"]["source_bindings"][0]["value"] for event in result["events"]}
        self.assertEqual(
            {
                "/repo/.spacedock/explore:project-cockpit",
                "/repo/.spacedock/dev:project-cockpit",
            },
            sources,
        )

    def test_rolling_day_prunes_old_events_and_persists_dispatch_relation(self) -> None:
        now = 100_000.0
        work_item_id = "workflow:project-cockpit"
        recent = self._fact(
            "dispatch-recent",
            now - semantic_history.HISTORY_WINDOW_SEC + 1,
            "prepared_dispatch",
            "prepared_dispatch",
            "Project cockpit dispatched",
            work_item_id,
        )
        old = self._fact(
            "dispatch-old",
            now - semantic_history.HISTORY_WINDOW_SEC - 1,
            "prepared_dispatch",
            "prepared_dispatch",
            "Old task dispatched",
            "workflow:old",
        )
        semantic = {
            "facts": [recent, old],
            "work_items": [
                {
                    "work_item_id": work_item_id,
                    "label": "Project cockpit",
                    "kind": "workflow_item",
                },
                {"work_item_id": "workflow:old", "label": "Old task", "kind": "workflow_item"},
            ],
            "relations": [
                {
                    "from": "dispatch-recent",
                    "to": work_item_id,
                    "type": "binds_to",
                    "confidence": "structural",
                }
            ],
        }
        state = build_runtime_state(self.config, started=1)
        first = semantic_history.update(self.config, state, "git:project", semantic, [], now=now)
        duplicate = semantic_history.update(
            self.config, state, "git:project", semantic, [], now=now
        )
        restarted = semantic_history.update(
            self.config,
            build_runtime_state(self.config, started=2),
            "git:project",
            {"facts": [], "work_items": [], "relations": []},
            [],
            now=now,
        )
        self.assertEqual(["dispatch-recent"], [row["event_id"] for row in first["events"]])
        self.assertEqual(first["events"], duplicate["events"])
        self.assertEqual(first["events"], restarted["events"])
        self.assertEqual("binds_to", restarted["events"][0]["relations"][0]["type"])
        self.assertEqual(semantic_history.HISTORY_WINDOW_SEC, restarted["window_sec"])

    def test_operator_promotion_and_gate_application_fields_survive_restart(self) -> None:
        # Given: an unpromoted direction and pending gate have been persisted.
        direction = self._fact(
            "direction", 10, "user_message", "steer", "Keep exact evidence", None
        )
        direction["intent_promoted"] = False
        gate = self._fact(
            "gate", 11, "gate_decision", "gate", "Cockpit approved", "workflow:cockpit"
        )
        gate.update(
            {
                "decision": "approve",
                "by": "person:captain",
                "application_state": "pending",
                "target_stage": "review",
            }
        )
        state = build_runtime_state(self.config, started=1)
        semantic_history.update(
            self.config,
            state,
            "git:project",
            {"facts": [direction, gate], "work_items": []},
            [],
            now=20,
        )

        # When: read history from a restarted runtime.
        restarted = semantic_history.read(
            self.config, build_runtime_state(self.config, started=2), "git:project"
        )
        facts = {event["event_id"]: event["fact"] for event in restarted["events"]}

        # Then
        self.assertFalse(facts["direction"]["intent_promoted"])
        self.assertEqual("pending", facts["gate"]["application_state"])
        self.assertEqual("review", facts["gate"]["target_stage"])

    def test_backfill_cursor_skips_unchanged_and_rescans_bounded_overlap(self) -> None:
        state = build_runtime_state(self.config, started=1)
        signature = {"size": 1_000_000, "mtime_ns": 10}
        cold = semantic_history.backfill_scan_bytes(
            self.config,
            state,
            "git:project",
            "codex:root",
            signature,
            full_max_bytes=2_000_000,
        )
        semantic_history.update(
            self.config,
            state,
            "git:project",
            {"facts": [], "work_items": []},
            [],
            now=100,
            source_scans={"codex:root": signature},
        )
        cached = semantic_history.backfill_scan_bytes(
            self.config,
            state,
            "git:project",
            "codex:root",
            signature,
            full_max_bytes=2_000_000,
        )
        resumed = semantic_history.backfill_scan_bytes(
            self.config,
            state,
            "git:project",
            "codex:root",
            {"size": 1_001_000, "mtime_ns": 11},
            full_max_bytes=2_000_000,
        )
        rotated = semantic_history.backfill_scan_bytes(
            self.config,
            state,
            "git:project",
            "codex:root",
            {"size": 500_000, "mtime_ns": 12},
            full_max_bytes=2_000_000,
        )
        self.assertEqual(1_000_000, cold)
        self.assertEqual(0, cached)
        self.assertEqual(1_000 + semantic_history.RESCAN_OVERLAP_BYTES, resumed)
        self.assertEqual(500_000, rotated)

    def test_a_reader_recovers_a_source_whose_scanned_events_were_evicted(self) -> None:
        state = build_runtime_state(self.config, started=1)
        signature = {"size": 1_000_000, "mtime_ns": 10}
        fact = self._fact("old", 100, "user_message", "steer", "Older direction", None)
        semantic_history.update(
            self.config,
            state,
            "project",
            {"facts": [fact]},
            [],
            now=100,
            source_scans={"codex:root": signature},
        )
        semantic_history.update(
            self.config,
            state,
            "project",
            {},
            [],
            now=100 + semantic_history.HISTORY_WINDOW_SEC + 1,
        )
        self.assertEqual([], semantic_history.read(self.config, state, "project")["events"])
        self.assertEqual(
            1_000_000,
            semantic_history.backfill_scan_bytes(
                self.config,
                state,
                "project",
                "codex:root",
                signature,
                full_max_bytes=2_000_000,
            ),
        )

    def test_a_reader_recovers_a_source_crowded_out_by_a_busier_session(self) -> None:
        state = build_runtime_state(self.config, started=1)
        signature = {"size": 1_000_000, "mtime_ns": 10}
        fact = self._fact("old", 100, "user_message", "steer", "Older direction", None)
        semantic_history.update(
            self.config,
            state,
            "project",
            {"facts": [fact]},
            [],
            now=100,
            source_scans={"codex:root": signature},
        )
        busy = [
            self._fact(f"busy-{n}", 101 + n, "user_message", "steer", "Busy", None)
            for n in range(3)
        ]
        for row in busy:
            row["branch"] = {"harness": "codex", "sid": "sibling"}
        with patch.object(semantic_history, "MAX_EVENTS_PER_PROJECT", 3):
            semantic_history.update(self.config, state, "project", {"facts": busy}, [], now=105)
        self.assertEqual(
            1_000_000,
            semantic_history.backfill_scan_bytes(
                self.config,
                state,
                "project",
                "codex:root",
                signature,
                full_max_bytes=2_000_000,
            ),
        )

    def test_a_reader_rescans_after_a_failed_write_or_an_over_cap_store(self) -> None:
        state = build_runtime_state(self.config, started=1)
        signature = {"size": 1_000_000, "mtime_ns": 10}
        with patch.object(semantic_history, "_write", return_value=False):
            result = semantic_history.update(
                self.config, state, "project", {}, [], source_scans={"codex:root": signature}
            )
        self.assertFalse(result["persisted"])
        self.assertEqual(
            1_000_000,
            semantic_history.backfill_scan_bytes(
                self.config, state, "project", "codex:root", signature, full_max_bytes=2_000_000
            ),
        )
        path = Path(semantic_history.store_path(self.config))
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(
            b'{"v": 1, "projects": {}}' + b" " * self.config.semantic_history_read_cap_bytes
        )
        self.assertEqual(
            1_000_000,
            semantic_history.backfill_scan_bytes(
                self.config, state, "project", "codex:root", signature, full_max_bytes=2_000_000
            ),
        )

    def test_a_reader_does_not_lose_coverage_if_an_incremental_read_outlives_the_store(
        self,
    ) -> None:
        state = build_runtime_state(self.config, started=1)
        fact = self._fact("old", 100, "user_message", "steer", "Older direction", None)
        signature = {"size": 1_000_000, "mtime_ns": 10}
        semantic_history.update(
            self.config,
            state,
            "project",
            {"facts": [fact]},
            [],
            source_scans={"codex:root": signature},
        )
        prior = semantic_history.read(self.config, state, "project")["source_scans"]["codex:root"]
        Path(semantic_history.store_path(self.config)).unlink()
        grown = {"size": 1_001_000, "mtime_ns": 11, "prior_coverage": prior["coverage"]}
        semantic_history.update(
            self.config, state, "project", {}, [], source_scans={"codex:root": grown}
        )
        self.assertEqual(
            1_001_000,
            semantic_history.backfill_scan_bytes(
                self.config,
                state,
                "project",
                "codex:root",
                grown,
                full_max_bytes=2_000_000,
            ),
        )


class HistoryLineageTest(unittest.TestCase):
    """Each project bucket carries a lineage a prune keeps and a loss replaces (DRC-5543).

    A stored check compares its own record against it, so a prune must never look like a loss and
    a loss must never look like a prune.
    """

    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        self.config = build_runtime_config(
            environ={"HOME": str(root), "COMPASS_HOME": str(root / "state")},
            platform_name="linux",
            os_name="posix",
            launcher_path=root / "server.py",
        )
        self.state = build_runtime_state(self.config, started=1)
        self.path = Path(semantic_history.store_path(self.config))

    def update(self, project: str = "p", *, at: float = 100, now: float = 105) -> Any:
        fact = {"fact_id": f"u{at}", "type": "user_message", "summary": "s", "at": at}
        return semantic_history.update(
            self.config, self.state, project, {"facts": [fact]}, [], now=now
        )

    def test_the_first_write_mints_a_lineage_and_each_later_one_keeps_it(self) -> None:
        first = self.update()["mark"]
        second = self.update(at=101)["mark"]
        self.assertRegex(first["lineage"], r"\A[0-9a-f]{32}\Z")
        self.assertEqual(
            ("p", first["lineage"], 1, 2),
            (second["key"], second["lineage"], first["generation"], second["generation"]),
        )

    def test_a_prune_that_empties_the_bucket_keeps_its_lineage(self) -> None:
        first = self.update()["mark"]
        pruned = self.update(at=100, now=100 + semantic_history.HISTORY_WINDOW_SEC + 60)
        self.assertEqual([], pruned["events"])
        self.assertEqual(first["lineage"], pruned["mark"]["lineage"])
        self.assertGreater(pruned["mark"]["generation"], first["generation"])

    def test_a_lost_or_unreadable_file_starts_a_new_lineage(self) -> None:
        cases: dict[str, Any] = {
            "deleted": self.path.unlink,
            "emptied": lambda: self.path.write_text('{"projects": {}}'),
            "corrupt": lambda: self.path.write_text("{"),
            # The same history, intact, and only too big to read: a foreign or damaged writer.
            "oversize": lambda: self.path.write_bytes(
                self.path.read_bytes() + b" " * self.config.semantic_history_read_cap_bytes
            ),
            "rewritten by an older build": lambda: self.path.write_text(
                json.dumps(
                    {
                        "v": 1,
                        "projects": {
                            "p": {
                                key: value
                                for key, value in json.loads(self.path.read_text())["projects"][
                                    "p"
                                ].items()
                                if key not in {"lineage", "generation"}
                            }
                        },
                    }
                )
            ),
        }
        for name, damage in cases.items():
            with self.subTest(history=name):
                before = self.update()["mark"]
                damage()
                after = self.update(at=102)["mark"]
                self.assertNotEqual(before["lineage"], after["lineage"])
                self.assertEqual(1, after["generation"])

    def test_a_read_that_rewrites_a_redaction_never_mints_or_moves_it(self) -> None:
        mark = self.update()["mark"]
        stored = json.loads(self.path.read_text())
        stored["projects"]["p"]["events"][0]["summary"] = "cfg_ghp_" + "D" * 36
        self.path.write_text(json.dumps(stored))
        semantic_history.read(self.config, self.state, "p")
        self.assertNotIn("D" * 36, self.path.read_text())
        self.assertEqual(mark, semantic_history.mark_for(self.config, self.state, "p"))

    def test_joining_a_display_label_keeps_the_lineage_and_moves_the_generation(self) -> None:
        mark = self.update("key")["mark"]
        self.update("label", at=99)
        semantic_history.reconcile_project(self.config, self.state, "key", ("label",))
        joined = semantic_history.mark_for(self.config, self.state, "key")
        assert joined is not None
        self.assertEqual(mark["lineage"], joined["lineage"])
        self.assertGreater(joined["generation"], mark["generation"])

    def test_a_write_that_fails_or_evicts_the_bucket_returns_no_mark(self) -> None:
        with patch.object(semantic_history, "_write", return_value=False):
            self.assertNotIn("mark", self.update())
        for k in range(semantic_history.MAX_PROJECTS):
            self.update(f"newer-{k}", at=200 + k, now=300)
        self.assertNotIn("mark", self.update("p", at=1, now=300))
        self.assertIsNone(semantic_history.mark_for(self.config, self.state, "p"))

    @unittest.skipUnless(os.name == "posix", "requires stat change time")
    def test_the_mark_read_back_parses_the_file_only_after_it_changes(self) -> None:
        mark = self.update()["mark"]
        with patch.object(semantic_history, "_read", wraps=semantic_history._read) as read:
            self.assertEqual(mark, semantic_history.mark_for(self.config, self.state, "p"))
            self.assertEqual(mark, semantic_history.mark_for(self.config, self.state, "p"))
            self.assertEqual(1, read.call_count)
        self.path.unlink()
        self.assertIsNone(semantic_history.mark_for(self.config, self.state, "p"))

    def test_a_same_size_history_rewrite_with_its_old_mtime_has_no_old_mark(self) -> None:
        mark = self.update()["mark"]
        original = self.path.stat()
        self.assertEqual(mark, semantic_history.mark_for(self.config, self.state, "p"))

        empty = b'{"v":1,"projects":{}}'
        self.path.write_bytes(empty.ljust(original.st_size))
        os.utime(self.path, ns=(original.st_atime_ns, original.st_mtime_ns))
        rewritten = self.path.stat()
        self.assertEqual(original.st_ino, rewritten.st_ino)
        self.assertEqual(original.st_size, rewritten.st_size)
        self.assertEqual(original.st_mtime_ns, rewritten.st_mtime_ns)
        self.assertIsNone(semantic_history.mark_for(self.config, self.state, "p"))

    def test_a_bucket_over_the_old_cap_keeps_its_lineage_and_fits_the_cap(self) -> None:
        # 300 facts of about the size a real operator direction files: far past the old 64 KiB.
        marks = []
        for round_ in range(3):
            facts = [
                {
                    "fact_id": f"u{round_}-{k}",
                    "type": "user_message",
                    "summary": "Please also tidy the helpers " + "x" * 200,
                    "at": 100 + round_ * 100 + k * 0.1,
                    "evidence": {"source": "transcript " + "y" * 600, "confidence": "exact"},
                }
                for k in range(100)
            ]
            marks.append(
                semantic_history.update(
                    self.config, self.state, "p", {"facts": facts}, [], now=500
                )["mark"]
            )
        size = self.path.stat().st_size
        self.assertGreater(size, 65_536)
        self.assertLessEqual(size, self.config.semantic_history_read_cap_bytes)
        self.assertEqual(1, len({mark["lineage"] for mark in marks}))
        self.assertEqual([1, 2, 3], [mark["generation"] for mark in marks])
        self.assertEqual(marks[-1], semantic_history.mark_for(self.config, self.state, "p"))

    def test_a_size_trim_drops_oldest_first_and_keeps_the_lineage(self) -> None:
        self.config = dataclasses.replace(self.config, semantic_history_read_cap_bytes=65_536)
        first = self.update("p", at=1, now=10)["mark"]
        self.update("q", at=2, now=10)
        scans = {"claude:s": {"size": 10, "mtime_ns": 1}}
        for k in range(200):
            fact = {
                "fact_id": f"big{k}",
                "type": "user_message",
                "summary": "s" * 200,
                "at": 3 + k,
                "evidence": {"source": "z" * 400, "confidence": "exact"},
                "source_session": {"harness": "claude", "sid": "s"},
            }
            last = semantic_history.update(
                self.config, self.state, "p", {"facts": [fact]}, [], now=300, source_scans=scans
            )
        # One more write, large enough that it must trim whatever headroom the last trim left.
        before = len(json.loads(self.path.read_text())["projects"]["p"]["events"])
        fact = {
            "fact_id": "big-last",
            "type": "user_message",
            "summary": "s" * 200,
            "at": 500,
            "evidence": {"source": "z" * 8000, "confidence": "exact"},
            "source_session": {"harness": "claude", "sid": "s"},
        }
        last = semantic_history.update(
            self.config, self.state, "p", {"facts": [fact]}, [], now=600, source_scans=scans
        )
        stored = json.loads(self.path.read_text())
        bucket = stored["projects"]["p"]
        kept = [event["event_id"] for event in bucket["events"]]
        self.assertLess(len(kept), before + 1, "the last write did not trim")
        self.assertLessEqual(self.path.stat().st_size, 65_536)
        self.assertIn("big-last", kept)
        self.assertIn("big199", kept)
        self.assertNotIn("big0", kept)
        self.assertNotIn("u1", kept)
        # The other project's older bucket gave its old event up before this one's newer ones.
        self.assertEqual([], stored["projects"].get("q", {}).get("events", []))
        self.assertEqual(first["lineage"], last["mark"]["lineage"])
        self.assertEqual(kept, [event["event_id"] for event in last["events"]])
        # The trim is a prune, so the scan that covered the bucket still covers what is left.
        plan = semantic_history.backfill_plan(
            self.config, self.state, "p", "claude:s", {"size": 10, "mtime_ns": 1}, full_max_bytes=99
        )
        self.assertEqual(0, plan[0])

    def test_a_foreign_file_over_the_cap_reads_as_lost_and_starts_a_new_lineage(self) -> None:
        before = self.update()["mark"]
        self.path.write_bytes(
            self.path.read_bytes() + b" " * self.config.semantic_history_read_cap_bytes
        )
        self.assertIsNone(semantic_history.mark_for(self.config, self.state, "p"))
        after = self.update(at=101)["mark"]
        self.assertNotEqual(before["lineage"], after["lineage"])
