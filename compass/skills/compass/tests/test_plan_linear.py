"""Offline replays of Linear CLI 3.1.0 shapes using entirely invented records."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from typing import Any
from unittest import mock
from uuid import UUID

from compass_runtime import records
from compass_runtime.plan import grammar, model, publish, settings, tracker_refresh

FIXTURES = Path(__file__).with_name("fixtures") / "plan" / "linear"

PROJECT = "f9ca1a11-24e5-4892-a13e-960a48bd2223"
MILESTONE = "acb05865-94ba-4b5f-b961-6a54c71dc5c2"
NEXT_MILESTONE = "f9b39525-e6a3-4748-a274-4cc5819aef3b"
UPDATED = "2024-04-09T13:37:42.451Z"
COMPLETED = "2024-04-08T15:30:00+02:00"
TARGET = "2024-05-17"
DECLARATION = {
    "provider": "linear",
    "kind": "project",
    "workspace": "orchard-labs",
    "project": "Orchard Inventory",
}
PROJECT_ROW = {
    "id": PROJECT,
    "name": "Orchard Inventory",
    "slugId": "25fb972bc19d",
    "url": "https://linear.app/orchard-labs/project/orchard-inventory",
    "targetDate": TARGET,
    "updatedAt": UPDATED,
    "completedAt": None,
}
MILESTONES = [
    {
        "id": uid,
        "name": name,
        "targetDate": target,
        "sortOrder": order,
        "project": {"id": PROJECT, "name": PROJECT_ROW["name"]},
    }
    for uid, name, target, order in (
        (MILESTONE, "Spring Survey", "2024-04-30", 0),
        (NEXT_MILESTONE, "Summer Survey", None, 1),
    )
]


def issue(
    number: int = 3, *, kind: str = "unstarted", name: str = "Ready for field work"
) -> dict[str, Any]:
    return {
        "id": str(UUID(int=number)),
        "identifier": f"ORC-{number}",
        "title": f"Catalogue orchard plot {number}",
        "url": f"https://linear.app/orchard-labs/issue/orc-{number}/catalogue-plot",
        "createdAt": "2024-04-07T02:00:18Z",
        "updatedAt": UPDATED,
        "state": {
            "id": "00d56411-a8ef-4fa3-90f6-2ad81d297c53",
            "name": name,
            "type": kind,
            "color": "#54199F",
            "position": 10,
        },
        "project": {"id": PROJECT, "name": PROJECT_ROW["name"]},
        "projectMilestone": {"id": MILESTONE, "name": "Spring Survey"},
        "team": {"id": "258dd938-ad00-4a0e-acc4-d9412ad860eb", "key": "ORC", "name": "Orchard"},
        "assignee": None,
        "cycle": None,
        "estimate": 1,
        "priority": 2,
        "priorityLabel": "Sample priority",
        "labels": [],
        "inverseRelations": [],
    }


class LinearTrackerTest(unittest.TestCase):
    def setUp(self) -> None:
        root = tempfile.TemporaryDirectory(dir="/tmp" if sys.platform == "darwin" else None)
        self.addCleanup(root.cleanup)
        self.root = Path(root.name).resolve()
        self.binary = self.root / ("linear.exe" if os.name == "nt" else "linear")
        self.binary.touch(mode=0o700)
        self.environ = {
            "PATH": str(self.root),
            "HOME": str(self.root),
            "linear_api_key": "synthetic-credential",
            "LINEAR_TEAM_ID": "INCIDENTAL",
            "LINEAR_WORKSPACE": "other-workspace",
        }
        self.responses: dict[tuple[str, ...], tuple[int, object, bytes]] = {
            ("project", "view"): (0, PROJECT_ROW, b""),
            ("milestone", "list"): (0, MILESTONES, b""),
            ("issue", "query"): (0, [issue()], b""),
        }
        self.runner = mock.Mock(side_effect=self.run_cli)

    def run_cli(self, argv: list[str], **options: Any) -> subprocess.CompletedProcess[bytes]:
        code, payload, stderr = self.responses[tuple(argv[4:6])]
        options["stdout"].write(
            payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        )
        options["stderr"].write(stderr)
        return subprocess.CompletedProcess(argv, code)

    def load(self, declarations: list[dict[str, Any]]) -> settings.Loaded:
        path = self.root / settings.FILENAME
        path.write_text(json.dumps({"version": 1, "trackers": declarations}), encoding="utf-8")
        return settings.load(str(self.root), git_enabled=False)

    def read(self, **fields: Any) -> tracker_refresh.Observation:
        loaded = self.load([{**DECLARATION, **fields}])
        self.assertIsNotNone(loaded.settings, loaded.reason)
        assert loaded.settings is not None
        plan = loaded.settings
        refresh = tracker_refresh.TrackerRefresh(environ=self.environ, runner=self.runner)
        first = refresh.observe(plan.digest, plan.trackers, enabled=True)[0]
        self.assertEqual("refreshing", first.reason)
        deadline = time.monotonic() + 3
        result = first
        while time.monotonic() < deadline:
            result = refresh.observe(plan.digest, plan.trackers, enabled=True)[0]
            if result.reason != "refreshing":
                return result
            time.sleep(0.005)
        self.assertNotEqual("refreshing", result.reason)
        return result

    def measurement(self, **fields: Any) -> tracker_refresh.TrackerData:
        result = self.read(**fields)
        self.assertIsNotNone(result.data, result.reason)
        assert result.data is not None
        return result.data

    def assert_unmeasured(self, reason: str, **fields: Any) -> None:
        result = self.read(**fields)
        self.assertIsNone(result.data)
        self.assertIsNone(result.observed_at)
        self.assertEqual(reason, result.reason)

    def test_settings_validate_linear_selectors_and_status_word_map(self) -> None:
        self.assertIsNotNone(self.load([DECLARATION]).settings)
        self.assertIsNotNone(
            self.load(
                [
                    DECLARATION,
                    {
                        **DECLARATION,
                        "kind": "milestone",
                        "milestone": MILESTONE,
                        "words": {"On hold": "waiting"},
                    },
                ]
            ).settings
        )
        for invalid in (
            {"workspace": "--help"},
            {"workspace": "other workspace"},
            {"project": "--web"},
            {"project": "Orchard\nInventory"},
            {"kind": "milestone"},
            {"milestone": "Spring Survey"},
            {"kind": "milestone", "milestone": "--help"},
            {"words": {"Ready": "invented"}},
            {"words": {"Ready": "blocked", "ready": "done"}},
            {"argv": ["issue", "delete"]},
        ):
            with self.subTest(invalid=invalid):
                self.assertEqual(settings.MALFORMED, self.load([{**DECLARATION, **invalid}]).reason)
        self.assertEqual(settings.MALFORMED, self.load([DECLARATION, DECLARATION]).reason)
        self.runner.assert_not_called()

    def test_project_membership_and_dates_replay_with_exact_read_only_argv(self) -> None:
        self.responses["project", "view"] = (0, {**PROJECT_ROW, "completedAt": COMPLETED}, b"")
        self.responses["issue", "query"] = (
            0,
            [issue(), {**issue(4, kind="completed"), "projectMilestone": None}],
            b"",
        )
        result = self.measurement()
        (goal,) = result.goals
        self.assertEqual("Orchard Inventory", goal.title)
        self.assertEqual(model.ItemDate("Target", TARGET), goal.origin.date)
        self.assertEqual(
            [("Updated", UPDATED), ("Completed", COMPLETED)],
            [(date.label, date.value) for date in goal.origin.additional_dates],
        )
        self.assertEqual(tuple(lane.slug for lane in result.lanes), goal.lanes)
        self.assertEqual(
            [("not_started", (goal.id,)), ("done", (goal.id,))],
            [(lane.state, lane.serves) for lane in result.lanes],
        )
        self.assertEqual(model.ItemDate("Updated", UPDATED), result.lanes[0].date)
        self.assertEqual((), result.lanes[1].additional_dates)
        root = [str(self.binary), "--workspace", "orchard-labs", "--no-input"]
        self.assertEqual(
            [
                [*root, "project", "view", "Orchard Inventory", "--json", "--no-pager"],
                [
                    *root,
                    "issue",
                    "query",
                    "--project",
                    PROJECT,
                    "--all-teams",
                    "--limit",
                    "all",
                    "--json",
                    "--no-pager",
                ],
            ],
            [call.args[0] for call in self.runner.call_args_list],
        )
        for call in self.runner.call_args_list:
            env = call.kwargs["env"]
            self.assertEqual(
                {"LINEAR_API_KEY": "", "LINEAR_IGNORE_ENV_FILE": "1"},
                {key: value for key, value in env.items() if key.upper().startswith("LINEAR_")},
            )
            self.assertEqual(str(self.root), env["HOME"])
            self.assertEqual(b"", call.kwargs["input"])

    def test_milestone_membership_dates_and_lane_identity_replay(self) -> None:
        project = self.measurement()
        self.runner.reset_mock()
        self.responses["issue", "query"] = (
            0,
            [
                {
                    **issue(),
                    "title": "Renamed orchard survey",
                    "identifier": "TREES-39",
                    "dueDate": "2024-04-17",
                    "completedAt": COMPLETED,
                }
            ],
            b"",
        )
        result = self.measurement(kind="milestone", milestone="Spring Survey")
        (goal,) = result.goals
        (lane,) = result.lanes
        self.assertEqual("Spring Survey", goal.title)
        self.assertEqual(model.ItemDate("Target", "2024-04-30"), goal.origin.date)
        self.assertEqual(project.lanes[0].slug, lane.slug)
        self.assertTrue(grammar.is_safe_lane_id(lane.slug))
        self.assertEqual((lane.slug,), goal.lanes)
        self.assertEqual((goal.id,), lane.serves)
        self.assertEqual(
            (model.ItemDate("Due", "2024-04-17"), model.ItemDate("Completed", COMPLETED)),
            lane.additional_dates,
        )
        root = [str(self.binary), "--workspace", "orchard-labs", "--no-input"]
        self.assertEqual(
            [
                [*root, "project", "view", "Orchard Inventory", "--json", "--no-pager"],
                [*root, "milestone", "list", "--project", PROJECT, "--limit", "all", "--json"],
                [
                    *root,
                    "issue",
                    "query",
                    "--project",
                    PROJECT,
                    "--milestone",
                    MILESTONE,
                    "--all-teams",
                    "--limit",
                    "all",
                    "--json",
                    "--no-pager",
                ],
            ],
            [call.args[0] for call in self.runner.call_args_list],
        )
        self.assertEqual(
            goal.id, self.measurement(kind="milestone", milestone=MILESTONE).goals[0].id
        )
        self.responses["project", "view"] = (
            0,
            {**PROJECT_ROW, "url": "https://linear.app/second-orchard/project/orchard-inventory"},
            b"",
        )
        self.responses["issue", "query"] = (
            0,
            [{**issue(), "url": "https://linear.app/second-orchard/issue/orc-3/catalogue-plot"}],
            b"",
        )
        self.assertNotEqual(lane.slug, self.measurement(workspace="second-orchard").lanes[0].slug)

    def test_cli_response_shapes_replay_project_and_filtered_milestone(self) -> None:
        selector = {
            "workspace": "lantern-fieldwork",
            "project": "https://linear.app/lantern-fieldwork/project/lantern-field-guide-de70ba5e12e9/overview",
        }
        for command, filename in (
            (("project", "view"), "project.json"),
            (("milestone", "list"), "milestones.json"),
            (("issue", "query"), "issues.json"),
        ):
            self.responses[command] = (0, (FIXTURES / filename).read_bytes(), b"")

        project = self.measurement(**selector)
        self.assertEqual("Lantern Field Guide", project.goals[0].title)
        self.assertEqual(
            ["Trace the ridge path", "File the lantern map", "Index the survey notes"],
            [lane.goal for lane in project.lanes],
        )
        self.assertEqual(["running", "done", "not_started"], [lane.state for lane in project.lanes])
        self.assertEqual(
            model.ItemDate("Updated", "2024-03-22T16:52:47.128Z"), project.lanes[0].date
        )
        self.assertTrue(all(not lane.additional_dates for lane in project.lanes))

        self.responses["issue", "query"] = (
            0,
            (FIXTURES / "milestone-issues.json").read_bytes(),
            b"",
        )
        milestone = self.measurement(**selector, kind="milestone", milestone="Trail Markers")
        self.assertEqual("Trail Markers", milestone.goals[0].title)
        self.assertEqual(model.ItemDate("Target", "2024-04-11"), milestone.goals[0].origin.date)
        self.assertEqual(tuple(lane.slug for lane in project.lanes[:2]), milestone.goals[0].lanes)
        self.assertEqual(milestone.goals[0].lanes, tuple(lane.slug for lane in milestone.lanes))
        self.assertTrue(all(lane.serves == (milestone.goals[0].id,) for lane in milestone.lanes))

    def test_project_url_must_prove_workspace_before_requesting_issues(self) -> None:
        self.responses["issue", "query"] = (0, [], b"")
        for url in (
            None,
            "https://linear.app/elsewhere/project/orchard-inventory",
            "https://linear.app/orchard-labs/issue/orc-3",
            "http://linear.app/orchard-labs/project/orchard-inventory",
            "https://linear.app.example.test/orchard-labs/project/orchard-inventory",
            "https://user@linear.app/orchard-labs/project/orchard-inventory",
            "https://linear.app/orchard-labs/project/",
        ):
            with self.subTest(url=url):
                self.runner.reset_mock()
                row = {key: value for key, value in PROJECT_ROW.items() if key != "url"}
                if url is not None:
                    row["url"] = url
                self.responses["project", "view"] = (0, row, b"")
                self.assert_unmeasured("partial-result")
                self.assertEqual(1, self.runner.call_count)

    def test_project_uuid_cannot_match_a_different_projects_name(self) -> None:
        self.responses["project", "view"] = (
            0,
            {**PROJECT_ROW, "id": NEXT_MILESTONE, "name": PROJECT},
            b"",
        )
        self.responses["issue", "query"] = (0, [], b"")
        self.assert_unmeasured("partial-result", project=PROJECT)
        self.assertEqual(1, self.runner.call_count)

    def test_milestone_uuid_cannot_match_a_different_milestones_name(self) -> None:
        self.responses["milestone", "list"] = (0, [{**MILESTONES[1], "name": MILESTONE}], b"")
        self.responses["issue", "query"] = (0, [], b"")
        self.assert_unmeasured("not-found-or-inaccessible", kind="milestone", milestone=MILESTONE)
        self.assertEqual(2, self.runner.call_count)

    def test_project_url_binds_to_declared_workspace_and_returned_slug_id(self) -> None:
        prefix = "https://linear.app/orchard-labs/project/"
        slug_id = PROJECT_ROW["slugId"]
        expected = self.measurement(project=slug_id)
        self.assertEqual(
            expected, self.measurement(project=f"{prefix}orchard-inventory-{slug_id}/overview")
        )
        self.assertEqual(expected, self.measurement(project=f"{prefix}{slug_id}"))
        for selector in (
            f"https://linear.app/elsewhere/project/orchard-inventory-{slug_id}/overview",
            f"https://linear.app/orchard-labs/issue/orchard-inventory-{slug_id}",
            f"{prefix}orchard-inventory-ff00ff00ff00/overview",
        ):
            with self.subTest(selector=selector):
                self.assert_unmeasured("partial-result", project=selector)

    def test_bare_project_selector_requires_exact_name_or_slug_id(self) -> None:
        self.responses["project", "view"] = (0, {**PROJECT_ROW, "identifier": "ORCHARD-7"}, b"")
        self.assertEqual("Orchard Inventory", self.measurement().goals[0].title)
        loaded = self.load([DECLARATION, {**DECLARATION, "project": "orchard inventory"}])
        self.assertIsNotNone(loaded.settings, loaded.reason)
        for selector in ("orchard inventory", "ORCHARD-7", str(PROJECT_ROW["slugId"]).upper()):
            with self.subTest(selector=selector):
                self.assert_unmeasured("partial-result", project=selector)

    def test_every_issue_url_must_prove_workspace_membership(self) -> None:
        for url in (
            None,
            "https://linear.app/elsewhere/issue/orc-4",
            "https://linear.app/orchard-labs/project/orchard-inventory",
            "https://other.example.test/orchard-labs/issue/orc-4",
        ):
            with self.subTest(url=url):
                row = issue(4)
                del row["url"]
                if url is not None:
                    row["url"] = url
                self.responses["issue", "query"] = (0, [issue(), row], b"")
                self.assert_unmeasured("partial-result")

    def test_word_map_overrides_state_type_and_unknown_states_stay_explicit(self) -> None:
        types = ("backlog", "triage", "unstarted", "started", "completed", "canceled", "extension")
        rows = [issue(i, kind=kind) for i, kind in enumerate(types, 1)]
        rows.extend([issue(8, kind="started", name="ON HOLD"), issue(9, name="Equipment missing")])
        self.responses["issue", "query"] = (0, rows, b"")
        lanes = self.measurement(words={"On hold": "waiting", "Equipment missing": "blocked"}).lanes
        self.assertEqual(
            [
                "not_started",
                "not_started",
                "not_started",
                "running",
                "done",
                "dropped",
                "Status not recognised",
                "waiting",
                "blocked",
            ],
            [lane.state for lane in lanes],
        )

    def test_duplicate_issues_are_dropped_unless_the_word_map_overrides_them(self) -> None:
        self.responses["issue", "query"] = (0, [issue(kind="duplicate", name="Duplicate")], b"")
        self.assertEqual("dropped", self.measurement().lanes[0].state)
        self.assertEqual("waiting", self.measurement(words={"duplicate": "waiting"}).lanes[0].state)

    def test_titles_and_provenance_keep_only_admitted_text_and_link_hosts(self) -> None:
        token = "lin_api_" + "7b" * 24
        title = "Survey https://field.example.test/private/plot?token=hidden"
        self.responses["project", "view"] = (0, {**PROJECT_ROW, "name": title}, b"")
        self.responses["issue", "query"] = (
            0,
            [{**issue(), "title": f"{title} {token}"}],
            b"",
        )
        data = self.measurement(project=PROJECT)
        self.assertEqual("https://linear.app", data.goals[0].origin.source.path)
        self.assertEqual("https://linear.app", data.lanes[0].source.path)
        plan = model.PlanModel(data.goals, (), (), (), (), data.lanes, (), (), None)
        payload = publish._project(plan, {})
        self.assertIn("field.example.test", payload["goals"][0]["title"])
        self.assertIn(records.SECRET_MARKER, payload["lanes"][0]["title"])
        for private in ("/private/plot", "token=hidden", "/orchard-labs/", token):
            self.assertNotIn(private, json.dumps(payload))
            self.assertNotIn(private, repr(data))

    def test_cli_failures_with_forged_complete_stdout_are_unmeasured(self) -> None:
        for code, error, reason in (
            (4, b'Workspace "another-orchard" not found in credentials', "unknown-workspace"),
            (4, b"No usable API key", "signed-out"),
            (1, b"No default team configured and no team scope provided", "missing-team-scope"),
            (3, b"Cannot find the selected item", "not-found-or-inaccessible"),
            (1, b"GraphQL returned partial data", "partial-result"),
        ):
            with self.subTest(code=code, error=error):
                self.responses["issue", "query"] = (code, [issue()], error)
                self.assert_unmeasured(reason)
        self.responses["issue", "query"] = (1, b"", b"GraphQL returned partial data")
        self.assert_unmeasured("partial-result")

    def test_missing_or_mismatched_membership_and_partial_results_are_unmeasured(self) -> None:
        no_milestone = issue()
        del no_milestone["projectMilestone"]
        for rows, stderr in (
            ([issue(), no_milestone], b""),
            ([{**issue(), "project": {"id": NEXT_MILESTONE}}], b""),
            ([{**issue(), "projectMilestone": None}], b""),
            ([issue(), issue()], b""),
            ({"data": [issue()], "errors": [{"message": "unavailable"}]}, b""),
            ([issue()], b"Partial result"),
        ):
            with self.subTest(rows=rows, stderr=stderr):
                self.responses["issue", "query"] = (0, rows, stderr)
                self.assert_unmeasured("partial-result", kind="milestone", milestone=MILESTONE)

    def test_refuses_invalid_project_id_before_reusing_it_in_argv(self) -> None:
        self.responses["project", "view"] = (0, {**PROJECT_ROW, "id": "--web"}, b"")
        self.responses["issue", "query"] = (0, [], b"")
        self.assert_unmeasured("unreadable-output")
        self.assertEqual(1, self.runner.call_count)

    def test_refuses_invalid_milestone_id_before_reusing_it_in_argv(self) -> None:
        row = {**MILESTONES[0], "id": "../bad"}
        self.responses["milestone", "list"] = (0, [row], b"")
        self.responses["issue", "query"] = (0, [], b"")
        self.assert_unmeasured("unreadable-output", kind="milestone", milestone=row["name"])
        self.assertEqual(2, self.runner.call_count)

    def test_unrelated_project_cannot_confirm_empty_membership(self) -> None:
        self.responses["issue", "query"] = (0, [], b"")
        self.assert_unmeasured("partial-result", project="Other project")
        self.assertEqual(1, self.runner.call_count)

    def test_milestones_must_belong_to_the_resolved_project(self) -> None:
        row = {**MILESTONES[0], "project": {"id": NEXT_MILESTONE}}
        self.responses["milestone", "list"] = (0, [row], b"")
        self.assert_unmeasured("partial-result", kind="milestone", milestone=MILESTONE)

    def test_duplicate_milestone_id_is_refused_even_for_unselected_rows(self) -> None:
        first, other = MILESTONES
        self.responses["milestone", "list"] = (0, [first, other, other], b"")
        self.assert_unmeasured("partial-result", kind="milestone", milestone=MILESTONE)

    def test_ambiguous_milestone_name_is_refused(self) -> None:
        first, other = MILESTONES
        self.responses["milestone", "list"] = (0, [first, {**other, "name": "SPRING SURVEY"}], b"")
        self.assert_unmeasured("partial-result", kind="milestone", milestone="Spring Survey")

    def test_project_object_with_errors_is_incomplete(self) -> None:
        self.responses["project", "view"] = (
            0,
            {**PROJECT_ROW, "errors": [{"message": "unavailable"}]},
            b"",
        )
        self.assert_unmeasured("partial-result")

    def test_calendar_dates_must_use_canonical_format(self) -> None:
        self.responses["project", "view"] = (0, {**PROJECT_ROW, "targetDate": "20240517"}, b"")
        self.assert_unmeasured("unreadable-output")

    def test_nonzero_exit_with_stdout_is_partial_without_a_provider_diagnostic(self) -> None:
        self.responses["issue", "query"] = (1, [], b"generic failure")
        self.assert_unmeasured("partial-result")

    def test_invalid_output_and_dates_are_unmeasured(self) -> None:
        malformed: tuple[object, ...] = (
            b'[{"id":',
            {},
            [None],
            [{**issue(), "updatedAt": "2024-02-30"}],
        )
        for rows in malformed:
            with self.subTest(rows=rows):
                self.responses["issue", "query"] = (0, rows, b"")
                self.assert_unmeasured("unreadable-output")

    def test_project_and_issue_require_nonblank_titles_and_valid_updated_at(self) -> None:
        for field, value in (
            ("name", "   "),
            ("updatedAt", None),
            ("updatedAt", "2024-02-30T10:00:00Z"),
        ):
            with self.subTest(project_field=field, value=value):
                self.runner.reset_mock()
                self.responses["project", "view"] = (0, {**PROJECT_ROW, field: value}, b"")
                self.assert_unmeasured("unreadable-output", project=PROJECT)
                self.assertEqual(1, self.runner.call_count)

        self.responses["project", "view"] = (0, PROJECT_ROW, b"")
        for field, value in (
            ("title", "   "),
            ("updatedAt", None),
            ("updatedAt", "2024-02-30T10:00:00Z"),
        ):
            with self.subTest(issue_field=field, value=value):
                self.responses["issue", "query"] = (0, [{**issue(), field: value}], b"")
                self.assert_unmeasured("unreadable-output")

    def test_milestone_rejects_malformed_parent_before_fetching_milestones(self) -> None:
        for field, value in (
            ("name", "  "),
            ("name", None),
            ("updatedAt", None),
            ("targetDate", "2024-02-30"),
            ("completedAt", 123),
        ):
            with self.subTest(field=field, value=value):
                self.runner.reset_mock()
                self.responses["project", "view"] = (0, {**PROJECT_ROW, field: value}, b"")
                self.assert_unmeasured(
                    "unreadable-output", project=PROJECT, kind="milestone", milestone=MILESTONE
                )
                self.assertEqual(1, self.runner.call_count)

    def test_milestone_rejects_malformed_rows_even_when_unselected(self) -> None:
        for index in (0, 1):
            for field, value in (("name", "  "), ("targetDate", "2024-02-30")):
                with self.subTest(index=index, field=field):
                    self.runner.reset_mock()
                    rows = list(MILESTONES)
                    rows[index] = {**rows[index], field: value}
                    self.responses["milestone", "list"] = (0, rows, b"")
                    self.assert_unmeasured(
                        "unreadable-output", kind="milestone", milestone=MILESTONE
                    )
                    self.assertEqual(2, self.runner.call_count)

    def test_target_and_completion_dates_can_be_null(self) -> None:
        self.responses["project", "view"] = (0, {**PROJECT_ROW, "targetDate": None}, b"")
        self.responses["issue", "query"] = (
            0,
            [{**issue(), "completedAt": None, "dueDate": None}],
            b"",
        )
        result = self.measurement()
        self.assertIsNone(result.goals[0].origin.date)
        self.assertEqual(
            (model.ItemDate("Updated", UPDATED),), result.goals[0].origin.additional_dates
        )
        self.assertEqual((), result.lanes[0].additional_dates)

        self.responses["issue", "query"] = (0, [], b"")
        milestone = self.measurement(kind="milestone", milestone=NEXT_MILESTONE).goals[0]
        self.assertIsNone(milestone.origin.date)
        self.assertEqual((), milestone.origin.additional_dates)

    def test_row_cap_reports_overflow_even_at_the_limit(self) -> None:
        self.responses["issue", "query"] = (0, [issue(i) for i in range(1, 200)], b"")
        self.assertEqual(199, len(self.measurement().lanes))
        self.responses["issue", "query"] = (0, [issue(i) for i in range(1, 201)], b"")
        self.assert_unmeasured("limit-exceeded")

    def test_complete_empty_membership_is_measured_and_absent_milestone_is_not(self) -> None:
        self.responses["issue", "query"] = (0, [], b"")
        result = self.measurement()
        self.assertEqual((), result.goals[0].lanes)
        self.assertEqual((), result.lanes)
        self.assert_unmeasured(
            "not-found-or-inaccessible", kind="milestone", milestone="Autumn Survey"
        )
