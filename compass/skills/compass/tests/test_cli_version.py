"""`--version`: the bare version on one line, from the stamp a binary carries or the manifest."""

from __future__ import annotations

import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from compass_runtime import cli

from .support import SERVER_PATH

MANIFEST = SERVER_PATH.parents[2] / ".claude-plugin" / "plugin.json"


def run_main(*argv: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main(list(argv))
    return code, out.getvalue(), err.getvalue()


class VersionFlagTest(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def stamp_at(self, name: str, text: str | None) -> Path:
        path = self.root / name
        if text is not None:
            path.write_text(text, encoding="utf-8")
        return path

    def test_it_prints_the_manifest_version_alone_on_one_line(self) -> None:
        expected = json.loads(MANIFEST.read_text(encoding="utf-8"))["version"]

        with mock.patch.object(cli, "BUNDLED_VERSION_PATH", self.stamp_at("none", None)):
            code, out, err = run_main("--version")

        self.assertEqual((0, f"{expected}\n", ""), (code, out, err))

    def test_a_binary_prints_its_stamp_not_the_manifest_of_the_tree_it_was_built_from(self) -> None:
        with mock.patch.object(cli, "BUNDLED_VERSION_PATH", self.stamp_at("stamp", "9.8.7\n")):
            code, out, _ = run_main("--version")

        self.assertEqual((0, "9.8.7\n"), (code, out))

    def test_an_empty_stamp_falls_back_to_the_manifest(self) -> None:
        expected = json.loads(MANIFEST.read_text(encoding="utf-8"))["version"]

        with mock.patch.object(cli, "BUNDLED_VERSION_PATH", self.stamp_at("stamp", "\n")):
            code, out, _ = run_main("--version")

        self.assertEqual((0, f"{expected}\n"), (code, out))

    def test_it_says_so_and_exits_nonzero_when_nothing_records_the_version(self) -> None:
        for manifest in (self.stamp_at("missing.json", None), self.stamp_at("bad.json", "{")):
            with (
                self.subTest(manifest=manifest.name),
                mock.patch.object(cli, "BUNDLED_VERSION_PATH", self.stamp_at("none", None)),
                mock.patch.object(cli, "PLUGIN_MANIFEST_PATH", manifest),
            ):
                code, out, err = run_main("--version")

            self.assertEqual((1, ""), (code, out))
            self.assertIn("does not record its version", err)

    def test_it_answers_before_the_operation_flags_are_checked_against_each_other(self) -> None:
        with mock.patch.object(cli, "BUNDLED_VERSION_PATH", self.stamp_at("stamp", "1.2.3\n")):
            code, out, _ = run_main("--version", "--daemon", "--status")

        self.assertEqual((0, "1.2.3\n"), (code, out))

    def test_the_launcher_prints_it(self) -> None:
        expected = json.loads(MANIFEST.read_text(encoding="utf-8"))["version"]

        done = subprocess.run(
            [sys.executable, str(SERVER_PATH), "--version"],
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )

        self.assertEqual((0, f"{expected}\n"), (done.returncode, done.stdout))


if __name__ == "__main__":
    unittest.main()
