"""Replay synthetic GitHub CLI responses through the production adapter and worker."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from compass_runtime.plan import grammar, model, publish, tracker_refresh, tracker_source

from .test_plan_trackers import TrackerTestCase

REPLAY = Path(__file__).parent / "fixtures" / "plan" / "github"

MILESTONE = {"provider": "github", "kind": "milestone", "repo": "paper-kite/atlas", "number": 7}
PARENT = {**MILESTONE, "kind": "parent-issue", "number": 18}
PROJECT = {
    "provider": "github",
    "kind": "project",
    "owner": "Paper-Kite",
    "number": 12,
    "status_field": "PVTSSF_example_progress",
    "words": {"In Workshop": "running", "Parked": "waiting"},
}
MILESTONE_INFO = {
    "node_id": "MI_example_7",
    "number": 7,
    "title": "Map the estuary",
    "description": "Body kept out of the plan",
    "html_url": "https://github.com/paper-kite/atlas/milestone/7",
    "due_on": "2026-12-06T08:00:00Z",
    "open_issues": 2,
    "closed_issues": 3,
}
PARENT_INFO = {
    "id": "I_example_parent",
    "number": 18,
    "title": "Prepare the observatory",
    "url": "https://github.com/paper-kite/atlas/issues/18",
}
PROJECT_INFO = {
    "id": "PVT_example_board",
    "number": 12,
    "title": "Expedition planning",
    "url": "https://github.com/orgs/paper-kite/projects/12",
}
STATUS_FIELD = {
    "type": "ProjectV2SingleSelectField",
    "id": PROJECT["status_field"],
    "name": "Workshop Stage",
}


def issue(
    number: int,
    *,
    repo: str = "paper-kite/atlas",
    state: str | None = "OPEN",
    reason: str | None = None,
    title: str = "Survey the salt flats",
) -> dict[str, Any]:
    return {
        "id": f"I_synthetic_{repo.split('/')[1]}_{number}",
        "number": number,
        "title": title,
        "url": f"https://github.com/{repo}/issues/{number}",
        "state": state,
        "stateReason": reason,
        "updatedAt": "2026-11-25T19:26:00Z",
    }


def connection(
    *items: object, total: int | None = None, next_cursor: str | None = None
) -> dict[str, Any]:
    return {
        "totalCount": len(items) if total is None else total,
        "nodes": list(items),
        "pageInfo": {"hasNextPage": next_cursor is not None, "endCursor": next_cursor},
    }


def milestone_page(*items: object, **page: Any) -> dict[str, Any]:
    return {
        "data": {
            "node": {
                "id": MILESTONE_INFO["node_id"],
                "number": 7,
                "url": MILESTONE_INFO["html_url"],
                "issues": connection(*items, **page),
            }
        }
    }


def parent_page(*items: object, **page: Any) -> dict[str, Any]:
    return {
        "data": {"repository": {"issue": {**PARENT_INFO, "subIssues": connection(*items, **page)}}}
    }


def project_fields(*fields: object, **page: Any) -> dict[str, Any]:
    return {
        "data": {
            "repositoryOwner": {
                "projectV2": {**PROJECT_INFO, "fields": connection(*fields, **page)}
            }
        }
    }


def project_page(*items: object, **page: Any) -> dict[str, Any]:
    return {
        "data": {
            "node": {
                "id": PROJECT_INFO["id"],
                "statusField": {"id": PROJECT["status_field"]},
                "items": connection(*items, **page),
            }
        }
    }


def project_item(content: dict[str, Any], status: str | None = None) -> dict[str, Any]:
    return {
        "id": f"PVTI_{content['id']}",
        "content": {"__typename": "Issue", **content},
        "status": (
            {
                "__typename": "ProjectV2ItemFieldSingleSelectValue",
                "field": {"id": PROJECT["status_field"]},
                "name": status,
            }
            if status is not None
            else None
        ),
    }


class GitHubAdapterTest(TrackerTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.environ.update({"GH_HOST": "wrong-host.invalid", "GITHUB_TOKEN": "synthetic override"})
        self.refresh = tracker_refresh.TrackerRefresh(
            environ=self.environ, clock=self.clock, runner=self.runner
        )
        self.calls: list[tuple[str, ...]] = []
        self.attempt = 0

    def read(self, source: dict[str, Any], *responses: Any) -> tracker_refresh.Observation:
        self.attempt += 1
        declaration = tracker_source.declaration(source)
        self.calls.clear()
        pending = iter(responses)

        def replay(argv: list[str], **options: Any) -> subprocess.CompletedProcess[bytes]:
            self.assertEqual(str(self.binary), argv[0])
            self.assertNotIn("GH_HOST", options["env"])
            self.assertNotIn("GITHUB_TOKEN", options["env"])
            self.calls.append(tuple(argv[1:]))
            response = next(pending)
            code, output, error = response if isinstance(response, tuple) else (0, response, b"")
            options["stdout"].write(
                output if isinstance(output, bytes) else json.dumps(output).encode()
            )
            options["stderr"].write(error)
            return subprocess.CompletedProcess(argv, code)

        self.runner.side_effect = replay
        return self.result(lambda: self.snapshot(str(self.attempt), sources=(declaration,))[0])

    def measured(self, observation: tracker_refresh.Observation) -> tracker_refresh.TrackerData:
        self.assertIsNone(observation.reason)
        self.assertIsNotNone(observation.observed_at)
        assert observation.data is not None
        return observation.data

    def abstains(self, expected: str, observation: tracker_refresh.Observation) -> None:
        self.assertEqual(expected, observation.reason)
        self.assertIsNone(observation.data)
        self.assertIsNone(observation.observed_at)

    def test_settings_validate_parent_and_project_selectors(self) -> None:
        self.assertEqual(
            ("github", "parent-issue", "paper-kite/atlas", 18),
            tracker_source.declaration(PARENT).key,
        )
        self.assertEqual(
            ("github", "project", "paper-kite", 12), tracker_source.declaration(PROJECT).key
        )
        for invalid in (
            {**PARENT, "repo": "github.example/paper-kite/atlas"},
            {**PROJECT, "owner": "--hostname"},
            {**PROJECT, "status_field": "@/tmp/secret"},
            {**PROJECT, "words": {"Parked": "guess"}},
            {**PROJECT, "words": {"PARKED": "done", "Parked": "waiting"}},
            {**PROJECT, "repo": "paper-kite/atlas"},
            {key: value for key, value in PROJECT.items() if key != "status_field"},
        ):
            with self.subTest(invalid=invalid), self.assertRaises(grammar.SettingsError):
                tracker_source.declaration(invalid)
        with self.assertRaises(grammar.SettingsError):
            tracker_source.declarations([PROJECT, {**PROJECT, "owner": "paper-kite"}])

    def test_milestone_reads_all_issues_and_dates_with_exact_read_only_argv(self) -> None:
        data = self.measured(
            self.read(
                MILESTONE,
                MILESTONE_INFO,
                milestone_page(
                    issue(1),
                    issue(2, state="CLOSED", reason="COMPLETED"),
                    issue(3, state="CLOSED", reason="NOT_PLANNED"),
                    issue(4, state="CLOSED", reason="DUPLICATE"),
                    issue(5, state="OPEN", reason="REOPENED"),
                ),
            )
        )
        (goal,) = data.goals
        self.assertEqual("Map the estuary", goal.title)
        self.assertEqual(model.ItemDate("Due", "2026-12-06T08:00:00Z"), goal.origin.date)
        self.assertIsNone(goal.done)
        self.assertEqual(tuple(lane.slug for lane in data.lanes), goal.lanes)
        self.assertTrue(all(lane.serves == (goal.id,) for lane in data.lanes))
        self.assertEqual(
            ["not_started", "done", "dropped", "dropped", "not_started"],
            [lane.state for lane in data.lanes],
        )
        self.assertEqual(model.ItemDate("Updated", "2026-11-25T19:26:00Z"), data.lanes[0].date)
        self.assertEqual(
            (
                "api",
                "--hostname",
                "github.com",
                "--method",
                "GET",
                "https://api.github.com/repos/paper-kite/atlas/milestones/7",
            ),
            self.calls[0],
        )
        self.assertEqual(2, len(self.calls))
        self.assert_graphql(1, "MilestoneIssues", ("-f", "variables[id]=MI_example_7"))

    def assert_graphql(self, index: int, operation: str, operands: tuple[str, ...]) -> str:
        call = self.calls[index]
        self.assertEqual(
            ("api", "https://api.github.com/graphql", "--hostname", "github.com", "-f"), call[:5]
        )
        self.assertTrue(call[5].startswith(f"query=\nquery {operation}("))
        self.assertNotIn("mutation", call[5])
        self.assertEqual(operands, call[6:])
        return call[5]

    def test_parent_paginates_and_uses_provider_identity_across_sources_and_renames(self) -> None:
        original = self.measured(self.read(MILESTONE, MILESTONE_INFO, milestone_page(issue(1))))
        first = issue(1, title="Revised survey description")
        child = issue(1, repo="other-harbor/signal", state="CLOSED", reason="COMPLETED")
        data = self.measured(
            self.read(
                PARENT,
                parent_page(first, total=2, next_cursor="@opaque=child"),
                parent_page(child, total=2),
            )
        )
        (goal,) = data.goals
        self.assertEqual("Prepare the observatory", goal.title)
        self.assertIsNone(goal.origin.date)
        self.assertEqual(original.lanes[0].slug, data.lanes[0].slug)
        self.assertEqual(first["title"], data.lanes[0].goal)
        self.assertEqual(2, len(set(goal.lanes)))
        self.assertTrue(all(grammar.is_safe_lane_id(slug) for slug in goal.lanes))
        self.assertEqual("done", data.lanes[1].state)
        operands = (
            "-f",
            "variables[owner]=paper-kite",
            "-f",
            "variables[repo]=atlas",
            "-F",
            "variables[number]=18",
        )
        self.assertEqual(
            self.assert_graphql(0, "SubIssues", operands),
            self.assert_graphql(
                1, "SubIssues", (*operands, "-f", "variables[cursor]=@opaque=child")
            ),
        )

    def test_project_status_precedes_issue_state_and_explicit_non_issues_are_skipped(self) -> None:
        items = [
            project_item(issue(1, state="CLOSED", reason="COMPLETED"), "in WORKSHOP"),
            project_item(issue(1, repo="other-harbor/signal", state="CLOSED", reason="DUPLICATE")),
            project_item(issue(2), "On Watch"),
            project_item(issue(3, state="CLOSED")),
            project_item(issue(4, state="OPEN", reason="COMPLETED")),
            project_item(issue(5, state="CLOSED", reason="NEW_REASON")),
            {"id": "PVTI_synthetic_draft", "content": {"__typename": "DraftIssue"}},
            {"id": "PVTI_synthetic_pr", "content": {"__typename": "PullRequest"}},
        ]
        data = self.measured(
            self.read(
                PROJECT,
                project_fields(STATUS_FIELD),
                project_page(*items),
            )
        )
        self.assertEqual("Expedition planning", data.goals[0].title)
        self.assertEqual(
            ["running", "dropped", "Status not recognised", None, None, "Status not recognised"],
            [lane.state for lane in data.lanes],
        )
        self.assertEqual(
            frozenset({data.lanes[0].slug, data.lanes[2].slug}), data.project_status_lanes
        )
        self.assertEqual(6, len(set(data.goals[0].lanes)))
        self.assert_graphql(
            0, "ProjectFields", ("-f", "variables[owner]=paper-kite", "-F", "variables[number]=12")
        )
        query = self.assert_graphql(
            1,
            "ProjectIssues",
            ("-f", "variables[id]=PVT_example_board", "-f", "variables[status]=Workshop Stage"),
        )
        self.assertIn("archivedStates: [ARCHIVED, NOT_ARCHIVED]", query)

    def test_project_pages_and_milestones_preserve_calendar_due_dates(self) -> None:
        data = self.measured(
            self.read(
                PROJECT,
                project_fields(STATUS_FIELD),
                project_page(project_item(issue(1)), total=2, next_cursor="board/next=="),
                project_page(project_item(issue(2), "Parked"), total=2),
            )
        )
        self.assertEqual(["not_started", "waiting"], [lane.state for lane in data.lanes])
        self.assert_graphql(
            2,
            "ProjectIssues",
            (
                "-f",
                "variables[id]=PVT_example_board",
                "-f",
                "variables[status]=Workshop Stage",
                "-f",
                "variables[cursor]=board/next==",
            ),
        )
        data = self.measured(
            self.read(
                MILESTONE,
                {**MILESTONE_INFO, "due_on": "2026-12-06"},
                milestone_page(),
            )
        )
        self.assertEqual(model.ItemDate("Due", "2026-12-06"), data.goals[0].origin.date)
        self.abstains(
            "unreadable-output",
            self.read(
                MILESTONE,
                {**MILESTONE_INFO, "due_on": "2026-02-29"},
                milestone_page(),
            ),
        )

    def test_null_project_status_name_falls_back_to_issue_state_after_field_validation(
        self,
    ) -> None:
        first = project_item(issue(1, state="CLOSED", reason="COMPLETED"), "In Workshop")
        first["status"]["name"] = None
        second = project_item(issue(2), "Parked")
        fields = project_fields(STATUS_FIELD)
        with self.subTest(status="explicit null"):
            data = self.measured(self.read(PROJECT, fields, project_page(first, second)))
            self.assertEqual(["done", "waiting"], [lane.state for lane in data.lanes])
            self.assertEqual(frozenset({data.lanes[1].slug}), data.project_status_lanes)
        with self.subTest(status="wrong field"):
            wrong = {**first["status"], "field": {"id": "PVTSSF_synthetic_wrong"}}
            self.abstains(
                "partial-result",
                self.read(PROJECT, fields, project_page({**first, "status": wrong}, second)),
            )
        with self.subTest(status="missing name"):
            del first["status"]["name"]
            self.abstains(
                "unreadable-output", self.read(PROJECT, fields, project_page(first, second))
            )

    def test_project_field_must_be_unique_single_select_and_item_value_must_match_its_id(
        self,
    ) -> None:
        for fields in (
            connection(),
            connection({**STATUS_FIELD, "type": "ProjectV2Field"}),
            connection(
                STATUS_FIELD,
                {**STATUS_FIELD, "id": "PVTF_example_collision", "name": "workshop STAGE"},
            ),
        ):
            response = {
                "data": {"repositoryOwner": {"projectV2": {**PROJECT_INFO, "fields": fields}}}
            }
            with self.subTest(fields=fields):
                self.abstains("unreadable-output", self.read(PROJECT, response))
                self.assertEqual(1, len(self.calls))
        item = project_item(issue(1), "Parked")
        item["status"]["field"]["id"] = "PVTSSF_other"
        self.abstains(
            "partial-result", self.read(PROJECT, project_fields(STATUS_FIELD), project_page(item))
        )

    def test_project_field_removed_between_pages_is_partial(self) -> None:
        field_removed = project_page(project_item(issue(2)), total=2)
        field_removed["data"]["node"]["statusField"] = None
        self.abstains(
            "partial-result",
            self.read(
                PROJECT,
                project_fields(STATUS_FIELD),
                project_page(project_item(issue(1)), total=2, next_cursor="first"),
                field_removed,
            ),
        )

    def test_milestone_graphql_id_can_differ_from_rest_node_id(self) -> None:
        first = milestone_page(issue(1), total=2, next_cursor="first")
        final = milestone_page(issue(2), total=2)
        for page in (first, final):
            page["data"]["node"]["id"] = "MI_current_identity"
        data = self.measured(self.read(MILESTONE, MILESTONE_INFO, first, final))
        self.assertEqual(2, len(data.lanes))

    def test_missing_rows_cursor_errors_shifting_counts_and_duplicates_are_unmeasured(self) -> None:
        first = parent_page(issue(1), total=2, next_cursor="cursor-a")
        for pages in (
            (parent_page(issue(1), total=2),),
            (first, parent_page(issue(1), total=2)),
            (first, parent_page(issue(2), total=3)),
            (first, parent_page(issue(2), total=2, next_cursor="cursor-a")),
            (parent_page(None),),
            (parent_page(total=2, next_cursor="cursor-a"),),
        ):
            with self.subTest(pages=pages):
                self.abstains("partial-result", self.read(PARENT, *pages))
        self.abstains(
            "partial-result",
            self.read(
                PROJECT,
                project_fields(STATUS_FIELD),
                project_page({"id": "PVTI_hidden", "content": None}),
            ),
        )
        self.abstains(
            "partial-result",
            self.read(
                MILESTONE,
                MILESTONE_INFO,
                milestone_page(issue(1), total=2),
            ),
        )

    def test_provider_totals_and_page_limits_are_closed_overflow(self) -> None:
        pages = [parent_page(issue(i), total=9, next_cursor=f"page-{i}") for i in range(1, 9)]
        self.abstains("limit-exceeded", self.read(PARENT, *pages))
        self.assertEqual(8, len(self.calls))
        self.abstains("limit-exceeded", self.read(PARENT, parent_page(total=201)))
        self.abstains(
            "limit-exceeded",
            self.read(
                PROJECT,
                project_fields(STATUS_FIELD),
                project_page(total=201),
            ),
        )
        self.abstains(
            "limit-exceeded", self.read(MILESTONE, MILESTONE_INFO, milestone_page(total=201))
        )
        self.abstains("limit-exceeded", self.read(PROJECT, project_fields(total=101)))

    def test_captured_query_shapes_preserve_complete_membership(self) -> None:
        # gh 2.105.0 returned these shapes for the four queries. All values are synthetic.
        def replay(name: str) -> bytes:
            return (REPLAY / f"{name}.json").read_bytes()

        milestone = self.measured(self.read(MILESTONE, MILESTONE_INFO, replay("milestone")))
        parent = self.measured(self.read(PARENT, replay("parent")))
        project = self.measured(
            self.read(PROJECT, replay("project-fields"), replay("project-items"))
        )
        self.assertEqual(["done", "not_started"], [lane.state for lane in milestone.lanes])
        self.assertEqual(["done", "dropped", "not_started"], [lane.state for lane in parent.lanes])
        self.assertEqual(
            ["running", "waiting", "Status not recognised"],
            [lane.state for lane in project.lanes],
        )
        self.assertEqual(parent.lanes[1].slug, project.lanes[1].slug)
        self.assertEqual("Calibrate the fog bell", project.lanes[1].goal)
        self.assertEqual(tuple(lane.slug for lane in project.lanes), project.goals[0].lanes)

    def test_graphql_error_envelopes_use_target_data_at_either_exit_status(self) -> None:
        missing = (REPLAY / "not-found.json").read_bytes()
        stderr = (REPLAY / "not-found.err").read_bytes()
        for code in (0, 1):
            with self.subTest(code=code, fixture="not-found"):
                self.abstains(
                    "not-found-or-inaccessible", self.read(PARENT, (code, missing, stderr))
                )
            for source, before, data in (
                (PARENT, (), {"repository": {"issue": None}}),
                (PROJECT, (), {"repositoryOwner": {"projectV2": None}}),
                (PROJECT, (project_fields(STATUS_FIELD),), {"node": None}),
                (MILESTONE, (MILESTONE_INFO,), {"node": None}),
                (PARENT, (), None),
            ):
                for kind, reason in (
                    ("NOT_FOUND", "not-found-or-inaccessible"),
                    ("FORBIDDEN", "not-found-or-inaccessible"),
                    ("INSUFFICIENT_SCOPES", "not-found-or-inaccessible"),
                    ("RATE_LIMITED", "rate-limited"),
                    ("UNKNOWN", "cli-failed"),
                ):
                    with self.subTest(code=code, target=data, kind=kind):
                        envelope = {"data": data, "errors": [{"type": kind, "message": "Fixture"}]}
                        result = self.read(source, *before, (code, envelope, b"gh: Fixture"))
                        self.abstains(reason, result)
            partial = {
                **parent_page(issue(1)),
                "errors": [{"type": "RATE_LIMITED", "message": "Fixture"}],
            }
            self.abstains("partial-result", self.read(PARENT, (code, partial, b"gh: Fixture")))
        self.abstains("signed-out", self.read(PARENT, (4, missing, stderr)))

    def test_graphql_partial_data_and_cli_failures_are_unmeasured(self) -> None:
        partial = {
            **parent_page(issue(1)),
            "errors": [{"type": "NOT_FOUND", "message": "synthetic details"}],
        }
        for source, response, reason in (
            (PARENT, partial, "partial-result"),
            (PARENT, (1, partial, b"some referenced issue was not found"), "partial-result"),
            (
                PARENT,
                (
                    4,
                    b"",
                    (
                        b"To get started with GitHub CLI, please run:  gh auth login\n"
                        b"Alternatively, populate the GH_TOKEN environment variable with a GitHub API authentication token.\n"
                    ),
                ),
                "signed-out",
            ),
            (
                PARENT,
                (
                    1,
                    b"",
                    b"GraphQL: Could not resolve to a Repository with the name 'paper-kite/missing'. (repository)",
                ),
                "not-found-or-inaccessible",
            ),
            (
                PROJECT,
                {"data": {"repositoryOwner": {"projectV2": None}}},
                "not-found-or-inaccessible",
            ),
            (PARENT, b'{"data":{"repository":{"issue":null, "issue":{}}}}', "unreadable-output"),
            (PARENT, {"data": []}, "unreadable-output"),
            (
                PARENT,
                parent_page(
                    {**issue(1), "url": "https://github.com.evil.invalid/paper-kite/atlas/issues/1"}
                ),
                "unreadable-output",
            ),
        ):
            with self.subTest(reason=reason, response=response):
                self.abstains(reason, self.read(source, response))

    def test_complete_empty_membership_is_measured_and_missing_dates_are_null(self) -> None:
        data = self.measured(
            self.read(MILESTONE, {**MILESTONE_INFO, "due_on": None}, milestone_page())
        )
        self.assertEqual((), data.goals[0].lanes)
        self.assertEqual((), data.lanes)
        self.assertIsNone(data.goals[0].origin.date)
        data = self.measured(self.read(PARENT, parent_page({**issue(1), "updatedAt": None})))
        self.assertIsNone(data.lanes[0].date)

    def test_existing_projection_redacts_titles_and_keeps_only_link_hosts(self) -> None:
        secret = "ghp_" + "0" * 36
        title = f"Sky chart {secret} https://github.com/paper-kite/hidden/issues/17 " + "z" * 600
        data = self.measured(
            self.read(
                PARENT,
                parent_page(
                    {
                        **issue(1, title=title),
                        "body": "Synthetic private body",
                        "assignees": [{"login": "fictional-watchkeeper"}],
                    }
                ),
            )
        )
        plan = model.PlanModel(data.goals, (), (), (), (), data.lanes, (), (), None)
        projected = publish._project(plan, {})
        wire = json.dumps(projected)
        self.assertNotIn(secret, wire)
        self.assertNotIn("/paper-kite/hidden", wire)
        self.assertNotIn("Synthetic private body", wire)
        self.assertNotIn("fictional-watchkeeper", wire)
        self.assertIn("github.com", projected["lanes"][0]["title"])
        self.assertLessEqual(len(projected["lanes"][0]["title"]), 512)
        self.assertIsNone(projected["lanes"][0]["sessions"])
