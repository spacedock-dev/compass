"""The post-bump archive proof stops a bad release before `stable` can move.

Each failing case builds the commit a real release could have produced and runs
the proof against its `git archive`, so a check that only looked at the working
tree would pass where the shipped bytes do not.
"""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from typing import TYPE_CHECKING
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import release_transition as rt
import verify_release_archive as vra

if TYPE_CHECKING:
    from tests.release_fixture import MANIFESTS, WEB, Fixture, git
else:
    from release_fixture import MANIFESTS, WEB, Fixture, git

BUNDLE = f"{WEB}/react.html"
RUNTIME_FILE = "compass/skills/compass/compass_runtime/http_api.py"


class ArchiveProofTest(unittest.TestCase):
    def setUp(self) -> None:
        self.fx = Fixture(self)
        self.verified = self.fx.commit("feat: work")

    def bumped(self, version: str = "0.2.0") -> str:
        rt.bump(self.fx.work, version)
        return rt.commit_bump(self.fx.work, f"v{version}")

    def prove(self, commit: str, version: str = "0.2.0", verified: str | None = None) -> None:
        vra.verify_archive(self.fx.work, commit, verified or self.verified, version)

    def rejected(self, commit: str, needle: str, version: str = "0.2.0") -> None:
        with self.assertRaises(vra.ArchiveError) as caught:
            self.prove(commit, version)
        self.assertIn(needle, str(caught.exception))

    def test_the_real_bump_commit_passes_every_check(self) -> None:
        report = vra.verify_archive(self.fx.work, self.bumped(), self.verified, "0.2.0")
        self.assertEqual(
            ["versions", "changes", "bundle", "inventory", "page", "launch"],
            list(report.checks),
        )

    def test_a_resumed_release_is_proven_against_itself(self) -> None:
        self.prove(self.verified, version="0.1.0")

    def test_the_proof_reads_the_commit_not_the_working_tree(self) -> None:
        final = self.bumped()
        (self.fx.work / BUNDLE).write_text("<!doctype html>\n", encoding="utf-8")
        self.prove(final)

    def test_a_bundle_changed_after_verification_is_refused(self) -> None:
        rt.bump(self.fx.work, "0.2.0")
        (self.fx.work / BUNDLE).write_bytes((self.fx.work / BUNDLE).read_bytes() + b"<!-- x -->\n")
        git(self.fx.work, "add", "-A")
        git(self.fx.work, "commit", "-q", "-m", "chore(release): v0.2.0 plus a rebuilt bundle")
        self.rejected(git(self.fx.work, "rev-parse", "HEAD"), "changed")

    def test_a_tampered_bundle_verified_and_final_alike_fails_the_integrity_check(self) -> None:
        self.fx.commit("fix: tamper", files={BUNDLE: "<!doctype html>\n"})
        tampered = git(self.fx.work, "rev-parse", "HEAD")
        rt.bump(self.fx.work, "0.2.0")
        final = rt.commit_bump(self.fx.work, "v0.2.0")
        with self.assertRaises(vra.ArchiveError) as caught:
            vra.verify_archive(self.fx.work, final, tampered, "0.2.0")
        self.assertIn("react page failed its integrity check", str(caught.exception))

    def test_a_wrong_version_is_refused(self) -> None:
        final = self.bumped("0.2.0")
        self.rejected(final, "0.3.0", version="0.3.0")

    def test_a_partial_bump_is_refused_as_version_drift(self) -> None:
        path = self.fx.work / MANIFESTS[0]
        data = json.loads(path.read_text(encoding="utf-8"))
        data["version"] = "0.2.0"
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        git(self.fx.work, "add", "-A")
        git(self.fx.work, "commit", "-q", "-m", "chore(release): v0.2.0")
        self.rejected(git(self.fx.work, "rev-parse", "HEAD"), "parity")

    def test_a_missing_runtime_file_is_refused(self) -> None:
        git(self.fx.work, "rm", "-q", RUNTIME_FILE)
        git(self.fx.work, "commit", "-q", "-m", "fix: drop a module")
        broken = git(self.fx.work, "rev-parse", "HEAD")
        rt.bump(self.fx.work, "0.2.0")
        final = rt.commit_bump(self.fx.work, "v0.2.0")
        with self.assertRaises(vra.ArchiveError) as caught:
            vra.verify_archive(self.fx.work, final, broken, "0.2.0")
        self.assertIn("http_api.py", str(caught.exception))

    def test_a_release_commit_that_changes_anything_but_the_manifests_is_refused(self) -> None:
        rt.bump(self.fx.work, "0.2.0")
        (self.fx.work / "README.md").write_text("changed in the release commit\n", encoding="utf-8")
        git(self.fx.work, "add", "-A")
        git(self.fx.work, "commit", "-q", "-m", "chore(release): v0.2.0")
        self.rejected(git(self.fx.work, "rev-parse", "HEAD"), "README.md")

    def test_a_release_commit_with_a_repeated_manifest_key_is_refused(self) -> None:
        rt.bump(self.fx.work, "0.2.0")
        path = self.fx.work / MANIFESTS[1]
        body = path.read_text(encoding="utf-8")
        description = json.loads(body)["description"]
        path.write_text(
            '{"description": ' + json.dumps(description) + "," + body[1:], encoding="utf-8"
        )
        git(self.fx.work, "add", "-A")
        git(self.fx.work, "commit", "-q", "-m", "chore(release): v0.2.0")
        self.rejected(git(self.fx.work, "rev-parse", "HEAD"), MANIFESTS[1])

    def test_a_release_commit_that_makes_a_manifest_executable_is_refused(self) -> None:
        rt.bump(self.fx.work, "0.2.0")
        git(self.fx.work, "add", "-A")
        git(self.fx.work, "update-index", "--chmod=+x", MANIFESTS[1])
        git(self.fx.work, "commit", "-q", "-m", "chore(release): v0.2.0")
        self.rejected(git(self.fx.work, "rev-parse", "HEAD"), MANIFESTS[1])

    def test_an_archive_that_differs_from_the_commit_is_refused(self) -> None:
        # export-subst rewrites a blob on the way into the archive, which is the one
        # way `git archive` can ship bytes that the commit's own diff does not show.
        licenses = f"{WEB}/react-licenses.txt"
        (self.fx.work / ".gitattributes").write_text(f"{licenses} export-subst\n", encoding="utf-8")
        body = (self.fx.work / licenses).read_text(encoding="utf-8")
        (self.fx.work / licenses).write_text(body + "$Format:%H$\n", encoding="utf-8")
        git(self.fx.work, "add", "-A")
        git(self.fx.work, "commit", "-q", "-m", "fix: a placeholder")
        verified = git(self.fx.work, "rev-parse", "HEAD")
        rt.bump(self.fx.work, "0.2.0")
        final = rt.commit_bump(self.fx.work, "v0.2.0")
        with self.assertRaises(vra.ArchiveError) as caught:
            vra.verify_archive(self.fx.work, final, verified, "0.2.0")
        self.assertIn("changed after verification", str(caught.exception))

    def test_a_launcher_that_cannot_start_is_refused(self) -> None:
        launcher = "compass/skills/compass/server.py"
        self.fx.commit("fix: broken launcher", files={launcher: "raise SystemExit(3)\n"})
        broken = git(self.fx.work, "rev-parse", "HEAD")
        rt.bump(self.fx.work, "0.2.0")
        final = rt.commit_bump(self.fx.work, "v0.2.0")
        with self.assertRaises(vra.ArchiveError) as caught:
            vra.verify_archive(self.fx.work, final, broken, "0.2.0")
        self.assertIn("launcher", str(caught.exception))

    def test_a_release_commit_two_steps_from_the_verified_one_is_refused(self) -> None:
        git(self.fx.work, "commit", "-q", "--allow-empty", "-m", "an unverified commit")
        final = self.bumped()
        self.rejected(final, "direct child")

    def test_a_scratch_directory_never_outlives_the_proof(self) -> None:
        final = self.bumped()
        created: list[str] = []
        real = tempfile.mkdtemp

        def spy(*args: object, **kwargs: object) -> str:
            path = real(*args, **kwargs)  # type: ignore[call-overload]
            created.append(path)
            return str(path)

        with mock.patch.object(tempfile, "mkdtemp", spy):
            self.prove(final)
        self.assertTrue(created)
        self.assertFalse([path for path in created if Path(path).exists()])


class IsolationTest(unittest.TestCase):
    def test_the_smoke_environment_carries_no_ambient_state(self) -> None:
        with tempfile.TemporaryDirectory() as home:
            planted = {
                "GITHUB_TOKEN": "x",
                "RELEASE_DEPLOY_KEY": "x",
                "SSH_AUTH_SOCK": "/tmp/agent",
                "NODE_OPTIONS": "--require /tmp/x",
                "PYTHONPATH": "/tmp/x",
                "HOME": "/Users/someone",
            }
            with mock.patch.dict(os.environ, planted):
                env = vra.isolated_env(Path(home))
            self.assertEqual(
                {"PATH", "HOME", "USERPROFILE", "COMPASS_HOME", "PYTHONNOUSERSITE", "LC_ALL"},
                set(env),
            )
            self.assertEqual(home, env["HOME"])
            self.assertTrue(env["COMPASS_HOME"].startswith(home))
            path = Path(env["PATH"])
            self.assertTrue(path.is_dir())
            self.assertEqual([], list(path.iterdir()), "no executable, so no Node, is reachable")

    def test_the_interpreter_runs_isolated_from_site_and_environment(self) -> None:
        with tempfile.TemporaryDirectory() as home:
            self.assertEqual(["-I"], vra.PAGE_FLAGS)
            self.assertEqual(["-E", "-s"], vra.LAUNCH_FLAGS)
            result = vra.run_python(
                Path(home), ["-I", "-c", "import sys; print(sys.flags.isolated)"]
            )
            self.assertEqual("1", result.stdout.strip())


class ExtractionTest(unittest.TestCase):
    def archive(self, names: list[str], *, link: tuple[str, str] | None = None) -> Path:
        handle, name = tempfile.mkstemp(suffix=".tar")
        os.close(handle)
        self.addCleanup(Path(name).unlink)
        with tarfile.open(name, "w") as tar:
            for member in names:
                info = tarfile.TarInfo(member)
                data = b"x"
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))
            if link:
                info = tarfile.TarInfo(link[0])
                info.type = tarfile.SYMTYPE
                info.linkname = link[1]
                tar.addfile(info)
        return Path(name)

    def test_members_that_escape_the_destination_are_refused(self) -> None:
        for names in (["../evil"], ["/abs/evil"], ["ok", "a/../../evil"]):
            with self.subTest(names=names), tempfile.TemporaryDirectory() as dest:
                with self.assertRaises(vra.ArchiveError):
                    vra.extract_archive(self.archive(names), Path(dest))
                self.assertEqual([], list(Path(dest).iterdir()))

    def tar_of(self, entries: list[tuple[str, bytes, str, str]]) -> Path:
        """Entries are (name, kind, linkname-or-data); kind is file, sym, hard or fifo."""
        handle, name = tempfile.mkstemp(suffix=".tar")
        os.close(handle)
        self.addCleanup(Path(name).unlink)
        with tarfile.open(name, "w") as tar:
            for entry in entries:
                member, kind, target = entry[0], entry[2], entry[3]
                info = tarfile.TarInfo(member)
                if kind == "sym":
                    info.type, info.linkname = tarfile.SYMTYPE, target
                    tar.addfile(info)
                elif kind == "hard":
                    info.type, info.linkname = tarfile.LNKTYPE, target
                    tar.addfile(info)
                elif kind == "fifo":
                    info.type = tarfile.FIFOTYPE
                    tar.addfile(info)
                else:
                    info.size = len(entry[1])
                    tar.addfile(info, io.BytesIO(entry[1]))
        return Path(name)

    def test_every_link_is_refused_whatever_it_points_at(self) -> None:
        for target in ("/etc/passwd", "../../outside", "a/../../outside", "real", "."):
            with (
                self.subTest(target=target),
                tempfile.TemporaryDirectory() as dest,
                self.assertRaises(vra.ArchiveError),
            ):
                vra.extract_archive(
                    self.tar_of([("real", b"x", "file", ""), ("alias", b"", "sym", target)]),
                    Path(dest),
                )

    def test_a_hard_link_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as dest, self.assertRaises(vra.ArchiveError):
            vra.extract_archive(
                self.tar_of([("real", b"x", "file", ""), ("alias", b"", "hard", "real")]),
                Path(dest),
            )

    def test_a_symlink_chain_cannot_write_above_the_root(self) -> None:
        # Each link is individually harmless under a lexical check; together they
        # walk two directories up before the final file is written.
        with tempfile.TemporaryDirectory() as outer:
            root = Path(outer) / "one" / "two"
            root.mkdir(parents=True)
            chain = [
                ("a", b"", "sym", "."),
                ("a/b", b"", "sym", ".."),
                ("a/b/c", b"", "sym", "../.."),
                ("a/b/c/ESCAPED.txt", b"escaped", "file", ""),
            ]
            with self.assertRaises(vra.ArchiveError):
                vra.extract_archive(self.tar_of(chain), root)
            self.assertEqual([], list(Path(outer).rglob("ESCAPED.txt")))

    def test_a_member_that_is_not_a_file_or_directory_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as dest, self.assertRaises(vra.ArchiveError):
            vra.extract_archive(self.tar_of([("pipe", b"", "fifo", "")]), Path(dest))

    def test_ordinary_members_extract(self) -> None:
        with tempfile.TemporaryDirectory() as dest:
            vra.extract_archive(self.archive(["a/b.txt"]), Path(dest))
            self.assertEqual(b"x", (Path(dest) / "a/b.txt").read_bytes())


class StricterProofTest(unittest.TestCase):
    """The bump may change the version value and nothing else, and every guard is pinned."""

    def setUp(self) -> None:
        self.fx = Fixture(self)
        self.verified = self.fx.commit("feat: work")
        rt.bump(self.fx.work, "0.2.0")

    def commit_and_prove(self, needle: str) -> None:
        git(self.fx.work, "add", "-A")
        git(self.fx.work, "commit", "-q", "-m", "chore(release): v0.2.0")
        final = git(self.fx.work, "rev-parse", "HEAD")
        with self.assertRaises(vra.ArchiveError) as caught:
            vra.verify_archive(self.fx.work, final, self.verified, "0.2.0")
        self.assertIn(needle, str(caught.exception))

    def test_a_key_added_to_a_manifest_alongside_the_version_is_refused(self) -> None:
        path = self.fx.work / MANIFESTS[0]
        data = json.loads(path.read_text(encoding="utf-8"))
        data["hooks"] = "./evil/hooks.json"
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        self.commit_and_prove("beyond the version")

    def test_a_key_removed_from_a_manifest_alongside_the_version_is_refused(self) -> None:
        path = self.fx.work / MANIFESTS[0]
        data = json.loads(path.read_text(encoding="utf-8"))
        data.pop("description")
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        self.commit_and_prove("beyond the version")

    def test_a_deleted_file_is_a_change(self) -> None:
        git(self.fx.work, "rm", "-q", "compass/hooks.json")
        self.commit_and_prove("beyond the version")

    def test_a_deleted_manifest_is_a_change(self) -> None:
        final = git(self.fx.work, "rev-parse", "HEAD")
        git(self.fx.work, "rm", "-q", "-f", MANIFESTS[1])
        git(self.fx.work, "commit", "-q", "-m", "chore(release): v0.2.0")
        with self.assertRaises(vra.ArchiveError) as caught:
            vra.check_changes(
                self.fx.work, git(self.fx.work, "rev-parse", "HEAD"), final, list(MANIFESTS)
            )
        self.assertIn(MANIFESTS[1], str(caught.exception))

    def test_the_allowed_paths_come_from_the_verified_script_not_the_release_commit(self) -> None:
        script = self.fx.work / "scripts/bump_version.py"
        text = script.read_text(encoding="utf-8")
        script.write_text(
            text.replace(
                '    ROOT / "compass-gemini/gemini-extension.json",',
                '    ROOT / "compass-gemini/gemini-extension.json",\n    ROOT / "README.md",',
            ),
            encoding="utf-8",
        )
        (self.fx.work / "README.md").write_text("changed in the release commit\n", encoding="utf-8")
        self.commit_and_prove("beyond the version")

    def test_a_symlink_elsewhere_in_the_repository_does_not_block_the_archive(self) -> None:
        link = self.fx.work / ".agents/skills/alias"
        link.parent.mkdir(parents=True)
        link.symlink_to("../../scripts")
        git(self.fx.work, "add", "-A")
        git(self.fx.work, "commit", "-q", "-m", "feat: alias")
        verified = git(self.fx.work, "rev-parse", "HEAD")
        final = rt.commit_bump(self.fx.work, "v0.2.0")
        vra.verify_archive(self.fx.work, final, verified, "0.2.0")

    def test_arguments_are_validated_before_git_sees_them(self) -> None:
        head = git(self.fx.work, "rev-parse", "HEAD")
        for bad in ("main", "HEAD", "--output=x", head[:12], head.upper(), ""):
            with self.subTest(bad=bad), self.assertRaises(vra.ArchiveError):
                vra.verify_archive(self.fx.work, bad, head, "0.1.0")
            with self.subTest(verified=bad), self.assertRaises(vra.ArchiveError):
                vra.verify_archive(self.fx.work, head, bad, "0.1.0")
        for version in ("01.2.3", "0.2", "v0.2.0", "0.2.0-rc1", "1.2.1\u0663"):
            with (
                self.subTest(version=version),
                self.assertRaisesRegex(vra.ArchiveError, "strict semver"),
            ):
                vra.verify_archive(self.fx.work, head, head, version)

    def test_the_page_must_be_the_verified_document_not_just_a_valid_one(self) -> None:
        wrong = subprocess.CompletedProcess(
            [], 0, stdout='{"sha256": "' + "0" * 64 + '"}\n', stderr=""
        )
        with (
            tempfile.TemporaryDirectory() as scratch,
            mock.patch.object(vra, "run_python", return_value=wrong),
            self.assertRaises(vra.ArchiveError) as caught,
        ):
            vra.check_page(
                self.fx.work, Path(scratch), git(self.fx.work, "rev-parse", "HEAD"), Path(scratch)
            )
        self.assertIn("other than the verified document", str(caught.exception))

    def test_a_failure_is_printed_as_one_annotation_line(self) -> None:
        output = io.StringIO()
        boom = vra.ArchiveError("bad\n::stop-commands::abc\r%")
        with (
            mock.patch.object(vra, "verify_archive", side_effect=boom),
            mock.patch("sys.stdout", output),
        ):
            code = vra.main(["--commit", "a", "--verified", "b", "--version", "0.2.0"])
        self.assertEqual(1, code)
        self.assertEqual(1, len(output.getvalue().splitlines()), output.getvalue())
        self.assertTrue(output.getvalue().startswith("::error::"))


if __name__ == "__main__":
    unittest.main()
