"""`rooted_path`: the one rule for which program a PATH lookup may start.

Every command Compass starts by name (git, gh, glab, spacedock, tmux, the model CLIs) is
resolved against PATH elements no working directory can reinterpret, and the answer is held to
the same rule, because the working directory of a lookup is often a repository Compass does not
trust.
"""

from __future__ import annotations

import ntpath
import os
import shutil
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from compass_runtime import git_status, observer, rooted_path


def _program(path: Path) -> None:
    path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


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

    def test_a_driveless_answer_is_refused_under_the_windows_flavour(self) -> None:
        with (
            mock.patch.object(os, "name", "nt"),
            mock.patch.object(os, "path", ntpath),
            mock.patch.object(shutil, "which", return_value="\\bin\\tmux.exe"),
        ):
            resolved = rooted_path.executable("tmux", {"PATH": "C:\\bin"})
        self.assertIsNone(resolved)

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


if __name__ == "__main__":
    unittest.main()
