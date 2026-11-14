"""The marketplace stamp: what it writes, what it refuses, and the push it makes.

`update_marketplace.py` is called directly. `publish-marketplace.sh` runs for real against a
local bare repository standing in for spacedock-dev/marketplace, which exercises the clone,
the commit and the push and needs no key: the script asks for one only of an SSH remote.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import TYPE_CHECKING, Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import update_marketplace

if TYPE_CHECKING:
    from tests import publish_fakes
else:
    import publish_fakes

SCRIPTS = Path(__file__).resolve().parents[1]
PUBLISH = SCRIPTS / "publish-marketplace.sh"
SH = shutil.which("sh") or "sh"
GIT = shutil.which("git") or "git"
INDEX = ".claude-plugin/marketplace.json"


def entry(version: str = "0.4.2", **source: str) -> dict[str, Any]:
    return {
        "name": "compass",
        "source": {
            "source": "git-subdir",
            "url": "https://github.com/spacedock-dev/compass.git",
            "path": "compass",
            "ref": "stable",
            **source,
        },
        "description": "Agnostic agent cartography — a live local dashboard",
        "version": version,
        "category": "monitoring",
    }


def sibling() -> dict[str, Any]:
    return {"name": "behavior-diff", "version": "0.4.6", "source": {"ref": "v0.4.6"}}


def render(plugins: list[dict[str, Any]]) -> str:
    return (
        json.dumps({"name": "spacedock", "plugins": plugins}, indent=2, ensure_ascii=False) + "\n"
    )


class UpdateMarketplaceTest(unittest.TestCase):
    def index(self, plugins: list[dict[str, Any]]) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "marketplace.json"
        path.write_text(render(plugins), encoding="utf-8")
        return path

    def test_it_stamps_the_version_and_touches_nothing_else(self) -> None:
        path = self.index([sibling(), entry("0.4.2"), entry("9.9.9", ref="x") | {"name": "other"}])
        before = json.loads(path.read_text(encoding="utf-8"))

        message = update_marketplace.stamp(path, "1.0.0")

        after = json.loads(path.read_text(encoding="utf-8"))
        before["plugins"][1]["version"] = "1.0.0"
        self.assertEqual(before, after)
        self.assertEqual("marketplace now lists compass 1.0.0", message)

    def test_the_file_keeps_its_shape_so_a_stamp_is_a_one_line_diff(self) -> None:
        path = self.index([sibling(), entry("0.4.2")])

        update_marketplace.stamp(path, "1.0.0")

        self.assertEqual(render([sibling(), entry("1.0.0")]), path.read_text(encoding="utf-8"))

    def test_the_same_version_is_left_alone(self) -> None:
        path = self.index([entry("1.0.0")])
        before = path.read_bytes()

        self.assertEqual(
            "marketplace already lists compass 1.0.0", update_marketplace.stamp(path, "1.0.0")
        )
        self.assertEqual(before, path.read_bytes())

    def test_an_older_release_never_rolls_the_listing_back(self) -> None:
        path = self.index([entry("1.1.0")])
        before = path.read_bytes()

        message = update_marketplace.stamp(path, "1.0.9")

        self.assertIn("newer than 1.0.9", message)
        self.assertEqual(before, path.read_bytes())

    def test_versions_compare_as_numbers_not_text(self) -> None:
        path = self.index([entry("1.9.0")])

        update_marketplace.stamp(path, "1.10.0")

        self.assertEqual(
            "1.10.0", json.loads(path.read_text(encoding="utf-8"))["plugins"][0]["version"]
        )

    def test_a_listed_version_that_is_not_semver_is_replaced(self) -> None:
        path = self.index([entry("1.0.0-beta.1")])

        update_marketplace.stamp(path, "1.0.0")

        self.assertEqual(
            "1.0.0", json.loads(path.read_text(encoding="utf-8"))["plugins"][0]["version"]
        )

    def test_it_refuses_an_entry_that_is_not_the_one_the_release_publishes_to(self) -> None:
        for name, plugins in {
            "no entry": [sibling()],
            "two entries": [entry(), entry()],
            "pinned to a tag": [entry(ref="v0.4.2")],
            "wrong path": [entry(path="cargento")],
        }.items():
            with self.subTest(name):
                path = self.index(plugins)
                before = path.read_bytes()
                with self.assertRaises(SystemExit):
                    update_marketplace.stamp(path, "1.0.0")
                self.assertEqual(before, path.read_bytes())

    def test_it_refuses_anything_but_strict_semver(self) -> None:
        path = self.index([entry()])
        for version in ("v1.0.0", "1.0", "01.0.0", "1.0.0-rc.1", "1.0.0 ", ""):
            with self.subTest(version=version), self.assertRaises(SystemExit):
                update_marketplace.stamp(path, version)

    def test_it_refuses_an_index_it_cannot_read(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        for name, body in {"missing": None, "not json": "{", "no list": '{"plugins": 3}'}.items():
            path = Path(tmp.name) / f"{name}.json"
            if body is not None:
                path.write_text(body, encoding="utf-8")
            with self.subTest(name), self.assertRaises(SystemExit):
                update_marketplace.stamp(path, "1.0.0")

    def test_the_command_takes_exactly_an_index_and_a_version(self) -> None:
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(2, update_marketplace.main([]))
            self.assertEqual(2, update_marketplace.main(["only-one"]))

    def test_the_command_reports_what_it_did(self) -> None:
        path = self.index([entry("0.4.2")])

        done = subprocess.run(
            [sys.executable, "-I", str(SCRIPTS / "update_marketplace.py"), str(path), "1.0.0"],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )

        self.assertEqual(0, done.returncode, done.stderr)
        self.assertEqual("marketplace now lists compass 1.0.0\n", done.stdout)


class PublishMarketplaceTest(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.scratch = self.root / "scratch"
        self.scratch.mkdir()
        self.remote = self.root / "marketplace.git"
        self.env = {
            **os.environ,
            # The developer's own git configuration (signing, hooks) must not decide a test.
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_SYSTEM": os.devnull,
            "TMPDIR": str(self.scratch),
            "MARKETPLACE_REMOTE": str(self.remote),
            "MARKETPLACE_RETRY_DELAY": "0",
        }
        self.env.pop("RUNNER_TEMP", None)
        self.env.pop("MARKETPLACE_DEPLOY_KEY", None)
        self.git(self.root, "init", "--quiet", "--bare", "--initial-branch=main", str(self.remote))
        self.seed([sibling(), entry("0.4.2")])

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

    def seed(self, plugins: list[dict[str, Any]]) -> None:
        work = self.root / "seed"
        shutil.rmtree(work, ignore_errors=True)
        self.git(self.root, "clone", "--quiet", str(self.remote), str(work))
        (work / INDEX).parent.mkdir(exist_ok=True)
        (work / INDEX).write_text(render(plugins), encoding="utf-8")
        self.git(work, "add", INDEX)
        self.git(
            work, "-c", "user.name=seed", "-c", "user.email=seed@example.com",
            "commit", "--quiet", "-m", "seed",
        )  # fmt: skip
        self.git(work, "push", "--quiet", "origin", "HEAD:main")

    def publish(self, version: str = "1.0.0") -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [SH, str(PUBLISH), version],
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
            env=self.env,
        )

    def listed(self) -> dict[str, str]:
        raw = self.git(self.remote, "show", f"main:{INDEX}")
        return {p["name"]: p["version"] for p in json.loads(raw)["plugins"]}

    def commits(self) -> list[str]:
        return self.git(self.remote, "log", "--format=%s", "main").splitlines()

    def test_it_pushes_one_signed_off_commit_that_changes_only_the_version(self) -> None:
        done = self.publish("1.0.0")

        self.assertEqual(0, done.returncode, done.stderr)
        self.assertEqual({"behavior-diff": "0.4.6", "compass": "1.0.0"}, self.listed())
        self.assertEqual(["compass 1.0.0", "seed"], self.commits())
        body = self.git(self.remote, "log", "-1", "--format=%an <%ae>%n%b", "main")
        self.assertIn("github-actions <actions@github.com>", body)
        self.assertIn("Signed-off-by: github-actions <actions@github.com>", body)
        self.assertEqual(
            [INDEX], self.git(self.remote, "show", "--name-only", "--format=", "main").split()
        )
        self.assertEqual(
            render([sibling(), entry("1.0.0")]), self.git(self.remote, "show", f"main:{INDEX}")
        )

    def test_a_second_run_for_the_same_version_pushes_nothing(self) -> None:
        self.assertEqual(0, self.publish("1.0.0").returncode)
        head = self.git(self.remote, "rev-parse", "main")

        done = self.publish("1.0.0")

        self.assertEqual(0, done.returncode, done.stderr)
        self.assertEqual(head, self.git(self.remote, "rev-parse", "main"))

    def test_an_older_release_pushes_nothing(self) -> None:
        self.assertEqual(0, self.publish("1.1.0").returncode)
        head = self.git(self.remote, "rev-parse", "main")

        done = self.publish("1.0.0")

        self.assertEqual(0, done.returncode, done.stderr)
        self.assertEqual(head, self.git(self.remote, "rev-parse", "main"))
        self.assertEqual("1.1.0", self.listed()["compass"])

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

        done = self.publish("1.0.0")

        self.assertEqual(0, done.returncode, done.stderr)
        self.assertTrue(refused.exists())
        self.assertEqual("1.0.0", self.listed()["compass"])
        self.assertEqual(["compass 1.0.0", "seed"], self.commits())

    def test_it_gives_up_after_three_rejections_rather_than_forcing(self) -> None:
        hook = self.remote / "hooks" / "pre-receive"
        hook.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
        hook.chmod(0o755)

        done = self.publish("1.0.0")

        self.assertEqual(1, done.returncode)
        self.assertIn("rejected the push 3 times", done.stderr)
        self.assertEqual(["seed"], self.commits())

    def test_it_pushes_nothing_when_the_entry_is_not_the_stable_listing(self) -> None:
        self.seed([sibling(), entry("0.4.2", ref="v0.4.2")])

        done = self.publish("1.0.0")

        self.assertNotEqual(0, done.returncode)
        self.assertEqual(["seed", "seed"], self.commits())

    def test_it_asks_for_the_key_before_any_network_call_on_an_ssh_remote(self) -> None:
        self.env["MARKETPLACE_REMOTE"] = "git@github.com:spacedock-dev/marketplace.git"

        done = self.publish("1.0.0")

        self.assertEqual(1, done.returncode)
        self.assertIn("MARKETPLACE_DEPLOY_KEY is empty", done.stderr)

    def test_the_ssh_key_paths_reach_ssh_whole_whatever_the_scratch_path_holds(self) -> None:
        # git runs GIT_SSH_COMMAND through the shell. A scratch path spliced into it would be
        # split at the space and the `;` would end the ssh command; passed through the
        # environment and quoted, it arrives as one argument. curl, jq and ssh are shims.
        log = self.root / "log"
        publish_fakes.install(self.root / "bin", log)
        odd = self.root / "scratch dir;x"
        odd.mkdir()
        self.env.update(
            {
                "PATH": f"{self.root / 'bin'}{os.pathsep}{self.env['PATH']}",
                "FAKE_LOG": str(log),
                "TMPDIR": str(odd),
                "MARKETPLACE_REMOTE": "git@github.com:spacedock-dev/marketplace.git",
                "MARKETPLACE_DEPLOY_KEY": "placeholder, not a key",
            }
        )

        done = self.publish("1.0.0")

        self.assertNotEqual(0, done.returncode)
        argv = publish_fakes.ssh_argv(log)
        self.assertIn("-i", argv, done.stderr)
        identity = argv[argv.index("-i") + 1]
        self.assertTrue(identity.startswith(f"{odd}/marketplace."), identity)
        self.assertTrue(identity.endswith("/key"), identity)
        options = [argv[i + 1] for i, arg in enumerate(argv) if arg == "-o"]
        known = identity.removesuffix("/key") + "/known_hosts"
        for option in (
            "IdentitiesOnly=yes",
            "IdentityAgent=none",
            "StrictHostKeyChecking=yes",
            f"UserKnownHostsFile={known}",
        ):
            self.assertIn(option, options)
        self.assertEqual(
            ["identity file present", "known_hosts present"], publish_fakes.ssh_files(log)
        )
        (meta,) = publish_fakes.curl_calls(log)
        self.assertEqual("=https", meta[meta.index("--proto") + 1])
        self.assertIn("--tlsv1.2", meta)
        self.assertEqual([], list(odd.iterdir()))

    def test_it_refuses_a_missing_version(self) -> None:
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
        self.assertEqual(0, self.publish("1.0.0").returncode)
        self.assertEqual([], list(self.scratch.iterdir()))


if __name__ == "__main__":
    unittest.main()
