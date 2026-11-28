"""Plan declarations and the no-content-open boundary."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unicodedata
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from compass_runtime import io
from compass_runtime.plan import grammar, settings

from .test_project_script_checks import GIT

FIXTURES = Path(__file__).parent / "fixtures" / "plan"


@unittest.skipIf(os.name == "nt", "Plan reads require POSIX directory descriptors")
class PlanSettingsTest(unittest.TestCase):
    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory(dir="/tmp" if sys.platform == "darwin" else None)
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.home = self.root / "state"
        self.lanes = self.root / "lanes"
        self.repo = self.root / "repo"
        self.private = self.root / "hide-this"
        for folder in (self.home, self.lanes, self.repo, self.private):
            folder.mkdir()
        (self.repo / "plan").mkdir()
        self.log = self.root / "events.log"
        self.log.write_bytes(b"ask lane:one Check on this")
        self.path = self.home / "compass-plan.json"

    def fixture(self, name: str = "stand-in") -> dict[str, Any]:
        fixture: dict[str, Any] = json.loads(
            (FIXTURES / f"{name}.json").read_text(encoding="utf-8")
        )
        fixture["repos"][0]["path"] = str(self.repo)
        fixture["briefs"]["folder"] = str(self.lanes)
        fixture["private"]["roots"] = [str(self.private)]
        fixture["log"]["path"] = str(self.log)
        return fixture

    def load(self, doc: dict[str, Any], *, git_enabled: bool = True) -> settings.Loaded:
        self.path.write_text(json.dumps(doc), encoding="utf-8")
        return settings.load(str(self.home), git_enabled=git_enabled)

    def loaded(self, doc: dict[str, Any], *, git_enabled: bool = True) -> settings.Settings:
        result = self.load(doc, git_enabled=git_enabled)
        self.assertIsNone(result.reason)
        assert result.settings is not None
        return result.settings

    def test_absent_file_and_disabled_flag(self) -> None:
        self.assertEqual(settings.load(str(self.home)).reason, "no settings file")
        with mock.patch.object(io, "read_plan_settings") as read:
            disabled = settings.load(str(self.home), enabled=False)
        read.assert_not_called()
        self.assertEqual(disabled.reason, "plan is off")
        self.assertIsNone(disabled.settings)

    def test_settings_refuse_bad_json_and_bounds_as_a_whole(self) -> None:
        valid = json.dumps(self.fixture()).encode()
        self.path.write_bytes(valid)
        self.assertIsNotNone(settings.load(str(self.home)).settings)
        version = b'"version": 1'
        self.assertIn(version, valid)
        for raw, reason in (
            (valid.replace(version, b'"version": 2, "version": 1'), "malformed settings"),
            (valid.replace(version, b'"version": 2'), "malformed settings"),
            (b" " * 65537, "over the byte cap"),
            (b"\xff", "malformed settings"),
        ):
            with self.subTest(reason=reason, preview=raw[:20]):
                self.path.write_bytes(raw)
                loaded = settings.load(str(self.home))
                self.assertEqual(loaded.reason, reason)
                self.assertIsNone(loaded.settings)

        # Even with strict schema types, the JSON parser itself must refuse NaN.
        self.path.write_bytes(valid.replace(version, b'"version": NaN'))
        with mock.patch.object(settings, "keys", wraps=grammar.keys) as validate:
            self.assertEqual(settings.load(str(self.home)).reason, "malformed settings")
        validate.assert_not_called()

    @unittest.skipIf(GIT is None, "Needs Git")
    def test_bare_repo_and_special_briefs_stop_before_open(self) -> None:
        bare = self.root / "bare"
        subprocess.run([GIT or "git", "init", "--bare", "-q", str(bare)], check=True)
        inside = bare / settings.FILENAME
        inside.write_text(json.dumps(self.fixture()))
        with mock.patch.object(io, "open_plan_source") as opened:
            self.assertEqual(settings.load(str(bare)).reason, "settings are inside a repository")
        opened.assert_not_called()

        os.mkfifo(self.lanes / "fifo.md")
        (self.lanes / "folder.md").mkdir()
        sources = self.loaded(self.fixture()).sources
        self.assertEqual(sources.brief_names().names, ("fifo.md", "folder.md"))
        with mock.patch.object(io, "open_plan_source") as opened:
            for name in sources.brief_names().names:
                self.assertEqual(sources.read_brief(name).reason, "not an owned regular file")
        opened.assert_not_called()

    def test_schema_refuses_unknown_or_inconsistent_grammar_before_metadata(self) -> None:
        for section, key, value in (
            ("tracker", "words", {"open": "made_up"}),
            ("briefs", "filename", [{"name": "x", "kind": "regex", "max_chars": 64}]),
            ("briefs", "filename", [{"name": "lane", "kind": "text", "max_chars": 64}]),
            ("log", "templates", [["answer ", {"name": "id", "kind": "id", "max_chars": 900}]]),
            (
                "log",
                "templates",
                [["answer ", {"name": "id", "kind": "id", "max_chars": 64}, " trailing"]],
            ),
            ("log", "answer_key", "unknown"),
            ("log", "lane", {"source": "field"}),
            ("log", "max_bytes", 10**8),
            ("private", "markers", [{"value": "", "mode": "substring"}]),
            ("private", "marker_files", ["../marker"]),
            ("goals", "unknown", True),
        ):
            with self.subTest(section=section, key=key, value=value):
                doc = self.fixture()
                doc[section][key] = value
                with mock.patch.object(io, "plan_private_identities") as identities:
                    loaded = self.load(doc)
                identities.assert_not_called()
                self.assertEqual(loaded.reason, "malformed settings")
                self.assertIsNone(loaded.settings)

    def test_variants_and_bounded_full_line_matching(self) -> None:
        base = self.loaded(self.fixture())
        self.assertFalse(base.summary_enabled)
        self.assertEqual(
            base.log.match("2026-11-27T00:00:00.123456789Z ask lane:one Check on this"),
            {
                "ts": "2026-11-27T00:00:00.123456789Z",
                "verb": "ask",
                "id": "lane:one",
                "text": "Check on this",
            },
        )
        self.assertEqual(base.log.match("answer lane:one"), {"verb": "answer", "id": "lane:one"})
        self.assertEqual(base.briefs.filename.match("one-lane.md"), {"lane": "one-lane"})
        for line in (
            "unknown lane:one",
            "ask lane:one",
            "answer lane:one more",
            "ask lane:one bad\rline",
            "ask lane:one bad\u202eline",
            "ask lane:one " + "x" * 201,
            "2026-11-27T00:00:00.1234567890Z ask lane:one Question",
        ):
            with self.subTest(line=line):
                self.assertIsNone(base.log.match(line))
        variant = self.loaded(self.fixture("variant"))
        self.assertTrue(variant.summary_enabled)
        self.assertIsNone(variant.briefs.filename.match("one-lane.md"))
        self.assertEqual(variant.briefs.filename.match("one-lane.brief.md"), {"lane": "one-lane"})
        self.assertEqual(
            variant.log.match("2026-11-27T00:00:00.123456+00:00 DONE blue one"),
            {"ts": "2026-11-27T00:00:00.123456+00:00", "verb": "DONE", "lane": "blue", "id": "one"},
        )
        self.assertIsNone(variant.log.match("2026-11-27T00:00:00Z DONE blue one extra"))
        self.assertIsNone(variant.log.match("2026-11-27T00:00:00Z ASK blue one"))
        self.assertEqual(
            variant.goals.templates[0].match("P42. A goal"), {"n": "42", "title": "A goal"}
        )
        self.assertEqual(variant.inventory.form, "checklist")

    def test_stand_in_accepts_both_table_headers_and_numbered_goal_ids(self) -> None:
        doc = self.fixture()
        doc["tracker"]["status_column"] = ["Status", "State"]
        doc["goals"]["templates"][0][1]["kind"] = "numbered_goal_id"
        plan = self.loaded(doc)
        self.assertEqual(plan.tracker.status_columns, ("Status", "State"))
        self.assertEqual(
            plan.goals.templates[0].match("- P42a: A goal"), {"id": "P42a", "title": "A goal"}
        )

    def test_tracker_lane_column_is_optional_and_distinct(self) -> None:
        self.assertIsNone(self.loaded(self.fixture()).tracker.lane_column)
        self.assertIsNone(self.loaded(self.fixture("variant")).tracker.lane_column)
        declared = self.fixture()
        declared["tracker"]["lane_column"] = "Lane"
        self.assertEqual(self.loaded(declared).tracker.lane_column, "Lane")
        for value in (
            "",
            " ",
            "Item",
            "item",
            "STATE",
            ["Lane"],
            7,
            None,
            "L" * 129,
            "La\nne",
            " Lane ",
            "Lane ",
            " Item ",
            " Status ",
        ):
            with self.subTest(value=value):
                doc = self.fixture()
                doc["tracker"]["lane_column"] = value
                loaded = self.load(doc)
                self.assertEqual(loaded.reason, "malformed settings")
                self.assertIsNone(loaded.settings)

    def test_tracker_column_names_cannot_carry_padding(self) -> None:
        # Table cells are stripped before matching, so a padded name could never match one.
        for key, value in (
            ("title_column", " Item "),
            ("title_column", " "),
            ("status_column", " Status"),
            ("status_column", ["Status", "State "]),
        ):
            with self.subTest(key=key, value=value):
                doc = self.fixture()
                doc["tracker"][key] = value
                self.assertEqual(self.load(doc).reason, "malformed settings")

    def test_private_identity_refuses_at_load_and_before_source_open(self) -> None:
        folder = self.private / "nested"
        folder.mkdir()
        log = folder / "log"
        log.touch()
        alias = self.root / "alias"
        alias.symlink_to(self.private, target_is_directory=True)
        doc = self.fixture()
        doc["private"]["roots"] = [str(alias)]
        doc["log"]["path"] = str(log)
        plan = self.loaded(doc)
        self.assertEqual(plan.sources.events.reason, "private")
        with mock.patch.object(io, "open_plan_source") as opened:
            self.assertEqual(plan.sources.read_log().reason, "private")
        opened.assert_not_called()
        doc["log"]["path"] = str(alias / "nested" / "log")
        self.assertEqual(self.loaded(doc).sources.events.reason, "symbolic link")

    def test_case_normalisation_and_platform_alias_preserve_private_identity(self) -> None:
        private = self.root / "Café"
        private.mkdir()
        log = private / "event.log"
        log.touch()
        for alias in (
            self.root / "CAFÉ",
            self.root / unicodedata.normalize("NFD", private.name),
            Path(str(private).removeprefix("/private")),
        ):
            with self.subTest(alias=alias):
                if alias == private:
                    continue
                doc = self.fixture()
                doc["private"]["roots"] = [str(private)]
                doc["log"]["path"] = str(alias / log.name)
                expected = "private" if alias.exists() else "missing"
                self.assertEqual(self.loaded(doc).sources.events.reason, expected)

    def test_private_guard_is_rechecked_when_a_parent_is_replaced(self) -> None:
        plan = self.loaded(self.fixture())
        self.lanes.rmdir()
        self.private.rename(self.lanes)
        (self.lanes / "one.md").touch()
        with mock.patch.object(io, "open_plan_source") as opened:
            self.assertEqual(plan.sources.read_brief("one.md").reason, "private")
        opened.assert_not_called()

    def test_markers_on_brief_ancestors_are_checked_before_open(self) -> None:
        for mark, mode, folder_name in (
            ("café", "component", "CAFÉ"),
            ("café", "component", "Cafe\u0301"),
            ("sealed", "token", "lane_SEALED.old"),
            ("sealed", "substring", "lanesealed"),
        ):
            with self.subTest(mark=mark, mode=mode, folder_name=folder_name):
                folder = self.lanes / folder_name
                folder.mkdir(exist_ok=True)
                (folder / "one.md").touch()
                doc = self.fixture()
                doc["private"]["markers"] = [{"value": mark, "mode": mode}]
                doc["briefs"]["folder"] = str(folder)
                plan = self.loaded(doc)
                self.assertEqual(plan.sources.brief_folder.reason, "private")
                with mock.patch.object(io, "open_plan_source") as opened:
                    self.assertEqual(plan.sources.read_brief("one.md").reason, "private")
                opened.assert_not_called()

    def test_marker_filename_at_read_does_not_open_marker_or_brief(self) -> None:
        plan = self.loaded(self.fixture())
        (self.root / ".restricted").touch()
        (self.lanes / "one.md").touch()
        with mock.patch.object(io, "open_plan_source") as opened:
            self.assertEqual(plan.sources.read_brief("one.md").reason, "private")
        opened.assert_not_called()

    @unittest.expectedFailure
    def test_homoglyph_marker_is_not_a_privacy_match(self) -> None:
        folder = self.lanes / "h\u0456dden"  # Cyrillic letter i
        folder.mkdir()
        doc = self.fixture()
        doc["private"]["markers"] = [{"value": "hidden", "mode": "component"}]
        doc["briefs"]["folder"] = str(folder)
        self.assertEqual(self.loaded(doc).sources.brief_folder.reason, "private")

    def test_briefs_only_open_direct_matching_regular_files(self) -> None:
        (self.lanes / "one.md").write_bytes(b"Goal: Fixture")
        (self.lanes / "sibling.txt").touch()
        (self.lanes / "nested").mkdir()
        (self.lanes / "nested" / "two.md").touch()
        (self.lanes / "link.md").symlink_to(self.log)
        os.link(self.log, self.lanes / "hard.md")
        plan = self.loaded(self.fixture())
        with mock.patch.object(io, "open_plan_source") as opened:
            for name, reason in (
                ("sibling.txt", "not named in settings"),
                ("../events.log", "outside declared root"),
                (str(self.log), "outside declared root"),
                ("nested/two.md", "outside declared root"),
                ("link.md", "symbolic link"),
                ("hard.md", "hard link"),
            ):
                with self.subTest(name=name):
                    self.assertEqual(plan.sources.read_brief(name).reason, reason)
        opened.assert_not_called()
        self.assertEqual(plan.sources.read_brief("one.md").data, b"Goal: Fixture")
        listing = plan.sources.brief_names()
        self.assertIsNone(listing.reason)
        self.assertEqual(listing.names, ("hard.md", "link.md", "one.md"))

    def test_leaf_is_rechecked_by_the_open_primitive(self) -> None:
        plan = self.loaded(self.fixture())
        self.log.unlink()
        self.log.symlink_to(self.path)
        original_open = os.open
        with mock.patch("compass_runtime.io.os.open", wraps=original_open) as opened:
            self.assertEqual(plan.sources.read_log().reason, "symbolic link")
        self.assertFalse(any(call.args[0] == self.log.name for call in opened.call_args_list))

    def test_open_refuses_a_leaf_swapped_after_metadata(self) -> None:
        plan = self.loaded(self.fixture())
        replacement = self.root / "replacement"
        replacement.write_bytes(b"Different file")
        original_open = os.open

        def move_then_open(name: str, *args: Any, **kwargs: Any) -> int:
            if name == self.log.name:
                replacement.replace(self.log)
            return original_open(name, *args, **kwargs)

        with mock.patch("compass_runtime.io.os.open", side_effect=move_then_open):
            read = plan.sources.read_log()
        self.assertIsNone(read.data)
        self.assertEqual(read.reason, "file changed before it could be read")

    def rewrite_during_read(self, path: Path, old: bytes, new: bytes) -> Any:
        """Return part of the file, then rewrite it in place to the same size."""
        self.assertEqual(len(old), len(new))
        original_read = os.read
        rewritten: list[bool] = []

        def read(fd: int, size: int) -> bytes:
            if rewritten:
                return original_read(fd, size)
            rewritten.append(True)
            chunk = original_read(fd, min(size, 16))
            data = path.read_bytes()
            self.assertIn(old, data[16:])
            with path.open("r+b") as stream:
                stream.write(data.replace(old, new))
            info = path.stat()
            os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns + 1_000_000_000))
            self.assertEqual(path.stat().st_size, len(data))
            return chunk

        self.addCleanup(lambda: self.assertTrue(rewritten, "the read was not intercepted"))
        return mock.patch("compass_runtime.io.os.read", side_effect=read)

    def test_settings_refuse_a_same_size_rewrite_during_the_read(self) -> None:
        self.path.write_text(json.dumps(self.fixture()), encoding="utf-8")
        with self.rewrite_during_read(self.path, b'"ref": "main"', b'"ref": "next"'):
            loaded = settings.load(str(self.home))
        self.assertEqual(loaded.reason, "file changed before it could be read")
        self.assertIsNone(loaded.settings)
        # The finished rewrite is read whole on the next load.
        repo = self.loaded(json.loads(self.path.read_text(encoding="utf-8"))).sources
        self.assertEqual(repo.repositories[0].ref, "next")

    def test_log_refuses_a_same_size_rewrite_during_the_read(self) -> None:
        plan = self.loaded(self.fixture())
        with self.rewrite_during_read(self.log, b"on this", b"on that"):
            read = plan.sources.read_log()
        self.assertIsNone(read.data)
        self.assertEqual(read.reason, "file changed before it could be read")
        self.assertEqual(plan.sources.read_log().data, b"ask lane:one Check on that")

    def test_log_refuses_a_rewrite_that_restores_its_modification_time(self) -> None:
        plan = self.loaded(self.fixture())
        before = self.log.stat()
        original_read = os.read
        rewritten: list[bool] = []

        def read(fd: int, size: int) -> bytes:
            if rewritten:
                return original_read(fd, size)
            rewritten.append(True)
            chunk = original_read(fd, min(size, 16))
            with self.log.open("r+b") as stream:
                stream.write(self.log.read_bytes().replace(b"on this", b"on that"))
            # Only the change time still shows the write.
            os.utime(self.log, ns=(before.st_atime_ns, before.st_mtime_ns))
            self.assertEqual(self.log.stat().st_mtime_ns, before.st_mtime_ns)
            return chunk

        with mock.patch("compass_runtime.io.os.read", side_effect=read):
            read_back = plan.sources.read_log()
        self.assertTrue(rewritten)
        self.assertIsNone(read_back.data)
        self.assertEqual(read_back.reason, "file changed before it could be read")

    def test_brief_listing_refuses_an_overfull_folder_without_opening_briefs(self) -> None:
        doc = self.fixture()
        doc["briefs"]["max_files"] = 1
        (self.lanes / "one.md").touch()
        (self.lanes / "two.md").touch()
        plan = self.loaded(doc)
        with mock.patch.object(io, "open_plan_source") as opened:
            listing = plan.sources.brief_names()
        self.assertEqual(listing.names, ())
        self.assertEqual(listing.reason, "over the brief folder entry cap")
        opened.assert_not_called()

    def test_repo_file_must_match_repo_ref_and_exact_tree_path(self) -> None:
        plan = self.loaded(self.fixture())
        sources = plan.sources
        self.assertIsNone(sources.tree_source("Example", "main", "plan/goals.md").reason)
        self.assertIsNone(sources.tree_source("Example", "draft/plan", "plan/goals.md").reason)
        self.assertEqual(
            sources.tree_source("Example", "main", "../goals.md").reason, "outside declared root"
        )
        self.assertEqual(
            sources.tree_source("Example", "main", "plan/other.md").reason, "not named in settings"
        )
        self.assertEqual(
            sources.tree_source("Example", "other", "plan/goals.md").reason, "not named in settings"
        )
        self.assertEqual(
            sources.tree_source("Other", "main", "plan/goals.md").reason, "not named in settings"
        )
        disabled = self.loaded(self.fixture(), git_enabled=False)
        self.assertEqual(
            disabled.sources.tree_source("Example", "main", "plan/goals.md").reason,
            "git reads are off",
        )

    def test_a_named_tree_file_can_supply_two_declared_formats(self) -> None:
        doc = self.fixture()
        doc["repos"][0]["files"]["diagrams"].append("plan/design.md")
        allowed = self.loaded(doc).sources
        for kind in ("decisions", "diagrams"):
            with self.subTest(kind=kind):
                source = allowed.tree_source("Example", "main", "plan/design.md", kind=kind)
                self.assertIsNone(source.reason)
                self.assertEqual(source.kind, kind)
        self.assertEqual(
            allowed.tree_source("Example", "main", "plan/design.md", kind="goals").reason,
            "not named in settings",
        )

    def test_a_repository_file_may_carry_a_short_label_that_is_never_a_path(self) -> None:
        doc = self.fixture()
        doc["repos"][0]["files"]["inventory"] = [
            "plan/built.md",
            {"path": "plan/parts.md", "label": "Spare parts"},
        ]
        repo = self.loaded(doc).sources.repositories[0]
        self.assertIn(("inventory", "plan/built.md"), repo.files)
        self.assertIn(("inventory", "plan/parts.md"), repo.files)
        self.assertEqual(dict(repo.file_labels), {("inventory", "plan/parts.md"): "Spare parts"})
        for entry in (
            {"path": "plan/parts.md", "label": "plan/parts.md"},
            {"path": "plan/parts.md", "label": "plan\\parts"},
            {"path": "plan/parts.md", "label": "  "},
            {"path": "plan/parts.md", "label": ""},
            {"path": "plan/parts.md", "label": "x" * 41},
            {"path": "plan/parts.md", "label": "Two\nlines"},
            {"path": "plan/parts.md", "label": 3},
            {"label": "Spare parts"},
            {"path": "plan/parts.md", "label": "Spare parts", "note": "unexpected"},
            {"path": "../parts.md", "label": "Spare parts"},
        ):
            with self.subTest(entry=entry):
                refused = self.fixture()
                refused["repos"][0]["files"]["inventory"] = ["plan/built.md", entry]
                self.assertEqual(self.load(refused).reason, "malformed settings")
        # Two files in one repository cannot share a label, so a label always tells them apart.
        for first, second in (("Parts", "PARTS"), ("Parts", "Pa\u200brts"), ("Parts", " Parts  ")):
            with self.subTest(first=first, second=second):
                twice = self.fixture()
                twice["repos"][0]["files"]["inventory"] = [
                    {"path": "plan/built.md", "label": first},
                    {"path": "plan/parts.md", "label": second},
                ]
                self.assertEqual(self.load(twice).reason, "malformed settings")

    def test_a_file_entry_may_leave_its_label_out(self) -> None:
        doc = self.fixture()
        doc["repos"][0]["files"]["inventory"] = ["plan/built.md", {"path": "plan/parts.md"}]
        repo = self.loaded(doc).sources.repositories[0]
        self.assertEqual(
            [path for kind, path in repo.files if kind == "inventory"],
            ["plan/built.md", "plan/parts.md"],
        )
        self.assertEqual(repo.file_labels, ())

    def test_a_label_cannot_hide_characters_or_stand_in_for_a_path_or_a_generated_name(
        self,
    ) -> None:
        refused = (
            # Invisible and unusual spacing characters.
            "\u200b",
            "a\u200bb",
            "Spare\u00adparts",
            "Spare\u00a0parts",
            "Spare\u3000parts",
            "Spare\u2028parts",
            "Spare\u2029parts",
            # Slashes that only look like one.
            *(f"plan{slash}parts" for slash in "\u2215\uff0f\u29f8\u2044\uff3c\u2216\u29f5"),
            # A declared file's name or path, in any case.
            "parts.md",
            "PARTS.MD",
            "built.md",
            "goals.md",
            # A name the page generates for a file without a label.
            "inventory",
            "Inventory 2",
            "tracker 12",
            "draft",
            "Draft goals",
            "draft inventory 3",
            " inventory  2 ",
        )
        for label in refused:
            with self.subTest(label=label):
                doc = self.fixture()
                doc["repos"][0]["files"]["inventory"] = [
                    "plan/built.md",
                    {"path": "plan/parts.md", "label": label},
                ]
                self.assertEqual(self.load(doc).reason, "malformed settings")
        for label in ("Spare parts", "Inventory of parts", "parts", "Parts 2", "Drafts"):
            with self.subTest(accepted=label):
                doc = self.fixture()
                doc["repos"][0]["files"]["inventory"] = [
                    "plan/built.md",
                    {"path": "plan/parts.md", "label": label},
                ]
                self.assertIsNone(self.load(doc).reason)

    def test_settings_links_and_checkouts_are_refused(self) -> None:
        self.path.symlink_to(self.log)
        self.assertEqual(settings.load(str(self.home)).reason, "symbolic link")
        self.path.unlink()
        os.link(self.log, self.path)
        self.assertEqual(settings.load(str(self.home)).reason, "hard link")
        self.path.unlink()
        self.path.write_text(json.dumps(self.fixture()), encoding="utf-8")
        (self.root / ".git").mkdir()
        with mock.patch.object(io, "open_plan_source") as opened:
            self.assertEqual(
                settings.load(str(self.home)).reason, "settings are inside a repository"
            )
        opened.assert_not_called()

    def test_compass_home_under_a_declared_repo_refuses_the_settings(self) -> None:
        doc = self.fixture()
        doc["repos"][0]["path"] = str(self.root)
        self.assertEqual(self.load(doc).reason, "settings are inside a repository")

    def test_unresolved_private_root_refuses_the_whole_settings_file(self) -> None:
        doc = self.fixture()
        doc["private"]["roots"] = [str(self.root / "missing")]
        loaded = self.load(doc)
        self.assertEqual(loaded.reason, "could not identify a private root")
        self.assertIsNone(loaded.settings)

    @unittest.skipIf(os.geteuid() == 0, "root reads a directory whatever its mode")
    def test_execute_only_private_root_loads_and_refuses_beneath_it(self) -> None:
        for private in (self.private, self.repo / "sealed"):
            with self.subTest(private=private.name):
                (private / "nested").mkdir(parents=True)
                log = private / "nested" / "events.log"
                log.write_bytes(b"ask lane:one CANARY_EXECUTE_ONLY")
                (private / "goals.md").write_text("## Goals\n- G1: CANARY_EXECUTE_ONLY\n")
                doc = self.fixture()
                doc["private"]["roots"] = [str(private)]
                doc["log"]["path"] = str(log)
                doc["briefs"]["folder"] = str(private / "nested")
                doc["repos"][0]["files"] = {"goals": ["sealed/goals.md"]}
                private.chmod(0o111)
                self.addCleanup(private.chmod, 0o700)
                plan = self.loaded(doc).sources
                self.assertEqual(plan.events.reason, "private")
                self.assertEqual(plan.brief_folder.reason, "private")
                with mock.patch.object(io, "open_plan_source") as opened:
                    self.assertEqual(plan.read_log().reason, "private")
                    self.assertEqual(plan.brief_names().reason, "private")
                opened.assert_not_called()
                if private.parent == self.repo:
                    self.assertEqual(
                        plan.tree_source("Example", "main", "sealed/goals.md").reason, "private"
                    )
                # A private root that cannot even be entered still loads; beneath it is refused.
                private.chmod(0)
                self.assertIn(self.loaded(doc).sources.read_log().reason, {"private", "unreadable"})
                private.chmod(0o700)

    @unittest.skipIf(os.geteuid() == 0, "root reads a directory whatever its mode")
    def test_a_private_root_held_open_but_not_searchable_still_loads(self) -> None:
        # Linux opens a mode 000 folder with O_PATH, but any lookup inside it is refused.
        (self.private / "nested").mkdir()
        log = self.private / "nested" / "events.log"
        log.write_bytes(b"ask lane:one CANARY_NOT_SEARCHABLE")
        doc = self.fixture()
        doc["log"]["path"] = str(log)
        held = os.open(self.private, os.O_RDONLY)
        self.addCleanup(os.close, held)
        self.private.chmod(0)
        self.addCleanup(self.private.chmod, 0o700)
        lookup = io._lookup_fd

        def opened_anyway(path: str) -> int | None:
            return os.dup(held) if path == str(self.private) else lookup(path)

        with mock.patch.object(io, "_lookup_fd", side_effect=opened_anyway):
            plan = self.loaded(doc)
        self.assertIn(plan.sources.read_log().reason, {"private", "unreadable"})

    @unittest.skipUnless(sys.platform == "darwin", "the macOS lookup-only flag")
    def test_lookup_only_flag_does_not_depend_on_the_python_build(self) -> None:
        # Python built against an SDK before O_SEARCH was declared does not export it.
        with mock.patch.dict(os.__dict__):
            for name in ("O_SEARCH", "O_EXEC", "O_PATH"):
                os.__dict__.pop(name, None)
            self.assertEqual(io._search_only_flag(), 0x40000000 | os.O_DIRECTORY)

    def test_an_unreadable_repository_does_not_refuse_other_sources(self) -> None:
        doc = self.fixture()
        locked = self.root / "locked"
        locked.mkdir()
        (locked / "repo").mkdir()
        doc["repos"][0]["path"] = str(locked / "repo")
        locked.chmod(0)
        try:
            plan = self.loaded(doc)
            self.assertEqual(
                plan.sources.tree_source("Example", "main", "plan/goals.md").reason, "unreadable"
            )
            self.assertEqual(plan.sources.read_log().data, b"ask lane:one Check on this")
        finally:
            locked.chmod(0o700)

    @unittest.skipUnless(sys.platform == "darwin", "macOS standard ancestor alias")
    def test_platform_alias_cannot_hide_private_parent_above_tmp(self) -> None:
        self.assertTrue(self.root.is_relative_to("/private/tmp"))
        doc = self.fixture()
        doc["private"]["roots"] = ["/private"]
        doc["log"]["path"] = str(self.log).removeprefix("/private")
        self.assertEqual(self.loaded(doc).sources.events.reason, "private")


class LineRuleTest(unittest.TestCase):
    def test_the_line_rule_matches_the_category_rule_for_every_code_point(self) -> None:
        refused = {"Cc", "Cs", "Zl", "Zp"}
        bidi = set("\u061c\u200e\u200f\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069")
        wrong = [
            point
            for point in range(0x110000)
            if grammar.is_line(char := chr(point))
            != (unicodedata.category(char) not in refused and char not in bidi and char != "\ufeff")
        ]
        self.assertEqual(wrong, [])
        self.assertTrue(grammar.is_line("plain words ⚓ 船"))
        self.assertFalse(grammar.is_line("two\nlines"))
