"""The Homebrew formula: what it renders, what it refuses, and the push it makes.

`update_homebrew.py` is called directly. `publish-homebrew.sh` runs for real against a local bare
repository standing in for spacedock-dev/homebrew-tap and a local directory standing in for the
GitHub releases, which exercises the fetch, the clone, the commit and the push and needs no key
or network: the script asks for a key only of an SSH remote.
"""

from __future__ import annotations

import contextlib
import io
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import update_homebrew

SCRIPTS = Path(__file__).resolve().parents[1]
PUBLISH = SCRIPTS / "publish-homebrew.sh"
SH = shutil.which("sh") or "sh"
GIT = shutil.which("git") or "git"
FORMULA = "Formula/compass.rb"
TARGETS = ("darwin_arm64", "darwin_amd64", "linux_arm64", "linux_amd64")

V130 = {
    "darwin_arm64": "e170523f71be1e7a02be3fc4b5a185319b246afb9c4244a276bdaf31be7990a0",
    "darwin_amd64": "5ad704e74d37c5704ed1a53b8b64c8765678385ea14842adb18ccb0f5c154204",
    "linux_arm64": "4ffaa68ce57b1d4b81fa68657b61d97d3c96c1503e99979e97c027c87d4ea0fa",
    "linux_amd64": "5a97c404034a82afc8df444a76bee61548c5fc94816b7fffca056e0fd88dae6c",
}

GOLDEN_V130 = """\
class Compass < Formula
  desc "Agnostic agent cartography and visualization tool"
  homepage "https://github.com/spacedock-dev/compass"
  version "1.3.0"
  license all_of: ["Apache-2.0", "OFL-1.1"]

  on_macos do
    on_arm do
      url "https://github.com/spacedock-dev/compass/releases/download/v1.3.0/compass_1.3.0_darwin_arm64.tar.gz"
      sha256 "e170523f71be1e7a02be3fc4b5a185319b246afb9c4244a276bdaf31be7990a0"
    end
    on_intel do
      url "https://github.com/spacedock-dev/compass/releases/download/v1.3.0/compass_1.3.0_darwin_amd64.tar.gz"
      sha256 "5ad704e74d37c5704ed1a53b8b64c8765678385ea14842adb18ccb0f5c154204"
    end
  end

  on_linux do
    on_arm do
      url "https://github.com/spacedock-dev/compass/releases/download/v1.3.0/compass_1.3.0_linux_arm64.tar.gz"
      sha256 "4ffaa68ce57b1d4b81fa68657b61d97d3c96c1503e99979e97c027c87d4ea0fa"
    end
    on_intel do
      url "https://github.com/spacedock-dev/compass/releases/download/v1.3.0/compass_1.3.0_linux_amd64.tar.gz"
      sha256 "5a97c404034a82afc8df444a76bee61548c5fc94816b7fffca056e0fd88dae6c"
    end
  end

  def install
    libexec.install Dir["*"]
    bin.install_symlink libexec/"compass" => "compass"
    bin.install_symlink libexec/"compass" => "spacedock-compass"
  end

  test do
    assert_match version.to_s, shell_output("#{bin}/compass --version")
  end
end
"""


def checksums(version: str, digests: dict[str, str] | None = None) -> str:
    """A checksums.txt in the shape scripts/publish-cli.sh writes."""
    return "".join(
        f"{(digests or {}).get(t, 'ab' * 32)}  compass_{version}_{t}.tar.gz\n" for t in TARGETS
    )


class UpdateHomebrewTest(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.formula = self.root / "Formula" / "compass.rb"

    def sums(self, text: str) -> Path:
        path = self.root / "checksums.txt"
        path.write_text(text, encoding="utf-8")
        return path

    def test_it_renders_the_released_formula_from_the_published_checksums(self) -> None:
        message = update_homebrew.write_formula(
            self.formula, self.sums(checksums("1.3.0", V130)), "v1.3.0"
        )

        self.assertEqual("tap now lists compass 1.3.0", message)
        self.assertEqual(GOLDEN_V130, self.formula.read_text(encoding="utf-8"))

    def test_a_bare_tag_names_the_bare_tag_in_every_download_url(self) -> None:
        update_homebrew.write_formula(self.formula, self.sums(checksums("1.3.0", V130)), "1.3.0")

        urls = [
            line.split('"')[1]
            for line in self.formula.read_text(encoding="utf-8").splitlines()
            if line.lstrip().startswith("url ")
        ]
        self.assertEqual(4, len(urls))
        for url in urls:
            self.assertRegex(
                url, r"/releases/download/1\.3\.0/compass_1\.3\.0_[a-z]+_[a-z0-9]+\.tar\.gz$"
            )

    def test_the_same_version_is_left_alone(self) -> None:
        sums = self.sums(checksums("1.3.0", V130))
        update_homebrew.write_formula(self.formula, sums, "v1.3.0")
        before = self.formula.read_bytes()

        message = update_homebrew.write_formula(self.formula, sums, "v1.3.0")

        self.assertEqual("tap already lists compass 1.3.0", message)
        self.assertEqual(before, self.formula.read_bytes())

    def test_a_newer_version_replaces_it(self) -> None:
        update_homebrew.write_formula(self.formula, self.sums(checksums("1.3.0", V130)), "v1.3.0")

        update_homebrew.write_formula(self.formula, self.sums(checksums("1.4.0")), "v1.4.0")

        text = self.formula.read_text(encoding="utf-8")
        self.assertIn("compass_1.4.0_", text)
        self.assertNotIn("1.3.0", text)

    def test_an_older_release_never_rolls_the_tap_back(self) -> None:
        update_homebrew.write_formula(self.formula, self.sums(checksums("1.3.0", V130)), "v1.3.0")
        before = self.formula.read_bytes()

        message = update_homebrew.write_formula(
            self.formula, self.sums(checksums("1.2.9")), "v1.2.9"
        )

        self.assertIn("newer than 1.2.9", message)
        self.assertEqual(before, self.formula.read_bytes())

    def test_the_tap_version_is_the_explicit_field_even_when_no_url_carries_one(self) -> None:
        self.formula.parent.mkdir(parents=True)
        self.formula.write_text(
            'class Compass < Formula\n  version "1.9.0"\nend\n', encoding="utf-8"
        )

        message = update_homebrew.write_formula(
            self.formula, self.sums(checksums("1.3.0", V130)), "v1.3.0"
        )

        self.assertIn("lists compass 1.9.0, newer than 1.3.0", message)
        self.assertNotIn("1.3.0", self.formula.read_text(encoding="utf-8"))

    def test_a_formula_with_no_version_line_is_read_from_its_download_urls(self) -> None:
        # What the tap holds if a formula was written before the version field was rendered.
        self.formula.parent.mkdir(parents=True)
        legacy = GOLDEN_V130.replace('  version "1.3.0"\n', "").replace("1.3.0", "1.4.0")
        self.formula.write_text(legacy, encoding="utf-8")

        older = update_homebrew.write_formula(
            self.formula, self.sums(checksums("1.3.0", V130)), "v1.3.0"
        )
        newer = update_homebrew.write_formula(self.formula, self.sums(checksums("1.5.0")), "v1.5.0")

        self.assertIn("lists compass 1.4.0, newer than 1.3.0", older)
        self.assertEqual("tap now lists compass 1.5.0", newer)
        self.assertIn('version "1.5.0"', self.formula.read_text(encoding="utf-8"))

    def test_versions_compare_as_numbers_not_text(self) -> None:
        update_homebrew.write_formula(self.formula, self.sums(checksums("1.9.0")), "v1.9.0")

        update_homebrew.write_formula(self.formula, self.sums(checksums("1.10.0")), "v1.10.0")

        self.assertIn("compass_1.10.0_", self.formula.read_text(encoding="utf-8"))

    def test_it_refuses_a_checksums_file_that_is_not_exactly_the_four_archives(self) -> None:
        good = checksums("1.3.0", V130).splitlines(keepends=True)
        digest = "cd" * 32
        for name, text in {
            "a missing archive": "".join(good[:3]),
            "a stray file": "".join(good) + f"{digest}  notes.txt\n",
            "another version": checksums("1.2.0"),
            "a duplicate": "".join(good) + good[0],
            "no digest": "".join(good[:3]) + "compass_1.3.0_linux_amd64.tar.gz\n",
            "an upper-case digest": "".join(good).replace(V130["linux_amd64"], "A" * 64),
            "a short digest": "".join(good).replace(V130["linux_amd64"], "ab" * 31),
            "an empty file": "",
        }.items():
            with self.subTest(name), self.assertRaises(SystemExit):
                update_homebrew.write_formula(self.formula, self.sums(text), "v1.3.0")
            self.assertFalse(self.formula.exists(), name)

    def test_it_refuses_anything_but_strict_semver(self) -> None:
        sums = self.sums(checksums("1.3.0", V130))
        for tag in ("v1.3", "01.3.0", "v1.3.0-rc.1", "vv1.3.0", "1.3.0 ", ""):
            with self.subTest(tag=tag), self.assertRaises(SystemExit):
                update_homebrew.write_formula(self.formula, sums, tag)

    def test_it_refuses_a_checksums_file_it_cannot_read(self) -> None:
        with self.assertRaises(SystemExit):
            update_homebrew.write_formula(self.formula, self.root / "missing.txt", "v1.3.0")

    def test_the_command_takes_exactly_a_formula_checksums_and_a_tag(self) -> None:
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(2, update_homebrew.main([]))
            self.assertEqual(2, update_homebrew.main(["formula", "checksums"]))

    def test_the_command_reports_what_it_did(self) -> None:
        sums = self.sums(checksums("1.3.0", V130))

        done = subprocess.run(
            [
                sys.executable,
                "-I",
                str(SCRIPTS / "update_homebrew.py"),
                str(self.formula),
                str(sums),
                "v1.3.0",
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )

        self.assertEqual(0, done.returncode, done.stderr)
        self.assertEqual("tap now lists compass 1.3.0\n", done.stdout)


class PublishHomebrewTest(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.scratch = self.root / "scratch"
        self.scratch.mkdir()
        self.remote = self.root / "homebrew-tap.git"
        self.releases = self.root / "releases"
        self.env = {
            **os.environ,
            # The developer's own git configuration (signing, hooks) must not decide a test.
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_SYSTEM": os.devnull,
            "TMPDIR": str(self.scratch),
            "HOMEBREW_TAP_REMOTE": str(self.remote),
            "COMPASS_RELEASE_URL": self.releases.as_uri(),
            "HOMEBREW_RETRY_DELAY": "0",
        }
        self.env.pop("RUNNER_TEMP", None)
        self.env.pop("HOMEBREW_TAP_DEPLOY_KEY", None)
        self.git(self.root, "init", "--quiet", "--bare", "--initial-branch=main", str(self.remote))
        self.seed("Formula/subspace-beta.rb", "class SubspaceBeta < Formula\nend\n")
        self.release("v1.3.0", checksums("1.3.0", V130))

    def git(self, cwd: Path, *argv: str) -> str:
        done = subprocess.run(
            [GIT, *argv],
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
            cwd=cwd,
            env=self.env,
        )
        return done.stdout

    def seed(self, path: str, text: str) -> None:
        work = self.root / "seed"
        shutil.rmtree(work, ignore_errors=True)
        self.git(self.root, "clone", "--quiet", str(self.remote), str(work))
        (work / path).parent.mkdir(exist_ok=True)
        (work / path).write_text(text, encoding="utf-8")
        self.git(work, "add", path)
        self.git(
            work, "-c", "user.name=seed", "-c", "user.email=seed@example.com",
            "commit", "--quiet", "-m", "seed",
        )  # fmt: skip
        self.git(work, "push", "--quiet", "origin", "HEAD:main")

    def release(self, tag: str, text: str) -> None:
        (self.releases / tag).mkdir(parents=True, exist_ok=True)
        (self.releases / tag / "checksums.txt").write_text(text, encoding="utf-8")

    def publish(self, tag: str = "v1.3.0") -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [SH, str(PUBLISH), tag],
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
            env=self.env,
        )

    def head(self) -> str:
        return self.git(self.remote, "rev-parse", "main").strip()

    def commits(self) -> list[str]:
        return self.git(self.remote, "log", "--format=%s", "main").splitlines()

    def test_it_pushes_one_signed_off_commit_that_adds_only_the_formula(self) -> None:
        done = self.publish("v1.3.0")

        self.assertEqual(0, done.returncode, done.stderr)
        self.assertEqual(["compass 1.3.0", "seed"], self.commits())
        body = self.git(self.remote, "log", "-1", "--format=%an <%ae>%n%b", "main")
        self.assertIn("github-actions <actions@github.com>", body)
        self.assertIn("Signed-off-by: github-actions <actions@github.com>", body)
        self.assertEqual(
            [FORMULA], self.git(self.remote, "show", "--name-only", "--format=", "main").split()
        )
        self.assertEqual(GOLDEN_V130, self.git(self.remote, "show", f"main:{FORMULA}"))
        self.assertEqual(
            "class SubspaceBeta < Formula\nend\n",
            self.git(self.remote, "show", "main:Formula/subspace-beta.rb"),
        )

    def test_a_second_run_for_the_same_version_pushes_nothing(self) -> None:
        self.assertEqual(0, self.publish("v1.3.0").returncode)
        head = self.head()

        done = self.publish("v1.3.0")

        self.assertEqual(0, done.returncode, done.stderr)
        self.assertEqual(head, self.head())

    def test_the_next_release_replaces_the_formula_in_a_second_commit(self) -> None:
        self.assertEqual(0, self.publish("v1.3.0").returncode)
        self.release("v1.4.0", checksums("1.4.0"))

        done = self.publish("v1.4.0")

        self.assertEqual(0, done.returncode, done.stderr)
        self.assertEqual(["compass 1.4.0", "compass 1.3.0", "seed"], self.commits())
        self.assertIn("compass_1.4.0_", self.git(self.remote, "show", f"main:{FORMULA}"))

    def test_an_older_release_pushes_nothing(self) -> None:
        self.release("v1.4.0", checksums("1.4.0"))
        self.assertEqual(0, self.publish("v1.4.0").returncode)
        head = self.head()

        done = self.publish("v1.3.0")

        self.assertEqual(0, done.returncode, done.stderr)
        self.assertEqual(head, self.head())
        self.assertIn("compass_1.4.0_", self.git(self.remote, "show", f"main:{FORMULA}"))

    def test_a_rejected_push_is_retried_from_a_fresh_clone(self) -> None:
        # Another product's release landing between the clone and the push rejects the first
        # push. The hook stands in for it by refusing once.
        refused = self.root / "refused-once"
        hook = self.remote / "hooks" / "pre-receive"
        hook.write_text(
            f'#!/bin/sh\n[ -e "{refused}" ] && exit 0\ntouch "{refused}"\nexit 1\n',
            encoding="utf-8",
        )
        hook.chmod(0o755)

        done = self.publish("v1.3.0")

        self.assertEqual(0, done.returncode, done.stderr)
        self.assertTrue(refused.exists())
        self.assertEqual(["compass 1.3.0", "seed"], self.commits())

    def test_it_gives_up_after_three_rejections_rather_than_forcing(self) -> None:
        hook = self.remote / "hooks" / "pre-receive"
        hook.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
        hook.chmod(0o755)

        done = self.publish("v1.3.0")

        self.assertEqual(1, done.returncode)
        self.assertIn("rejected the push 3 times", done.stderr)
        self.assertEqual(["seed"], self.commits())

    def test_a_concurrent_tap_commit_is_kept_not_overwritten(self) -> None:
        # Another product's commit lands after our clone and before our push. A force push would
        # erase it; the retry must build on it. The python3 shim lands it once, at the point
        # between clone and push where the script first calls python3.
        other = self.root / "other"
        self.git(self.root, "clone", "--quiet", str(self.remote), str(other))
        (other / "Formula" / "other.rb").write_text(
            "class Other < Formula\nend\n", encoding="utf-8"
        )
        self.git(other, "add", "Formula/other.rb")
        self.git(
            other, "-c", "user.name=other", "-c", "user.email=other@example.com",
            "commit", "--quiet", "-m", "other",
        )  # fmt: skip
        landed = self.root / "landed-once"
        shim = self.root / "bin"
        shim.mkdir()
        (shim / "python3").write_text(
            "#!/bin/sh\n"
            f'if [ ! -e "{landed}" ]; then touch "{landed}"; '
            f'git -C "{other}" push --quiet "{self.remote}" HEAD:main; fi\n'
            f'exec "{sys.executable}" "$@"\n',
            encoding="utf-8",
        )
        (shim / "python3").chmod(0o755)
        self.env["PATH"] = f"{shim}{os.pathsep}{os.environ['PATH']}"

        done = self.publish("v1.3.0")

        self.assertEqual(0, done.returncode, done.stderr)
        self.assertTrue(landed.exists())
        self.assertEqual(["compass 1.3.0", "other", "seed"], self.commits())

    def test_it_pushes_nothing_when_the_release_has_no_checksums(self) -> None:
        done = self.publish("v1.9.0")

        self.assertNotEqual(0, done.returncode)
        self.assertIn("cannot fetch checksums.txt for v1.9.0", done.stderr)
        self.assertEqual(["seed"], self.commits())

    def test_it_pushes_nothing_when_the_checksums_are_not_the_four_archives(self) -> None:
        self.release("v1.5.0", "".join(checksums("1.5.0").splitlines(keepends=True)[:3]))

        done = self.publish("v1.5.0")

        self.assertNotEqual(0, done.returncode)
        self.assertEqual(["seed"], self.commits())

    def test_it_asks_for_the_key_before_any_network_call_on_an_ssh_remote(self) -> None:
        self.env["HOMEBREW_TAP_REMOTE"] = "git@github.com:spacedock-dev/homebrew-tap.git"

        done = self.publish("v1.3.0")

        self.assertEqual(1, done.returncode)
        self.assertIn("HOMEBREW_TAP_DEPLOY_KEY is empty", done.stderr)

    def test_it_refuses_a_missing_tag(self) -> None:
        done = subprocess.run(
            [SH, str(PUBLISH)],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
            env=self.env,
        )

        self.assertNotEqual(0, done.returncode)
        self.assertIn("usage", done.stderr)

    def test_it_leaves_no_scratch_directory_behind(self) -> None:
        self.assertEqual(0, self.publish("v1.3.0").returncode)
        self.assertEqual([], list(self.scratch.iterdir()))


if __name__ == "__main__":
    unittest.main()
