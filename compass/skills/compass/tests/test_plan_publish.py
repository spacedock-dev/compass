"""Plan publication through the HTTP parser, with in-memory request streams."""

from __future__ import annotations

import errno
import io
import json
import os
import subprocess
import time
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest import mock

from compass_runtime import (
    diagnostics,
    events,
    git_status,
    history,
    http_api,
    records,
    sessions,
    state,
)
from compass_runtime import io as runtime_io
from compass_runtime.plan import (
    model,
    publish,
    readers,
    settings,
    sources,
    tracker_cli,
    tracker_github,
    tracker_linear,
    tracker_refresh,
    tracker_source,
)

from . import test_plan_linear as linear
from .support import make_config
from .test_history import stub_application
from .test_plan_readers import LANE_TRACKER, STAND_IN, VARIANT, PlanRepoTestCase
from .test_project_script_checks import GIT, git
from .test_sessions import DECLARED_SESSION_FIELDS

READY_FIELDS = {
    "state",
    "goals",
    "lanes",
    "asks",
    "trackerAsks",
    "trackerAsksEnabled",
    "trackerAsksFreshForMs",
    "design",
    "tracker",
    "inventory",
    "diagrams",
    "sources",
    "logRejected",
    "trackerRead",
    "limits",
}
LIMITS = "Compass cannot detect health information or confidential text typed into these sources."


def request(
    application: Any,
    *,
    peer: str = "127.0.0.1",
    host: str = "127.0.0.1:8000",
    headers: str = "",
) -> tuple[int, bytes, bytes]:
    handler: Any = http_api._RequestHandler.__new__(http_api._RequestHandler)
    handler.server = SimpleNamespace(
        bound_host="0.0.0.0",
        server_port=8000,
        application=application,
    )
    handler.client_address = (peer, 12345)
    handler.rfile = io.BytesIO(
        f"GET /api/plan HTTP/1.1\r\nHost: {host}\r\nConnection: close\r\n{headers}\r\n".encode()
    )
    handler.wfile = io.BytesIO()
    handler.connection = SimpleNamespace()
    handler.handle()
    head, body = handler.wfile.getvalue().split(b"\r\n\r\n", 1)
    return int(head.split()[1]), head, body


class PlanAdmissionTest(unittest.TestCase):
    def test_denied_calls_do_not_check_settings(self) -> None:
        cases = (
            {"peer": "192.0.2.10"},
            {"peer": "192.0.2.10", "host": "board.example"},
            {"host": "board.example"},
            {"headers": "Forwarded: for=192.0.2.10\r\n"},
            {"headers": "X-Forwarded-For: 192.0.2.10\r\n"},
            {"headers": "Sec-Fetch-Site: same-site\r\nSec-Fetch-Dest: empty\r\n"},
            {
                "headers": "Sec-Fetch-Site: same-origin\r\nSec-Fetch-Mode: navigate\r\nSec-Fetch-Dest: document\r\n"
            },
            {"headers": "Sec-Fetch-Site: same-origin\r\nSec-Fetch-Dest: iframe\r\n"},
            {
                "host": "board.example",
                "headers": "X-ExeDev-Email: reader@example.net\r\nSec-Fetch-Site: same-origin\r\n",
            },
        )
        for enabled in (True, False):
            application = SimpleNamespace(
                config=make_config(
                    allowed_hosts=("board.example",),
                    login_proxy="exe.dev",
                    allowed_users=("reader@example.net",),
                    plan_enabled=enabled,
                )
            )
            for case in cases:
                with (
                    self.subTest(enabled=enabled, case=case),
                    mock.patch.object(settings, "load") as load,
                ):
                    self.assertEqual(request(application, **case)[0], 403)
                    load.assert_not_called()
        application.state = state.build_runtime_state(application.config, started=0.0)
        with mock.patch.object(settings, "load") as load:
            self.assertEqual(request(application)[0], 404)
            load.assert_not_called()


@unittest.skipIf(GIT is None or os.name == "nt", "Needs Git and POSIX directory descriptors")
class PlanPublicationTest(PlanRepoTestCase):
    def application(self, rows: list[dict[str, Any]] | None = None, **changes: Any) -> Any:
        config = make_config(state_home=str(self.home), state_dir=self.home, **changes)
        return stub_application(config, rows or [], [])

    def payload(self, application: Any | None = None) -> tuple[dict[str, Any], bytes]:
        status, headers, body = request(application or self.application())
        self.assertEqual(status, 200)
        self.assertIn(b"Cache-Control: no-store", headers)
        self.assertIn(b"Content-Type: application/json", headers)
        return json.loads(body), body

    def tracker_plan(
        self, *, mixed: bool = False, count: int = 1, asks: int = 0, **extra: Any
    ) -> None:
        file = self.home / settings.FILENAME
        if mixed:
            self.write_sources(STAND_IN)
            self.configure()
        doc = json.loads(file.read_bytes()) if mixed else {"version": 1}
        declarations: list[dict[str, Any]] = [
            {"provider": "github", "kind": "milestone", "repo": "owner/repo", "number": n}
            for n in range(1, count + 1)
        ]
        for declaration in declarations[:asks]:
            declaration["ask_labels"] = ["needs-material-review"]
        doc["trackers"] = declarations
        file.write_text(json.dumps({**doc, **extra}), encoding="utf-8")

    def tracker_data(
        self, goal_id: str = "remote", *, state: str = "done", empty: bool = False
    ) -> model.TrackerData:
        source = model.Source("github milestone", "GitHub milestone", "https://github.com")
        date = model.ItemDate("Due", "2026-12-08")
        goal = model.Goal(
            goal_id,
            "Finish the model",
            None,
            model.Origin(source, date=date),
            () if empty else ("hull",),
        )
        lane = model.Lane("hull", "Build the hull", None, (goal_id,), source, state=state)
        return model.TrackerData((goal,), () if empty else (lane,), frozenset({"hull"}))

    def test_tracker_only_plan_publishes_due_dates_and_joins_declared_folders(self) -> None:
        self.tracker_plan(lane_folders={"hull": str(self.hull)})
        app = self.application()
        tracker = tracker_refresh.Observation(self.tracker_data(), observed_at=time.monotonic())
        with mock.patch.object(app.state.plan_trackers, "observe", return_value=(tracker,)):
            self.assertIsNone(self.payload(app)[0]["lanes"][0]["sessions"])
            app.snapshot.publish((app.config.window_hours, False), b"{}", folders=())
            self.assertEqual(self.payload(app)[0]["lanes"][0]["sessions"], [])
            app.snapshot.publish(
                (app.config.window_hours, False),
                b"{}",
                folders=(("claude", "public", str(self.hull)),),
            )
            payload, body = self.payload(app)
        self.assertEqual(payload["goals"][0]["date"], {"label": "Due", "at": "2026-12-08"})
        self.assertEqual(payload["lanes"][0]["sessions"], ['session:["claude","public"]'])
        self.assertEqual(payload["sources"][0]["label"], "GitHub milestone")
        self.assertEqual(payload["sources"][0]["state"], "ok")
        for key in ("goals", "lanes", "sources"):
            self.assertEqual(set(payload[key][0]), publish.PLAN_ITEM_FIELDS[key])
        self.assertEqual(set(payload["trackerRead"]), publish.PLAN_ITEM_FIELDS["trackerRead"])
        self.assertNotIn(os.fsencode(self.hull), body)

    def read_linear_plan(
        self,
        declaration: dict[str, Any],
        issues: list[dict[str, Any]] | None = None,
        *,
        viewer: str = linear.VIEWER_ID,
    ) -> model.TrackerData:
        child = mock.Mock()
        workspace = declaration["workspace"]
        project_url = linear.PROJECT_ROW["url"]
        assert isinstance(project_url, str)
        project = {
            **linear.PROJECT_ROW,
            "url": project_url.replace("orchard-labs", workspace),
            "completedAt": linear.COMPLETED,
        }
        if issues is None:
            issues = [{**linear.issue(kind="completed"), "completedAt": linear.COMPLETED}]
        responses: list[object] = [project]
        if declaration["kind"] == "milestone":
            responses.append(linear.MILESTONES)
        responses.append(
            [{**issue, "url": issue["url"].replace("orchard-labs", workspace)} for issue in issues]
        )
        if declaration.get("ask_labels"):
            responses.append({"data": {"viewer": {"id": viewer}}})
        child.read_json.side_effect = responses
        return tracker_linear.read(tracker_source.declaration(declaration), child)

    def test_a_linear_only_plan_shows_both_sources_and_joins_their_shared_lane(self) -> None:
        project = linear.DECLARATION
        milestone = {**project, "kind": "milestone", "milestone": linear.MILESTONE}
        data = (self.read_linear_plan(project), self.read_linear_plan(milestone))
        lane_id = data[0].lanes[0].slug
        self.tracker_plan(trackers=[project, milestone], lane_folders={lane_id: str(self.hull)})
        app = self.application()
        app.snapshot.publish(
            (app.config.window_hours, False),
            b"{}",
            folders=(("claude", "public", str(self.hull)),),
        )
        observations = tuple(tracker_refresh.Observation(read, observed_at=100.0) for read in data)
        with (
            mock.patch.object(app.state.plan_trackers, "observe", return_value=observations),
            mock.patch.object(app.state.plan_trackers, "_clock", return_value=101.0),
        ):
            payload, body = self.payload(app)
        self.assertEqual(
            [
                (row["kind"], row["label"], row["state"], row["position"])
                for row in payload["sources"]
            ],
            [
                ("linear project", "Linear project", "ok", None),
                ("linear milestone", "Linear project milestone", "ok", None),
            ],
        )
        project_goal, milestone_goal = payload["goals"]
        self.assertEqual("Orchard Inventory", project_goal["title"])
        self.assertEqual("Spring Survey", milestone_goal["title"])
        self.assertEqual({"label": "Target", "at": linear.TARGET}, project_goal["date"])
        self.assertIn(
            {"label": "Completed", "at": linear.COMPLETED}, project_goal["additionalDates"]
        )
        self.assertEqual({"label": "Target", "at": "2024-04-30"}, milestone_goal["date"])
        self.assertEqual([], milestone_goal["additionalDates"])
        self.assertEqual([[lane_id], [lane_id]], [goal["lanes"] for goal in payload["goals"]])
        self.assertEqual(1, len(payload["lanes"]))
        lane = payload["lanes"][0]
        self.assertEqual("done", lane["state"])
        self.assertEqual({"label": "Updated", "at": linear.UPDATED}, lane["date"])
        self.assertEqual([{"label": "Completed", "at": linear.COMPLETED}], lane["additionalDates"])
        self.assertEqual(['session:["claude","public"]'], lane["sessions"])
        self.assertEqual(
            {
                "freshForMs": 29_000,
                "localGoals": [],
                "localLanes": [],
                "localSources": [
                    {**source, "state": "expired", "reason": "expired"}
                    for source in payload["sources"]
                ],
                "updates": [],
            },
            payload["trackerRead"],
        )
        self.assertFalse(payload["trackerAsksEnabled"])
        self.assertIsNone(payload["trackerAsks"])
        self.assertIsNone(payload["trackerAsksFreshForMs"])
        self.assertNotIn(os.fsencode(self.hull), body)

    def test_selectors_for_the_same_project_keep_the_freshest_complete_membership(self) -> None:
        by_name = linear.DECLARATION
        by_id = {**by_name, "project": linear.PROJECT}
        older = self.read_linear_plan(by_name)
        newer = self.read_linear_plan(by_id, [])
        reads = (
            (by_name, tracker_refresh.Observation(older, observed_at=100.0)),
            (by_id, tracker_refresh.Observation(newer, observed_at=110.0)),
        )
        for order in (reads, reads[::-1]):
            with self.subTest(order=order[0][0]["project"]):
                self.tracker_plan(trackers=[declaration for declaration, _ in order])
                app = self.application()
                with (
                    mock.patch.object(
                        app.state.plan_trackers,
                        "observe",
                        return_value=tuple(observation for _, observation in order),
                    ),
                    mock.patch.object(app.state.plan_trackers, "_clock", return_value=120.0),
                ):
                    payload, _ = self.payload(app)
                self.assertEqual([[]], [goal["lanes"] for goal in payload["goals"]])
                self.assertEqual([], payload["lanes"])
                self.assertCountEqual(
                    ["ok", "empty"], [source["state"] for source in payload["sources"]]
                )
                (update,) = payload["trackerRead"]["updates"]
                self.assertEqual({"remove": [], "upsert": []}, update["lanes"])

    def test_shared_issue_dates_use_the_latest_revision_and_withhold_disputed_ties(self) -> None:
        project = linear.DECLARATION
        milestone = {**project, "kind": "milestone", "milestone": linear.MILESTONE}
        first = {
            **linear.issue(kind="completed"),
            "dueDate": "2024-04-20",
            "completedAt": linear.COMPLETED,
        }
        newer_update = "2024-04-10T10:00:00Z"
        older = self.read_linear_plan(project, [first])
        for updated, due, completed, expected in (
            (newer_update, "2024-05-04", None, [{"label": "Due", "at": "2024-05-04"}]),
            (newer_update, None, None, []),
            (
                linear.UPDATED,
                "2024-05-04",
                linear.COMPLETED,
                [{"label": "Completed", "at": linear.COMPLETED}],
            ),
            (linear.UPDATED, None, None, []),
        ):
            other = self.read_linear_plan(
                milestone,
                [
                    {
                        **linear.issue(kind="started"),
                        "updatedAt": updated,
                        "dueDate": due,
                        "completedAt": completed,
                    }
                ],
            )
            reads = (
                (project, tracker_refresh.Observation(older, observed_at=110.0)),
                (milestone, tracker_refresh.Observation(other, observed_at=100.0)),
            )
            for order in (reads, reads[::-1]):
                with self.subTest(updated=updated, due=due, order=order[0][0]["kind"]):
                    self.tracker_plan(trackers=[declaration for declaration, _ in order])
                    app = self.application()
                    with (
                        mock.patch.object(
                            app.state.plan_trackers,
                            "observe",
                            return_value=tuple(observation for _, observation in order),
                        ),
                        mock.patch.object(app.state.plan_trackers, "_clock", return_value=120.0),
                    ):
                        payload, _ = self.payload(app)
                    (lane,) = payload["lanes"]
                    self.assertEqual({"label": "Updated", "at": updated}, lane["date"])
                    self.assertEqual(expected, lane["additionalDates"])
                    self.assertIsNone(lane["state"])

    def test_a_mixed_tracker_plan_expires_linear_rows_without_affecting_github_asks(self) -> None:
        github = {
            "provider": "github",
            "kind": "project",
            "owner": "owner",
            "number": 1,
            "status_field": "PVT_status",
            "words": {"Planned": "not_started"},
            "ask_labels": ["needs-material-review"],
        }
        linear_data = self.read_linear_plan(linear.DECLARATION)
        self.tracker_plan(
            trackers=[linear.DECLARATION, github],
            lane_folders={linear_data.lanes[0].slug: str(self.hull)},
        )
        app = self.application()
        app.snapshot.publish(
            (app.config.window_hours, False),
            b"{}",
            folders=(("claude", "public", str(self.hull)),),
        )
        github_data = self.measured_tracker_data()
        observations = (
            tracker_refresh.Observation(linear_data, observed_at=100.0),
            tracker_refresh.Observation(github_data, observed_at=110.0),
        )
        with (
            mock.patch.object(app.state.plan_trackers, "observe", return_value=observations),
            mock.patch.object(app.state.plan_trackers, "_clock", return_value=129.0) as clock,
        ):
            fresh, _ = self.payload(app)
            clock.return_value = 130.0
            expired, _ = self.payload(app)
        self.assertEqual(
            [("Linear project", None, "ok"), ("GitHub project", None, "ok")],
            [(row["label"], row["position"], row["state"]) for row in fresh["sources"]],
        )
        self.assertEqual(
            ["Orchard Inventory", "Finish the model"], [g["title"] for g in fresh["goals"]]
        )
        self.assertEqual(['session:["claude","public"]'], fresh["lanes"][0]["sessions"])
        self.assertEqual(1_000, fresh["trackerRead"]["freshForMs"])
        (update,) = fresh["trackerRead"]["updates"]
        self.assertEqual(set(update), publish.PLAN_ITEM_FIELDS["trackerRead.update"])
        for key in ("goals", "lanes"):
            self.assertEqual(set(update[key]), publish.PLAN_ITEM_FIELDS["trackerRead.changes"])
        self.assertEqual(11_000, update["freshForMs"])
        self.assertEqual([fresh["goals"][0]["id"]], update["goals"]["remove"])
        self.assertEqual([fresh["lanes"][0]["id"]], update["lanes"]["remove"])
        self.assertEqual(["expired", "ok"], [row["state"] for row in update["sources"]])
        self.assertEqual(11_000, fresh["trackerAsksFreshForMs"])
        self.assertEqual(["Build the hull"], [ask["title"] for ask in fresh["trackerAsks"]])
        self.assertEqual(
            [("Linear project", "expired"), ("GitHub project", "ok")],
            [(row["label"], row["state"]) for row in expired["sources"]],
        )
        self.assertEqual(["Finish the model"], [g["title"] for g in expired["goals"]])
        self.assertEqual(["hull"], [lane["id"] for lane in expired["lanes"]])
        self.assertEqual(10_000, expired["trackerRead"]["freshForMs"])
        self.assertEqual(fresh["trackerAsks"], expired["trackerAsks"])
        self.assertEqual(10_000, expired["trackerAsksFreshForMs"])

    def test_expiring_one_github_read_recomputes_the_shared_lane(self) -> None:
        self.tracker_plan(count=2)
        app = self.application()
        observations = (
            tracker_refresh.Observation(self.tracker_data("remote-a"), observed_at=100.0),
            tracker_refresh.Observation(
                self.tracker_data("remote-b", state="running"), observed_at=110.0
            ),
        )
        with (
            mock.patch.object(app.state.plan_trackers, "observe", return_value=observations),
            mock.patch.object(app.state.plan_trackers, "_clock", return_value=129.0),
        ):
            payload, _ = self.payload(app)
        self.assertIsNone(payload["lanes"][0]["state"])
        (update,) = payload["trackerRead"]["updates"]
        self.assertEqual({"remove": ["remote-a"], "upsert": []}, update["goals"])
        self.assertEqual([], update["lanes"]["remove"])
        self.assertEqual(
            [("hull", "running")], [(row["id"], row["state"]) for row in update["lanes"]["upsert"]]
        )

    def test_missing_tracker_lane_folder_is_reported_without_a_path_or_a_diagnostic_read(
        self,
    ) -> None:
        missing = self.hull / "missing"
        self.tracker_plan(asks=1, lane_folders={"hull": str(missing)})
        app = self.application()
        tracker = tracker_refresh.Observation(
            self.measured_tracker_data(), observed_at=time.monotonic()
        )
        with mock.patch.object(app.state.plan_trackers, "observe", return_value=(tracker,)) as read:
            payload, body = self.payload(app)
            read.reset_mock()
            report = diagnostics._plan_report(app.state)
            read.assert_not_called()
        self.assertIsNone(payload["lanes"][0]["sessions"])
        self.assertEqual("Build the hull", payload["trackerAsks"][0]["title"])
        self.assertNotIn(os.fsencode(missing), body)
        self.assertNotIn(str(missing), json.dumps(report))
        self.assertIn(
            {
                "kind": "lane folder",
                "label": "hull",
                "fileLabel": None,
                "position": None,
                "state": "refused",
                "reason": "missing",
            },
            payload["sources"],
        )
        self.assertIn({"kind": "lane folder", "reason": "missing"}, report["sources"])

    def test_mixed_goals_share_one_lane_and_conflicting_explicit_states_are_unmeasured(
        self,
    ) -> None:
        self.tracker_plan(mixed=True, count=2)
        (self.briefs / "hull.md").write_text("## Goal\nLocal brief\n\n*Serves*: G1\n")
        self.log.write_text("2026-01-02T03:04:05Z note hull:1 Started\n", encoding="utf-8")
        app = self.application()
        now = time.monotonic()
        results = (
            tracker_refresh.Observation(self.tracker_data("remote-a"), observed_at=now),
            tracker_refresh.Observation(
                self.tracker_data("remote-b", state="running"), observed_at=now
            ),
        )
        with mock.patch.object(app.state.plan_trackers, "observe", return_value=results):
            payload, _ = self.payload(app)
        self.assertEqual(len([lane for lane in payload["lanes"] if lane["id"] == "hull"]), 1)
        self.assertIsNone(next(lane for lane in payload["lanes"] if lane["id"] == "hull")["state"])
        self.assertEqual([goal["lanes"] for goal in payload["goals"][-2:]], [["hull"], ["hull"]])
        fallback = payload["trackerRead"]
        self.assertEqual(fallback["localLanes"][0]["title"], "Local brief")
        self.assertIsNotNone(fallback["localLanes"][0]["date"])
        for key, rows in (("goals", fallback["localGoals"]), ("lanes", fallback["localLanes"])):
            with self.subTest(fallback=key):
                self.assertTrue(rows)
                for row in rows:
                    self.assertEqual(set(row), publish.PLAN_ITEM_FIELDS[key])
                    if row["date"] is not None:
                        self.assertEqual(set(row["date"]), publish.PLAN_ITEM_FIELDS["date"])

    def test_file_and_project_conflict_is_unmeasured_with_or_without_a_brief(self) -> None:
        from .test_plan_github import PROJECT, issue  # noqa: PLC0415

        self.tracker_plan(mixed=True, trackers=[PROJECT])
        config_file = self.home / settings.FILENAME
        document = json.loads(config_file.read_bytes())
        document["tracker"]["lane_column"] = "Lane"
        config_file.write_text(json.dumps(document), encoding="utf-8")
        goal = tracker_github._goal("project", "PVT_example_board", "Project goal")
        project = tracker_github._rows(goal, [(issue(1), "done")], ask_labels=(), viewers=set())
        slug = project.lanes[0].slug
        table = f"| Item | Lane | Status |\n| --- | --- | --- |\n| Prepare | {slug} | driving |\n"
        self.write_sources({"tracker": table})
        app = self.application()
        observation = tracker_refresh.Observation(project, observed_at=time.monotonic())
        brief = self.briefs / f"{slug}.md"
        with mock.patch.object(app.state.plan_trackers, "observe", return_value=(observation,)):
            brief.write_text("## Goal\nLocal work\n", encoding="utf-8")
            with self.subTest(brief=True):
                self.assertIsNone(self.payload(app)[0]["lanes"][0]["state"])
            brief.unlink()
            with self.subTest(brief=False):
                self.assertIsNone(self.payload(app)[0]["lanes"][0]["state"])

    def test_ambiguous_file_rows_do_not_take_the_ordinary_tracker_state(self) -> None:
        from .test_plan_github import MILESTONE, issue  # noqa: PLC0415

        self.write_sources(STAND_IN)
        self.configure(tracker={"lane_column": "Lane"})
        config_file = self.home / settings.FILENAME
        document = json.loads(config_file.read_bytes())
        document["trackers"] = [MILESTONE]
        config_file.write_text(json.dumps(document), encoding="utf-8")
        goal = tracker_github._goal("milestone", "MI_example_7", "Milestone goal")
        milestone = tracker_github._rows(
            goal,
            [(issue(1, state="CLOSED", reason="COMPLETED"), None)],
            ask_labels=(),
            viewers=set(),
        )
        slug = milestone.lanes[0].slug
        table = f"| Item | Lane | Status |\n| --- | --- | --- |\n| Prepare | {slug} | driving |\n"
        self.write_sources({"tracker": table})
        (self.briefs / f"{slug}.md").write_text("## Goal\nLocal work\n", encoding="utf-8")
        app = self.application()
        observation = tracker_refresh.Observation(milestone, observed_at=time.monotonic())
        with mock.patch.object(app.state.plan_trackers, "observe", return_value=(observation,)):
            self.assertEqual(self.payload(app)[0]["lanes"][0]["state"], "running")
            self.write_sources({"tracker": table + f"| Recheck | {slug} | open |\n"})
            self.assertIsNone(self.payload(app)[0]["lanes"][0]["state"])

    def test_ordinary_reads_that_disagree_leave_a_shared_lane_unmeasured(self) -> None:
        from .test_plan_github import MILESTONE, PARENT, issue  # noqa: PLC0415

        self.tracker_plan(trackers=[MILESTONE, PARENT])
        app = self.application()
        closed = tracker_github._rows(
            tracker_github._goal("milestone", "MI_example_7", "Milestone goal"),
            [(issue(1, state="CLOSED"), None)],
            ask_labels=(),
            viewers=set(),
        )
        opened = tracker_github._rows(
            tracker_github._goal("parent-issue", "I_example_parent", "Parent goal"),
            [(issue(1), None)],
            ask_labels=(),
            viewers=set(),
        )
        now = time.monotonic()
        observations = tuple(
            tracker_refresh.Observation(data, observed_at=now) for data in (closed, opened)
        )
        with mock.patch.object(app.state.plan_trackers, "observe", return_value=observations):
            payload, _ = self.payload(app)
        self.assertIsNone(payload["lanes"][0]["state"])

    def test_incomplete_tracker_reads_withdraw_rows_and_complete_empty_reads_are_distinct(
        self,
    ) -> None:
        self.tracker_plan(asks=1)
        app = self.application()
        now = time.monotonic()
        for result, status, reason in (
            (
                tracker_refresh.Observation(reason=tracker_cli.Reason.SIGNED_OUT),
                "refused",
                "signed-out",
            ),
            (
                tracker_refresh.Observation(reason=tracker_cli.Reason.SIGNED_OUT, retrying=True),
                "retrying",
                "signed-out",
            ),
            (
                tracker_refresh.Observation(reason=tracker_cli.Reason.PARTIAL),
                "refused",
                "partial-result",
            ),
            (
                tracker_refresh.Observation(reason=tracker_cli.Reason.REFRESHING),
                "refreshing",
                "refreshing",
            ),
            (
                tracker_refresh.Observation(reason=tracker_cli.Reason.REFRESHING, retrying=True),
                "refreshing",
                "refreshing",
            ),
            (tracker_refresh.Observation(retrying=True), "refused", "cli-failed"),
            (
                tracker_refresh.Observation(self.tracker_data(), observed_at=now - 31),
                "expired",
                "expired",
            ),
            (
                tracker_refresh.Observation(self.tracker_data(empty=True), observed_at=now),
                "empty",
                None,
            ),
        ):
            with (
                self.subTest(status=status, reason=reason),
                mock.patch.object(app.state.plan_trackers, "observe", return_value=(result,)),
            ):
                payload, _ = self.payload(app)
                self.assertEqual(payload["sources"][0]["state"], status)
                self.assertEqual(payload["sources"][0]["reason"], reason)
                self.assertEqual(payload["lanes"], [])
                self.assertEqual(len(payload["goals"]), int(status == "empty"))
                if status != "empty":
                    self.assertIsNone(payload["trackerRead"])
                    self.assertTrue(payload["trackerAsksEnabled"])
                    self.assertIsNone(payload["trackerAsks"])
                    self.assertIsNone(payload["trackerAsksFreshForMs"])

    def measured_tracker_data(
        self, goal_id: str = "remote", *, matches: bool = True
    ) -> model.TrackerData:
        data = self.tracker_data(goal_id, state="not_started")
        issue = model.TrackerAskIssue(data.lanes[0], matches, frozenset({"needs-material-review"}))
        return replace(data, ask_read=model.TrackerAskRead("reader", (issue,)))

    def tracker_ask_payload(
        self, *reads: tuple[dict[str, Any], tuple[dict[str, Any], ...]]
    ) -> tuple[dict[str, Any], bytes]:
        (self.home / settings.FILENAME).write_text(
            json.dumps({"version": 1, "trackers": [declaration for declaration, _ in reads]}),
            encoding="utf-8",
        )
        app = self.application()
        results = []
        for declaration, responses in reads:
            child = mock.Mock()
            child.read_json.side_effect = responses
            data = tracker_github.read(tracker_source.declaration(declaration), child)
            results.append(tracker_refresh.Observation(data, observed_at=time.monotonic()))
        with mock.patch.object(app.state.plan_trackers, "observe", return_value=tuple(results)):
            return self.payload(app)

    def linear_ask_payload(
        self, *reads: tuple[dict[str, Any], model.TrackerData, float]
    ) -> dict[str, Any]:
        self.tracker_plan(trackers=[declaration for declaration, _, _ in reads])
        app = self.application()
        observations = tuple(
            tracker_refresh.Observation(data, observed_at=at) for _, data, at in reads
        )
        with (
            mock.patch.object(app.state.plan_trackers, "observe", return_value=observations),
            mock.patch.object(app.state.plan_trackers, "_clock", return_value=120),
        ):
            return self.payload(app)[0]

    def test_saturated_label_pages_abstain_with_or_without_visible_match(self) -> None:
        project = {**linear.DECLARATION, "ask_labels": [linear.ASK_LABEL]}
        for matching in (False, True):
            with self.subTest(matching=matching):
                row = linear.ask_issue(label=linear.ASK_LABEL if matching else "other-0")
                row["labels"].extend({"name": f"other-{i}"} for i in range(1, 50))
                payload = self.linear_ask_payload(
                    (project, self.read_linear_plan(project, [row]), 110)
                )
                self.assertEqual(1, len(payload["goals"]))
                self.assertEqual(1, len(payload["lanes"]))
                self.assertIsNone(payload["trackerAsks"])
                self.assertIsNone(payload["trackerAsksFreshForMs"])

    def test_superseding_closed_alias_withdraws_ask(self) -> None:
        project = {**linear.DECLARATION, "ask_labels": [linear.ASK_LABEL]}
        older = (project, self.read_linear_plan(project, [linear.ask_issue()]), 100)
        for labels in ([], [linear.ASK_LABEL]):
            alias = {**project, "project": linear.PROJECT, "ask_labels": labels}
            if not labels:
                del alias["ask_labels"]
            newer = (
                alias,
                self.read_linear_plan(alias, [linear.ask_issue(kind="completed")]),
                110,
            )
            for reads in ((older, newer), (newer, older)):
                with self.subTest(labels=labels, first=reads[0][0]["project"]):
                    payload = self.linear_ask_payload(*reads)
                    self.assertEqual("done", payload["lanes"][0]["state"])
                    self.assertIsNone(payload["trackerAsks"])
                    self.assertIsNone(payload["trackerAsksFreshForMs"])

    def test_new_alias_member_is_not_a_measured_absence(self) -> None:
        project = {**linear.DECLARATION, "ask_labels": [linear.ASK_LABEL]}
        alias = {**project, "project": linear.PROJECT, "ask_labels": ["unrelated"]}
        older = (project, self.read_linear_plan(project, []), 100)
        newer = (alias, self.read_linear_plan(alias, [linear.ask_issue()]), 110)
        for reads in ((older, newer), (newer, older)):
            with self.subTest(first=reads[0][0]["project"]):
                payload = self.linear_ask_payload(*reads)
                self.assertEqual(1, len(payload["goals"]))
                self.assertEqual(1, len(payload["lanes"]))
                (ask,) = payload["trackerAsks"]
                self.assertEqual(payload["lanes"][0]["id"], ask["lane"])
                self.assertEqual(10_000, payload["trackerAsksFreshForMs"])

    def test_tracker_ask_carries_declared_source_label(self) -> None:
        project = {**linear.DECLARATION, "ask_labels": [linear.ASK_LABEL]}
        milestone = {**project, "kind": "milestone", "milestone": linear.MILESTONE}
        for source in (project, milestone):
            with self.subTest(kind=source["kind"]):
                payload = self.linear_ask_payload(
                    (source, self.read_linear_plan(source, [linear.ask_issue()]), 110)
                )
                self.assertEqual(
                    payload["sources"][0]["label"], payload["trackerAsks"][0]["source"]
                )

    def test_triage_and_backlog_issues_can_be_asks(self) -> None:
        project = {**linear.DECLARATION, "ask_labels": [linear.ASK_LABEL]}
        rows = [
            linear.ask_issue(3, kind="triage", name="Triage"),
            linear.ask_issue(4, kind="backlog", name="Backlog"),
        ]
        payload = self.linear_ask_payload((project, self.read_linear_plan(project, rows), 110))
        self.assertEqual(
            ["Catalogue orchard plot 3", "Catalogue orchard plot 4"],
            [ask["title"] for ask in payload["trackerAsks"]],
        )

    def test_different_workspace_viewers_leave_tracker_asks_unmeasured_even_without_issues(
        self,
    ) -> None:
        first = {**linear.DECLARATION, "ask_labels": [linear.ASK_LABEL]}
        second = {**first, "workspace": "other-orchard"}
        for left, right in (
            ([linear.ask_issue()], [linear.ask_issue(assignee=linear.OTHER_ID)]),
            ([linear.ask_issue()], []),
            ([], []),
        ):
            older = (first, self.read_linear_plan(first, left), 100)
            newer = (second, self.read_linear_plan(second, right, viewer=linear.OTHER_ID), 110)
            for reads in ((older, newer), (newer, older)):
                with self.subTest(left=len(left), right=len(right), first=reads[0][0]["workspace"]):
                    payload = self.linear_ask_payload(*reads)
                    self.assertTrue(payload["trackerAsksEnabled"])
                    self.assertEqual(2, len(payload["goals"]))
                    self.assertEqual(len(left) + len(right), len(payload["lanes"]))
                    self.assertIsNone(payload["trackerAsks"])
                    self.assertIsNone(payload["trackerAsksFreshForMs"])

    def test_linear_asks_dedupe_expire_and_withdraw_on_conflicting_or_removed_labels(self) -> None:
        project = {**linear.DECLARATION, "ask_labels": [linear.ASK_LABEL]}
        milestone = {**project, "kind": "milestone", "milestone": linear.MILESTONE}
        matching = linear.ask_issue()
        removed = linear.ask_issue(label=None)
        self.tracker_plan(trackers=[project, milestone])
        app = self.application()
        for left, right, now, count in (
            (matching, matching, 129.0, 1),
            (matching, matching, 130.0, None),
            (matching, removed, 129.0, None),
            (removed, removed, 129.0, 0),
        ):
            reads = (
                tracker_refresh.Observation(
                    self.read_linear_plan(project, [left]), observed_at=100
                ),
                tracker_refresh.Observation(
                    self.read_linear_plan(milestone, [right]), observed_at=110
                ),
            )
            with (
                self.subTest(now=now, count=count),
                mock.patch.object(app.state.plan_trackers, "observe", return_value=reads),
                mock.patch.object(app.state.plan_trackers, "_clock", return_value=now),
            ):
                payload, body = self.payload(app)
                self.assertTrue(payload["trackerAsksEnabled"])
                self.assertNotIn(linear.VIEWER_ID.encode(), body)
                self.assertNotIn(linear.ASK_LABEL.encode(), body)
                self.assertNotIn(b"/orchard-labs/", body)
                if count is None:
                    self.assertIsNone(payload["trackerAsks"])
                    self.assertIsNone(payload["trackerAsksFreshForMs"])
                    continue
                self.assertEqual(1_000, payload["trackerAsksFreshForMs"])
                self.assertEqual(count, len(payload["trackerAsks"]))
                if count:
                    (ask,) = payload["trackerAsks"]
                    self.assertEqual("Catalogue orchard plot 3", ask["title"])
                    self.assertEqual("linear.app", ask["linkHost"])
                    self.assertEqual(payload["lanes"][0]["id"], ask["lane"])
                    self.assertCountEqual([goal["id"] for goal in payload["goals"]], ask["goals"])

    def test_mixed_opted_in_providers_cannot_establish_account_agreement(self) -> None:
        from . import test_plan_github as github  # noqa: PLC0415

        github_source = {**github.MILESTONE, "ask_labels": [github.ASK_LABEL]}
        linear_source = {**linear.DECLARATION, "ask_labels": [linear.ASK_LABEL]}
        self.tracker_plan(mixed=True, trackers=[github_source, linear_source])
        self.log.write_text("ask hull:1 Check the test hull?\n", encoding="utf-8")
        app = self.application()
        child = mock.Mock()
        child.read_json.side_effect = (
            github.MILESTONE_INFO,
            github.with_viewer(
                github.milestone_page(github.ask_issue(assignee=linear.VIEWER_ID)),
                linear.VIEWER_ID,
            ),
        )
        github_data = tracker_github.read(tracker_source.declaration(github_source), child)
        linear_data = self.read_linear_plan(linear_source, [linear.ask_issue()])
        for data in (github_data, linear_data):
            read = data.ask_read
            self.assertIsNotNone(read)
            assert read is not None
            self.assertEqual(linear.VIEWER_ID, read.viewer)
            self.assertTrue(read.issues[0].open_and_assigned)
        now = time.monotonic()
        observations = tuple(
            tracker_refresh.Observation(data, observed_at=now)
            for data in (github_data, linear_data)
        )
        with mock.patch.object(app.state.plan_trackers, "observe", return_value=observations):
            payload, _ = self.payload(app)
        self.assertTrue(payload["trackerAsksEnabled"])
        self.assertIsNone(payload["trackerAsks"])
        self.assertIsNone(payload["trackerAsksFreshForMs"])
        self.assertEqual(
            ["ok", "ok"],
            [
                source["state"]
                for source in payload["sources"]
                if source["kind"].startswith(("github", "linear"))
            ],
        )
        self.assertEqual(["Check the test hull?"], [ask["text"] for ask in payload["asks"]])

    def test_different_signed_in_accounts_leave_tracker_asks_unmeasured(self) -> None:
        from . import test_plan_github as github  # noqa: PLC0415

        other = "another-cartographer"
        for empty in (True, False):
            first = () if empty else (github.ask_issue(),)
            second = () if empty else ({**github.ask_issue(assignee=other), **github.issue(22)},)
            with self.subTest(empty=empty):
                payload, body = self.tracker_ask_payload(
                    (
                        {**github.MILESTONE, "ask_labels": [github.ASK_LABEL]},
                        (github.MILESTONE_INFO, github.with_viewer(github.milestone_page(*first))),
                    ),
                    (
                        {**github.PARENT, "ask_labels": [github.ASK_LABEL]},
                        (github.with_viewer(github.parent_page(*second), other),),
                    ),
                )
                self.assertTrue(payload["trackerAsksEnabled"])
                self.assertNotIn(github.VIEWER.encode(), body)
                self.assertNotIn(other.encode(), body)
                self.assertIsNone(payload["trackerAsks"])

    def test_conflicting_issue_observations_leave_tracker_asks_unmeasured(self) -> None:
        from . import test_plan_github as github  # noqa: PLC0415

        issue = github.ask_issue()
        first = (
            {**github.MILESTONE, "ask_labels": [github.ASK_LABEL]},
            (github.MILESTONE_INFO, github.with_viewer(github.milestone_page(issue))),
        )
        for change in (
            {"state": "CLOSED", "stateReason": "COMPLETED"},
            {"labels": github.connection()},
            {"assignees": github.connection({"login": "another-cartographer"})},
        ):
            revised = {**issue, **change, "updatedAt": "2026-11-25T19:26:20Z"}
            second = (
                {**github.PARENT, "ask_labels": [github.ASK_LABEL]},
                (github.with_viewer(github.parent_page(revised)),),
            )
            for reads in ((first, second), (second, first)):
                with self.subTest(change=change, first=reads[0][0]["kind"]):
                    payload, _ = self.tracker_ask_payload(*reads)
                    self.assertIsNone(payload["trackerAsks"])

    def test_an_ask_shows_the_newest_title_in_either_source_order(self) -> None:
        from . import test_plan_github as github  # noqa: PLC0415

        old = github.ask_issue()
        new = {**old, "title": "Approve the revised map", "updatedAt": "2026-11-25T14:26:20-05:00"}
        first = (
            {**github.MILESTONE, "ask_labels": [github.ASK_LABEL]},
            (github.MILESTONE_INFO, github.with_viewer(github.milestone_page(old))),
        )
        second = (
            {**github.PARENT, "ask_labels": [github.ASK_LABEL]},
            (github.with_viewer(github.parent_page(new)),),
        )
        for reads in ((first, second), (second, first)):
            with self.subTest(first=reads[0][0]["kind"]):
                payload, _ = self.tracker_ask_payload(*reads)
                self.assertEqual(
                    ["Approve the revised map"], [a["title"] for a in payload["trackerAsks"]]
                )

    def test_different_label_rules_can_agree_on_the_same_issue_evidence(self) -> None:
        from . import test_plan_github as github  # noqa: PLC0415

        issue = github.ask_issue()
        payload, _ = self.tracker_ask_payload(
            (
                {**github.MILESTONE, "ask_labels": [github.ASK_LABEL]},
                (github.MILESTONE_INFO, github.with_viewer(github.milestone_page(issue))),
            ),
            (
                {**github.PARENT, "ask_labels": ["unrelated-label"]},
                (github.with_viewer(github.parent_page(issue), github.VIEWER.upper()),),
            ),
        )
        self.assertEqual(1, len(payload["trackerAsks"]))
        self.assertEqual(2, len(payload["trackerAsks"][0]["goals"]))

    def test_contradictory_issue_states_leave_tracker_asks_unmeasured(self) -> None:
        from . import test_plan_github as github  # noqa: PLC0415

        for issue_state, reason, count in (
            ("OPEN", "COMPLETED", None),
            ("CLOSED", "REOPENED", None),
            ("OPEN", "REOPENED", 1),
            ("CLOSED", None, 0),
        ):
            with self.subTest(state=issue_state, reason=reason):
                issue = {**github.ask_issue(state=issue_state), "stateReason": reason}
                payload, _ = self.tracker_ask_payload(
                    (
                        {**github.MILESTONE, "ask_labels": [github.ASK_LABEL]},
                        (github.MILESTONE_INFO, github.with_viewer(github.milestone_page(issue))),
                    )
                )
                self.assertEqual("ok", payload["sources"][0]["state"])
                asks = payload["trackerAsks"]
                self.assertEqual(count, len(asks) if asks is not None else None)

    def test_a_parent_issue_ask_uses_the_same_label_as_sources(self) -> None:
        from . import test_plan_github as github  # noqa: PLC0415

        payload, _ = self.tracker_ask_payload(
            (
                {**github.PARENT, "ask_labels": [github.ASK_LABEL]},
                (github.with_viewer(github.parent_page(github.ask_issue())),),
            )
        )
        self.assertEqual("GitHub parent issue", payload["sources"][0]["label"])
        self.assertEqual(payload["sources"][0]["label"], payload["trackerAsks"][0]["source"])

    def test_an_issue_in_two_tracker_sources_is_one_ask_with_both_goals(self) -> None:
        self.tracker_plan(count=2, asks=2)
        app = self.application()
        observations = tuple(
            tracker_refresh.Observation(
                self.measured_tracker_data(goal),
                observed_at=time.monotonic(),
            )
            for goal in ("remote-a", "remote-b")
        )
        with mock.patch.object(app.state.plan_trackers, "observe", return_value=observations):
            payload, _ = self.payload(app)
        self.assertTrue(payload["trackerAsksEnabled"])
        self.assertEqual(
            payload["trackerAsks"],
            [
                {
                    "title": "Build the hull",
                    "linkHost": "github.com",
                    "source": "GitHub milestone",
                    "lane": "hull",
                    "goals": ["remote-a", "remote-b"],
                }
            ],
        )
        self.assertEqual(set(payload["trackerAsks"][0]), publish.PLAN_ITEM_FIELDS["trackerAsks"])

    def test_an_incomplete_enabled_source_withdraws_tracker_asks_and_keeps_log_asks(self) -> None:
        self.tracker_plan(mixed=True, count=2, asks=2)
        self.log.write_text("ask hull:1 Check the test hull?\n", encoding="utf-8")
        app = self.application()
        now = time.monotonic()
        measured = tracker_refresh.Observation(
            self.measured_tracker_data("remote-a"), observed_at=now
        )
        for missing in (
            tracker_refresh.Observation(self.tracker_data("remote-b"), observed_at=now),
            tracker_refresh.Observation(reason=tracker_cli.Reason.SIGNED_OUT),
            tracker_refresh.Observation(reason=tracker_cli.Reason.DISABLED),
            replace(measured, observed_at=now - 31),
        ):
            with (
                self.subTest(missing=missing),
                mock.patch.object(
                    app.state.plan_trackers, "observe", return_value=(measured, missing)
                ),
            ):
                payload, _ = self.payload(app)
                self.assertTrue(payload["trackerAsksEnabled"])
                self.assertIsNone(payload["trackerAsks"])
                self.assertEqual(["Check the test hull?"], [ask["text"] for ask in payload["asks"]])

    def test_a_source_without_ask_labels_does_not_affect_the_ask_measurement(self) -> None:
        self.tracker_plan(count=2, asks=1)
        app = self.application()
        results = (
            tracker_refresh.Observation(
                self.measured_tracker_data(matches=False), observed_at=time.monotonic()
            ),
            tracker_refresh.Observation(reason=tracker_cli.Reason.SIGNED_OUT),
        )
        with mock.patch.object(app.state.plan_trackers, "observe", return_value=results):
            payload, _ = self.payload(app)
        self.assertTrue(payload["trackerAsksEnabled"])
        self.assertEqual([], payload["trackerAsks"])

    def test_ask_freshness_uses_only_enabled_sources_even_when_the_measurement_is_zero(
        self,
    ) -> None:
        self.tracker_plan(count=3, asks=2)
        app = self.application()
        refresh = app.state.plan_trackers
        for matches in (True, False):
            with self.subTest(matches=matches):
                results = (
                    tracker_refresh.Observation(
                        self.measured_tracker_data("remote-a", matches=matches), observed_at=100
                    ),
                    tracker_refresh.Observation(
                        self.measured_tracker_data("remote-b", matches=matches), observed_at=105
                    ),
                    tracker_refresh.Observation(self.tracker_data("remote-c"), observed_at=90),
                )
                with (
                    mock.patch.object(refresh, "_clock", return_value=105),
                    mock.patch.object(refresh, "observe", return_value=results),
                ):
                    payload, _ = self.payload(app)
                self.assertEqual(int(matches), len(payload["trackerAsks"]))
                self.assertEqual(15_000, payload["trackerRead"]["freshForMs"])
                self.assertEqual(25_000, payload.get("trackerAsksFreshForMs"))

    def test_tracker_asks_are_off_without_labels(self) -> None:
        self.tracker_plan()
        payload, _ = self.payload(self.application(plan_trackers_enabled=False))
        self.assertFalse(payload["trackerAsksEnabled"])
        self.assertIsNone(payload["trackerAsks"])

    def test_missing_and_refused_settings_have_no_partial_data(self) -> None:
        self.assertEqual(self.payload()[0], {"state": "not-configured"})
        self.configure()
        config_file = self.home / settings.FILENAME
        configured = json.loads(config_file.read_bytes())
        configured["repos"][0]["label"] = "CANARY_BAD_SETTINGS"
        configured["log"]["unknown"] = "unexpected"
        config_file.write_text(json.dumps(configured), encoding="utf-8")
        self.assertEqual(self.payload()[0], {"state": "refused", "reason": "malformed settings"})

    def test_projection_fields_match_the_closed_inventory(self) -> None:
        from compass_runtime.plan.publish import PLAN_FIELDS  # noqa: PLC0415

        self.assertEqual(set(PLAN_FIELDS), READY_FIELDS)
        self.assertEqual(len(PLAN_FIELDS), len(READY_FIELDS))
        self.write_sources(STAND_IN)
        self.configure()
        payload, _ = self.payload()
        self.assertEqual(set(payload), set(PLAN_FIELDS))

    def test_every_configured_fixture_publishes_the_same_fields(self) -> None:
        from compass_runtime.plan.publish import PLAN_FIELDS  # noqa: PLC0415

        for fixture, files in (("stand-in", STAND_IN), ("variant", VARIANT)):
            with self.subTest(fixture=fixture):
                self.configure(fixture)
                self.write_sources(files)
                payload, body = self.payload()
                self.assertEqual(set(payload), set(PLAN_FIELDS))
                self.assertEqual(payload["state"], "ready")
                self.assertEqual(payload["limits"], LIMITS)
                self.assertTrue(
                    all(
                        set(source) == {"label", "kind", "fileLabel", "position", "state", "reason"}
                        for source in payload["sources"]
                    )
                )
                self.assertNotIn(os.fsencode(self.root), body)
                self.assertNotIn(b"unusual seabird", body)
                self.assertNotIn(b"hidden tail", body)
                if fixture == "stand-in":
                    self.assertIn(
                        "Status not recognised", [row["group"] for row in payload["tracker"]]
                    )
                    self.assertEqual(payload["goals"][0]["doneWhen"], "The model floats.")
                    self.assertEqual(
                        payload["design"][0]["date"], {"label": "Changed", "at": "2026-09-01"}
                    )

    def test_every_published_row_has_exactly_its_documented_keys(self) -> None:
        expected = {
            "goals": {"id", "title", "doneWhen", "lanes", "proposal", "date", "additionalDates"},
            "lanes": {"id", "title", "doneWhen", "state", "date", "additionalDates", "sessions"},
            "asks": {"id", "text", "at", "timeLabel", "source", "lane"},
            "asks.lane": {"id", "title"},
            "trackerAsks": {"title", "linkHost", "source", "lane", "goals"},
            "design": {"title", "summary", "decided", "source", "date"},
            "tracker": {"title", "group", "source", "date"},
            "inventory": {"title", "group", "source", "date"},
            "diagrams": {"title", "caption", "kind", "source", "date", "linkHosts", "body"},
            "date": {"label", "at"},
            "trackerRead": {"freshForMs", "localGoals", "localLanes", "localSources", "updates"},
            "trackerRead.update": {"freshForMs", "goals", "lanes", "sources"},
            "trackerRead.changes": {"remove", "upsert"},
            "sources": {"label", "kind", "fileLabel", "position", "state", "reason"},
        }
        self.assertEqual(publish.PLAN_ITEM_FIELDS, expected)
        for fixture, files, brief, brief_text, log in (
            ("stand-in", STAND_IN, "hull.md", "## Goal\nBuild it.\n", "ask hull:1 Sample?\n"),
            (
                "variant",
                VARIANT,
                "hull.brief.md",
                "**Objective:** Build it.\n",
                "2026-01-02T03:04:05Z ASK hull a1 Sample?\n",
            ),
        ):
            with self.subTest(fixture=fixture):
                self.write_sources(files)
                self.configure(fixture)
                (self.briefs / brief).write_text(brief_text, encoding="utf-8")
                self.log.write_text(log, encoding="utf-8")
                plan, _ = self.payload()
                rows = {
                    name: plan[name]
                    for name in expected.keys()
                    - {"asks.lane", "date", "trackerRead.update", "trackerRead.changes"}
                }
                rows["asks.lane"] = [ask["lane"] for ask in plan["asks"]]
                rows["date"] = [
                    row["date"]
                    for name in ("lanes", "design", "tracker", "inventory", "diagrams")
                    for row in plan[name]
                    if row["date"] is not None
                ]
                for name, fields in expected.items():
                    with self.subTest(row=name):
                        if name in ("trackerRead.update", "trackerRead.changes"):
                            continue
                        if name in ("trackerRead", "trackerAsks"):
                            self.assertIsNone(rows[name])
                            continue
                        self.assertTrue(rows[name])
                        for row in rows[name]:
                            self.assertEqual(set(row), fields)

    def test_tracker_goal_and_lane_dates_publish_only_the_documented_keys(self) -> None:
        project = linear.DECLARATION
        milestone = {**project, "kind": "milestone", "milestone": linear.MILESTONE}
        issue = {
            **linear.issue(kind="completed"),
            "dueDate": "2024-05-04",
            "completedAt": linear.COMPLETED,
        }
        reads = (
            tracker_refresh.Observation(self.read_linear_plan(project, [issue]), observed_at=100.0),
            tracker_refresh.Observation(
                self.read_linear_plan(milestone, [issue]), observed_at=110.0
            ),
        )
        self.tracker_plan(trackers=[project, milestone])
        app = self.application()
        with (
            mock.patch.object(app.state.plan_trackers, "observe", return_value=reads),
            mock.patch.object(app.state.plan_trackers, "_clock", return_value=129.0),
        ):
            payload, _ = self.payload(app)
        for kind, primary, extra in (
            ("goals", ["Target", "Target"], ["Updated", "Completed"]),
            ("lanes", ["Updated"], ["Due", "Completed"]),
        ):
            with self.subTest(kind=kind):
                rows = payload[kind]
                dates = [row["date"] for row in rows if row["date"] is not None]
                additional = [date for row in rows for date in row["additionalDates"]]
                self.assertCountEqual(primary, [date["label"] for date in dates])
                self.assertCountEqual(extra, [date["label"] for date in additional])
                for date in [*dates, *additional]:
                    self.assertEqual({"label", "at"}, set(date))

    def test_sources_tell_files_of_one_kind_apart_without_paths(self) -> None:
        self.write_sources(STAND_IN)
        (self.repo / "plan" / "parts.md").write_text(STAND_IN["built"], encoding="utf-8")
        git(self.repo, "add", "plan")
        git(self.repo, "commit", "-qm", "Synthetic parts")
        self.configure()
        file = self.home / settings.FILENAME
        doc = json.loads(file.read_bytes())
        # The second file is not committed, and the draft branch the fixture names does not exist.
        doc["repos"][0]["files"]["inventory"] = [
            "plan/built.md",
            "plan/uncommitted-canary.md",
            {"path": "plan/parts.md", "label": "Spare parts"},
        ]
        file.write_text(json.dumps(doc), encoding="utf-8")
        plan, body = self.payload()
        rows = [
            (s["kind"], s["fileLabel"], s["position"], s["state"], s["reason"])
            for s in plan["sources"]
            if s["kind"].endswith("inventory") or s["kind"].endswith("goals")
        ]
        self.assertEqual(
            rows,
            [
                ("goals", None, None, "ok", None),
                ("inventory", None, 1, "ok", None),
                ("inventory", None, 2, "refused", "not in branch"),
                ("inventory", "Spare parts", 3, "ok", None),
                ("draft goals", None, None, "refused", "branch missing"),
                ("draft inventory", None, 1, "refused", "branch missing"),
                ("draft inventory", None, 2, "refused", "branch missing"),
                ("draft inventory", "Spare parts", 3, "refused", "branch missing"),
            ],
        )
        self.assertTrue(all(set(s) == publish.PLAN_ITEM_FIELDS["sources"] for s in plan["sources"]))
        self.assertEqual({s["fileLabel"] for s in plan["sources"]}, {None, "Spare parts"})
        self.assertNotIn(b"uncommitted-canary", body)
        self.assertNotIn(b"parts.md", body)
        self.assertNotIn(os.fsencode(self.root), body)

    def test_lane_state_is_a_closed_group_or_null(self) -> None:
        self.assertEqual(
            publish.LANE_STATES,
            (
                "not_started",
                "running",
                "waiting",
                "blocked",
                "done",
                "dropped",
                "Status not recognised",
            ),
        )
        self.write_sources({"tracker": LANE_TRACKER})
        for slug in ("hull", "paint", "mast", "keel"):
            (self.briefs / f"{slug}.md").write_text("## Goal\nSample lane\n", encoding="utf-8")
        self.configure(tracker={"lane_column": "Lane"})
        plan, body = self.payload()
        self.assertEqual(
            {lane["id"]: lane["state"] for lane in plan["lanes"]},
            {"hull": "done", "paint": "Status not recognised", "mast": None, "keel": None},
        )
        self.assertNotIn(b"unusual seabird", body)
        self.assertTrue(
            all(set(row) == publish.PLAN_ITEM_FIELDS["tracker"] for row in plan["tracker"])
        )

        unmeasured, _ = self.payload(self.application(git_probe_enabled=False))
        self.assertEqual({lane["state"] for lane in unmeasured["lanes"]}, {None})

    def test_projection_publishes_only_closed_lane_states(self) -> None:
        source = model.Source("lane brief", "hull", "")
        lanes = tuple(
            model.Lane(f"lane-{n}", "Sample", None, (), source, state=state)
            for n, state in enumerate(("done", "Status not recognised", None, "seabird", "Done"))
        )
        plan = model.PlanModel((), (), (), (), (), lanes, (), (), None)
        self.assertEqual(
            [lane["state"] for lane in publish._project(plan, {})["lanes"]],
            ["done", "Status not recognised", None, None, None],
        )

    def test_no_git_refuses_git_sources_and_keeps_the_log(self) -> None:
        self.write_sources(STAND_IN)
        self.configure()
        self.log.write_text("ask hull:1 Is the model ready?\n", encoding="utf-8")
        with mock.patch.object(git_status, "plan_reader") as git:
            payload, _ = self.payload(self.application(git_probe_enabled=False))
        git.assert_not_called()
        self.assertEqual(payload["goals"], [])
        self.assertEqual(payload["asks"][0]["text"], "Is the model ready?")
        git_sources = [s for s in payload["sources"] if s["kind"] in sources.FILE_KINDS]
        self.assertEqual(len(git_sources), 5)
        self.assertTrue(
            all(s["state"] == "refused" and s["reason"] == "git reads are off" for s in git_sources)
        )

    def test_canary_link_forms_publish_only_hosts_in_every_source_kind(self) -> None:
        credential = "xoxb-225556655-example-token"
        links = (
            ("https://key.example.test/p?key=CANARY_KEY", "key.example.test"),
            ("https://code.example.test/p?code=CANARY_CODE", "code.example.test"),
            ("https://hook.example.test/webhooks/CANARY_HOOK", "hook.example.test"),
            ("https://magic.example.test/magic/CANARY_MAGIC", "magic.example.test"),
            ("https://share.example.test/share/CANARY_SHARE", "share.example.test"),
            ("bare.example.test/share/CANARY_BARE", "bare.example.test"),
            ("bare.example.test?code=CANARY_BARE_QUERY", "bare.example.test"),
            ("_docs.example.test/d/CANARY_ITALIC/edit_", "docs.example.test"),
            ("-docs.example.test/d/CANARY_DASH/edit", "docs.example.test"),
            ("参考docs.example.test/d/CANARY_CJK/edit", "docs.example.test"),
            ("参考www.example.test/d/CANARY_CJK_WWW/edit", "www.example.test"),
            ("参考https://example.test/p/CANARY_CJK_SCHEME", "example.test"),
            ("@docs.example.test/d/CANARY_AT/edit", "docs.example.test"),
            ("a@docs.example.test/d/CANARY_EMAIL/edit", "docs.example.test"),
            ("docs.example.test:8443/d/CANARY_PORT", "docs.example.test"),
            ("staging.example.test:8443/invite?key=CANARY_PORT_QUERY", "staging.example.test"),
            ("docs.example.test#code=CANARY_FRAGMENT", "docs.example.test"),
            ("localhost:3000/reset?code=CANARY_LOCALHOST", "localhost"),
            ("192.168.1.1/hooks/CANARY_IPV4", "192.168.1.1"),
            ("192.168.1.10:8080/share/CANARY_IP_PORT", "192.168.1.10"),
            ("example.xn--p1ai/reset?code=CANARY_PUNY", "example.xn--p1ai"),
            ("user:CANARY_PASS@example.test/CANARY_PATH", "example.test"),
            ("exämple.test/share/CANARY_IDN", "[link]"),
            ("!www.prefix.example.test/CANARY_PUNCT", "www.prefix.example.test"),
            ("_www.prefix.example.test/CANARY_UNDERSCORE", "www.prefix.example.test"),
            ("-www.prefix.example.test/CANARY_HYPHEN", "www.prefix.example.test"),
            ("!mailto:CANARY_OPAQUE@example.test", "[link]"),
            ("slack:channel?code=CANARY_CUSTOM_OPAQUE", "[link]"),
            ("_tel:CANARY_OPAQUE_UNDERSCORE", "[link]"),
            ("-data:CANARY_OPAQUE_HYPHEN", "[link]"),
            ("https://quote.example.test/?q='CANARY_QUOTED TAIL'", "quote.example.test"),
            ("https://quote.example.test/?q=`CANARY_BACKTICK TAIL`", "quote.example.test"),
            ("https://quote.example.test/?q=value'_CANARY_SUFFIX'", "quote.example.test"),
            ("https://example.test/share/a' 'b/CANARY_PATH_QUOTE", "example.test"),
            ("www.example.test/share/a' 'b/CANARY_WWW_QUOTE", "www.example.test"),
            ("'https://example.test/p?q=foo' ,bar&key=CANARY_SINGLE'", "example.test"),
            ('"https://example.test/p?q=a",b&key=CANARY_DOUBLE"', "example.test"),
            ("`https://example.test/p?q=a`;key=CANARY_TICK`", "example.test"),
            ("https://example.test/a?x=1>2&key=CANARY_GT", "example.test"),
            ("[guide](https://md.example.test/p(CANARY_NESTED)tail)", "md.example.test"),
            ('[x](https://example.test/p?a=")"&key=CANARY_MD_QUOTE)', "example.test"),
            ("[x](https://example.test/r?mood=:)&key=CANARY_MD_PAREN)", "example.test"),
            ('[x](https://example.test/p?a=") CANARY_MD_QUOTED_SPACE"&key=Z)', "example.test"),
            ('[x](https://example.test/p(v) "title ) CANARY_MD_QUOTED_TITLE")', "example.test"),
            ("[x](https://example.test/c?f=sum(a)&key=CANARY_MD_NESTED)", "example.test"),
            ("[x](https://example.test/p)?code=CANARY_MD_TAIL", "example.test"),
            ("[x](<https://example.test/p>)?code=CANARY_MD_ANGLE_TAIL", "example.test"),
            ('[x](https://example.test/p "t")&key=CANARY_MD_TITLE_TAIL', "example.test"),
            ("[guide](../guide(CANARY_RELATIVE).md)", "[guide]"),
            ("[guide] (./secret/CANARY_SPACE_PAREN.md)", "[guide]"),
            ("[ref]: ./CANARY_REFERENCE.md", "[ref]"),
            (r"[a\]]: ./secret/CANARY_ESCAPED_REF.md", r"[a\]]"),
            (f"Authorization: Bearer {credential}", "REDACTED"),
            # A backslash after a host is a path separator to WHATWG, so the link is unnamed.
            ("example.test\\CANARY_BACKSLASH", "[link]"),
            ("localhost:3000\\CANARY_BACKSLASH_LOCAL", "[link]"),
            ("example.рф/r?c=CANARY_IDN_TLD", "[link]"),
            ("пример.рф/r?c=CANARY_IDN_HOST", "[link]"),
            ("sub.пример.рф/r?c=CANARY_IDN_SUB", "[link]"),
            ("example。test/CANARY_IDEOGRAPHIC_DOT", "[link]"),
            ("example\uff0etest/CANARY_FULLWIDTH_DOT", "[link]"),
            ("example｡test/CANARY_HALFWIDTH_DOT", "[link]"),
            ("example.test./CANARY_TRAILING_DOT", "example.test"),
            ("a-localhost:3000/reset/CANARY_GLUED_LOCAL", "localhost"),
            ("1localhost:3000/reset/CANARY_DIGIT_LOCAL", "localhost"),
            ("a.192.168.1.10/admin/CANARY_DOT_IP", "192.168.1.10"),
            ("a-10.0.0.5:8080/CANARY_DASH_IP", "10.0.0.5"),
            ("1192.168.1.10/admin/CANARY_DIGIT_IP", "192.168.1.10"),
            ("a-data:text/plain,CANARY_DASH_DATA", "[link]"),
            ("1data:text/plain,CANARY_DIGIT_DATA", "[link]"),
            ("adata:text/plain;base64,CANARY_LETTER_DATA", "[link]"),
            ("git@host:CANARY_ORG/CANARY_REPO.git", "host"),
            ("git@github.com:CANARY_ORG/repo.git", "github.com"),
            ("git@[::1]:CANARY_ORG/repo.git", "[::1]"),
            ("git@host:CANARY_REPO_ONLY.git", "host"),
            ("_git@host:CANARY_EMPHASIS.git_", "host"),
            ("CANARY_REMOTE_USER:CANARY_REMOTE_PASS@host:CANARY_ORG/repo.git", "host"),
            ("CANARY_IP_USER:CANARY_IP_PASS@1192.168.1.10/admin/CANARY_IP_PATH", "192.168.1.10"),
            ("CANARY_LOCAL_USER@a-localhost:3000/CANARY_LOCAL_PATH", "localhost"),
            ("CANARY_IDN_USER@пример.рф/CANARY_IDN_PATH", "[link]"),
            ("webcal:feed?c=CANARY_WEBCAL", "[link]"),
            ("web+example:opaque-CANARY_WEB_PLUS", "[link]"),
            ("1webcal:CANARY_GLUED_WEBCAL", "[link]"),
            # A known link later in the token keeps its own span; the added form masks the rest.
            ("CANARY_U1:CANARY_P1@1192.168.1.10/admin?r=//x", "192.168.1.10"),
            ("git@host:CANARY_ORG/repo.git#readme", "host"),
            ("example.рф/CANARY_NEXT?next=https://other.test/", "[link]"),
            ("webcal:CANARY_WEBCAL_NEXT?next=https://x.test/", "[link]"),
            ("a-localhost\\CANARY_GLUED_BACKSLASH", "[link]"),
            ("example.xn--p1ai\\CANARY_PUNY_BACKSLASH", "[link]"),
            ("x@webcal:org/CANARY_OPAQUE_REMOTE.git", "[link]"),
            ("参考docs.example.test\\CANARY_CJK_BACKSLASH", "参考[link]"),
            ("CANARY_U2:CANARY_P2%3A@host:org/repo.git", "host"),
            ("CANARY_U3:CANARY_P3!@host:org/repo.git", "host"),
            ("CANARY_U4:CANARY_P4@host:/srv/CANARY_SLASH.git", "[link]"),
            ("CANARY_U5:CANARY_P5@CANARY_P6@1192.168.1.10/CANARY_AT", "192.168.1.10"),
            ("adata:;base64,CANARY_DATA_PARAMS", "[link]"),
            ("उदाहरण.भारत/CANARY_DEVANAGARI", "[link]"),
            ("ตัวอย่าง.ไทย/CANARY_THAI", "[link]"),
            ("cafe\u0301.test/CANARY_COMBINING", "[link]"),
            ("пример1.рф/CANARY_MIXED_LABEL", "[link]"),  # noqa: RUF001 - a digit inside an IDN label
            ("git@host:CANARY_ORG\\repo.git", "[link]"),
            ("git@host:/srv/CANARY_ABSOLUTE.git", "[link]"),
            ("[repo](git@host:CANARY_ORG/repo.git)", "[repo]"),
            # A bracketed IPv6 address before a path, a query or a fragment.
            ("[::1]/CANARY_IPV6", "[::1]"),
            ("[2001:db8::1]/r?c=CANARY_IPV6_LONG", "[2001:db8::1]"),
            ("参考[::1]?code=CANARY_IPV6_QUERY", "[::1]"),
            ("CANARY_V6_USER@[::1]#CANARY_IPV6_FRAGMENT", "[::1]"),
            ("_[::1]/CANARY_IPV6_EMPHASIS_", "[::1]"),
            ("[fe80::1%25CANARY_ZONE]/CANARY_IPV6_ZONE", "[link]"),
            # Userinfo before a bare `www.` host with nothing after it.
            ("CANARY_W_USER:CANARY_W_PASS@www.example.test", "www.example.test"),
            # A full-width solidus or a zero-width character between a host and its path.
            ("example.test\uff0fCANARY_FULLWIDTH_SOLIDUS", "[link]"),
            (
                "\uff45\uff58\uff41\uff4d\uff50\uff4c\uff45\uff0e\uff43\uff4f\uff4d\uff0fCANARY_WIDE",
                "[link]",
            ),
            ("example.test\u200b/CANARY_ZERO_WIDTH", "[link]"),
            ("example.test\u200b:8443/CANARY_ZERO_WIDTH_PORT", "[link]"),
            ("localhost\uff0fCANARY_LOCAL_SOLIDUS", "[link]"),
            # Masked from the token's start, so a later link's userinfo is still covered.
            ("CANARY_PRE!example.test\uff0fx@host:org/r.git", "[link]"),
            (":/CANARY_SCHEME:WWW.a.bc\uff0f:pw@blob:x", "[link]"),
            ("example.test\u2060\u00ad?code=CANARY_WORD_JOINER", "[link]"),
            # A git remote whose path holds a colon: what follows the colon may be another link
            # form, so no host is named.
            ("git@host:CANARY_ORG:CANARY_COLON.git", "[link]"),
            ("git@host:22:CANARY_PORT_PATH/r.git", "[link]"),
            # A slash, a query mark or a hash inside a password.
            ("CANARY_S_USER:CANARY_S1/CANARY_S2@host:org/r.git", "host"),
            ("CANARY_T_USER:CANARY_T1/CANARY_T2@example.test/x", "example.test"),
            ("CANARY_Q_USER:CANARY_Q1?CANARY_Q2#CANARY_Q3@1192.168.1.10/x", "192.168.1.10"),
            ("CANARY_B64/CANARY_B64+x@www.example.test/x", "www.example.test"),
            ("CANARY_X/CANARY_Y@www.example.test", "www.example.test"),
            ("x.рф\u200b/CANARY_ZW_IDN", "[link]"),
            ("例子。com\u200b/CANARY_ZW_WIDE", "[link]"),
            ("CANARY_V6_PREFIX![::1]/x", "[::1]"),
            ("CANARY_GZ!a-localhost\u200b/x", "[link]"),
            # An `@` after a remote's colon may be a password's: the host after it is named, or
            # none is.
            ("CANARY_R1@CANARY_R2:CANARY_R3@host:org/r.git", "host"),
            ("CANARY_R4@CANARY_R5:CANARY_R6/x@host:org/r.git", "[link]"),
        )
        self.write_sources(
            {
                "goals": "## Goals\n"
                + "".join(f"- G{i}: {link}\n" for i, (link, _) in enumerate(links, 1)),
                "design": "".join(f"### Decision: {link}\n" for link, _ in links),
                "tracker": "| Item | Status |\n| --- | --- |\n"
                + "".join(f"| {link} | fixed |\n" for link, _ in links),
                "diagrams": "## Sample\n```mermaid\nflowchart LR\n"
                + "\n".join(link for link, _ in links)
                + "\n```\n",
            }
        )
        self.configure()
        self.log.write_text(
            "".join(f"ask hull:{i} {link}\n" for i, (link, _) in enumerate(links)), encoding="utf-8"
        )
        payload, body = self.payload()
        diagram = payload["diagrams"][0]["body"].splitlines()[1:]
        for index, (link, expected) in enumerate(links):
            with self.subTest(link=link):
                for actual in (
                    payload["goals"][index]["title"],
                    payload["design"][index]["title"],
                    payload["tracker"][index]["title"],
                    payload["asks"][index]["text"],
                    diagram[index],
                ):
                    self.assertIn(expected, actual)
                    self.assertNotIn("CANARY_", actual)
                    self.assertNotIn(credential, actual)
        self.assertNotIn(b"CANARY_", body)
        self.assertNotIn(b"https://", body)
        self.assertNotIn(credential.encode(), body)
        hosts = payload["diagrams"][0]["linkHosts"]
        self.assertNotIn("-docs.example.test", hosts)
        self.assertTrue({"host", "github.com", "[::1]", "localhost", "10.0.0.5"} <= set(hosts))
        self.assertFalse([host for host in hosts if not host.isascii() or "\\" in host])

    def test_multiline_diagram_link_destinations_are_stripped(self) -> None:
        long_label = "[" + "a" * 1000 + "]"
        self.write_sources(
            {
                "diagrams": "```\n[guide](\n./secret/CANARY_REL.md)\n"
                "[guide](  \n  ./secret/CANARY_INDENTED.md)\n"
                "[guide](\nhttps://example.test/p?code=CANARY_URL)\n"
                "[ref]:\n  ./secret/CANARY_REF.md\n"
                "[x](./guide.md\n)?code=CANARY_TAIL\n"
                "[outer]([inner](\n./secret/CANARY_NESTED_LEGACY.md))\n"
                '[x](https://example.test/p "title\nCANARY_INLINE_TITLE")\n'
                '[reference]: ./guide.md\n  "title\nCANARY_REFERENCE_TITLE"\n'
                f"{long_label}: ./secret/CANARY_LONG_LABEL.md\n"
                "Keep this line\n"
                "[mailto:CANARY_REFERENCE_LABEL<]:\n  ./guide.md\n```\n",
            }
        )
        self.configure()
        plan, body = self.payload()
        self.assertNotIn(b"CANARY_", body)
        self.assertEqual(
            plan["diagrams"][0]["body"],
            "[guide]\n[guide]\n[guide] (example.test)\n[ref]\n[x]\n[outer]\n"
            f"[x] (example.test)\n[reference]\n{long_label}\nKeep this line\n[[link]",
        )

    def test_common_markdown_destinations_are_stripped(self) -> None:
        self.write_sources(
            {
                "goals": "## Goals\n- G1: [Guide](./guide(v2).md) followed by words\n",
                "diagrams": "## Sample\n```\n[guide]: ./offline-guide.md\n```\n",
            }
        )
        self.configure()
        plan, _ = self.payload()
        self.assertEqual(plan["goals"][0]["title"], "[Guide] followed by words")
        self.assertNotIn("./offline-guide.md", plan["diagrams"][0]["body"])

    def test_lane_ids_follow_the_same_credential_redaction_as_text(self) -> None:
        credential = "xoxb-225556655-example-token"
        self.write_sources({"goals": f"## Goals\n- G1: Sample\n**Lanes:** {credential}, hull\n"})
        (self.briefs / f"{credential}.md").write_text("*Serves*: G1\n")
        (self.briefs / "hull.md").write_text("## Goal\nBuild the hull\n\n*Serves*: G1\n")
        self.log.write_text(f"ask {credential}:1 Sample question\n")
        self.only_goals()
        plan, body = self.payload()
        self.assertEqual([lane["id"] for lane in plan["lanes"]], ["hull"])
        self.assertEqual(plan["goals"][0]["lanes"], ["hull"])
        self.assertIsNone(plan["asks"][0]["lane"])
        self.assertNotIn(credential.encode(), body)

    def test_log_lane_and_projection_refuse_credential_shaped_lane_ids(self) -> None:
        credential = "xoxb-225556655-example-token"
        self.write_sources({"goals": "## Goals\n- G1: Sample\n**Lanes:** hull\n"})
        (self.briefs / "hull.md").write_text("## Goal\nBuild the hull\n", encoding="utf-8")
        self.log.write_text(f"ask {credential}:1 Sample question\n", encoding="utf-8")
        plan = readers.read_plan(self.only_goals()).model
        self.assertIsNone(plan.asks[0].lane)

        unsafe = replace(
            plan,
            goals=(replace(plan.goals[0], lanes=(credential, "hull")),),
            lanes=(*plan.lanes, model.Lane(credential, None, None, (), plan.lanes[0].source)),
            asks=(replace(plan.asks[0], lane=credential),),
        )
        projected = publish._project(unsafe, {credential: ["Synthetic session"]})
        self.assertEqual([lane["id"] for lane in projected["lanes"]], ["hull"])
        self.assertEqual(projected["goals"][0]["lanes"], ["hull"])
        self.assertIsNone(projected["asks"][0]["lane"])

        config_file = self.home / settings.FILENAME
        doc = json.loads(config_file.read_bytes())
        doc["briefs"]["lane_folders"][credential] = str(self.hull)
        config_file.write_text(json.dumps(doc), encoding="utf-8")
        self.assertEqual(settings.load(str(self.home)).reason, settings.MALFORMED)

    def test_caps_keep_redaction_markers_whole(self) -> None:
        from compass_runtime import records  # noqa: PLC0415

        for limit in (512, 8192):
            with self.subTest(limit=limit):
                marker = records.SECRET_MARKER
                for remaining in range(1, len(marker)):
                    text = "x" * (limit - 1 - remaining) + marker + " suffix"
                    capped = publish._cap(text, limit)
                    self.assertLessEqual(len(capped), limit)
                    self.assertNotIn(marker[:2], capped.removesuffix(marker))

    def test_private_child_session_never_joins_public_parent(self) -> None:
        child = self.hull / "sealed"
        child.mkdir()
        alias = self.root / "alias"
        alias.symlink_to(child, target_is_directory=True)
        (self.briefs / "hull.md").write_text("## Goal\nBuild the hull\n")
        for private in (
            {"roots": [str(alias)]},
            {"markers": [{"value": "sealed", "mode": "component"}]},
            {"marker_files": [".restricted"]},
        ):
            with self.subTest(private=private):
                if "marker_files" in private:
                    (child / ".restricted").touch()
                self.configure(private=private)
                app = self.application()
                app.snapshot.publish(
                    (app.config.window_hours, False),
                    b"{}",
                    folders=(
                        ("claude", "private", str(child)),
                        ("claude", "alias", str(alias)),
                        ("claude", "public", str(self.hull)),
                    ),
                )
                self.assertEqual(
                    self.payload(app)[0]["lanes"][0]["sessions"], ['session:["claude","public"]']
                )

    def test_unmeasured_join_differs_from_warm_zero(self) -> None:
        for slug in ("hull", "none", "refused"):
            (self.briefs / f"{slug}.md").write_text("## Goal\nSample lane\n")
        refused = self.root / "refused"
        refused.mkdir()
        (refused / ".restricted").touch()
        self.configure(briefs={"lane_folders": {"hull": str(self.hull), "refused": str(refused)}})
        app = self.application()
        cold = {row["id"]: row["sessions"] for row in self.payload(app)[0]["lanes"]}
        app.snapshot.publish((app.config.window_hours, False), b"{}", folders=())
        warm = {row["id"]: row["sessions"] for row in self.payload(app)[0]["lanes"]}
        self.assertEqual(cold, {"hull": None, "none": None, "refused": None})
        self.assertEqual(warm, {"hull": [], "none": None, "refused": None})

    @unittest.skipIf(os.geteuid() == 0, "root reads a directory whatever its mode")
    def test_unexaminable_session_folder_leaves_the_join_unmeasured(self) -> None:
        (self.briefs / "hull.md").write_text("## Goal\nBuild the hull\n")
        locked = self.root / "locked"
        (locked / "inner").mkdir(parents=True)
        sealed = self.root / "sealed"
        (sealed / "inner").mkdir(parents=True)
        policy = self.configure(private={"roots": [str(sealed)]}).sources.policy
        app = self.application()

        def lanes(*folders: Path) -> Any:
            app.snapshot.publish(
                (app.config.window_hours, False),
                b"{}",
                folders=(
                    ("claude", "public", str(self.hull)),
                    *(("claude", f"s{index}", str(path)) for index, path in enumerate(folders)),
                ),
            )
            return self.payload(app)[0]["lanes"][0]["sessions"]

        public = ['session:["claude","public"]']
        self.assertEqual(lanes(locked / "inner", self.root / "gone"), public)
        locked.chmod(0)
        self.addCleanup(locked.chmod, 0o700)
        # The locked folder might sit below the lane folder, so neither a full nor an empty
        # list would be true.
        self.assertIsNone(lanes(locked / "inner"))
        self.assertIsNone(runtime_io.plan_session_ancestry(str(locked / "inner"), policy))
        # A private folder is excluded rather than unexamined, even when it cannot be listed.
        sealed.chmod(0o111)
        self.addCleanup(sealed.chmod, 0o700)
        self.assertEqual(lanes(sealed / "inner"), public)
        self.assertEqual(
            runtime_io.plan_session_ancestry(str(sealed / "inner"), policy), frozenset()
        )
        # A folder that can be entered but not listed cannot be cleared of marker files, so it
        # is not examined, unless an exact marker name or a private identity settles it.
        listed_only = self.hull / "exec"
        (listed_only / "inner").mkdir(parents=True)
        listed_only.chmod(0o111)
        self.addCleanup(listed_only.chmod, 0o700)
        self.assertIsNone(lanes(listed_only / "inner"))
        self.assertIsNone(runtime_io.plan_session_ancestry(str(listed_only / "inner"), policy))
        listed_only.chmod(0o700)
        (listed_only / ".restricted").touch()
        listed_only.chmod(0o111)
        self.assertEqual(lanes(listed_only / "inner"), public)
        # Even one that cannot be entered at all is identified by its metadata.
        sealed.chmod(0)
        self.assertEqual(lanes(sealed, sealed / "inner"), public)
        for folder in (sealed, sealed / "inner"):
            self.assertEqual(runtime_io.plan_session_ancestry(str(folder), policy), frozenset())

    def test_root_owned_and_crowded_ancestors_keep_the_join_measured(self) -> None:
        (self.briefs / "hull.md").write_text("## Goal\nBuild the hull\n")
        crowded = self.root / "crowded"
        (crowded / "inner").mkdir(parents=True)
        for index in range(4100):
            (crowded / f"entry-{index}").touch()
        policy = self.configure().sources.policy
        app = self.application()
        app.snapshot.publish(
            (app.config.window_hours, False),
            b"{}",
            folders=(
                ("claude", "public", str(self.hull)),
                ("claude", "root", "/"),
                ("claude", "tmp", "/tmp"),
                ("claude", "crowded", str(crowded / "inner")),
            ),
        )
        lanes = self.payload(app)[0]["lanes"]
        self.assertEqual(lanes[0]["sessions"], ['session:["claude","public"]'])
        for folder in ("/", "/tmp"):
            self.assertIsNotNone(runtime_io.plan_session_ancestry(folder, policy))
        # The root folder is examined, not merely excluded.
        self.assertTrue(runtime_io.plan_session_ancestry("/", policy))
        # Only a lookup the system refuses leaves the join unmeasured.
        for error, expected in (
            (errno.EMFILE, None),
            (errno.EIO, None),
            (errno.ENOENT, frozenset()),
            (errno.ENOTDIR, frozenset()),
            (errno.ELOOP, frozenset()),
        ):
            with (
                self.subTest(errno=errno.errorcode[error]),
                mock.patch.object(
                    runtime_io, "_session_identities", side_effect=OSError(error, "probe")
                ),
            ):
                self.assertEqual(runtime_io.plan_session_ancestry("/", policy), expected)
        # A marker scan over the cap cannot clear the folder, so it joins no lane.
        self.assertEqual(
            runtime_io.plan_session_ancestry(str(crowded / "inner"), policy), frozenset()
        )

    def test_refused_lane_folder_has_a_path_free_reason(self) -> None:
        (self.briefs / "hull.md").write_text("## Goal\nBuild the hull\n")
        (self.hull / ".restricted").touch()
        self.configure()
        app = self.application()
        plan, body = self.payload(app)
        self.assertIn(
            {
                "kind": "lane folder",
                "label": "hull",
                "fileLabel": None,
                "position": None,
                "state": "refused",
                "reason": "private",
            },
            plan["sources"],
        )
        self.assertNotIn(os.fsencode(self.hull), body)
        report = diagnostics._plan_report(app.state)
        self.assertIn({"kind": "lane folder", "reason": "private"}, report["sources"])
        self.assertNotIn(str(self.hull), json.dumps(report))

    def test_draft_unavailable_differs_from_measured_no_proposals(self) -> None:
        self.write_sources({"goals": "## Goals\n- G1: Primary goal\n"})
        self.only_goals()
        git(self.repo, "branch", "draft/plan")
        measured, _ = self.payload()
        git(self.repo, "branch", "-D", "draft/plan")
        unavailable, body = self.payload()
        self.assertIn(
            {
                "kind": "draft goals",
                "label": "Example",
                "fileLabel": None,
                "position": None,
                "state": "ok",
                "reason": None,
            },
            measured["sources"],
        )
        self.assertIn(
            {
                "kind": "draft goals",
                "label": "Example",
                "fileLabel": None,
                "position": None,
                "state": "refused",
                "reason": "branch missing",
            },
            unavailable["sources"],
        )
        self.assertEqual(unavailable["goals"], measured["goals"])
        self.assertNotIn(b"draft/plan", body)

    def test_target_ref_marker_matches_case_and_nfd_variants_before_blob(self) -> None:
        git(self.repo, "config", "core.precomposeunicode", "false")
        self.write_sources({"anchor": "Keep the parent in the checkout"})
        run = git_status.PlanTreeReader._run
        for name, marker_file in (
            (".RESTRICTED", ".restricted"),
            (".re\u0301stricted", ".réstricted"),
        ):
            git(self.repo, "switch", "-qc", "target")
            (self.repo / "plan" / name).touch()
            self.write_sources({"goals": "## Goals\n- G1: CANARY_REF_MARKER\n"})
            git(self.repo, "switch", "main")
            git(self.repo, "branch", "-f", "draft/plan", "target")
            self.assertFalse((self.repo / "plan" / name).exists())
            self.only_goals(private={"marker_files": [marker_file]})
            path = self.home / settings.FILENAME
            doc = json.loads(path.read_bytes())
            doc["repos"][0]["files"]["goals"].append("plan/second.md")
            for primary in (True, False):
                with self.subTest(name=name, primary=primary):
                    doc["repos"][0]["ref"] = "target" if primary else "main"
                    path.write_text(json.dumps(doc), encoding="utf-8")
                    with mock.patch.object(
                        git_status.PlanTreeReader, "_run", autospec=True, side_effect=run
                    ) as observed:
                        plan, body = self.payload()
                    kind = "goals" if primary else "draft goals"
                    self.assertEqual(
                        next(row["reason"] for row in plan["sources"] if row["kind"] == kind),
                        "private",
                    )
                    self.assertNotIn(b"CANARY_REF_MARKER", body)
                    self.assertTrue(
                        all(call.args[1][0] != "cat-file" for call in observed.call_args_list)
                    )
                    listings = [
                        call.args[1]
                        for call in observed.call_args_list
                        if call.args[1][:2] == ("ls-tree", "-z")
                    ]
                    with self.subTest(listings=listings):
                        self.assertEqual(len(listings), 2 if primary else 4)
                        self.assertEqual(len(set(listings)), len(listings))
            git(self.repo, "branch", "-D", "target")

    def test_target_ref_marker_listing_fails_closed_before_blob(self) -> None:
        self.write_sources({"goals": "## Goals\n- G1: CANARY_LISTING\n"})
        self.only_goals()
        run = git_status.PlanTreeReader._run
        oid = b"a" * 40
        over_cap = b"".join(
            b"100644 blob " + oid + b"\tplan/entry-" + str(index).encode() + b"\0"
            for index in range(4097)
        )
        for listing in (None, over_cap):
            with self.subTest(over_cap=listing is not None):

                def broken_listing(
                    tree: git_status.PlanTreeReader,
                    args: tuple[str, ...],
                    deadline: float,
                    listing: bytes | None = listing,
                ) -> bytes:
                    if args[:2] == ("ls-tree", "-z") and args[-1] == "plan/":
                        if listing is None:
                            raise git_status.PlanGitError("unreadable")
                        return listing
                    return run(tree, args, deadline)

                with mock.patch.object(
                    git_status.PlanTreeReader, "_run", autospec=True, side_effect=broken_listing
                ) as observed:
                    plan, body = self.payload()
                self.assertEqual(plan["sources"][0]["state"], "refused")
                self.assertNotIn(b"CANARY_LISTING", body)
                self.assertTrue(
                    all(call.args[1][0] != "cat-file" for call in observed.call_args_list)
                )

    def test_draft_goal_has_proposal_status_without_progress_date(self) -> None:
        self.write_sources({"goals": "## Goals\n- G1: Primary goal\n"})
        git(self.repo, "switch", "-qc", "draft/plan")
        self.write_sources({"goals": "## Goals\n- G1: Primary goal\n- G2: Draft goal\n"})
        git(self.repo, "switch", "main")
        self.only_goals()
        goals = self.payload()[0]["goals"]
        self.assertEqual([g["proposal"] for g in goals], [None, "Proposed, not merged"])
        self.assertTrue(all(goal["date"] is None and "at" not in goal for goal in goals))

    def test_untimestamped_ask_has_no_time_label(self) -> None:
        self.configure()
        self.log.write_text("ask hull:one Question\n")
        ask = self.payload()[0]["asks"][0]
        self.assertIsNone(ask["at"])
        self.assertIsNone(ask["timeLabel"])

    def test_diagnostics_only_echo_status_words(self) -> None:
        self.write_sources(
            {
                "tracker": "| Item | Status |\n| --- | --- |\n"
                "| Sample | https://example.test/a |\n"
                "| Other | unusual seabird |\n"
            }
        )
        self.configure(tracker={"tail_separators": []})
        report = diagnostics._plan_report(self.application().state)
        self.assertEqual(
            [row["word"] for row in report["unknown_statuses"]],
            ["Status not recognised", "unusual seabird"],
        )

    def test_diagnostics_hide_alpha_only_credentials(self) -> None:
        credential = "Bearer Abcdefghijklmnopqrstuvwx"
        self.write_sources(
            {"tracker": f"| Item | Status |\n| --- | --- |\n| Sample | {credential} |\n"}
        )
        self.configure(tracker={"tail_separators": []})
        report = diagnostics._plan_report(self.application().state)
        self.assertNotIn(credential, json.dumps(report))
        self.assertEqual(
            [row["word"] for row in report["unknown_statuses"]], ["Status not recognised"]
        )

    def test_disabled_payload_opens_nothing(self) -> None:
        self.configure()
        app = self.application(plan_enabled=False)
        with mock.patch.object(
            runtime_io, "read_plan_settings", wraps=runtime_io.read_plan_settings
        ) as read:
            self.assertEqual(
                publish.payload(app.config, app.state),
                {"state": "refused", "reason": "plan is off"},
            )
        read.assert_not_called()

    def test_disabled_collection_captures_no_folders(self) -> None:
        def captured_folders(enabled: bool) -> Any:
            app = self.application(
                [{"sid": "one", "state": "working", "last_activity": 4_900.0}],
                plan_enabled=enabled,
            )
            board = app.collect(show_all=False)

            def collect(*, show_all: bool) -> Any:
                self.assertFalse(show_all)
                sessions.apply_project_identity(app.config, board["sessions"][0], str(self.hull))
                return board

            with mock.patch.object(app, "collect", side_effect=collect):
                app.collect_json(show_all=False)
            return app.snapshot.session_folders((app.config.window_hours, False))

        self.assertEqual(captured_folders(False), ())
        self.assertEqual(captured_folders(True), (("claude", "one", str(self.hull)),))

    def test_diagram_body_source_labels_and_links_are_filtered_before_the_cap(self) -> None:
        from compass_runtime import records  # noqa: PLC0415

        self.write_sources(
            {
                "diagrams": "## Model assembly\n```mermaid\nflowchart LR\n"
                '  A["https://login:password@diagram.example.test:8443/path?key=CANARY_DIAGRAM"] --> B\n'
                "```\n"
            }
        )
        self.configure(log={"label": "https://log.example.test/path?code=CANARY_SOURCE"})
        payload, body = self.payload()
        diagram = payload["diagrams"][0]
        self.assertEqual(diagram["body"], 'flowchart LR\n  A["diagram.example.test --> B')
        self.assertEqual(diagram["linkHosts"], ["diagram.example.test"])
        self.assertTrue(any(row["label"] == "log.example.test" for row in payload["sources"]))
        self.assertNotIn(b"CANARY_", body)
        self.assertNotIn(b"password", body)
        self.assertNotIn(b":8443", body)
        text, hosts = records.hosts_only(
            "See [the note](<https://note.example.test/path?key=CANARY_NOTE>) "
            "and <//team.example.test/share/CANARY_TEAM>. "
            "Also [a file](../CANARY_LOCAL)."
        )
        self.assertEqual(hosts, ("note.example.test", "team.example.test"))
        self.assertNotIn("CANARY_", text)

    def test_diagram_cap_applies_after_redaction_and_host_replacement(self) -> None:
        lines = (
            'flowchart LR\n  A["'
            + "x " * 4050
            + "https://bounded.example.test/"
            + "CANARY_LONG_URL_" * 250
            + '"] --> B\n'
            + '  B["Authorization: Bearer xoxb-225556655-example-token"]\n'
            + '  C["'
            + "X " * 180
            + '"]'
        )
        self.write_sources({"diagrams": f"## Assembly\n```mermaid\n{lines}\n```\n"})
        self.configure()
        payload, body = self.payload()
        diagram = payload["diagrams"][0]
        self.assertEqual(len(diagram["body"]), 8192)
        self.assertTrue(diagram["body"].endswith("…"))
        self.assertIn("bounded.example.test --> B", diagram["body"])
        self.assertNotIn(b"CANARY_LONG_URL_", body)
        self.assertNotIn(b"xoxb-22555", body)
        self.assertIn("REDACTED", diagram["body"])

    def test_lane_sessions_match_one_folder_identity_and_asks_keep_lane_ids(self) -> None:
        self.write_sources(STAND_IN)
        other = self.root / "work" / "other"
        nested = self.hull / "nested"
        child = self.hull / "child"
        for folder in (other, nested, child):
            folder.mkdir()
        alias = self.root / "alias"
        alias.symlink_to(self.hull, target_is_directory=True)
        for slug in ("hull", "paint", "nested", "empty"):
            (self.briefs / f"{slug}.md").write_text(
                "## Goal\nSame lane title\n\n*Serves*: G1\n", encoding="utf-8"
            )
        self.configure(
            briefs={
                "lane_folders": {
                    "hull": str(self.hull),
                    "paint": str(other),
                    "nested": str(nested),
                }
            }
        )
        self.log.write_text(
            "ask paint:1 Choose a color\n"
            "2026-01-02T03:04:05Z ask hull:2 Pick a material\n"
            "ask unknown:3 No admitted lane\n",
            encoding="utf-8",
        )
        folders = {"one": alias / "child", "two": nested, "three": other, "four": self.root}
        app = self.application(
            [{"sid": sid, "state": "working", "last_activity": 4_900.0} for sid in folders]
        )
        collect = app.collect

        def collect_with_folders(*, show_all: bool) -> Any:
            # Feed the same metadata hook the real collectors use, before the
            # collection becomes a snapshot. Goose has no transcript resolver.
            board = collect(show_all=show_all)
            for row in board["sessions"]:
                if row["sid"] == "three":
                    row["harness"] = "goose"
                sessions.apply_project_identity(app.config, row, str(folders[row["sid"]]))
            return board

        with mock.patch.object(app, "collect", side_effect=collect_with_folders):
            _, before = app.collect_json(show_all=False)
        payload, body = self.payload(app)
        lanes = {row["id"]: row for row in payload["lanes"]}
        self.assertEqual(set(payload["goals"][0]["lanes"]), set(lanes))
        self.assertEqual(lanes["hull"]["sessions"], ['session:["claude","one"]'])
        self.assertEqual(lanes["paint"]["sessions"], ['session:["goose","three"]'])
        self.assertEqual(lanes["nested"]["sessions"], [])
        self.assertIsNone(lanes["empty"]["sessions"])
        self.assertEqual(lanes["hull"]["title"], lanes["paint"]["title"])
        self.assertEqual(
            [(row["source"], row["lane"], row["timeLabel"], row["at"]) for row in payload["asks"]],
            [
                ("Coordination", {"id": "paint", "title": "Same lane title"}, None, None),
                (
                    "Coordination",
                    {"id": "hull", "title": "Same lane title"},
                    "from the log",
                    "2026-01-02T03:04:05Z",
                ),
                ("Coordination", None, None, None),
            ],
        )
        self.assertNotIn(os.fsencode(self.root), body)
        self.assertEqual(app.snapshot.current((app.config.window_hours, False))[1], before)
        for row in json.loads(before)["sessions"]:
            self.assertLessEqual(set(row), DECLARED_SESSION_FIELDS)
        self.assertLessEqual(set(events.PATCHABLE), DECLARED_SESSION_FIELDS)
        self.assertEqual(
            set(sessions.base_session("claude", "one", "demo")), DECLARED_SESSION_FIELDS
        )

    def test_plan_canary_stays_out_of_collection_and_saved_history(self) -> None:
        canary = "CANARY_PLAN_ONLY_q917"
        self.write_sources({"goals": f"## Goals\n- G1: {canary}\n"})
        self.configure()
        app = self.application([{"sid": "one", "state": "working", "last_activity": 4_900.0}])
        self.assertIn(canary.encode(), self.payload(app)[1])
        _, board = app.collect_json(show_all=False)
        self.assertNotIn(canary.encode(), board)
        saved = Path(history.store_path(app.config)).read_bytes()
        self.assertNotIn(canary.encode(), saved)
        entries, _ = history.load(app.config)
        self.assertTrue(entries)
        self.assertEqual(set(entries[0]), set(history.OBSERVATION_FIELDS))

    def test_slow_git_shares_the_request_deadline_across_commands_and_repos(self) -> None:
        self.write_sources(STAND_IN)
        self.configure()
        config_file = self.home / settings.FILENAME
        config = json.loads(config_file.read_bytes())
        config["repos"].append({**config["repos"][0], "label": "Second repository"})
        config_file.write_text(json.dumps(config), encoding="utf-8")

        now = 100.0
        timeouts: list[float] = []

        def runner(argv: tuple[str, ...], *, timeout: float, **_: Any) -> Any:
            nonlocal now
            timeouts.append(timeout)
            if len(timeouts) == 1:
                now += 0.75
                return subprocess.CompletedProcess(argv, 0, b"\n", b"")
            now += timeout
            raise subprocess.TimeoutExpired(argv, timeout)

        factory = git_status.plan_reader
        app = self.application(git_probe_timeout_sec=1.0)
        with (
            mock.patch.object(time, "monotonic", side_effect=lambda: now),
            mock.patch.object(
                git_status,
                "plan_reader",
                side_effect=lambda *a, **kw: factory(*a, **kw, runner=runner),
            ),
        ):
            payload, _ = self.payload(app)
        self.assertEqual(timeouts, [1.0, 0.25])
        self.assertEqual(now, 101.0)
        self.assertEqual(payload["goals"], [])
        refused = [source for source in payload["sources"] if source["reason"] == "git timed out"]
        self.assertEqual(len(refused), 10)


class LinkProjectionTest(unittest.TestCase):
    def test_prose_that_only_resembles_a_link_is_kept(self) -> None:
        for text in (
            "metadata: foo, bar",
            "ping alice@corp: hello",
            "image@sha256:abcdef01",
            "release v1.2.3.4 shipped",
            "i.e.: see below",
            "notes on records.md",
            "a@b and c@d",
            "今日はリリース作業を行いました。次は?明日、レビューをお願いします。",
            "実験を行った．結果はA/Bの両方で改善した．詳細は付録を参照．",  # noqa: RUF001 - CJK prose
            "我们完成了迁移。下一步:更新文档，然后发布。",  # noqa: RUF001 - CJK prose
            "好的。为什么?",
            "完了。テスト:確認",
            "xwebcal:x",
            "git@host:x.gitx",
            "see webcal: later",
            "1tel: call me",
            "ping @team:design/ux",
            "arr[::2]/n",
            "[1:2]/3",
            "完了しました。詳細\uff0f補足は後で",
            "A\uff0fB testing",
            "see plan.md\u200b: notes",
            "ping alice@corp: 12:30/45",
        ):
            with self.subTest(text=text):
                self.assertEqual(records.hosts_only(text), (text, ()))

    def test_text_glued_to_a_link_stays_beside_its_host(self) -> None:
        for text, expected, host in (
            ("完了。https://example.test/p/CANARY", "完了。example.test", "example.test"),
            ("完了。example.test/p/CANARY", "完了。example.test", "example.test"),
            ("参考docs.example.test/d/CANARY", "参考docs.example.test", "docs.example.test"),
            ("a-localhost:3000/CANARY", "a-localhost", "localhost"),
            ("user:CANARY@host:org/repo.git", "host", "host"),
            ("参考docs.example.test\\CANARY", "参考[link]", None),
            ("ü-app.рф/CANARY", "[link]", None),
            ("例子。中国/CANARY，然后", "[link]，然后", None),  # noqa: RUF001 - CJK prose
            ("完了。example。test/CANARY", "完了。[link]", None),
            ("mail a@b then пример.рф/CANARY", "mail a@b then [link]", None),
            ("foo..example.рф/CANARY", "foo..[link]", None),
            ("u:p@secret-host:/srv/r.git", "[link][link]", None),
            ("webcal:CANARY@example.test/x", "example.test", "example.test"),
        ):
            with self.subTest(text=text):
                hosts = () if host is None else (host,)
                self.assertEqual(records.hosts_only(text), (expected, hosts))

    def test_a_form_found_here_first_never_cuts_a_later_link_short(self) -> None:
        # A form the board did not mask before can start ahead of one it did, whose own end
        # reaches further: to the line's end after an unmatched quote.
        for text in (
            "<example.test\u200b/x@host:org/r.git< CANARY_TAIL",
            "'a.bc\u200b/x@host:org/r.git' CANARY_TAIL",
            "'[::1]/webcal:x' CANARY_TAIL",
            '"[::1]/x-localhost:80/" CANARY_TAIL',
            "a.bc\uff0f'x@host:org/r.git' CANARY_TAIL 'tail",
            "'git@host:a:b.git`x-localhost/' CANARY_TAIL",
            "'git@host:a:b/c@d:e.git' CANARY_TAIL",
        ):
            with self.subTest(text=text):
                self.assertNotIn("CANARY", records.hosts_only(text)[0])

    def test_a_host_before_a_backslash_in_userinfo_is_not_named(self) -> None:
        # Userinfo read back past a backslash would leave a host before it named, where the
        # board left it unnamed.
        for text, host in (
            ("CANARY_USER:CANARY.secret\u3002/]\\@www.example.test", "www.example.test"),
            ("x-localhost/]\\@k.test/x", "k.test"),
            ("a.test\u3002/}\\x@www.example.test", "www.example.test"),
        ):
            with self.subTest(text=text):
                self.assertEqual(records.hosts_only(text)[1], (host,))

    def test_forms_found_here_first_keep_their_masks(self) -> None:
        for text, expected, hosts in (
            # A glued host before a colon is named, as before a path.
            ("a-localhost:CANARY", "a-localhost", ("localhost",)),
            ("example.test\ufeff/CANARY", "[link]", ()),
        ):
            with self.subTest(text=text):
                self.assertEqual(records.hosts_only(text), (expected, hosts))

    def test_prose_a_link_could_spell_stays_masked(self) -> None:
        # Each is prose here and a link elsewhere: `.md` is a country's top-level domain, git
        # reads `name@host:path` as a remote, and a word glued to a dotted quad is masked like
        # the hosts glued to one. Unmasking any of them would show what such a link carries.
        for text, expected, hosts in (
            ("README.md\\CANARY", "[link]", ()),
            ("v1.2.3.4/CANARY", "v1.2.3.4", ("1.2.3.4",)),
            ("docker image@sha256:abc/CANARY", "docker sha256", ("sha256",)),
            ("pkg@1.2.3:src/CANARY.js", "[link]", ()),
            ("完了。中国/CANARY", "[link]", ()),
        ):
            with self.subTest(text=text):
                self.assertEqual(records.hosts_only(text), (expected, hosts))


class KnownLinkOffsetsTest(unittest.TestCase):
    def test_linear_finder_matches_the_regex_search_at_every_offset(self) -> None:
        labels = [
            "a+b://x",
            "1+b://x y",
            "x.\u017f.com/",
            "\u017f" + "a" * 62 + ".com/",
            "a" * 63 + ".com/",
            "a" * 64 + ".com/",
            ".".join(["a"] * 126) + ".com/",
            ".".join(["a"] * 127) + ".com/",
            "\u0131example.com/ \u212a.test:80",
            "-a.com/ --.com/ a..b.com/",
            "a\u00e4.test/ \u017f-a.com/",
            "w\u0131ww.a/ localhost:3/",
        ]
        for text in labels:
            with self.subTest(text=text[:40]):
                known = records._KnownLinks(text)
                for offset in range(len(text) + 1):
                    found = known.match(offset)
                    expected = records._URL_START.search(text, offset)
                    self.assertEqual(
                        None if found is None else found.span(),
                        None if expected is None else expected.span(),
                    )


class LinkProjectionTimingTest(unittest.TestCase):
    # Measures elapsed time on adversarial input, to keep every link matcher linear.
    REAL_TIME_TESTS = True

    def test_adversarial_text_is_projected_in_linear_time(self) -> None:
        size = 250_000
        cases = {
            name: head + unit * ((size - len(head)) // len(unit)) + tail
            for name, head, unit, tail in (
                ("ascii and non-ascii letters", "", "aä", "!"),
                ("non-ascii letters and hyphens", "", "ä-a", "!"),
                ("scheme characters after plus signs", "", "a+", "!"),
                ("ideographic dots", "", "a。", "!"),
                ("full-width dotted labels", "", "ab\uff0e", "!"),
                ("non-ascii labels", "", "äb.", "!"),
                ("dashes", "", "-", "!"),
                ("scp-like remotes", "", "a@b:", "!"),
                ("userinfo", "", "a@", "!"),
                ("cyrillic", "", "п", "!"),
                ("digits and dots", "", "1.", "!"),
                ("glued data", "", "adata:", "!"),
                ("backslashes", "", "a.bc\\", "!"),
                ("brackets", "", "[", "!"),
                ("markdown destination", "[x](", "aä", ")"),
                ("markdown glued hosts", "", "[x](a-localhost/ ", "!"),
                ("userinfo before many glued hosts", "@", " x-localhost/", "!"),
                ("long s labels", "", "\u017f" * 63 + ".", "!"),
                ("kelvin labels", "", "\u212a" * 63 + ".", "!"),
                ("long s labels before a path", "", "\u017f" * 63 + ".", "com/"),
                ("overlong long s labels before a path", "", "\u017f" * 64 + ".", "com/"),
                ("repeated known links", "", "https://a.test/x ", "!"),
                ("repeated added links", "", "a.рф/x ", "!"),
                ("known links with no added form ahead", "", "//x ", "!"),
                ("bracketed addresses", "", "[::1]/ ", "!"),
                ("unclosed brackets of colons", "", "[1:", "!"),
                ("bracketed zones", "", "[::1%", "!"),
                ("full-width solidi after labels", "", "a.bc\uff0f", "!"),
                ("wide labels before solidi", "", "ab\uff0e\uff0f", "!"),
                ("zero-width characters after labels", "", "a.bc\u200b", "!"),
                ("a zero-width run before a path", "a.bc", "\u200b", "/"),
                ("scp-like remotes with colons", "", "a@b:c:", "!"),
                ("scp-like remotes before a far slash", "", "a@b:", "/x.git"),
                ("scp-like remotes with at signs", "", "a@b:c@", "/"),
                ("slashes, queries and hashes in userinfo", "", "a/?#", "@b.test/"),
                ("userinfo before www hosts", "", "a:b@www.", "!"),
                ("full-width solidi before quotes", "", "a.bc\uff0f'", "!"),
                ("quotes after a known link", "https://a.test/", "x'", "!"),
                ("quoted addresses before an opaque link", "", "'[::1]/webcal:x' ", "!"),
            )
        }
        for name, text in cases.items():
            with self.subTest(name=name):
                started = time.monotonic()
                records.hosts_only(text)
                # The slow shapes took 90 to 105 s before; linear projection takes under 0.4 s
                # here and up to 1.1 s on CI's 3.12 runner (measured 2026-11-27), so 5 s separates
                # them without failing on a slow runner.
                self.assertLess(time.monotonic() - started, 5.0)

    def test_an_added_link_before_a_known_one_scans_in_linear_time(self) -> None:
        # Linear time quadruples from 250 KB to 1 MB; a rescan to the line end for each added
        # link grows sixteenfold.
        for head, unit, tail in (
            ("", "a.рф/< //x ", "!"),
            ("", "x-localhost/< https://k.test/ ", ">"),
            ("", "[::1]/< www.k.test/ ", ">"),
            ("", "a.bc\uff0f< u:p@www.k.test ", ">"),
            # Each known link read the text back to an added link far after it: 4 s at 250 KB.
            ("", "//x ", "a.рф/x"),
            # Each quote searched for the line's end again.
            ("", "a.bc\uff0f'", "!"),
            ("https://a.test/", "x'", "!"),
            ("", "'[::1]/webcal:x' ", "!"),
        ):
            with self.subTest(unit=unit):
                took = []
                for size in (250_000, 1_000_000):
                    text = head + unit * (size // len(unit)) + tail
                    started = time.monotonic()
                    records.hosts_only(text)
                    took.append(time.monotonic() - started)
                self.assertLess(took[0], 5.0)
                self.assertLess(took[1], 8 * took[0])

    def test_a_long_userinfo_after_many_added_links_is_read_once(self) -> None:
        # Reading the userinfo back again for each added link before it was quadratic: 20 KB
        # of added links before a 20 KB token took 3.3 s (measured 2026-11-27).
        # Many known links before one added link read the text between them back once each:
        # 50 KB took 11.6 s.
        for links, link, token, tail in (
            ("a.рф/x ", 14, "a", "@b.test/"),
            ("//x ", 8, "!", "a.bc\uff0f"),
        ):
            took = []
            for size in (250_000, 1_000_000):
                text = links * (size // link) + token * (size // 2) + tail
                started = time.monotonic()
                records.hosts_only(text)
                took.append(time.monotonic() - started)
            self.assertLess(took[0], 5.0)
            self.assertLess(took[1], 8 * took[0])
