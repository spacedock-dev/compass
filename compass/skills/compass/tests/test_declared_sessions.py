"""Launcher declarations are local claims, resolved only against published rows."""

from __future__ import annotations

import contextlib
import copy
import dataclasses
import io
import json
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest import mock

import event_hook
from compass_runtime import (
    aggregate,
    cli,
    declared_sessions,
    dismissals,
    drift_view,
    events,
    footer_lines,
    http_api,
    live_monitor,
    observation,
    project_context,
    reading,
    records,
    session_summary,
    sessions,
    summary_source,
    terminal_client,
    terminal_sessions,
)
from compass_runtime import annotations as annotation_store

from . import test_live_monitor as monitor_tests
from . import test_session_summary as summary_tests
from .support import make_runtime
from .test_annotations import AReadingIsKeptBesideTheWordsItReadTest
from .test_claude_checks import SHORT as REAL_SHORT
from .test_claude_checks import SID as REAL_SID
from .test_events_ingress import FakeApplication
from .test_live_lease_http import LeaseRoute

NOW = 1_700_000_000.0
PARENT = "abcdef12-3456-7890-abcd-ef1234567890"
CHILD = "12345678-3456-7890-abcd-ef1234567890"


def row(harness: str, sid: str, **extra: Any) -> dict[str, Any]:
    return {
        **sessions.base_session(harness, sid, "project"),
        "state": "idle",
        "own_activity": NOW - 1,
        **extra,
    }


class ParentDeclarations(unittest.TestCase):
    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.config, self.state = make_runtime(state_home=temp.name, state_dir=Path(temp.name))
        self.source = observation.Observation(FakeApplication(self.config), clock=lambda: NOW)  # type: ignore[arg-type]

    def declare(self, child: str, parent: Any, *, event: str = "session_started") -> None:
        self.assertEqual(
            "accepted",
            self.source.submit(
                "claude", {"v": 1, "event": event, "session_id": child, "declared_parent": parent}
            ),
        )

    def attach(self, rows: list[dict[str, Any]], now: float = NOW) -> None:
        declared_sessions.attach(
            rows, self.source.parent_declarations(), config=self.config, now=now
        )

    def test_a_group_only_save_cannot_evict_another_sessions_goal_or_reading(self) -> None:
        for bound in ("sessions", "bytes"):
            with self.subTest(bound=bound), tempfile.TemporaryDirectory() as home:
                config = dataclasses.replace(self.config, state_home=home)
                annotation_store.annotate(
                    config, self.state, "claude", PARENT[:8], goal="Keep intent", now=NOW
                )
                annotation_store.record_reading(
                    config,
                    self.state,
                    "claude",
                    PARENT[:8],
                    assessment=AReadingIsKeptBesideTheWordsItReadTest._assessment(read_at=NOW),
                )
                before = annotation_store.load(config)
                self.assertIsNotNone(before[0].get("assessment"))
                if bound == "sessions":
                    config = dataclasses.replace(config, annotation_max_sessions=1)
                else:
                    config = dataclasses.replace(
                        config,
                        annotation_read_cap_bytes=Path(annotation_store.store_path(config))
                        .stat()
                        .st_size
                        + 10,
                    )
                result = annotation_store.annotate(
                    config, self.state, "claude", CHILD[:8], group="Worker", now=NOW + 1
                )
                self.assertEqual(annotation_store.OUTCOME_UNWRITABLE, result)
                self.assertEqual(before, annotation_store.load(config))

    def test_adding_a_group_to_existing_intent_cannot_evict_another_sessions_reading(self) -> None:
        annotation_store.annotate(
            self.config, self.state, "claude", PARENT[:8], goal="Keep intent", now=NOW
        )
        annotation_store.record_reading(
            self.config,
            self.state,
            "claude",
            PARENT[:8],
            assessment=AReadingIsKeptBesideTheWordsItReadTest._assessment(read_at=NOW),
        )
        annotation_store.annotate(
            self.config, self.state, "claude", CHILD[:8], goal="Worker goal", now=NOW + 1
        )
        before = annotation_store.load(self.config)
        config = dataclasses.replace(
            self.config,
            annotation_read_cap_bytes=Path(annotation_store.store_path(self.config)).stat().st_size
            + 10,
        )
        self.assertEqual(
            annotation_store.OUTCOME_UNWRITABLE,
            annotation_store.annotate(
                config, self.state, "claude", CHILD[:8], group="Worker", now=NOW + 2
            ),
        )
        self.assertEqual(before, annotation_store.load(config))

    def held(self, parent: dict[str, Any]) -> dict[str, Any]:
        held = copy.deepcopy(parent)
        self.declare(CHILD, {"harness": "claude", "sid": str(parent["sid"])})
        self.attach([held, row("claude", CHILD[:8], state="working")])
        self.assertIsNotNone(held["waiting_on_child"])
        return cast("dict[str, Any]", json.loads(json.dumps(held)))

    def test_a_held_parent_explains_its_wait_without_a_raw_child_identity(self) -> None:
        held = self.held(row("claude", PARENT[:8]))
        self.assertEqual("waiting on a linked child session", held["state_detail"])
        self.assertEqual({"harness": "claude", "sid": CHILD[:8]}, held["waiting_on_child"])

    def test_the_native_projection_preserves_the_parents_original_activity_and_detail(self) -> None:
        for active in (False, True):
            native = row("claude", PARENT[:8], active=active, state_detail="native idle detail")
            restored = declared_sessions.model_row(self.held(native))
            for key in ("state", "active", "state_detail"):
                self.assertEqual(native[key], restored[key])
            self.assertEqual(restored, declared_sessions.model_row(restored))

    def test_a_child_display_hold_leaves_interactive_and_live_reading_facts_unchanged(self) -> None:
        native = row(
            "claude",
            PARENT[:8],
            acquisition="event",
            finished_at=NOW - 10,
            last_activity=NOW - 10,
            last_output="The local parser checks passed.",
        )
        held = self.held(native)
        facts = []
        for current in (native, held):
            with tempfile.TemporaryDirectory() as home:
                config, state = make_runtime(state_home=home, state_dir=Path(home))
                app = SimpleNamespace(config=config, state=state, clock=lambda: NOW)
                context = http_api._session_context(app, current)
                facts.append(context["semantic"]["facts"])
        self.assertTrue(any(f["type"] == "result" for f in facts[0]))
        self.assertEqual(facts[0], facts[1])

    def test_a_display_hold_does_not_change_project_observer_membership_or_footer_inputs(
        self,
    ) -> None:
        for active in (False, True):
            native = row("claude", PARENT[:8], active=active, acquisition="scan")
            held = self.held(native)
            contexts = []
            for current in (native, held):
                with tempfile.TemporaryDirectory() as home:
                    config, state = make_runtime(state_home=home, state_dir=Path(home))
                    contexts.append(
                        project_context.collect(config, state, [current], "project", now=NOW)
                    )
            self.assertEqual(contexts[0], contexts[1])
            self.assertEqual(
                footer_lines._projection_inputs({}, native),
                footer_lines._projection_inputs({}, held),
            )

    def test_a_completed_reading_stays_completed_while_its_session_waits_on_a_child(self) -> None:
        fixtures = Path(__file__).resolve().parents[4] / "frontend/test/fixtures/client-contract"
        payload = json.loads((fixtures / "data-focused-drift-medium.json").read_text())["response"][
            "body"
        ]
        context = json.loads((fixtures / "context-focused-drift-medium.json").read_text())[
            "response"
        ]["body"]
        native = payload["sessions"][0]
        native.update(state="idle", ended_at=None)
        held = self.held(native)
        before = drift_view.derive(native, payload, context)
        self.assertIsNotNone(before["pill"])
        self.assertFalse(before["pill"]["so_far"])
        self.assertEqual(before, drift_view.derive(held, payload, context))
        app = SimpleNamespace(config=self.config, state=self.state, diagnostic_sink=lambda _: None)
        with mock.patch.object(
            http_api, "_record_page", return_value={"state": "ok", "entries": []}
        ):
            views = [
                http_api._with_drift_view(
                    app,
                    context,
                    {**payload, "sessions": [current]},
                    (native["harness"], native["sid"]),
                    native["project"],
                    b"test",
                )
                for current in (native, held)
            ]
        self.assertEqual(views[0], views[1])
        self.assertEqual(1, len(self.state.drift_view_cache))

    def test_mixed_case_uuid_declarations_and_group_selectors_resolve_to_existing_published_row(
        self,
    ) -> None:
        for harness in ("claude", "codex"):
            for upper in (False, True):
                published = PARENT[:8] if harness == "claude" else PARENT
                published = published.upper() if upper else published
                for selector in (
                    PARENT.upper(),
                    PARENT.lower(),
                    *([PARENT[:8].upper()] if harness == "claude" else []),
                ):
                    with self.subTest(harness=harness, published=published, selector=selector):
                        claim = events.parent_declaration({"harness": harness, "sid": selector})
                        assert claim is not None
                        self.assertEqual(selector.lower(), claim["sid"])
                        target = row(
                            harness, published, resume_id=PARENT.upper() if upper else PARENT
                        )
                        child = row("claude", "F2345678")
                        declared_sessions.attach(
                            [target, child],
                            {("claude", "f2345678"): claim},
                            config=self.config,
                            now=NOW,
                        )
                        self.assertEqual(
                            {"harness": harness, "sid": published}, child["declared_parent"]
                        )
                        self.assertTrue(terminal_sessions.names(target, selector))
                        resolved = terminal_client.resolve_session(
                            harness + ":" + selector, {}, None, action="group"
                        )
                        assert isinstance(resolved, terminal_client.Session)
                        self.assertEqual(selector.lower(), resolved.sid)
        self.assertFalse(terminal_sessions.names(row("codex", PARENT), PARENT[:8]))
        collision = row("claude", PARENT[:8], resume_id=PARENT[:9] + "0000-0000-0000-000000000000")
        child = row("claude", CHILD[:8])
        declared_sessions.attach(
            [collision, child],
            {("claude", CHILD[:8]): {"harness": "claude", "sid": PARENT}},
            config=self.config,
            now=NOW,
        )
        self.assertEqual("not_linked", child["declared_parent_state"])
        for duplicate in ("parent", "child"):
            rows = [row("claude", PARENT[:8]), row("claude", "a2345678")]
            rows.append(
                row("claude", (PARENT[:8] if duplicate == "parent" else "a2345678").upper())
            )
            declared_sessions.attach(
                rows,
                {("claude", "a2345678"): {"harness": "claude", "sid": PARENT}},
                config=self.config,
                now=NOW,
            )
            self.assertTrue(all(r["declared_parent"] is None for r in rows))
        forwarded = event_hook.declared_parent(
            {"COMPASS_PARENT_SESSION": "claude:" + PARENT.upper()}
        )
        assert forwarded is not None
        self.assertEqual(PARENT, forwarded["sid"])

    def test_a_dashboard_restart_preserves_a_running_childs_declared_parent_and_inherited_group(
        self,
    ) -> None:
        self.declare(CHILD, {"harness": "claude", "sid": PARENT})
        restarted = observation.Observation(FakeApplication(self.config), clock=lambda: NOW + 10)  # type: ignore[arg-type]
        rows = [
            row("claude", PARENT[:8], group="Coordinator", group_source="set"),
            row("claude", CHILD[:8], state="working"),
        ]
        declared_sessions.attach(
            rows, restarted.parent_declarations(), config=self.config, now=NOW + 10
        )
        self.assertEqual("linked", rows[1]["declared_parent_state"])
        self.assertEqual("Coordinator", rows[1]["group"])
        self.assertEqual("working", rows[0]["state"])
        restarted.submit(
            "claude",
            {
                "v": 1,
                "event": "turn_started",
                "session_id": CHILD,
                "declared_parent": {"harness": "codex", "sid": PARENT},
            },
        )
        self.assertEqual(
            "claude", restarted.parent_declarations()[("claude", CHILD[:8])]["harness"]
        )

    def test_a_grandchild_cannot_extend_its_ancestors_working_deadline(self) -> None:
        grandchild = "87654321-3456-7890-abcd-ef1234567890"
        self.declare(CHILD, {"harness": "claude", "sid": PARENT})
        self.declare(grandchild, {"harness": "claude", "sid": CHILD})
        deadline = NOW + self.config.claude_tool_in_flight_max_sec
        for intermediate_activity in (NOW - 100, NOW + 20):
            rows = [
                row("claude", PARENT[:8]),
                row("claude", CHILD[:8], own_activity=intermediate_activity),
                row("claude", grandchild[:8], state="working", own_activity=NOW),
            ]
            for now, held in ((NOW, True), (deadline - 1, True), (deadline, False)):
                rows = json.loads(json.dumps(rows))
                self.attach(rows, now)
                self.assertEqual(
                    [held, held, False], [r["waiting_on_child"] is not None for r in rows]
                )
                self.assertEqual(
                    ["working", "working"] if held else ["idle", "idle"],
                    [r["state"] for r in rows[:2]],
                )

    def test_a_dismissed_parent_cannot_receive_a_declared_link_or_hold(self) -> None:
        app = aggregate.Application(
            self.config,
            self.state,
            (
                aggregate.HarnessSpec(
                    "claude",
                    "Claude",
                    lambda *_: True,
                    lambda *_: [
                        row("claude", PARENT[:8], last_activity=NOW - 1),
                        row("claude", CHILD[:8], state="working"),
                    ],
                ),
            ),
            native_notifier=lambda _: "",
            popup_notifier=lambda *_: None,
            diagnostic_sink=lambda _: None,
            clock=lambda: NOW,
        )
        app.overlays = self.source
        self.declare(CHILD, {"harness": "claude", "sid": PARENT})
        self.assertTrue(dismissals.dismiss(self.config, self.state, "claude", PARENT[:8], now=NOW))
        rows = app.collect(show_all=False, notify=False)["sessions"]
        self.assertEqual([CHILD[:8]], [r["sid"] for r in rows])
        self.assertEqual("not_linked", rows[0]["declared_parent_state"])
        self.assertIsNone(rows[0]["declared_parent"])

    def test_setting_a_group_requires_an_explicit_selector_even_inside_a_session(self) -> None:
        with (
            mock.patch.dict("os.environ", {"CLAUDE_CODE_SESSION_ID": PARENT}),
            mock.patch.object(
                terminal_client, "ensure_dashboard", side_effect=AssertionError("must not discover")
            ),
            contextlib.redirect_stderr(io.StringIO()) as error,
        ):
            self.assertEqual(1, terminal_client.run_group("Owner", None))
        self.assertIn("explicit --session", error.getvalue())

    def test_group_dispatch_preserves_the_selected_port_and_rejects_unrelated_options(self) -> None:
        with mock.patch.object(terminal_client, "run_group", return_value=0) as run:
            self.assertEqual(
                0,
                cli.main(
                    [
                        "--set-group",
                        "Owner",
                        "--session",
                        "claude:" + PARENT,
                        "--port",
                        "4601",
                        "--no-update-check",
                    ]
                ),
            )
        self.assertEqual(4601, run.call_args.kwargs["port"])
        for option in ("--drift", "--goal", "--sessions", "--summary", "--all", "--stop"):
            self.assertIsNone(
                terminal_client.parse_group_args(
                    ["--set-group", "Owner", "--session", "claude:" + PARENT, option]
                )
            )

    def test_group_only_record_can_be_reloaded_given_intent_and_cleared(self) -> None:
        saved = annotation_store.annotate(
            self.config, self.state, "claude", PARENT[:8], group="Coordinator", now=NOW
        )
        self.assertEqual("stored", saved)
        entry = annotation_store.load(self.config)[0]
        self.assertEqual((), entry["revisions"])
        self.assertEqual("Coordinator", entry["group"])
        self.assertEqual(
            "stored",
            annotation_store.annotate(
                self.config, self.state, "claude", PARENT[:8], goal="Own goal", now=NOW + 1
            ),
        )
        entry = annotation_store.load(self.config)[0]
        self.assertEqual("Coordinator", entry["group"])
        self.assertEqual(1, entry["revisions"][-1]["n"])
        self.assertEqual(
            "stored",
            annotation_store.annotate(
                self.config, self.state, "claude", CHILD[:8], group="Worker", now=NOW
            ),
        )
        self.assertEqual(
            "stored",
            annotation_store.clear(
                self.config, self.state, "claude", CHILD[:8], expected_revision=0, now=NOW + 1
            ),
        )
        self.assertIsNone(
            annotation_store.find(annotation_store.load(self.config), "claude", CHILD[:8])
        )

    def test_label_after_discard_preserves_the_discard_and_forget_preserves_the_label(self) -> None:
        annotation_store.annotate(
            self.config, self.state, "claude", PARENT[:8], goal="Own goal", now=NOW
        )
        annotation_store.clear(self.config, self.state, "claude", PARENT[:8], now=NOW + 1)
        annotation_store.annotate(
            self.config, self.state, "claude", PARENT[:8], group="Owner", now=NOW + 2
        )
        entry = annotation_store.load(self.config)[0]
        self.assertTrue(annotation_store.is_discarded(entry))
        self.assertEqual(1, entry["discarded_revision"])
        self.assertEqual("Owner", entry["group"])
        self.assertEqual(annotation_store.FORGET_SWEPT, annotation_store.forget(self.config))
        entry = annotation_store.load(self.config)[0]
        self.assertFalse(annotation_store.is_discarded(entry))
        self.assertEqual("Owner", entry["group"])
        annotation_store.clear(self.config, self.state, "claude", PARENT[:8], now=NOW + 3)
        self.assertEqual((), annotation_store.load(self.config))

    def test_group_is_absent_from_the_real_reading_producer_prompt(self) -> None:
        annotation_store.annotate(
            self.config, self.state, "claude", CHILD[:8], goal="Ship the parser", now=NOW - 20
        )
        marker = "LOCAL_GROUP_SENTINEL"
        annotation_store.annotate(
            self.config, self.state, "claude", CHILD[:8], group=marker, now=NOW - 10
        )
        entry = annotation_store.load(self.config)[0]
        prompts: list[str] = []

        def model(prompt: str, *, output_cap_bytes: int) -> tuple[str, str]:
            del output_cap_bytes
            prompts.append(prompt)
            return "{}", "ok"

        result = reading.produce(
            self.config,
            row("claude", CHILD[:8], state="working", group=marker, group_source="set"),
            entry["revisions"],
            [
                {
                    "fact_id": "f1",
                    "evidence": {"source": "root transcript", "confidence": "exact"},
                    "type": "user_message",
                    "reader_words": "Ship the parser with passing tests",
                    "summary": "Ship the parser with passing tests",
                    "at": NOW - 5,
                    "source_session": {"harness": "claude", "sid": CHILD[:8]},
                }
            ],
            now=NOW,
            stamp_text="read now",
            model=model,
        )
        self.assertEqual(1, len(prompts), result)
        self.assertIn("Ship the parser", prompts[0])
        self.assertNotIn(marker, prompts[0])

    def test_intent_and_group_can_be_saved_together_without_a_new_intent_revision(self) -> None:
        for group in ("First", "Second", ""):
            self.assertEqual(
                "stored",
                annotation_store.annotate(
                    self.config,
                    self.state,
                    "claude",
                    PARENT[:8],
                    goal="Own goal",
                    group=group,
                    now=NOW,
                ),
            )
            entry = annotation_store.load(self.config)[0]
            self.assertEqual(1, len(entry["revisions"]))
            self.assertEqual(group or None, entry.get("group"))

    def test_group_inherits_through_ancestors_and_an_own_label_wins_until_cleared(self) -> None:
        grandchild = "87654321-3456-7890-abcd-ef1234567890"
        self.declare(CHILD, {"harness": "claude", "sid": PARENT})
        self.declare(grandchild, {"harness": "claude", "sid": CHILD})
        rows = [
            row("claude", PARENT[:8], group="Owner", group_source="set"),
            row("claude", CHILD[:8], group="Worker", group_source="set"),
            row("claude", grandchild[:8]),
        ]
        self.attach(rows)
        self.assertEqual(("Worker", "set"), (rows[1]["group"], rows[1]["group_source"]))
        self.assertEqual(("Worker", "parent"), (rows[2]["group"], rows[2]["group_source"]))
        rows[1].update(group=None, group_source=None)
        self.attach(rows)
        self.assertEqual(["Owner"] * 3, [r["group"] for r in rows])

    def test_collection_resolves_after_overlays_and_only_against_visible_rows(self) -> None:
        annotation_store.annotate(
            self.config, self.state, "claude", PARENT[:8], group="Coordinator"
        )
        current = [row("claude", PARENT[:8]), row("claude", CHILD[:8], state="working")]
        application = aggregate.Application(
            self.config,
            self.state,
            (
                aggregate.HarnessSpec(
                    "claude", "Claude", lambda *_: True, lambda *_: [dict(r) for r in current]
                ),
            ),
            native_notifier=lambda _: "",
            popup_notifier=lambda *_: None,
            diagnostic_sink=lambda _: None,
            clock=lambda: NOW,
        )
        source = observation.Observation(application, clock=lambda: NOW)
        application.overlays = source
        lane = mock.Mock()
        application.unasked_lane = lane
        payload = event_hook.envelope(
            {
                "hook_event_name": "SessionStart",
                "session_id": CHILD,
                "source": "startup",
                "cwd": "/project",
                "transcript_path": "/project/child.jsonl",
            },
            environ={"COMPASS_PARENT_SESSION": "claude:" + PARENT},
            uid=None,
        )
        assert payload is not None
        source.submit("claude", payload)
        first = {r["sid"]: r for r in application.collect(show_all=False, notify=False)["sessions"]}
        self.assertEqual("linked", first[CHILD[:8]]["declared_parent_state"])
        self.assertEqual(
            ("Coordinator", "parent"), (first[CHILD[:8]]["group"], first[CHILD[:8]]["group_source"])
        )
        candidates = {r["sid"]: r for r in lane.consider.call_args.args[1]}
        self.assertEqual("idle", candidates[PARENT[:8]]["state"])
        self.assertNotIn("group", candidates[PARENT[:8]])
        self.assertNotIn("declared_parent", candidates[PARENT[:8]])
        self.assertEqual(CHILD[:8], first[PARENT[:8]]["waiting_on_child"]["sid"])
        source.submit("claude", {"v": 1, "event": "session_ended", "session_id": CHILD})
        second = {
            r["sid"]: r for r in application.collect(show_all=False, notify=False)["sessions"]
        }
        self.assertIsNone(second[PARENT[:8]]["waiting_on_child"])
        self.assertEqual("idle", second[PARENT[:8]]["state"])
        current.pop(0)
        third = application.collect(show_all=False, notify=False)["sessions"][0]
        self.assertEqual("not_linked", third["declared_parent_state"])
        self.assertIsNone(third["declared_parent"])

    def test_hook_forwards_only_start_and_only_valid_environment_value(self) -> None:
        payload = {
            "hook_event_name": "SessionStart",
            "session_id": CHILD,
            "declared_parent": "codex:" + CHILD,
        }
        for harness in event_hook.EVENTS_BY_HARNESS:
            with self.subTest(harness=harness):
                result = event_hook.envelope(
                    payload,
                    harness,
                    environ={"COMPASS_PARENT_SESSION": "claude:" + PARENT},
                    uid=None,
                )
                assert result is not None
                self.assertEqual(
                    {"harness": "claude", "sid": PARENT}, result.get("declared_parent")
                )
        for bad in (
            "",
            "claude:../secret",
            "claude:a",
            "claude:" + "a" * 201,
            "unknown:" + PARENT,
            "claude:" + PARENT + "\n",
            "claude:" + PARENT + ":x",
        ):
            with self.subTest(bad=bad):
                self.assertNotIn(
                    "declared_parent",
                    event_hook.envelope(payload, environ={"COMPASS_PARENT_SESSION": bad}, uid=None)
                    or {},
                )

        class NoEnvironment:
            def get(self, _name: str) -> Any:
                raise AssertionError("read environment outside SessionStart")

        result = event_hook.envelope(
            {"hook_event_name": "Stop", "session_id": CHILD}, environ=NoEnvironment()
        )
        self.assertNotIn("declared_parent", result or {})
        self.assertNotIn(
            "declared_parent", event_hook.envelope(payload, environ={}, uid=None) or {}
        )

    def test_uuid_resolves_to_row_prefix_and_resume_keeps_the_declaration(self) -> None:
        self.declare(CHILD, {"harness": "claude", "sid": PARENT})
        self.source.submit("claude", {"v": 1, "event": "session_started", "session_id": CHILD})
        self.declare(CHILD, {"harness": "claude", "sid": CHILD}, event="store_changed")
        rows = [row("claude", PARENT[:8]), row("claude", CHILD[:8])]
        self.attach(rows)
        self.assertEqual({"harness": "claude", "sid": PARENT[:8]}, rows[1]["declared_parent"])
        self.assertEqual("linked", rows[1]["declared_parent_state"])
        self.assertIsNone(rows[0]["declared_parent_state"])

    def test_unmatched_self_and_all_cycle_members_are_not_linked(self) -> None:
        for parent in (
            {"harness": "unknown", "sid": PARENT},
            {"harness": "claude", "sid": CHILD},
            {"harness": "claude", "sid": PARENT},
        ):
            self.declare(CHILD, parent)
            rows = [row("claude", CHILD[:8])]
            self.attach(rows)
            self.assertIsNone(rows[0]["declared_parent"])
            self.assertEqual("not_linked", rows[0]["declared_parent_state"])
        self.declare(PARENT, {"harness": "claude", "sid": CHILD})
        rows = [row("claude", PARENT[:8]), row("claude", CHILD[:8])]
        self.attach(rows)
        self.assertEqual(["not_linked", "not_linked"], [r["declared_parent_state"] for r in rows])

    def test_display_hold_does_not_change_the_scope_of_a_drift_reading(self) -> None:
        self.declare(CHILD, {"harness": "claude", "sid": PARENT})
        parent = row("claude", PARENT[:8], finished_at=NOW - 30)
        before = reading.eligibility(
            parent, latest_revision_at=NOW - 60, now=NOW, settle_sec=1, admit_turn_stop=True
        )
        self.attach([parent, row("claude", CHILD[:8], state="working")])
        self.assertEqual("working", parent["state"])
        after = reading.eligibility(
            parent, latest_revision_at=NOW - 60, now=NOW, settle_sec=1, admit_turn_stop=True
        )
        self.assertEqual(before, after)

    def test_an_unknown_harness_cannot_link_even_if_a_custom_collector_publishes_its_row(
        self,
    ) -> None:
        self.declare(CHILD, {"harness": "unknown", "sid": PARENT})
        rows = [row("unknown", PARENT), row("claude", CHILD[:8])]
        self.attach(rows)
        self.assertEqual("not_linked", rows[1]["declared_parent_state"])
        self.assertIsNone(rows[1]["declared_parent"])

    def test_malformed_declarations_abstain_without_losing_session_event(self) -> None:
        for bad in (
            False,
            {},
            {"harness": [], "sid": PARENT},
            {"harness": "claude", "sid": "../secret"},
        ):
            self.declare(CHILD, bad)
            rows = [row("claude", CHILD[:8])]
            self.attach(rows)
            self.assertIsNone(rows[0]["declared_parent_state"])

    def test_parent_hold_stops_on_idle_end_finish_or_ceiling_and_preserves_input_wait(self) -> None:
        self.declare(CHILD, {"harness": "claude", "sid": PARENT})
        for child_fields, parent_fields, now, held in (
            ({"state": "working"}, {}, NOW, True),
            ({"state": "idle"}, {}, NOW, False),
            ({"state": "working", "ended_at": NOW - 1}, {}, NOW, False),
            ({"state": "working", "finished_at": NOW - 1}, {}, NOW, False),
            ({"state": "working"}, {}, NOW + self.config.claude_tool_in_flight_max_sec, False),
            ({"state": "working"}, {"state": "needs_input"}, NOW, False),
            ({"state": "working"}, {"ended_at": NOW - 1}, NOW, False),
        ):
            with self.subTest(child=child_fields, parent=parent_fields, now=now):
                rows = [
                    row("claude", PARENT[:8], **parent_fields),
                    row("claude", CHILD[:8], **child_fields),
                ]
                self.attach(rows, now)
                self.assertEqual(
                    {"harness": "claude", "sid": CHILD[:8]} if held else None,
                    rows[0]["waiting_on_child"],
                )
                if held:
                    self.assertEqual("working", rows[0]["state"])
                    self.assertTrue(rows[0]["active"])

    def test_a_finished_intermediate_cannot_hold_its_parent_via_a_grandchild(self) -> None:
        grandchild = "87654321-3456-7890-abcd-ef1234567890"
        self.declare(CHILD, {"harness": "claude", "sid": PARENT})
        self.declare(grandchild, {"harness": "claude", "sid": CHILD})
        rows = [
            row("claude", PARENT[:8]),
            row("claude", CHILD[:8], finished_at=NOW - 1),
            row("claude", grandchild[:8], state="working"),
        ]
        self.attach(rows)
        self.assertIsNone(rows[0]["waiting_on_child"])
        self.assertEqual(grandchild[:8], rows[1]["waiting_on_child"]["sid"])

    def test_recent_native_descendant_activity_can_hold_a_quiet_linked_child(self) -> None:
        self.declare(CHILD, {"harness": "claude", "sid": PARENT})
        rows = [
            row("claude", PARENT[:8]),
            row(
                "claude",
                CHILD[:8],
                state="working",
                own_activity=NOW - self.config.claude_tool_in_flight_max_sec - 1,
                last_activity=NOW - 1,
            ),
        ]
        self.attach(rows)
        self.assertEqual({"harness": "claude", "sid": CHILD[:8]}, rows[0]["waiting_on_child"])

    def test_parent_row_identity_is_harness_scoped_and_codex_is_never_prefix_matched(self) -> None:
        self.declare(CHILD, {"harness": "codex", "sid": PARENT})
        rows = [row("claude", PARENT[:8]), row("codex", PARENT), row("claude", CHILD[:8])]
        self.attach(rows)
        self.assertEqual({"harness": "codex", "sid": PARENT}, rows[2]["declared_parent"])
        self.declare(CHILD, {"harness": "codex", "sid": PARENT[:8]})
        self.attach(rows)
        self.assertEqual({"harness": "codex", "sid": PARENT}, rows[2]["declared_parent"])

    def test_newest_working_child_wins_and_group_inherits_without_goal(self) -> None:
        other = "87654321-3456-7890-abcd-ef1234567890"
        for child in (CHILD, other):
            self.declare(child, {"harness": "claude", "sid": PARENT})
        rows = [
            row(
                "claude",
                PARENT[:8],
                group="Coordinator",
                group_source="set",
                annotation_goal="Parent goal",
            ),
            row("claude", CHILD[:8], state="working"),
            row("claude", other[:8], state="working", own_activity=NOW),
        ]
        self.attach(rows)
        self.assertEqual(other[:8], rows[0]["waiting_on_child"]["sid"])
        self.assertEqual(("Coordinator", "parent"), (rows[1]["group"], rows[1]["group_source"]))
        self.assertEqual("", rows[1]["annotation_goal"])


class GroupWrites(LeaseRoute):
    def command(self, port: int, *args: str, tty: bool = True) -> tuple[int, str, str]:
        del tty
        out, err = io.StringIO(), io.StringIO()
        with (
            mock.patch.object(
                terminal_client,
                "ensure_dashboard",
                return_value=terminal_client.Dashboard(port, 1, 1, "1.0.0"),
            ),
            mock.patch.dict("os.environ", {"CLAUDE_CODE_SESSION_ID": REAL_SID}),
            contextlib.redirect_stdout(out),
            contextlib.redirect_stderr(err),
        ):
            code = terminal_client.run(list(args))
        return code, out.getvalue(), err.getvalue()

    def entry(self) -> Any:
        return annotation_store.find(annotation_store.load(self.config), "claude", REAL_SHORT)

    def test_group_http_and_terminal_write_clear_without_touching_intent_or_model_prompt(
        self,
    ) -> None:
        before = self.entry()
        marker = "GROUP_ONLY_SENTINEL"
        with self.serving() as port:
            code, _out, err = self.command(
                port, "--set-group", marker, "--session", "claude:" + REAL_SID, tty=False
            )
            self.assertEqual((0, ""), (code, err))
            status, payload = self.call(port, "GET", "/api/data")
            self.assertEqual(200, status)
            found = payload["sessions"][0]
            self.assertEqual((marker, "set"), (found["group"], found["group_source"]))
            prompt, _ = reading.build_prompt(
                [], goal=found["annotation_goal"], lines=(), max_bytes=8000
            )
            self.assertNotIn(marker, prompt)
            self.assertEqual(before["revisions"], self.entry()["revisions"])
            self.assertEqual(marker, annotation_store.load(self.config)[0]["group"])
            code, _, err = self.command(
                port, "--set-group", "", "--session", "claude:" + REAL_SID, tty=False
            )
            self.assertEqual((0, ""), (code, err))
            self.assertNotIn("group", self.entry())

    def test_group_receipt_reports_the_servers_normalized_empty_label_as_cleared(self) -> None:
        with self.serving() as port:
            code, out, err = self.command(
                port, "--set-group", "\u202e", "--session", "claude:" + REAL_SID
            )
            self.assertEqual((0, ""), (code, err))
            self.assertEqual("Group cleared.\n", out)
            self.assertIsNone(self.entry().get("group"))
            status, payload = self.call(
                port,
                "POST",
                "/api/annotate",
                {"harness": "claude", "sid": REAL_SHORT, "group": "\u202e"},
            )
            self.assertEqual(200, status)
            self.assertIsNone(payload["saved_group"])

    def test_group_writes_honor_annotation_availability_and_length_limits(self) -> None:
        application = self.app()
        with self.serving(application) as port:
            labels: tuple[Any, ...] = ("x" * 41, 42, {}, None)
            for group in labels:
                status, _ = self.call(
                    port,
                    "POST",
                    "/api/annotate",
                    {"harness": "claude", "sid": REAL_SHORT, "group": group},
                )
                self.assertEqual(400, status)
            self.assertEqual(
                200,
                self.call(
                    port,
                    "POST",
                    "/api/annotate",
                    {"harness": "claude", "sid": REAL_SHORT, "group": "x" * 40},
                )[0],
            )
        application.config = dataclasses.replace(self.config, annotations_enabled=False)
        with self.serving(application) as port:
            self.assertEqual(
                503,
                self.call(
                    port,
                    "POST",
                    "/api/annotate",
                    {"harness": "claude", "sid": REAL_SHORT, "group": "Owner"},
                )[0],
            )
        self.assertEqual("x" * 40, annotation_store.load(self.config)[0]["group"])

    def test_a_display_hold_leaves_live_inputs_and_reading_prompts_unchanged(self) -> None:
        self.enterContext(mock.patch.object(records, "fence_nonce", return_value="0" * 12))
        application = self.app()
        native = application.collect(show_all=False, notify=False)["sessions"][0]
        native.update(
            state="idle",
            active=True,
            state_detail="native detail",
            finished_at=application.clock() - 10,
        )
        held = copy.deepcopy(native)
        declared_sessions.attach(
            [held, row("claude", CHILD[:8], state="working", own_activity=application.clock())],
            {("claude", CHILD[:8]): {"harness": "claude", "sid": REAL_SID}},
            config=self.config,
            now=application.clock(),
        )
        held = json.loads(json.dumps(held))
        self.assertIsNotNone(held["waiting_on_child"])
        before = http_api._lease_inputs(application, "claude", REAL_SHORT, native)
        after = http_api._lease_inputs(application, "claude", REAL_SHORT, held)
        self.assertIsNotNone(before)
        self.assertEqual(before, after)
        prompts: list[str] = []

        def model(prompt: str, *, output_cap_bytes: int) -> tuple[str, str]:
            del output_cap_bytes
            prompts.append(prompt)
            return "{}", "ok"

        results = []
        for source in (native, held):
            current = {**source, "finished_at": NOW - 10}
            facts = [
                {
                    "fact_id": "f1",
                    "type": "user_message",
                    "at": NOW - 11,
                    "reader_words": "Ship parser",
                    "summary": "Ship parser",
                    "evidence": {"source": "root transcript", "confidence": "exact"},
                    "source_session": {"harness": "claude", "sid": REAL_SHORT},
                }
            ]
            results.append(
                reading.produce(
                    self.config,
                    current,
                    [{"n": 1, "at": NOW - 20, "goal": "Ship parser", "lines": ()}],
                    facts,
                    now=NOW,
                    stamp_text="now",
                    model=model,
                    admit_turn_stop=True,
                )
            )
        self.assertEqual(results[0], results[1])
        self.assertEqual(2, len(prompts), results)
        self.assertEqual(prompts[0], prompts[1])

    def test_group_stays_out_of_summary_sources_and_the_live_monitor_model_call(self) -> None:
        marker = "LOCAL_GROUP_SENTINEL"
        annotation_store.annotate(self.config, self.state, "claude", REAL_SHORT, group=marker)
        application = self.app()
        found = application.collect(show_all=False, notify=False)["sessions"][0]
        page, reason = summary_source.collect(
            self.config,
            str(self.path),
            "claude",
            REAL_SHORT,
            deadline=time.monotonic() + 30,
            check=lambda: "",
            progress=lambda *_: None,
        )
        self.assertEqual("", reason)
        self.assertNotIn(marker, repr(page.entries))
        assert page.coverage is not None
        replies = summary_tests.Replies()
        session_summary.summarize(
            page.entries,
            page.coverage,
            "claude",
            config=self.config,
            model=replies,
            clock=lambda: 0.0,
        )
        self.assertTrue(replies.prompts)
        self.assertTrue(all(marker not in prompt for prompt in replies.prompts))
        facts = http_api._facts_of(http_api._session_context(application, found))
        key = "claude:" + REAL_SHORT
        now = application.clock()
        live_monitor.begin_window(self.config, key, now=now)
        self.addCleanup(live_monitor.end, self.config, key)
        runner = monitor_tests.FakeRunner()
        tick = live_monitor.tick(
            self.config,
            key,
            now=now,
            transcript_path=str(self.path),
            facts=facts,
            intent=found["annotation_goal"],
            estimate=monitor_tests.OK_ESTIMATE,
            runner=runner,
            binary_resolver=lambda _: "/synthetic/claude",
        )
        self.assertTrue(runner.calls, tick)
        self.assertNotIn(marker, runner.calls[0][1]["input"])

    def test_group_input_is_typed_bounded_single_line_and_disabled_with_annotations(self) -> None:
        with self.serving() as port:
            for bad in ({"secret": "value"}, None, 123, "a" * 41):
                status, _ = self.call(
                    port,
                    "POST",
                    "/api/annotate",
                    {"harness": "claude", "sid": REAL_SHORT, "group": bad},
                )
                self.assertEqual(400, status)
            status, answer = self.call(
                port,
                "POST",
                "/api/annotate",
                {"harness": "claude", "sid": REAL_SHORT, "group": "a\nb\u202ec"},
            )
            self.assertEqual((200, True), (status, answer.get("persisted")))
            self.assertEqual("a b c", self.entry()["group"])
            self.application.config = dataclasses.replace(self.config, annotations_enabled=False)
            status, _ = self.call(
                port,
                "POST",
                "/api/annotate",
                {"harness": "claude", "sid": REAL_SHORT, "group": "off"},
            )
            self.assertEqual(503, status)
            _, data = self.call(port, "GET", "/api/data")
            self.assertIsNone(data["sessions"][0]["group"])
