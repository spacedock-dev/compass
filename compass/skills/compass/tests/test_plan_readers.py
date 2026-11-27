"""The plan's declared inputs, using two synthetic grammars and real Git trees."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any
from unittest import mock

from compass_runtime import git_status, io
from compass_runtime.plan import readers, settings, sources

from .test_project_script_checks import BEFORE_THE_SESSION, GIT, git

FIXTURES = Path(__file__).parent / "fixtures" / "plan"

STAND_IN = {
    "goals": "## Goals\n- G1 · Restore the model ship\n"
    "**Done when:** The model floats.\n**Lanes:** hull, paint\n"
    "- G2: Light the display\n#### Done when\nThe lamp lights.\n\n"
    "## Notes\n- G3: Unrelated outline\n",
    "design": "### Decision: Use a wooden stand\n\n"
    "This note is outside the entry grammar.\n\n"
    "### Clear coat, decided, 2026-01-01\n"
    "### Decided: Evaluate a brass stand\n"
    "### An owner ruling on adhesives\n### Reconsidered glue\n",
    "built": "| Item | State | Notes |\n| --- | --- | --- |\n"
    "| Frame | shipped | Detail omitted |\n| Lamp | partial | |\n| Plaque | new | |\n",
    "tracker": "| Item | Status | Other |\n| --- | --- | --- |\n"
    "| Cut the hull | 🔧 **FIXED** (work note) | Extra text |\n"
    "| Paint the deck | unusual seabird; hidden tail | |\n"
    "| Test buoyancy | driving | |\n\n"
    "| State | Item |\n| --- | --- |\n| open | Buy sandpaper |\n",
    "diagrams": "## Build order\n```mermaid\nflowchart LR\n"
    '  A["https://example.test/private?key=sample"] --> B\n```\n'
    "```\n[A] -> [B]\n```\n",
}
VARIANT = {
    "goals": "## Goals\n### P4. Align the telescope\n**Done when**: The stars are sharp.\n",
    "design": "### Choose a mount, decided,\n### Consider a tripod\n",
    "built": "- [x] Base plate\n* [ ] Lens cover\n",
    "tracker": "| Item | State |\n| --- | --- |\n| Focus | delivered — Change note |\n",
    "diagrams": "Figure: Optics\n```mermaid\nsequenceDiagram\n  Eye->>Lens: Look\n```\n",
}


class PlanRepoTestCase(unittest.TestCase):
    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory(dir="/tmp" if sys.platform == "darwin" else None)
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.repo = self.root / "repo"
        self.home = self.root / "state"
        self.briefs = self.root / "briefs"
        self.hull = self.root / "work" / "hull"
        self.log = self.root / "events.log"
        for folder in (self.repo, self.home, self.briefs, self.hull):
            folder.mkdir(parents=True)
        git(self.repo, "init", "-q", "-b", "main")
        self.log.write_bytes(b"")

    def write_sources(
        self, data: dict[str, str], *commit_args: str, when: str = BEFORE_THE_SESSION
    ) -> None:
        (self.repo / "plan").mkdir(exist_ok=True)
        for name, text in data.items():
            (self.repo / "plan" / f"{name}.md").write_text(text, encoding="utf-8")
        git(self.repo, "add", "plan")
        git(self.repo, "commit", "-qm", "Synthetic snapshot", *commit_args, when=when)

    def configure(self, fixture: str = "stand-in", **overrides: Any) -> settings.Settings:
        doc = json.loads((FIXTURES / f"{fixture}.json").read_text(encoding="utf-8"))
        doc["repos"][0]["path"] = str(self.repo)
        doc["briefs"]["folder"] = str(self.briefs)
        doc["briefs"]["lane_folders"] = {"hull": str(self.hull)}
        doc["private"]["roots"] = []
        doc["log"]["path"] = str(self.log)
        if fixture == "variant":
            # The system's real temp ancestry can contain a directory named "private".
            doc["private"]["markers"][0]["value"] = "sealed"
        for name, patch in overrides.items():
            doc[name].update(patch)
        (self.home / settings.FILENAME).write_text(json.dumps(doc), encoding="utf-8")
        loaded = settings.load(str(self.home))
        self.assertIsNone(loaded.reason)
        assert loaded.settings is not None
        return loaded.settings

    def only_goals(self, path: str = "plan/goals.md", **overrides: Any) -> settings.Settings:
        self.configure(**overrides)
        file = self.home / settings.FILENAME
        doc = json.loads(file.read_bytes())
        doc["repos"][0]["files"] = {"goals": [path]}
        file.write_text(json.dumps(doc), encoding="utf-8")
        loaded = settings.load(str(self.home))
        assert loaded.settings is not None
        return loaded.settings


@unittest.skipIf(GIT is None or os.name == "nt", "Needs Git and POSIX directory descriptors")
class PlanReadersTest(PlanRepoTestCase):
    def assert_private_without_tree_read(self, config: settings.Settings) -> None:
        with mock.patch.object(git_status.PlanTreeReader, "_run", autospec=True) as run:
            self.assertEqual(readers.read_plan(config).model.sources[0].reason, "private")
        run.assert_not_called()

    def test_private_child_is_refused_before_git_tree_access(self) -> None:
        self.write_sources({"goals": "## Goals\n- G1: Synthetic private goal\n"})
        alias = self.root / "alias"
        alias.symlink_to(self.repo / "plan", target_is_directory=True)
        config = self.only_goals(private={"roots": [str(alias)]})
        self.assertEqual(config.sources.declarations()[0].reason, "private")
        self.assert_private_without_tree_read(config)
        (self.repo / "plan").rename(self.root / "detached")
        self.assert_private_without_tree_read(config)

    def test_marker_file_in_tree_file_parent_is_refused(self) -> None:
        self.write_sources({"goals": "## Goals\n- G1: Synthetic private goal\n"})
        config = self.only_goals()
        self.assertIsNone(config.sources.declarations()[0].reason)
        (self.repo / "plan" / ".restricted").touch()
        self.assert_private_without_tree_read(config)
        self.assertEqual(self.only_goals().sources.declarations()[0].reason, "private")

    def test_disk_marker_matches_folded_filename(self) -> None:
        self.write_sources({"goals": "## Goals\n- G1: Synthetic private goal\n"})
        config = self.only_goals(private={"marker_files": [".réstricted"]})
        # A case-sensitive filesystem has no exact path for the declared spelling.
        (self.repo / "plan" / ".RE\u0301STRICTED").touch()
        present = io._present_at
        with mock.patch.object(
            io,
            "_present_at",
            side_effect=lambda fd, name: name != ".réstricted" and present(fd, name),
        ):
            self.assert_private_without_tree_read(config)

    def test_repo_name_marker_refuses_tree_path_without_checkout_parent(self) -> None:
        config = self.only_goals("restricted/deep/goals.md")
        self.assertEqual(config.sources.declarations()[0].reason, "private")
        self.assert_private_without_tree_read(config)

    def test_repo_becoming_private_is_refused_at_read(self) -> None:
        self.write_sources({"goals": "## Goals\n- G1: Synthetic private goal\n"})
        config = self.only_goals()
        marker = self.repo / ".restricted"
        marker.touch()
        self.assert_private_without_tree_read(config)
        marker.unlink()
        find_tip = git_status.PlanTreeReader.tip

        def mark_after_tip(tree: git_status.PlanTreeReader, ref: str) -> str:
            tip = find_tip(tree, ref)
            marker.touch()
            return tip

        with (
            mock.patch.object(git_status.PlanTreeReader, "tip", mark_after_tip),
            mock.patch.object(git_status.PlanTreeReader, "check_markers", create=True) as metadata,
            mock.patch.object(git_status.PlanTreeReader, "tree_file", return_value=b"") as blob,
        ):
            self.assertEqual(readers.read_plan(config).model.sources[0].reason, "private")
        metadata.assert_not_called()
        blob.assert_not_called()

    def test_missing_parent_refuses_when_checkout_privacy_cannot_be_checked(self) -> None:
        self.write_sources({"goals": "## Goals\n- G1: Synthetic checkout goal\n"})
        (self.repo / "plan").rename(self.root / "detached")
        config = self.only_goals()
        self.assertEqual(config.sources.declarations()[0].reason, "missing")
        with mock.patch.object(git_status.PlanTreeReader, "_run") as run:
            self.assertEqual(readers.read_plan(config).model.sources[0].reason, "missing")
        run.assert_not_called()

    def test_root_marker_added_after_load_refuses_top_level_file(self) -> None:
        (self.repo / "goals.md").write_text("## Goals\n- G1: Synthetic private goal\n")
        git(self.repo, "add", "goals.md")
        git(self.repo, "commit", "-qm", "Add a top-level goal")
        config = self.only_goals("goals.md")
        tip = git_status.PlanTreeReader.tip

        def mark_after_tip(tree: git_status.PlanTreeReader, ref: str) -> str:
            commit = tip(tree, ref)
            (self.repo / ".restricted").touch()
            return commit

        with (
            mock.patch.object(git_status.PlanTreeReader, "tip", mark_after_tip),
            mock.patch.object(git_status.PlanTreeReader, "tree_file", autospec=True) as file,
        ):
            result = readers.read_plan(config).model
        self.assertEqual(result.sources[0].reason, "private")
        self.assertEqual(result.goals, ())
        file.assert_not_called()

    def test_vanished_private_root_keeps_its_reason(self) -> None:
        self.write_sources({"goals": "## Goals\n- G1: Synthetic private goal\n"})
        private = self.repo / "plan"
        config = self.only_goals(private={"roots": [str(private)]})
        private.rename(self.root / "detached")
        # Exercise the live check independently of the refusal saved at settings load.
        (repo,) = config.sources.repositories
        current = replace(config.sources, repositories=(replace(repo, parent_refusals=()),))
        checked = current.tree_source(repo.label, repo.ref, "plan/goals.md")
        self.assertEqual(checked.reason, "private")

    def test_repo_replaced_after_load_is_changed(self) -> None:
        self.write_sources({"goals": "## Goals\n- G1: Admitted goal\n"})
        config = self.only_goals()
        self.repo.rename(self.root / "original")
        self.repo.mkdir()
        git(self.repo, "init", "-q", "-b", "main")
        self.write_sources({"goals": "## Goals\n- G1: Replacement goal\n"})
        with mock.patch.object(git_status, "plan_reader", wraps=git_status.plan_reader) as factory:
            result = readers.read_plan(config).model
        self.assertEqual(result.sources[0].reason, io.PlanRefusal.CHANGED)
        self.assertEqual(result.goals, ())
        factory.assert_not_called()

    def test_refused_draft_paths_keep_their_reasons(self) -> None:
        self.write_sources({"anchor": "Keep the parent in the checkout"})
        git(self.repo, "branch", "draft/plan")
        config = self.only_goals()
        tree_file = git_status.PlanTreeReader.tree_file

        def mark_after_primary(
            tree: git_status.PlanTreeReader, tip: str, path: str, *, max_bytes: int
        ) -> bytes:
            try:
                return tree_file(tree, tip, path, max_bytes=max_bytes)
            finally:
                (self.repo / "plan" / ".restricted").touch()

        with mock.patch.object(git_status.PlanTreeReader, "tree_file", mark_after_primary):
            result = readers.read_plan(config).model
        self.assertEqual(
            [(source.display_kind, source.reason) for source in result.sources[:2]],
            [("goals", "not in branch"), ("draft goals", "private")],
        )

    def test_target_ref_marker_refuses_before_blob(self) -> None:
        calls: list[tuple[str, ...]] = []
        run = git_status.PlanTreeReader._run

        def record(tree: git_status.PlanTreeReader, args: tuple[str, ...], at: float) -> bytes:
            calls.append(args)
            return run(tree, args, at)

        for marker in (".restricted", "plan/.restricted"):
            with self.subTest(marker=marker):
                self.write_sources({"goals": f"## Goals\n- G1: Private at {marker}\n"})
                git(self.repo, "switch", "-qc", "marked")
                (self.repo / marker).touch()
                git(self.repo, "add", marker)
                git(self.repo, "commit", "-qm", "Mark the branch private")
                git(self.repo, "switch", "main")
                git(self.repo, "branch", "-f", "target", "marked")
                git(self.repo, "branch", "-D", "marked")
                config = self.only_goals()
                file = self.home / settings.FILENAME
                doc = json.loads(file.read_bytes())
                doc["repos"][0]["ref"] = "target"
                doc["repos"][0].pop("draft_ref")
                file.write_text(json.dumps(doc))
                loaded = settings.load(str(self.home))
                assert loaded.settings is not None
                self.assertIsNone(config.sources.declarations()[0].reason)
                calls.clear()
                with mock.patch.object(git_status.PlanTreeReader, "_run", record):
                    result = readers.read_plan(loaded.settings).model
                self.assertEqual(result.sources[0].reason, "private")
                self.assertEqual(result.goals, ())
                self.assertFalse(
                    any(call[0] == "cat-file" or "plan/goals.md" in call for call in calls)
                )

    def test_repo_cwd_identity_is_held_through_git_dispatch(self) -> None:
        self.write_sources({"goals": "## Goals\n- G1: Admitted repo\n"})
        substitute = self.root / "other"
        substitute.mkdir()
        config = self.only_goals(private={"roots": [str(substitute)]})
        original = git_status.plan_reader
        runner = mock.Mock(wraps=subprocess.run)

        def factory(*args: Any, **kwargs: Any) -> git_status.PlanTreeReader:
            self.repo.rename(self.root / "original")
            substitute.rename(self.repo)
            return original(*args, **kwargs, runner=runner)

        with mock.patch.object(git_status, "plan_reader", side_effect=factory):
            result = readers.read_plan(config).model
        self.assertEqual(runner.call_count, 0)
        self.assertEqual(result.sources[0].reason, io.PlanRefusal.CHANGED)
        self.assertEqual(result.goals, ())

    def test_swap_during_git_run_discards_output(self) -> None:
        self.write_sources({"goals": "## Goals\n- G1: Admitted repo\n"})
        config = self.only_goals()
        substitute = self.root / "other"
        substitute.mkdir()
        canary = "Swapped bytes"
        original = git_status.plan_reader
        calls: list[tuple[str, ...]] = []

        def runner(
            argv: tuple[str, ...], *, check: bool, **kwargs: Any
        ) -> subprocess.CompletedProcess[bytes]:
            if argv[-3:-1] == ("cat-file", "blob"):
                calls.append(argv)
                self.repo.rename(self.root / "original")
                substitute.rename(self.repo)
                return subprocess.CompletedProcess(
                    argv, 0, f"## Goals\n- G1: {canary}\n".encode(), b""
                )
            return subprocess.run(argv, check=check, **kwargs)

        def factory(cwd: str, *, timeout_sec: float) -> git_status.PlanTreeReader:
            return original(cwd, timeout_sec=timeout_sec, runner=runner)

        with mock.patch.object(git_status, "plan_reader", side_effect=factory):
            result = readers.read_plan(config).model
        self.assertEqual(len(calls), 1)
        self.assertNotIn(canary, json.dumps(asdict(result)))
        self.assertEqual(result.sources[0].reason, io.PlanRefusal.CHANGED)
        self.assertEqual(result.goals, ())

    def test_frozen_build_reads_git_sources(self) -> None:
        self.write_sources({"goals": "## Goals\n- G1: Admitted repo\n"})
        config = self.only_goals()
        with mock.patch.object(sys, "frozen", True, create=True):
            result = readers.read_plan(config).model
        self.assertIsNone(result.sources[0].reason)
        self.assertEqual([row.title for row in result.goals], ["Admitted repo"])

    def test_unknown_goal_reference_is_a_measured_mismatch(self) -> None:
        self.write_sources({"goals": "## Goals\n- G1: Sample goal\n"})
        (self.briefs / "hull.md").write_text("## Goal\nSample lane\n\n*Serves*: G9\n")
        result = readers.read_plan(self.only_goals())
        self.assertEqual(result.diagnostics.goal_lane_mismatches, 1)
        self.assertEqual(result.model.lanes[0].serves, ())

    def test_stand_in_reads_each_declared_source(self) -> None:
        self.write_sources(STAND_IN)
        (self.briefs / "hull.md").write_text(
            "**Goal:** Shape the hull.\nIt needs to float.\n\n"
            "## Done\nThe hull floats.\n\n*Serves*: G1 G2\n",
            encoding="utf-8",
        )
        (self.briefs / "paint.md").write_text("## Goal\nPaint it.\n", encoding="utf-8")
        (self.briefs / "unlisted.txt").write_text("Skip this file", encoding="utf-8")
        self.log.write_bytes(b"ask hull:1 Can it float?\nask hull:2 Pick a color\nanswer hull:2\n")
        result = readers.read_plan(self.configure())
        model = result.model
        self.assertEqual(
            [(g.id, g.done, g.lanes) for g in model.goals],
            [
                ("G1", "The model floats.", ("hull",)),
                ("G2", "The lamp lights.", ("hull",)),
            ],
        )
        self.assertEqual([g.origin.line for g in model.goals], [2, 5])
        self.assertEqual(len({g.origin.commit for g in model.goals}), 1)
        self.assertEqual([d.decided for d in model.decisions], [True, True, False, True, False])
        self.assertEqual([i.status for i in model.inventory], ["built", "partial", "not_built"])
        self.assertEqual(
            [i.status for i in model.tracker],
            [
                "done",
                "Status not recognised",
                "running",
                "not_started",
            ],
        )
        self.assertNotIn("unusual seabird", repr(model))
        self.assertNotIn("hidden tail", repr(result))
        self.assertNotIn("work note", repr(model))
        self.assertNotIn("outside the entry grammar", repr(model))
        self.assertEqual(
            [word.word for word in result.diagnostics.unknown_statuses], ["unusual seabird"]
        )
        self.assertEqual(result.diagnostics.goal_lane_mismatches, 2)
        self.assertEqual([d.caption for d in model.diagrams], ["Build order", "Build order"])
        self.assertNotIn("https://example.test", repr(model))
        self.assertIn("https://example.test", model.diagrams[0].unredacted_body)
        self.assertEqual([lane.slug for lane in model.lanes], ["hull", "paint"])
        hull, paint = model.lanes
        self.assertEqual(
            (hull.goal, hull.done, hull.serves),
            ("Shape the hull. It needs to float.", "The hull floats.", ("G1", "G2")),
        )
        self.assertEqual(paint.serves, ())
        self.assertIsNone(paint.folder)
        assert hull.folder is not None
        stat = self.hull.stat()
        self.assertEqual(
            (hull.folder.path, hull.folder.device, hull.folder.inode),
            (str(self.hull), stat.st_dev, stat.st_ino),
        )
        self.assertEqual(
            [(ask.id, ask.text, ask.lane, ask.source, ask.timestamp) for ask in model.asks],
            [("hull:1", "Can it float?", "hull", "Coordination", None)],
        )
        self.assertEqual(model.log_rejected, 0)
        self.assertTrue(all(s.reason is None for s in model.sources if not s.draft))

    def test_variant_uses_declared_grammars(self) -> None:
        self.write_sources(VARIANT)
        (self.briefs / "hull.brief.md").write_text(
            "**Objective:** Set the lens.\nKeep it aligned.\n"
            "_Exit_: The image is sharp.\nGoals: P4\n",
            encoding="utf-8",
        )
        self.log.write_bytes(
            b"2026-01-02T03:04:05.123456789Z ASK hull a1 Is the lens set?\n"
            b"2026-01-02T03:04:06+00:00 ASK hull a2 Check alignment\n"
            b"2026-01-02T03:04:07Z DONE hull a2\n"
        )
        model = readers.read_plan(self.configure("variant")).model
        self.assertEqual(
            [(g.id, g.done, g.lanes) for g in model.goals],
            [("P4", "The stars are sharp.", ("hull",))],
        )
        self.assertEqual([row.status for row in model.inventory], ["built", "not_built"])
        self.assertEqual([row.status for row in model.tracker], ["done"])
        self.assertEqual([row.decided for row in model.decisions], [True, False])
        self.assertEqual(
            [(row.kind, row.caption) for row in model.diagrams], [("sequenceDiagram", "Optics")]
        )
        self.assertEqual(model.lanes[0].goal, "Set the lens. Keep it aligned.")
        self.assertEqual(
            [(a.id, a.timestamp, a.lane) for a in model.asks],
            [("a1", "2026-01-02T03:04:05.123456789Z", "hull")],
        )
        self.assertEqual(model.log_rejected, 0)

    def test_canary_physical_log_lines_are_counted_and_discarded(self) -> None:
        self.log.write_bytes(
            b"free text canary\n"
            b'{"kind":"json canary","id":"b"}\n'
            b"ask hull:over " + b"o" * 201 + b"\n"
            b"unknown hull:word unknown verb canary\n"
            b"ask hull:cr CR canary\rask hull:split Split canary\n"
            b"ask hull:ctrl Control canary\x1b[0m\n"
            b"ask hull:valid This ask is permitted\n"
        )
        model = readers.read_plan(self.configure()).model
        self.assertEqual(model.log_rejected, 6)
        self.assertEqual([ask.id for ask in model.asks], ["hull:valid"])
        self.assertNotIn("canary", str(asdict(model)).lower())
        self.assertNotIn("o" * 201, str(asdict(model)))

    def test_log_rejects_invalid_utf8_and_invalid_ask_answer_order(self) -> None:
        self.log.write_bytes(
            b"answer one\nask one question\nask one duplicate\n"
            b"answer one\nanswer one\nask one reopened\n"
            b"answer unknown\nask hull:two \xff\n"
            b"note locally audited note\n"
            b"ask hull:three question three"
        )
        model = readers.read_plan(self.configure()).model
        self.assertEqual(model.log_rejected, 6)
        self.assertEqual([ask.id for ask in model.asks], ["hull:three"])

    def test_only_local_branch_tip_content_survives_dirty_tree_and_history(self) -> None:
        self.write_sources({**STAND_IN, "gone": "## Goals\n- G9: Older blob"})
        git(self.repo, "rm", "plan/gone.md")
        self.write_sources(STAND_IN)
        (self.repo / "plan" / "goals.md").write_text("## Goals\n- G8: Dirty text", encoding="utf-8")
        (self.repo / "plan" / "gone.md").write_text("## Goals\n- G9: Untracked", encoding="utf-8")
        git(self.repo, "switch", "-qc", "unrelated")
        git(self.repo, "add", "plan/goals.md")
        git(self.repo, "commit", "-qm", "Unrelated branch")
        files = {"goals": ["plan/goals.md", "plan/gone.md"]}
        model = readers.read_plan(self.configure()).model
        self.assertEqual([g.id for g in model.goals], ["G1", "G2"])
        doc = json.loads((self.home / settings.FILENAME).read_text(encoding="utf-8"))
        doc["repos"][0]["files"] = files
        (self.home / settings.FILENAME).write_text(json.dumps(doc), encoding="utf-8")
        loaded = settings.load(str(self.home))
        assert loaded.settings is not None
        model = readers.read_plan(loaded.settings).model
        self.assertEqual([g.id for g in model.goals], ["G1", "G2"])
        self.assertEqual(
            [s.reason for s in model.sources if s.kind == "goals" and not s.draft],
            [None, "not in branch"],
        )
        self.assertNotIn("Older blob", repr(model))
        self.assertNotIn("Unrelated branch", repr(model))

    def test_refused_source_does_not_inherit_a_previous_read(self) -> None:
        self.write_sources(STAND_IN)
        (self.briefs / "hull.md").write_text("## Goal\nA valid brief.\n", encoding="utf-8")
        self.log.write_bytes(b"ask hull:1 Read me\n")
        config = self.configure(log={"max_bytes": 512})
        self.assertEqual(len(readers.read_plan(config).model.asks), 1)
        self.log.write_bytes(b"x" * 513)
        (self.briefs / "hull.md").write_text(
            "## Goal\nDuplicate\n## Goal\nAgain\n", encoding="utf-8"
        )
        self.write_sources(
            {
                "tracker": "| Item | Status |\n| --- | --- |\n| Column missing |\n",
                "diagrams": '```mermaid\nflowchart LR\nclick A href "https://example.test"\n```\n',
                "built": "x" * (256 * 1024 + 1),
            }
        )
        model = readers.read_plan(config).model
        self.assertEqual(
            (model.tracker, model.inventory, model.diagrams, model.lanes, model.asks),
            ((), (), (), (), ()),
        )
        self.assertIsNone(model.log_rejected)
        self.assertEqual(
            {s.kind: s.reason for s in model.sources if not s.draft},
            {
                "goals": None,
                "decisions": None,
                "inventory": "over the byte cap",
                "diagrams": "malformed",
                "tracker": "malformed",
                "lane briefs": None,
                "lane brief": "malformed",
                "event log": "over the byte cap",
            },
        )

    def test_no_git_keeps_the_local_plan_and_starts_no_subprocess(self) -> None:
        self.write_sources(STAND_IN)
        self.log.write_bytes(b"ask hull:1 Is the stand ready?\n")
        self.configure()
        loaded = settings.load(str(self.home), git_enabled=False)
        assert loaded.settings is not None
        with mock.patch.object(git_status, "plan_reader") as factory:
            model = readers.read_plan(loaded.settings).model
        factory.assert_not_called()
        self.assertEqual(len(model.asks), 1)
        self.assertEqual(model.goals, ())
        self.assertEqual([s.reason for s in model.sources[:5]], ["git reads are off"] * 5)

    def test_a_tag_remote_or_symbolic_alias_cannot_supply_the_configured_branch(self) -> None:
        self.write_sources(STAND_IN)
        git(self.repo, "branch", "-m", "committed")
        git(self.repo, "tag", "refs/heads/main")
        git(self.repo, "update-ref", "refs/remotes/origin/main", "HEAD")
        config = self.configure()
        for symbolic in (False, True):
            if symbolic:
                git(self.repo, "symbolic-ref", "refs/heads/main", "refs/remotes/origin/main")
            with self.subTest(symbolic=symbolic):
                model = readers.read_plan(config).model
                self.assertEqual(model.goals, ())
                self.assertEqual([s.reason for s in model.sources[:5]], ["branch missing"] * 5)

    def test_diagram_directives_discard_the_source_before_any_diagram_survives(self) -> None:
        for directive in (
            "%%{init: {}}%%",
            "click A B",
            "href value",
            "CALLBACK",
            "<script>",
            "javascript:value",
        ):
            with self.subTest(directive=directive):
                self.write_sources(
                    {
                        "diagrams": "```mermaid\nflowchart LR\nA --> B\n```\n"
                        "```mermaid\nsequenceDiagram\n" + directive + "\n```\n"
                    }
                )
                model = readers.read_plan(self.configure()).model
                self.assertEqual(model.diagrams, ())
                self.assertEqual(
                    next(s.reason for s in model.sources if s.kind == "diagrams"), "malformed"
                )

    def test_json_inventory_uses_declared_field_names(self) -> None:
        self.write_sources(
            {
                "built": json.dumps(
                    [
                        {"label": "Small mirror", "phase": "PARTIAL", "note": "Unselected field"},
                        {"label": "Large mirror", "phase": "shipped"},
                    ]
                )
            }
        )
        result = readers.read_plan(
            self.configure(
                inventory={"form": "json", "title_column": "label", "state_locator": "phase"}
            )
        )
        self.assertEqual(
            [(row.title, row.status) for row in result.model.inventory],
            [("Small mirror", "partial"), ("Large mirror", "built")],
        )
        self.assertNotIn("Unselected field", repr(result))

    def test_unknown_status_even_if_identical_to_header_affects_only_its_row(self) -> None:
        self.write_sources(
            {
                "tracker": "| Item | Status |\n| --- | --- |\n"
                "| Item | Status |\n| Second row | fixed |\n",
            }
        )
        result = readers.read_plan(self.configure())
        self.assertEqual(
            [(row.title, row.status) for row in result.model.tracker],
            [("Item", "Status not recognised"), ("Second row", "done")],
        )

    def test_overlong_goal_in_a_declared_list_withdraws_the_file(self) -> None:
        self.write_sources(
            {
                "goals": "## Goals\n- G1: Valid goal\n- G2: " + "x" * 201 + "\n",
            }
        )
        model = readers.read_plan(self.configure()).model
        self.assertEqual(model.goals, ())
        self.assertEqual(model.sources[0].reason, "over the byte cap")

    def test_lane_folders_are_declared_and_admitted_as_metadata(self) -> None:
        config = self.configure(briefs={"lane_folders": {"hull": str(self.hull)}})
        (self.briefs / "hull.md").write_text("## Goal\nShape it.\n", encoding="utf-8")
        (self.hull / ".restricted").touch()
        model = readers.read_plan(config).model
        self.assertEqual(len(model.lanes), 1)
        self.assertIsNone(model.lanes[0].folder)
        self.assertEqual(model.lanes[0].folder_reason, io.PlanRefusal.PRIVATE)
        doc = json.loads((self.home / settings.FILENAME).read_text(encoding="utf-8"))
        for folders in ({"hull": "relative"}, {"Not a slug": str(self.hull)}):
            with self.subTest(folders=folders):
                doc["briefs"]["lane_folders"] = folders
                (self.home / settings.FILENAME).write_text(json.dumps(doc), encoding="utf-8")
                self.assertEqual(settings.load(str(self.home)).reason, settings.MALFORMED)

    def test_git_tree_modes_are_checked_before_opening_a_blob(self) -> None:
        self.write_sources(STAND_IN)
        (self.repo / "plan" / "link").symlink_to("design.md")
        git(self.repo, "add", "plan/link")
        tip = subprocess.check_output(
            [GIT or "git", "rev-parse", "HEAD"], cwd=self.repo, text=True
        ).strip()
        git(self.repo, "update-index", "--add", "--cacheinfo", f"160000,{tip},plan/module")
        git(self.repo, "commit", "-qm", "Non-file entries")
        runner = mock.Mock(wraps=subprocess.run)
        reader = git_status.plan_reader(str(self.repo), timeout_sec=5, runner=runner)
        tip = reader.tip("main")
        assert tip is not None
        for name in ("link", "module", "absent"):
            with self.subTest(name=name), self.assertRaises(git_status.PlanGitError) as error:
                reader.tree_file(tip, f"plan/{name}", max_bytes=1024)
            expected = "not in branch" if name == "absent" else "not a regular file in branch"
            self.assertEqual(error.exception.reason, expected)
        with self.assertRaises(git_status.PlanGitError):
            reader.tree_file(tip, "../outside", max_bytes=1024)
        self.assertFalse(any("cat-file" in call.args[0] for call in runner.call_args_list))
        entry = f"100644 blob {tip} 2\tplan/other.md\0".encode()
        mismatched = mock.Mock(return_value=subprocess.CompletedProcess([], 0, entry))
        reader = git_status.plan_reader(str(self.repo), timeout_sec=5, runner=mismatched)
        with self.assertRaises(git_status.PlanGitError) as error:
            reader.tree_file(tip, "plan/design.md", max_bytes=10)
        self.assertEqual(error.exception.reason, "unreadable")
        self.assertEqual([call.args[0][6] for call in mismatched.call_args_list], ["ls-tree"])
        self.assertEqual(
            self.configure().sources.tree_source("Example", "main", "plan/gone").reason,
            sources.NOT_NAMED,
        )


LANE_TRACKER = (
    "| Item | Lane | Status |\n| --- | --- | --- |\n"
    "| Cut the hull | `Hull` | fixed |\n"
    "| Paint the deck | paint | unusual seabird |\n"
    "| Rig the mast | mast | open |\n"
    "| Rig the mast again | mast | driving |\n"
    "| Unassigned work | | open |\n"
    "| Not a lane id | Not a lane | open |\n\n"
    "| State | Item | Lane |\n| --- | --- | --- |\n| open | Buy sandpaper | |\n"
)


@unittest.skipIf(GIT is None or os.name == "nt", "Needs Git and POSIX directory descriptors")
class PlanLaneStateTest(PlanRepoTestCase):
    def setUp(self) -> None:
        super().setUp()
        for slug in ("hull", "paint", "mast", "keel"):
            (self.briefs / f"{slug}.md").write_text("## Goal\nSample lane\n", encoding="utf-8")

    def configure(self, fixture: str = "stand-in", **overrides: Any) -> settings.Settings:
        overrides.setdefault("tracker", {"lane_column": "Lane"})
        return super().configure(fixture, **overrides)

    def states(self, config: settings.Settings) -> dict[str, str | None]:
        return {lane.slug: lane.state for lane in readers.read_plan(config).model.lanes}

    def test_one_tracker_row_sets_the_lane_state_and_others_are_not_measured(self) -> None:
        self.write_sources({"tracker": LANE_TRACKER})
        result = readers.read_plan(self.configure())
        self.assertEqual(
            {lane.slug: lane.state for lane in result.model.lanes},
            # One row each for hull and paint; two rows name mast; no row names keel.
            {"hull": "done", "paint": "Status not recognised", "mast": None, "keel": None},
        )
        self.assertEqual(
            [row.lane for row in result.model.tracker],
            ["hull", "paint", "mast", "mast", None, None, None],
        )
        self.assertNotIn("unusual seabird", repr(result.model))
        self.assertEqual(
            [word.word for word in result.diagnostics.unknown_statuses], ["unusual seabird"]
        )

    def test_no_declared_lane_column_measures_no_lane(self) -> None:
        self.write_sources({"tracker": LANE_TRACKER})
        config = super().configure()
        self.assertIsNone(config.tracker.lane_column)
        model = readers.read_plan(config).model
        self.assertEqual(len(model.tracker), 7)
        self.assertEqual(set(self.states(config).values()), {None})
        self.assertEqual({row.lane for row in model.tracker}, {None})

    def test_a_table_without_the_declared_lane_column_withdraws_the_tracker(self) -> None:
        # A header typo must show as a refused source, not as every lane quietly unmeasured.
        for text in (
            STAND_IN["tracker"],
            LANE_TRACKER.replace("| State | Item | Lane |", "| State | Item | Lame |"),
        ):
            with self.subTest(text=text):
                self.write_sources({"tracker": text})
                model = readers.read_plan(self.configure()).model
                self.assertEqual(model.tracker, ())
                self.assertEqual(
                    [s.reason for s in model.sources if s.kind == "tracker"], ["malformed"]
                )
                self.assertEqual({lane.state for lane in model.lanes}, {None})

    def test_a_repeated_lane_column_withdraws_the_tracker(self) -> None:
        self.write_sources(
            {
                "tracker": "| Item | Lane | Status | Lane |\n| --- | --- | --- | --- |\n"
                "| Cut the hull | hull | fixed | hull |\n"
            }
        )
        model = readers.read_plan(self.configure()).model
        self.assertEqual(model.tracker, ())
        self.assertEqual([s.reason for s in model.sources if s.kind == "tracker"], ["malformed"])
        self.assertEqual({lane.state for lane in model.lanes}, {None})

    def test_an_unread_tracker_source_leaves_every_lane_unmeasured(self) -> None:
        self.write_sources({"tracker": LANE_TRACKER})
        file = self.home / settings.FILENAME
        self.configure()
        doc = json.loads(file.read_bytes())
        # The second file cannot be read, so it could hold a second row for hull.
        doc["repos"][0]["files"] = {"tracker": ["plan/tracker.md", "plan/absent.md"]}
        file.write_text(json.dumps(doc), encoding="utf-8")
        loaded = settings.load(str(self.home))
        assert loaded.settings is not None
        self.assertEqual(set(self.states(loaded.settings).values()), {None})

    def test_rows_across_tracker_files_are_counted_together(self) -> None:
        self.write_sources(
            {
                "tracker": LANE_TRACKER,
                "more": "| Item | Lane | Status |\n| --- | --- | --- |\n"
                "| Lay the keel | keel | driving |\n| Recut the hull | hull | open |\n",
            }
        )
        file = self.home / settings.FILENAME
        self.configure()
        doc = json.loads(file.read_bytes())
        doc["repos"][0]["files"] = {"tracker": ["plan/tracker.md", "plan/more.md"]}
        file.write_text(json.dumps(doc), encoding="utf-8")
        loaded = settings.load(str(self.home))
        assert loaded.settings is not None
        self.assertEqual(
            self.states(loaded.settings),
            {"hull": None, "paint": "Status not recognised", "mast": None, "keel": "running"},
        )

    def test_a_lane_cell_that_is_not_one_lane_id_makes_named_lanes_ambiguous(self) -> None:
        head = "| Item | Lane | Status |\n| --- | --- | --- |\n| Cut the hull | hull | fixed |\n"
        for rows, expected in (
            ("| Paint both | hull, paint | open |\n", {"hull": None, "paint": None}),
            ("| Sand the hull | hull. | open |\n", {"hull": None, "paint": None}),
            ("| Sand the hull | **Hull**; | open |\n", {"hull": None, "paint": None}),
            ("| Stray work | Not a lane | open |\n", {"hull": "done", "paint": None}),
            ("| Stray work | hull-paint | open |\n", {"hull": "done", "paint": None}),
        ):
            with self.subTest(rows=rows):
                self.write_sources({"tracker": head + rows})
                states = self.states(self.configure())
                self.assertEqual({lane: states[lane] for lane in expected}, expected)

    def test_a_lane_cell_naming_several_lanes_never_sets_a_state_alone(self) -> None:
        self.write_sources(
            {
                "tracker": "| Item | Lane | Status |\n| --- | --- | --- |\n"
                "| Paint both | hull, paint | fixed |\n"
            }
        )
        self.assertEqual(
            self.states(self.configure()),
            {"hull": None, "paint": None, "mast": None, "keel": None},
        )

    def test_credential_shaped_lane_cells_never_become_lane_ids(self) -> None:
        # Synthetic shapes, built here so no credential-shaped literal sits in the source.
        cells = (
            "AKIA" + "IOSFODNN7EXAMPLE",
            "`" + "AIza" + "Q" * 35 + "`",
            "xoxb-" + "1" * 20,
            "XOXB-" + "1" * 20,
        )
        rows = "".join(f"| Row {n} | {cell} | fixed |\n" for n, cell in enumerate(cells))
        self.write_sources({"tracker": "| Item | Lane | Status |\n| --- | --- | --- |\n" + rows})
        for cell in cells:
            (self.briefs / f"{cell.strip('`').lower()}.md").write_text(
                "## Goal\nSample lane\n", encoding="utf-8"
            )
        result = readers.read_plan(self.configure())
        self.assertEqual([row.lane for row in result.model.tracker], [None] * 4)
        mentioned = {lane for row in result.model.tracker for lane in row.mentions}
        for cell in cells:
            with self.subTest(cell=cell):
                self.assertNotIn(cell.strip("`").lower(), mentioned)
                self.assertNotIn(cell.strip("`").lower(), repr(result.model.tracker))
        self.assertEqual({lane.state for lane in result.model.lanes}, {None})

    def test_exact_case_lane_cells_must_match_the_slug(self) -> None:
        for cell, expected in (("Hull", None), ("hull", "done")):
            with self.subTest(cell=cell):
                self.write_sources(
                    {
                        "tracker": "| Item | Lane | Status |\n| --- | --- | --- |\n"
                        f"| Cut the hull | {cell} | fixed |\n"
                    }
                )
                config = self.configure(tracker={"lane_column": "Lane", "case": "exact"})
                self.assertEqual(self.states(config)["hull"], expected)

    def test_two_rows_with_the_same_status_still_leave_the_lane_unmeasured(self) -> None:
        self.write_sources(
            {
                "tracker": "| Item | Lane | Status |\n| --- | --- | --- |\n"
                "| Rig the mast | mast | fixed |\n| Rig it again | mast | fixed |\n"
            }
        )
        self.assertIsNone(self.states(self.configure())["mast"])

    def test_an_overlong_lane_cell_names_no_lane_and_still_counts_against_it(self) -> None:
        cell = "`" + " " * 510 + "hull`"
        self.write_sources(
            {
                "tracker": "| Item | Lane | Status |\n| --- | --- | --- |\n"
                f"| Cut the hull | {cell} | fixed |\n"
            }
        )
        result = readers.read_plan(self.configure())
        self.assertIsNone(result.model.tracker[0].lane)
        self.assertIsNone({lane.slug: lane.state for lane in result.model.lanes}["hull"])

    def test_a_draft_only_row_does_not_set_a_lane_state(self) -> None:
        self.write_sources({"tracker": LANE_TRACKER})
        git(self.repo, "switch", "-qc", "draft/plan")
        self.write_sources(
            {"tracker": LANE_TRACKER.replace("| Unassigned work | |", "| Lay the keel | keel |")}
        )
        git(self.repo, "switch", "main")
        model = readers.read_plan(self.configure()).model
        self.assertIn("keel", [row.lane for row in model.tracker if row.origin.source.draft])
        self.assertIsNone({lane.slug: lane.state for lane in model.lanes}["keel"])
