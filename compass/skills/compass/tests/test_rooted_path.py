"""`rooted_path`: the one rule for which program a PATH lookup may start.

Every command Compass starts by name (git, gh, glab, spacedock, tmux, the model CLIs) is
resolved against PATH elements no working directory can reinterpret, and the answer is held to
the same rule, because the working directory of a lookup is often a repository Compass does not
trust.
"""

from __future__ import annotations

import contextlib
import inspect
import ntpath
import os
import shutil
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from typing import TYPE_CHECKING
from unittest import mock

from compass_runtime import git_status, observer, reading, rooted_path, summary_jobs

from .support import make_config

if TYPE_CHECKING:
    from collections.abc import Iterator


@contextlib.contextmanager
def windows(path: str, pathext: str = ".com;.exe;.bat;.cmd") -> Iterator[Path]:
    """Windows path rules over real files, in a fresh current folder.

    `ntpath.join("C:\\Tools", "uv.exe")` is the single name `C:\\Tools\\uv.exe`, which a POSIX
    filesystem holds as one file in the current folder, so a real stat answers for it. PATHEXT
    is lower case so the names agree on a case-sensitive filesystem too.
    """
    with tempfile.TemporaryDirectory() as tmp:
        previous = os.getcwd()
        os.chdir(tmp)
        try:
            with (
                mock.patch.object(os, "name", "nt"),
                mock.patch.object(os, "path", ntpath),
                mock.patch.object(os, "pathsep", ";"),
                mock.patch.dict(os.environ, {"PATH": path, "PATHEXT": pathext}),
            ):
                yield Path(tmp)
        finally:
            os.chdir(previous)


def plant(name: str) -> None:
    """One executable file named exactly `name` in the current folder."""
    with open(name, "w", encoding="utf-8") as handle:
        handle.write("")
    os.chmod(name, 0o700)


def _program(path: Path) -> None:
    path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


# These build Windows names such as `C:\\Tools\\uv.exe` as single files in a scratch folder, which only
# works on a POSIX filesystem: on Windows they would write into the real folder of that name.
SIMULATED = "simulates Windows on a POSIX filesystem"


class RootedRuleTest(unittest.TestCase):
    def test_relative_empty_and_current_directory_elements_are_never_rooted(self) -> None:
        for element in ("", ".", "..", "bin", "./bin", "sub/bin"):
            with self.subTest(element=element):
                self.assertFalse(rooted_path.rooted(element))
        self.assertTrue(rooted_path.rooted(os.path.abspath(os.sep + "bin")))

    def test_a_driveless_windows_root_is_not_rooted(self) -> None:
        with mock.patch.object(os, "name", "nt"), mock.patch.object(os, "path", ntpath):
            driveless = rooted_path.rooted("\\bin")
            drive_relative = rooted_path.rooted("C:bin")
            qualified = rooted_path.rooted("C:\\bin")
        self.assertFalse(driveless)
        self.assertFalse(drive_relative)
        self.assertTrue(qualified, "a fully qualified Windows path was refused")

    def test_the_search_path_keeps_only_rooted_elements_in_order(self) -> None:
        first = os.path.abspath(os.sep + "first")
        second = os.path.abspath(os.sep + "second")
        joined = os.pathsep.join([".", first, "", "relbin", second, os.curdir])
        self.assertEqual(os.pathsep.join([first, second]), rooted_path.search_path(joined))
        self.assertEqual("", rooted_path.search_path(os.pathsep.join([".", "relbin", ""])))

    def test_git_status_and_observer_share_the_one_rule(self) -> None:
        # Three copies of this predicate existed; a fix to one could not reach the others.
        for candidate in ("", ".", "relbin", os.path.abspath(os.sep + "bin")):
            with self.subTest(candidate=candidate):
                expected = rooted_path.rooted(candidate)
                self.assertEqual(expected, git_status._rooted(candidate))
                self.assertEqual(expected, observer.rooted(candidate))


class ChildEnvironmentTest(unittest.TestCase):
    def test_the_child_gets_the_scrubbed_path_and_the_windows_current_directory_switch(
        self,
    ) -> None:
        absolute = os.path.abspath(os.sep + "bin")
        child = rooted_path.child_environment(
            {"PATH": os.pathsep.join([".", absolute, "relbin"]), "HOME": "/home/someone"}
        )
        self.assertEqual(absolute, child["PATH"])
        self.assertEqual("1", child["NoDefaultCurrentDirectoryInExePath"])
        self.assertEqual("/home/someone", child["HOME"], "everything else passes through")

    def test_the_caller_environment_is_not_mutated(self) -> None:
        environ = {"PATH": "."}
        rooted_path.child_environment(environ)
        self.assertEqual({"PATH": "."}, environ)


class ExecutableTest(unittest.TestCase):
    def test_a_program_reachable_only_through_a_relative_element_is_not_found(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "relbin").mkdir()
            _program(root / "relbin" / "tmux")
            previous = os.getcwd()
            os.chdir(root)
            try:
                # Armed: the ordinary lookup does find it.
                self.assertIsNotNone(shutil.which("tmux", path="relbin"))
                for path in ("relbin", f".{os.sep}relbin", os.pathsep.join(["", "relbin"])):
                    with self.subTest(path=path):
                        self.assertIsNone(rooted_path.executable("tmux", {"PATH": path}))
            finally:
                os.chdir(previous)

    def test_a_program_in_a_rooted_element_is_found(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            _program(root / "tmux")
            path = os.pathsep.join([".", str(root)])
            self.assertEqual(str(root / "tmux"), rooted_path.executable("tmux", {"PATH": path}))

    def test_a_current_directory_answer_is_refused(self) -> None:
        # Windows `shutil.which` puts the current directory first before 3.12, whatever PATH
        # it is handed, and answers `.\tmux.exe` when it matches there.
        with mock.patch.object(shutil, "which", return_value=os.path.join(".", "tmux")):
            self.assertIsNone(rooted_path.executable("tmux", {"PATH": os.sep}))

    def test_which_reads_the_live_environment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            _program(root / "spacedock")
            with mock.patch.dict(os.environ, {"PATH": os.pathsep.join(["relbin", str(root)])}):
                self.assertEqual(str(root / "spacedock"), rooted_path.which("spacedock"))
            with mock.patch.dict(os.environ, {"PATH": "relbin"}):
                self.assertIsNone(rooted_path.which("spacedock"))


@unittest.skipIf(sys.platform == "win32", SIMULATED)
class WindowsWalkTest(unittest.TestCase):
    """On Windows `shutil.which` looks in the current folder first, so it is not asked at all.

    Before 3.12 always, and from 3.12 unless this process's own environment turns it off. A
    planted `.\\uv.exe` then hid the real `uv`: refused as unrooted, but the real one later on
    PATH was never tried.
    """

    def test_a_planted_program_in_the_current_folder_is_skipped_for_the_real_one(self) -> None:
        for name in ("uv", "spacedock", "claude"):
            with self.subTest(name=name), windows("C:\\Tools;D:\\Other"):
                plant(f".\\{name}.exe")
                plant(f"{name}.exe")
                plant(f"C:\\Tools\\{name}.exe")
                self.assertEqual(f"C:\\Tools\\{name}.exe", rooted_path.which(name))

    def test_pathext_decides_the_extensions_in_their_order(self) -> None:
        with windows("C:\\Tools", pathext=".bat;.exe"):
            plant("C:\\Tools\\uv.exe")
            plant("C:\\Tools\\uv.bat")
            self.assertEqual("C:\\Tools\\uv.bat", rooted_path.which("uv"))
        with windows("C:\\Tools", pathext=".exe"):
            plant("C:\\Tools\\uv.cmd")
            self.assertIsNone(rooted_path.which("uv"), "an extension PATHEXT does not name ran")
        with windows("C:\\Tools"):
            plant("C:\\Tools\\uv.exe")
            self.assertEqual("C:\\Tools\\uv.exe", rooted_path.which("uv.exe"))

    def test_entries_are_tried_in_order_and_unrooted_ones_never(self) -> None:
        with windows("\\tools;C:bin;.;;C:\\First;C:\\Second"):
            for folder in ("\\tools", "C:bin", "C:\\Second"):
                plant(f"{folder}\\uv.exe")
            self.assertEqual("C:\\Second\\uv.exe", rooted_path.which("uv"))
            plant("C:\\First\\uv.exe")
            self.assertEqual("C:\\First\\uv.exe", rooted_path.which("uv"))

    def test_a_file_that_cannot_execute_or_a_folder_is_not_a_program(self) -> None:
        with windows("C:\\Tools"):
            os.mkdir("C:\\Tools\\uv.exe")
            self.assertIsNone(rooted_path.which("uv"))
        with windows("C:\\Tools"):
            Path("C:\\Tools\\uv.exe").write_text("", encoding="utf-8")
            os.chmod("C:\\Tools\\uv.exe", 0o644)
            self.assertIsNone(rooted_path.which("uv"))

    def test_a_name_with_a_folder_in_it_is_not_looked_up(self) -> None:
        with windows("C:\\Tools"):
            plant("C:\\Tools\\bin\\uv.exe")
            self.assertIsNone(rooted_path.which("bin\\uv"))


@unittest.skipIf(sys.platform == "win32", SIMULATED)
class PosixUnchangedTest(unittest.TestCase):
    def test_posix_answers_as_shutil_which_does_on_the_rooted_entries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            shims = root / ".pyenv" / "shims"
            brew = root / "opt" / "homebrew" / "bin"
            for folder in (shims, brew):
                folder.mkdir(parents=True)
                _program(folder / "uv")
            _program(brew / "claude")
            path = os.pathsep.join([str(shims), str(brew)])
            with mock.patch.dict(os.environ, {"PATH": path}):
                self.assertEqual(str(shims / "uv"), rooted_path.which("uv"))
                self.assertEqual(str(brew / "claude"), rooted_path.which("claude"))
                self.assertEqual(shutil.which("uv", path=path), rooted_path.which("uv"))


@unittest.skipIf(sys.platform == "win32", SIMULATED)
class ClaudeIsFoundByTheSameRuleTest(unittest.TestCase):
    """Every place Compass starts or checks for `claude` resolves it through `rooted_path`."""

    def test_every_default_resolver_is_the_rooted_one(self) -> None:
        for function in (observer.claude_exec, observer.prepare_claude_exec):
            with self.subTest(function=function.__name__):
                default = inspect.signature(function).parameters["binary_resolver"].default
                self.assertIs(rooted_path.which, default)
        model = reading.ClaudeReadingModel(make_config())
        self.assertIs(rooted_path.which, model.binary_resolver)

    def test_the_summary_check_finds_the_real_claude_past_a_planted_one(self) -> None:
        with windows("C:\\Tools"):
            plant(".\\claude.exe")
            self.assertFalse(summary_jobs.ClaudeSummaryModel.available())
            plant("C:\\Tools\\claude.exe")
            self.assertTrue(summary_jobs.ClaudeSummaryModel.available())

    def test_a_driveless_claude_is_refused_where_isabs_would_accept_it(self) -> None:
        with windows("\\tools"):
            plant("\\tools\\claude.exe")
            self.assertFalse(summary_jobs.ClaudeSummaryModel.available())
            model = reading.ClaudeReadingModel(
                make_config(), binary_resolver=lambda _name: "\\tools\\claude.exe"
            )
            self.assertFalse(model.available())
            with (
                mock.patch.object(observer, "claude_lane_refusal", return_value=""),
                self.assertRaises(observer.ClaudePreparationError) as refused,
                observer.prepare_claude_exec(
                    make_config(),
                    binary_resolver=lambda _name: "\\tools\\claude.exe",
                    validator=lambda model: model,
                ),
            ):
                pass
            self.assertEqual("unavailable", refused.exception.status)


if __name__ == "__main__":
    unittest.main()
