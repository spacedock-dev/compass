"""The standalone-binary release scripts, run for real against stand-ins.

PyInstaller and `gh` are the two things these scripts call that a unit test must not run for
real: one takes a minute and the other publishes. Each is replaced by a small shell program on
the script's own path that records what it was asked, so what is asserted is the script's
decisions: which archive name it writes, what it refuses, and the exact upload it would make.
The real build is proved by `scripts/smoke-cli.sh` in the release and `cli-package` workflows.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
PACKAGE = SCRIPTS / "package-cli.sh"
PUBLISH = SCRIPTS / "publish-cli.sh"
SMOKE = SCRIPTS / "smoke-cli.sh"
SH = shutil.which("sh") or "sh"
TARGETS = ("darwin_arm64", "darwin_amd64", "linux_arm64", "linux_amd64")


def write_program(path: Path, body: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
    path.chmod(0o755)
    return path


def run(
    argv: list[str], env: dict[str, str] | None = None, cwd: Path | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [SH, *argv],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
        env={**os.environ, **(env or {})},
        cwd=cwd,
    )


def host_target() -> str:
    os_name = {"Darwin": "darwin", "Linux": "linux"}[platform.system()]
    arch = {"arm64": "arm64", "aarch64": "arm64", "x86_64": "amd64", "AMD64": "amd64"}[
        platform.machine()
    ]
    return f"{os_name}_{arch}"


class PackageCliTest(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.src = self.root / "src"
        write_program(self.src / "compass/skills/compass/server.py", "")
        self.record = self.root / "pyinstaller-args"
        self.stamp = self.root / "stamp-as-built"
        # The stand-in answers the two probes the script makes, then "builds" a one-file
        # onedir into whichever --distpath it was handed.
        self.python = write_program(
            self.root / "python",
            f"""
case "$1" in
-c) exit ${{FAKE_PYTHON_REFUSES:-0}} ;;
esac
if [ "$3" = --version ]; then exit ${{FAKE_PYINSTALLER_MISSING:-0}}; fi
printf '%s\\n' "$@" > '{self.record}'
while [ $# -gt 0 ]; do
	[ "$1" = --distpath ] && dist="$2"
	case "$2" in */release-version.txt:*) [ "$1" = --add-data ] && cp "${{2%%:*}}" '{self.stamp}' ;; esac
	shift
done
mkdir -p "$dist/compass/_internal"
printf '#!/bin/sh\\n' > "$dist/compass/compass"
chmod +x "$dist/compass/compass"
""",
        )

    def package(self, version: str = "1.2.3", **env: str) -> subprocess.CompletedProcess[str]:
        return run(
            [str(PACKAGE), version, str(self.root / "out"), str(self.src)],
            env={"PYTHON": str(self.python), **env},
        )

    def test_it_packs_one_compass_directory_named_for_the_version_and_this_host(self) -> None:
        result = self.package()

        self.assertEqual(0, result.returncode, result.stderr)
        archive = self.root / "out" / f"compass_1.2.3_{host_target()}.tar.gz"
        self.assertEqual(str(archive), result.stdout.strip())
        with tarfile.open(archive) as tar:
            names = tar.getnames()
        self.assertEqual({"compass", "compass/compass", "compass/_internal"}, set(names))

    def test_it_hands_pyinstaller_the_runtime_package_and_its_page(self) -> None:
        self.package()

        args = self.record.read_text(encoding="utf-8").splitlines()
        skill = str(self.src / "compass/skills/compass")
        self.assertEqual(["-m", "PyInstaller"], args[:2])
        self.assertIn("--onedir", args)
        self.assertEqual(skill, args[args.index("--paths") + 1])
        self.assertEqual("compass_runtime", args[args.index("--collect-submodules") + 1])
        self.assertEqual(
            f"{skill}/compass_runtime/web:compass_runtime/web", args[args.index("--add-data") + 1]
        )
        self.assertEqual(f"{skill}/server.py", args[-1])

    def test_it_stamps_the_version_it_was_asked_for_into_the_runtime_package(self) -> None:
        self.package("4.5.6")

        args = self.record.read_text(encoding="utf-8").splitlines()
        data = [args[i + 1] for i, arg in enumerate(args) if arg == "--add-data"]
        self.assertEqual(2, len(data))
        self.assertTrue(data[1].endswith("/release-version.txt:compass_runtime"), data[1])
        self.assertEqual("4.5.6\n", self.stamp.read_text(encoding="utf-8"))

    def test_it_writes_nothing_into_the_source_tree(self) -> None:
        before = sorted(p.relative_to(self.src) for p in self.src.rglob("*"))

        self.package()

        self.assertEqual(before, sorted(p.relative_to(self.src) for p in self.src.rglob("*")))

    def test_it_refuses_an_interpreter_below_the_floor_rather_than_embed_it(self) -> None:
        result = self.package(FAKE_PYTHON_REFUSES="1")

        self.assertEqual(1, result.returncode)
        self.assertIn("3.11 or newer", result.stderr)
        self.assertEqual([], list((self.root / "out").glob("*.tar.gz")))

    def test_it_says_so_when_pyinstaller_is_not_installed(self) -> None:
        result = self.package(FAKE_PYINSTALLER_MISSING="1")

        self.assertEqual(1, result.returncode)
        self.assertIn("requirements-cli.txt", result.stderr)

    def test_it_refuses_a_tree_that_is_not_the_skill(self) -> None:
        shutil.rmtree(self.src / "compass")

        result = self.package()

        self.assertEqual(1, result.returncode)
        self.assertIn("server.py", result.stderr)


class PublishCliTest(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.archives = self.root / "archives"
        self.archives.mkdir()
        self.calls = self.root / "gh-calls"
        self.cwd = self.root / "gh-cwd"
        bin_dir = self.root / "bin"
        # The stand-in records its arguments and the directory it ran in: the real gh finds the
        # repository from that directory, which has to be a checkout and not the archives.
        write_program(
            bin_dir / "gh", f"printf '%s\\n' \"$*\" >> '{self.calls}'; pwd >> '{self.cwd}'"
        )
        self.env = {"PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"}

    def fill(self, version: str = "1.2.3", targets: tuple[str, ...] = TARGETS) -> None:
        for target in targets:
            (self.archives / f"compass_{version}_{target}.tar.gz").write_bytes(target.encode())

    def publish(self, *args: str) -> subprocess.CompletedProcess[str]:
        return run([str(PUBLISH), *args], env=self.env)

    def test_it_uploads_the_four_archives_and_their_checksums_in_one_call(self) -> None:
        self.fill()

        result = self.publish("v1.2.3", str(self.archives))

        self.assertEqual(0, result.returncode, result.stderr)
        paths = [f"{self.archives}/compass_1.2.3_{target}.tar.gz" for target in TARGETS]
        self.assertEqual(
            [f"release upload v1.2.3 {' '.join(paths)} {self.archives}/checksums.txt --clobber"],
            self.calls.read_text(encoding="utf-8").splitlines(),
        )

    def test_it_runs_gh_from_where_it_was_started_and_not_inside_the_archives(self) -> None:
        # gh learns the repository from its working directory. Inside the archive directory it
        # failed with "not a git repository", which is how the first release attached nothing.
        self.fill()
        start = self.root / "checkout"
        start.mkdir()

        result = run([str(PUBLISH), "v1.2.3", str(self.archives)], env=self.env, cwd=start)

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(
            [str(start.resolve())], self.cwd.read_text(encoding="utf-8").strip().splitlines()
        )

    def test_the_checksums_are_the_lines_the_installer_reads(self) -> None:
        self.fill()

        self.publish("v1.2.3", str(self.archives), "--dry-run")

        lines = (self.archives / "checksums.txt").read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(TARGETS), len(lines))
        for line, target in zip(lines, TARGETS, strict=True):
            digest, name = line.split("  ")
            self.assertEqual(f"compass_1.2.3_{target}.tar.gz", name)
            self.assertRegex(digest, r"^[0-9a-f]{64}$")

    def test_a_bare_tag_names_the_same_version_as_a_v_tag(self) -> None:
        self.fill()

        result = self.publish("1.2.3", str(self.archives), "--dry-run")

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("gh release upload 1.2.3 compass_1.2.3_darwin_arm64.tar.gz", result.stdout)

    def test_a_dry_run_uploads_nothing(self) -> None:
        self.fill()

        result = self.publish("v1.2.3", str(self.archives), "--dry-run")

        self.assertEqual(0, result.returncode)
        self.assertIn("would run: gh release upload", result.stdout)
        self.assertFalse(self.calls.exists())

    def test_it_refuses_when_a_target_is_missing(self) -> None:
        self.fill(targets=TARGETS[:3])

        result = self.publish("v1.2.3", str(self.archives))

        self.assertEqual(1, result.returncode)
        self.assertIn("missing compass_1.2.3_linux_amd64.tar.gz", result.stderr)
        self.assertFalse(self.calls.exists())

    def test_it_refuses_archives_built_for_another_version(self) -> None:
        self.fill(version="1.2.2")

        result = self.publish("v1.2.3", str(self.archives))

        self.assertEqual(1, result.returncode)
        self.assertIn("missing compass_1.2.3_darwin_arm64.tar.gz", result.stderr)
        self.assertFalse(self.calls.exists())

    def test_it_refuses_a_file_nobody_asked_it_to_attach(self) -> None:
        self.fill()
        (self.archives / "notes.txt").write_text("stray", encoding="utf-8")

        result = self.publish("v1.2.3", str(self.archives))

        self.assertEqual(1, result.returncode)
        self.assertIn("unexpected file notes.txt", result.stderr)
        self.assertFalse(self.calls.exists())

    def test_it_refuses_a_tag_that_is_not_plain_semver(self) -> None:
        self.fill()
        for tag in ("v1.2", "v1.2.3-rc1", "main", "v1..3", "v.1.2"):
            with self.subTest(tag=tag):
                result = self.publish(tag, str(self.archives), "--dry-run")
                self.assertEqual(1, result.returncode)
                self.assertIn("not a plain X.Y.Z tag", result.stderr)

    def test_it_refuses_an_option_it_does_not_know(self) -> None:
        self.fill()

        result = self.publish("v1.2.3", str(self.archives), "--force")

        self.assertEqual(1, result.returncode)
        self.assertIn("unknown option --force", result.stderr)
        self.assertFalse(self.calls.exists())


class SmokeCliTest(unittest.TestCase):
    def test_it_refuses_an_archive_without_the_program(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "compass").mkdir()
            (root / "compass" / "README").write_text("no program here", encoding="utf-8")
            archive = root / "compass_0.0.0_test.tar.gz"
            with tarfile.open(archive, "w:gz") as tar:
                tar.add(root / "compass", arcname="compass")

            result = run([str(SMOKE), str(archive)])

        self.assertEqual(1, result.returncode)
        self.assertIn("no compass/compass program", result.stderr)

    def archive_with_program(self, root: Path, name: str, body: str) -> Path:
        program = write_program(root / "stage" / "compass" / "compass", body)
        archive = root / name
        with tarfile.open(archive, "w:gz") as tar:
            tar.add(program.parent, arcname="compass")
        return archive

    def test_it_refuses_a_program_whose_version_is_not_the_one_the_archive_is_named_for(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as folder:
            archive = self.archive_with_program(
                Path(folder),
                "compass_1.2.3_test.tar.gz",
                'case "$1" in --version) echo 1.2.2 ;; esac',
            )

            result = run([str(SMOKE), str(archive)])

        self.assertEqual(1, result.returncode)
        self.assertIn(
            "--version printed '1.2.2', but the archive is named for 1.2.3", result.stderr
        )

    def test_it_refuses_a_program_that_cannot_report_a_version(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            archive = self.archive_with_program(
                Path(folder),
                "compass_1.2.3_test.tar.gz",
                'case "$1" in --version) exit 2 ;; esac',
            )

            result = run([str(SMOKE), str(archive)])

        self.assertEqual(1, result.returncode)
        self.assertIn("--version failed", result.stderr)


if __name__ == "__main__":
    unittest.main()
