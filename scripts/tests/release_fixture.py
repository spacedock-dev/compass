"""Temporary repositories for the release tests.

The shape is the release's real one: a bare "origin", a working clone of it, and
a tree that carries the shipped plugin, the version manifests and the release
scripts. The tree is the repository's own plugin, including declared runtime
additions, so the archive proof runs against the real runtime inventory and the real React bundle rather than a
stand-in that could pass for the wrong reason. Nothing here touches the real
remote, a real tag or a version field in the working tree.
"""

from __future__ import annotations

import atexit
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING
from unittest import mock

from release_transition import BOT_EMAIL, BOT_NAME
from validate_plugins import COMPASS_RUNTIME_FILES

if TYPE_CHECKING:
    import unittest

GIT = shutil.which("git") or "git"
REPO = Path(__file__).resolve().parents[2]
SCRIPTS = (
    "bump_version.py",
    "validate_plugins.py",
    "release_transition.py",
    "verify_release_archive.py",
)
MANIFESTS = (
    "compass/.claude-plugin/plugin.json",
    "compass/.codex-plugin/plugin.json",
    "compass-gemini/gemini-extension.json",
)
WEB = "compass/skills/compass/compass_runtime/web"
BASE_VERSION = "0.1.0"
IDENTITY = (
    "-c",
    "user.name=Rehearsal",
    "-c",
    "user.email=rehearsal@example.invalid",
    "-c",
    "commit.gpgsign=false",
    "-c",
    "tag.gpgsign=false",
)

# Every git process in these tests, including the ones the scripts under test start,
# inherits this. `gc --auto` and `maintenance run --auto` detach and keep writing
# into a repository after the command that started them returns, which races both a
# neighbouring clone of the shared template and the per-test temp-dir cleanup. None
# of the figures measured here depends on packing, so nothing is lost by switching
# it off.
QUIET_GIT = {
    "GIT_CONFIG_COUNT": "3",
    "GIT_CONFIG_KEY_0": "gc.auto",
    "GIT_CONFIG_VALUE_0": "0",
    "GIT_CONFIG_KEY_1": "maintenance.auto",
    "GIT_CONFIG_VALUE_1": "false",
    "GIT_CONFIG_KEY_2": "core.fsmonitor",
    "GIT_CONFIG_VALUE_2": "false",
}

_template: Path | None = None
_scratch: list[Path] = []


def git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        [GIT, *IDENTITY, "-C", str(cwd), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        message = f"git {' '.join(args)} failed in {cwd}: {result.stderr.strip()}"
        raise AssertionError(message)
    return result.stdout.strip()


def write_manifest_version(root: Path, version: str) -> None:
    for relative in MANIFESTS:
        path = root / relative
        data = json.loads(path.read_text(encoding="utf-8"))
        data["version"] = version
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _build_template() -> Path:
    root = Path(tempfile.mkdtemp(prefix="release-template-"))
    _scratch.append(root)
    tracked = subprocess.run(
        [GIT, "-C", str(REPO), "ls-files", "compass", "compass-gemini"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()
    # A builder must prove a new runtime module before staging or committing it.
    # Keep the archive proof's explicit inventory intact in that rehearsal too.
    runtime = {f"compass/{relative}" for relative in COMPASS_RUNTIME_FILES}
    for relative in sorted(set(tracked) | runtime):
        source = REPO / relative
        if source.is_symlink() or not source.is_file():
            continue
        destination = root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    (root / "scripts").mkdir()
    for name in SCRIPTS:
        source = REPO / "scripts" / name
        if source.is_file():
            shutil.copy2(source, root / "scripts" / name)
    write_manifest_version(root, BASE_VERSION)
    # The real repository pins its generated artifacts to LF in .gitattributes, which this copy does not carry.
    # Without it a Windows runner's core.autocrlf rewrites react.html to CRLF in `git archive` and in every
    # checkout, so the archive proof sees bytes that differ from the verified blob.
    (root / ".gitattributes").write_text("* -text\n", encoding="utf-8")
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "core.autocrlf", "false")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "initial")
    git(root, "tag", f"v{BASE_VERSION}")
    return root


def template() -> Path:
    """Built once per process; each test clones it, which is a hardlink copy."""
    global _template  # noqa: PLW0603 -- one lazily built read-only fixture per process
    if _template is None:
        _template = _build_template()
    return _template


@atexit.register
def _cleanup() -> None:
    for path in _scratch:
        shutil.rmtree(path, ignore_errors=True)


class Fixture:
    """One bare origin and one working clone, both under a per-test temp dir."""

    def __init__(self, case: unittest.TestCase) -> None:
        # Scoped to the test: other modules in the same process keep their own git.
        patch = mock.patch.dict(os.environ, QUIET_GIT)
        patch.start()
        case.addCleanup(patch.stop)
        self.root = Path(tempfile.mkdtemp(prefix=f"release-rehearsal-{os.getpid()}-"))
        case.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.origin = self.root / "origin.git"
        self.work = self.root / "work"
        git(self.root, "clone", "-q", "--no-hardlinks", "--bare", str(template()), str(self.origin))
        git(self.root, "clone", "-q", str(self.origin), str(self.work))

    def sync(self) -> None:
        """Local main becomes origin's main, as a fresh checkout of it would be."""
        git(self.work, "fetch", "-q", "origin", "main", "--tags", "--force")
        git(self.work, "checkout", "-q", "-B", "main", "origin/main")

    def commit(
        self,
        message: str,
        files: dict[str, str | bytes] | None = None,
        *,
        push: bool = True,
        branch: str = "main",
    ) -> str:
        """A commit on origin's main, pushed unless told otherwise; `branch` commits elsewhere."""
        if branch == "main":
            self.sync()
        else:
            git(self.work, "checkout", "-q", branch)
        for relative, content in (files or {"notes.txt": message}).items():
            path = self.work / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(content, bytes):
                path.write_bytes(content)
            else:
                path.write_text(content, encoding="utf-8")
        git(self.work, "add", "-A")
        git(self.work, "commit", "-q", "-m", message)
        if push:
            git(self.work, "push", "-q", "origin", "main")
        return git(self.work, "rev-parse", "HEAD")

    def set_version(self, version: str) -> str:
        """Edit the manifests the way a hand edit would; only fixtures may."""
        write_manifest_version(self.work, version)
        return self.commit(f"fixture: manifests at {version}", files={})

    def release_commit(
        self,
        tag: str,
        version: str,
        *,
        committer: tuple[str, str] = (BOT_NAME, BOT_EMAIL),
        extra: dict[str, str] | None = None,
    ) -> str:
        """A pushed commit shaped like the workflow's bump: the manifests only, by the bot.

        `committer` and `extra` (more files in the same commit) build the shapes a resume
        must refuse.
        """
        self.sync()
        write_manifest_version(self.work, version)
        for relative, content in (extra or {}).items():
            path = self.work / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        name, email = committer
        git(self.work, "add", "-A")
        git(
            self.work, "-c", f"user.name={name}", "-c", f"user.email={email}",
            "commit", "-q", "-m", f"chore(release): {tag}",
        )  # fmt: skip
        git(self.work, "push", "-q", "origin", "main")
        return git(self.work, "rev-parse", "HEAD")

    def tag(self, name: str, rev: str = "HEAD", *, push: bool = True) -> str:
        git(self.work, "tag", "-f", name, rev)
        if push:
            git(self.work, "push", "-q", "--force", "origin", f"refs/tags/{name}")
        return git(self.work, "rev-parse", f"{name}^{{commit}}")

    def origin_rev(self, ref: str) -> str | None:
        result = subprocess.run(
            [GIT, "-C", str(self.origin), "rev-parse", "--verify", "-q", f"{ref}^{{commit}}"],
            capture_output=True,
            text=True,
            check=False,
        )
        return result.stdout.strip() or None

    def fetch(self) -> None:
        git(self.work, "fetch", "-q", "origin", "main", "--tags", "--force")

    def origin_snapshot(self) -> dict[str, str]:
        out = git(self.origin, "for-each-ref", "--format=%(refname) %(objectname)")
        pairs = (line.split(" ", 1) for line in out.splitlines())
        return dict(pairs)
