"""Plan dates have independent evidence for committed rows and local log records."""

from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import unittest
from dataclasses import asdict
from typing import TYPE_CHECKING, Any
from unittest import mock

from compass_runtime import cli, git_status
from compass_runtime.plan import readers
from compass_runtime.state import RuntimeState

from . import support
from .test_plan_readers import STAND_IN, PlanRepoTestCase
from .test_project_script_checks import GIT, git

if TYPE_CHECKING:
    from compass_runtime.plan.model import ItemDate

INITIAL = "2026-01-01T00:00:00Z"
LATER = "2026-01-02T00:00:00Z"
DRAFT = "2026-01-03T00:00:00Z"
MESSAGE = "Synthetic message canary"
AUTHOR = "Synthetic author canary"


def date_fields(date: ItemDate | None) -> tuple[str, str | None] | None:
    return (date.label, date.value) if date is not None else None


@unittest.skipIf(GIT is None or os.name == "nt", "Needs Git and POSIX directory descriptors")
class PlanDatesTest(PlanRepoTestCase):
    def setUp(self) -> None:
        super().setUp()
        real_factory = git_status.plan_reader
        self.calls: list[tuple[tuple[str, ...], bytes]] = []
        self.blame_fails = False

        def run(
            argv: tuple[str, ...], *, check: bool, **kwargs: Any
        ) -> subprocess.CompletedProcess[bytes]:
            if self.blame_fails and "blame" in argv:
                result = subprocess.CompletedProcess(argv, 1, b"")
            else:
                result = subprocess.run(argv, check=check, **kwargs)
            self.calls.append((argv, result.stdout))
            return result

        def factory(cwd: str, *, timeout_sec: float) -> git_status.PlanTreeReader:
            return real_factory(cwd, timeout_sec=timeout_sec, runner=run)

        self.enterContext(mock.patch.object(git_status, "plan_reader", side_effect=factory))

    def test_committer_time_for_each_line_survives_the_configured_ignore_file(self) -> None:
        self.write_sources(STAND_IN, when=INITIAL)
        git(self.repo, "config", "log.showSignature", "true")
        tracker = STAND_IN["tracker"].replace("Cut the hull", "Cut the deck")
        self.write_sources(
            {"tracker": tracker},
            "--author",
            f"{AUTHOR} <canary@example.test>",
            "--date",
            INITIAL,
            "-m",
            MESSAGE,
            when=LATER,
        )
        tip = subprocess.check_output([GIT or "git", "rev-parse", "HEAD"], cwd=self.repo)
        (self.repo / ".git" / "ignored-revisions").write_bytes(tip)
        git(self.repo, "config", "blame.ignoreRevsFile", ".git/ignored-revisions")
        # Apple Git 2.54.0 (Apple Git-157) needs the empty --ignore-revs-file
        # argument as well as the config override to clear the configured list.
        model = readers.read_plan(self.configure()).model
        self.assertEqual(
            [(row.title, date_fields(row.origin.date)) for row in model.tracker[:2]],
            [
                ("Cut the deck", ("Changed", "2026-01-02")),
                ("Paint the deck", ("Changed", "2026-01-01")),
            ],
        )
        self.assertTrue(any("blame" in argv for argv, _ in self.calls))
        self.assertTrue(any("log" in argv for argv, _ in self.calls))
        captured = b"".join(stdout for _, stdout in self.calls)
        for canary in (AUTHOR, MESSAGE, "canary@example.test", "Cut the hull"):
            with self.subTest(canary=canary):
                self.assertNotIn(canary, repr(asdict(model)))
                self.assertNotIn(canary.encode(), captured)

    def test_goal_and_diagram_dates_include_their_body_lines(self) -> None:
        self.write_sources(STAND_IN, when=INITIAL)
        self.write_sources(
            {
                "goals": STAND_IN["goals"].replace("The model floats.", "The model stays afloat."),
                "diagrams": STAND_IN["diagrams"].replace(" --> B", " --> C"),
            },
            when=LATER,
        )
        model = readers.read_plan(self.configure()).model
        self.assertEqual(
            [date_fields(g.origin.date) for g in model.goals],
            [("Changed", "2026-01-02"), ("Changed", "2026-01-01")],
        )
        self.assertEqual(
            date_fields(model.diagrams[0].origin.date),
            ("Changed", "2026-01-02"),
        )

    def test_main_dates_a_merged_line_at_the_first_parent_merge(self) -> None:
        self.write_sources(STAND_IN, when=INITIAL)
        git(self.repo, "switch", "-qc", "topic")
        self.write_sources(
            {"tracker": STAND_IN["tracker"].replace("Buy sandpaper", "Buy a sanding block")},
            when=LATER,
        )
        git(self.repo, "switch", "main")
        git(self.repo, "merge", "--no-ff", "--no-edit", "topic", when=DRAFT)
        model = readers.read_plan(self.configure()).model
        self.assertEqual(
            date_fields(model.tracker[-1].origin.date),
            ("Changed", "2026-01-03"),
        )

    def test_unchanged_tip_reuses_dates_and_a_moved_tip_does_not(self) -> None:
        self.write_sources(STAND_IN, when=INITIAL)
        loaded = self.configure()
        state = RuntimeState(support.make_config(), 0)
        readers.read_plan(loaded, state=state)
        self.assertTrue(any("blame" in argv for argv, _ in self.calls))
        self.calls.clear()
        readers.read_plan(loaded, state=state)
        self.assertFalse(any("blame" in argv or "log" in argv for argv, _ in self.calls))
        self.write_sources({"tracker": STAND_IN["tracker"].replace("open", "fixed")}, when=LATER)
        model = readers.read_plan(loaded, state=state).model
        self.assertTrue(any("blame" in argv for argv, _ in self.calls))
        self.assertEqual(
            date_fields(model.tracker[-1].origin.date),
            ("Changed", "2026-01-02"),
        )

    def test_failed_blame_keeps_the_committed_row_without_a_date(self) -> None:
        self.write_sources(STAND_IN, when=INITIAL)
        self.blame_fails = True
        model = readers.read_plan(self.configure()).model
        self.assertTrue(any("blame" in argv for argv, _ in self.calls))
        self.assertEqual(model.tracker[-1].title, "Buy sandpaper")
        self.assertIsNone(model.tracker[-1].origin.date)

    def test_draft_shows_only_new_items_with_the_draft_tip_date(self) -> None:
        self.write_sources(STAND_IN, when=INITIAL)
        git(self.repo, "switch", "-qc", "draft/plan")
        self.write_sources(
            {
                "tracker": STAND_IN["tracker"].replace(
                    "open | Buy sandpaper", "fixed | Buy sandpaper"
                )
                + "| open | Add a nameplate |\n",
                "goals": "## Goals\n- G1: Rewrite an existing goal\n- G4: Add a nameplate\n",
            },
            when=LATER,
        )
        git(self.repo, "commit", "--allow-empty", "-qm", "Advance draft tip", when=DRAFT)
        config = self.configure()
        model = readers.read_plan(config).model
        self.assertEqual(
            [g.title for g in model.goals],
            [
                "Restore the model ship",
                "Light the display",
                "Add a nameplate",
            ],
        )
        self.assertEqual(
            [(r.title, r.status, date_fields(r.origin.date)) for r in model.tracker[-2:]],
            [
                ("Buy sandpaper", "not_started", ("Changed", "2026-01-01")),
                ("Add a nameplate", "not_started", ("Proposed, not merged", "2026-01-03")),
            ],
        )
        self.assertEqual(model.tracker[-1].origin.source.ref, "draft/plan")

        git(self.repo, "update-ref", "refs/remotes/origin/draft/plan", "HEAD")
        git(self.repo, "switch", "main")
        git(self.repo, "branch", "-D", "draft/plan")
        self.calls.clear()
        model = readers.read_plan(config).model
        self.assertEqual([g.id for g in model.goals], ["G1", "G2"])
        self.assertEqual(len(model.tracker), 4)
        self.assertFalse(any("refs/remotes/origin/draft/plan" in argv for argv, _ in self.calls))

    def test_json_inventory_has_no_line_date(self) -> None:
        self.write_sources({"built": '[{"label": "Mirror", "phase": "shipped"}]'}, when=INITIAL)
        model = readers.read_plan(
            self.configure(
                inventory={"form": "json", "title_column": "label", "state_locator": "phase"}
            )
        ).model
        self.assertEqual(model.inventory[0].title, "Mirror")
        self.assertIsNone(model.inventory[0].origin.date)
        self.assertFalse(any("blame" in argv for argv, _ in self.calls))

    def test_briefs_and_asks_use_only_admitted_log_times(self) -> None:
        for slug in ("hull", "paint", "lamp"):
            (self.briefs / f"{slug}.md").write_text("## Goal\nFinish it.\n", encoding="utf-8")
        self.log.write_text(
            "2026-01-02T03:04:05Z ask hull:one Is the hull ready?\n"
            "2026-01-02T03:05:00Z note hull:note Private event text\n"
            "2026-01-02T03:10:00Z unknown hull:note Rejected timestamp\n"
            "2026-01-02T03:00:00Z note paint:old Old note\n"
            "ask paint:one What paint?\n",
            encoding="utf-8",
        )
        model = readers.read_plan(self.configure()).model
        self.assertEqual(
            {lane.slug: date_fields(lane.date) for lane in model.lanes},
            {"hull": ("from the log", "2026-01-02T03:05:00Z"), "paint": None, "lamp": None},
        )
        self.assertEqual(
            [date_fields(ask.date) for ask in model.asks],
            [("from the log", "2026-01-02T03:04:05Z"), None],
        )
        self.assertNotIn("Private event text", json.dumps(asdict(model)))

    def test_no_git_and_no_plan_start_no_plan_commands(self) -> None:
        self.write_sources(STAND_IN, when=INITIAL)
        self.configure()
        for flag in ("--no-git", "--no-plan"):
            output = io.StringIO()
            with (
                self.subTest(flag=flag),
                mock.patch.dict(
                    os.environ, {"COMPASS_HOME": str(self.home), "HOME": str(self.root)}
                ),
                contextlib.redirect_stdout(output),
            ):
                self.assertEqual(
                    cli.main(["--diagnose", "--json", "--no-usage", "--no-spacedock", flag]), 0
                )
                report = json.loads(output.getvalue())["plan"]
                self.assertEqual(self.calls, [])
                if flag == "--no-plan":
                    self.assertEqual(report["reason"], "plan is off")
                else:
                    self.assertTrue(
                        any(s["reason"] == "git reads are off" for s in report["sources"])
                    )
