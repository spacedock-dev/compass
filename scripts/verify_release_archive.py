#!/usr/bin/env python3
"""Prove the exact release commit's `git archive` before `stable` can move.

Usage:
    python3 scripts/verify_release_archive.py --repo . --commit <final> \
        --verified <verified target> --version 0.2.0

The Release workflow verifies the frontend in a job that holds no credentials and
then bumps version fields in a job that does. The bump commit is therefore a tree
nobody built, and this is the check that it still ships what was verified. It runs
in the key-holding job with Python only: nothing here starts Node, pnpm or any
frontend dependency, and the archived Python runs with a throwaway home and an
empty PATH. That keeps Node out of reach; it is not credential isolation, because
the archived Python is still the job's user and first-party code from the verified
tree.

Checks, in order, each of which stops the release on failure:

    versions   the three owned manifests carry the tag's version, in parity
    changes    the release commit is the verified commit or its direct child and
               differs from it only in the `version` value of the owned manifests
    bundle     the React bundle files in the archive equal the verified blobs
    inventory  the archive's own runtime inventory check passes
    page       Python's integrity check accepts the archived React page, and the
               bytes it accepted are the verified document
    launch     the archived launcher starts and runs `--diagnose`

`launch` proves only that the launcher starts: `--diagnose` exits before it loads a
page. The `bundle` and `page` checks are what bind the served page to the verified
one.

The bundle is version-independent: build provenance carries no release version, so
a bump never changes it, and a changed bundle byte means a rebuild nobody verified.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

PLUGIN = "compass"
SKILL = "compass/skills/compass"
WEB = f"{SKILL}/compass_runtime/web"
BUNDLE_FILES = (
    f"{WEB}/react.html",
    f"{WEB}/react.integrity.json",
    f"{WEB}/react-licenses.txt",
    f"{WEB}/vendor/xterm.js",
    f"{WEB}/vendor/xterm.css",
)
FULL_SHA = re.compile(r"^[0-9a-f]{40}$")
SEMVER = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
# -I for the page probe: no user site, no PYTHON* variables, no script directory,
# so the only code that can import is the interpreter's own plus the archive path
# the probe inserts itself. server.py cannot use -I (it imports its sibling
# package from the script directory, which -I removes), so the launch uses the two
# flags that remove the same ambient inputs without removing that directory.
PAGE_FLAGS = ["-I"]
LAUNCH_FLAGS = ["-E", "-s"]
TIMEOUT = 120
GIT = shutil.which("git") or "git"
PAGE_PROBE = """
import hashlib, json, sys
sys.path.insert(0, sys.argv[1])
from compass_runtime.web import page
data = page.load_frontend_page()
print(json.dumps({"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}))
"""


def annotation(text: str) -> str:
    """One workflow-command line: a newline in the text must not start a second command."""
    escaped = text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    return f"::error::{escaped}"


class ArchiveError(Exception):
    """A release archive failed a check; the message is safe to print."""


@dataclass
class Report:
    checks: list[str] = field(default_factory=list)


def git_bytes(repo: Path, *args: str) -> bytes:
    result = subprocess.run(  # noqa: S603 -- argv is a list built from validated values
        [GIT, "-C", str(repo), *args], capture_output=True, check=False, timeout=TIMEOUT
    )
    if result.returncode:
        detail = result.stderr.decode("utf-8", "replace").strip()
        message = f"git {args[0]} failed: {detail}"
        raise ArchiveError(message)
    return result.stdout


def git_text(repo: Path, *args: str) -> str:
    return git_bytes(repo, *args).decode("utf-8").strip()


def full_sha(repo: Path, name: str, value: str) -> str:
    if not FULL_SHA.fullmatch(value):
        message = f"{name} must be a full lowercase commit SHA"
        raise ArchiveError(message)
    return git_text(repo, "rev-parse", "--verify", f"{value}^{{commit}}")


def isolated_env(home: Path) -> dict[str, str]:
    """Nothing ambient: no PATH entry to resolve Node, no real home, no secrets."""
    empty = home / "no-executables"
    empty.mkdir(parents=True, exist_ok=True)
    return {
        "PATH": str(empty),
        "HOME": str(home),
        "USERPROFILE": str(home),
        "COMPASS_HOME": str(home / "state"),
        "PYTHONNOUSERSITE": "1",
        "LC_ALL": "C.UTF-8",
    }


def run_python(
    home: Path, args: list[str], cwd: Path | None = None
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(  # noqa: S603 -- the interpreter running this script
            [sys.executable, *args],
            capture_output=True,
            text=True,
            check=False,
            cwd=cwd or home,
            env=isolated_env(home),
            timeout=TIMEOUT,
        )
    except subprocess.TimeoutExpired as exc:
        message = f"python {' '.join(args[:2])} exceeded {TIMEOUT} seconds"
        raise ArchiveError(message) from exc


def tail(result: subprocess.CompletedProcess[str]) -> str:
    return (result.stdout + result.stderr).strip()[-600:]


def _safe_target(name: str, root: Path) -> Path:
    pure = PurePosixPath(name)
    if pure.is_absolute() or ".." in pure.parts or not pure.parts:
        message = f"archive member {name!r} escapes the extraction directory"
        raise ArchiveError(message)
    return root.joinpath(*pure.parts)


def extract_archive(archive: Path, destination: Path) -> None:
    """Extract regular files and directories only; refuse every link and special member.

    The archive is of a repository commit, which can hold a hostile member, and
    `tarfile.extractall` filters differ across the supported Python floor, so the
    policy is spelled out here. Links are refused outright rather than checked
    lexically: a chain of individually harmless symlinks (`a -> .`, `a/b -> ..`)
    walks out of the root, and nothing this proof reads needs one. `build_archive`
    leaves out the paths that carry the repository's own links.
    """
    root = destination.resolve()
    with tarfile.open(archive) as tar:
        members = tar.getmembers()
        for member in members:
            _safe_target(member.name, root)
            if not (member.isfile() or member.isdir()):
                message = f"archive member {member.name!r} is not a regular file or directory"
                raise ArchiveError(message)
        for member in members:
            target = _safe_target(member.name, root)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.parent.resolve().is_relative_to(root):
                message = f"archive member {member.name!r} resolves outside the tree"
                raise ArchiveError(message)
            source = tar.extractfile(member)
            if source is None:  # pragma: no cover -- isfile() members always open
                message = f"archive member {member.name!r} is unreadable"
                raise ArchiveError(message)
            target.write_bytes(source.read())
            target.chmod(0o755 if member.mode & 0o111 else 0o644)


ARCHIVE_PATHS = ("compass", "compass-gemini", "scripts")


def build_archive(repo: Path, commit: str, archive: Path) -> None:
    """`git archive` of the exact commit, limited to what the smoke reads.

    The repository root carries relative symlinks (the Codex skill aliases) that the
    extraction policy refuses; none of them is under these three trees.
    """
    git_bytes(repo, "archive", "--format=tar", "-o", str(archive), commit, "--", *ARCHIVE_PATHS)


def verified_manifest_paths(repo: Path, verified: str, scratch: Path) -> list[str]:
    """The paths a bump may touch, read from the verified tree's own script.

    Taken from the verified commit, not the release commit: a release commit that
    widened the list in order to change more would otherwise bless itself.
    """
    script = scratch / "verified-bump" / "scripts" / "bump_version.py"
    script.parent.mkdir(parents=True)
    script.write_bytes(git_bytes(repo, "show", f"{verified}:scripts/bump_version.py"))
    home = scratch / "home"
    home.mkdir(exist_ok=True)
    result = run_python(home, [*PAGE_FLAGS, str(script), "--paths"])
    if result.returncode:
        message = f"the verified tree's bump script could not list its paths: {tail(result)}"
        raise ArchiveError(message)
    return result.stdout.split()


def check_versions(tree: Path, paths: list[str], version: str) -> None:
    found: dict[str, str] = {}
    for relative in paths:
        try:
            manifest = json.loads((tree / relative).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            message = f"{relative} is missing or unreadable in the archive"
            raise ArchiveError(message) from exc
        found[relative] = str(manifest.get("version")) if isinstance(manifest, dict) else ""
    if len(set(found.values())) != 1:
        message = f"version fields are not in parity: {found}"
        raise ArchiveError(message)
    carried = next(iter(found.values()))
    if carried != version:
        message = f"manifests carry {carried} but the tag's version is {version}"
        raise ArchiveError(message)


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            message = f"duplicate JSON key {key!r}"
            raise ValueError(message)
        value[key] = item
    return value


def _json_at(repo: Path, rev: str, relative: str) -> dict[str, object]:
    try:
        value = json.loads(
            git_bytes(repo, "cat-file", "blob", f"{rev}:{relative}"),
            object_pairs_hook=_unique_object,
        )
    except (ArchiveError, ValueError) as exc:
        message = f"{relative} is missing or not JSON at {rev[:12]}: {exc}"
        raise ArchiveError(message) from exc
    if not isinstance(value, dict):
        message = f"{relative} is not a JSON object at {rev[:12]}"
        raise ArchiveError(message)
    return value


def check_changes(repo: Path, commit: str, verified: str, allowed: list[str]) -> None:
    """The release commit may change the owned manifests' `version` value and nothing else."""
    if commit != verified and git_text(repo, "rev-parse", f"{commit}^") != verified:
        message = "the release commit must be the verified commit or its direct child"
        raise ArchiveError(message)
    raw = git_bytes(repo, "diff", "--raw", "-z", "--no-renames", verified, commit)
    fields = raw.split(b"\0")[:-1]
    changes = [(fields[i].split(), fields[i + 1].decode("utf-8")) for i in range(0, len(fields), 2)]
    changed = [relative for _, relative in changes]
    extra = sorted(set(changed) - set(allowed))
    if extra:
        message = f"release commit changed files beyond the version manifests: {extra}"
        raise ArchiveError(message)
    for metadata, relative in changes:
        old_mode, new_mode = metadata[0].removeprefix(b":"), metadata[1]
        if old_mode != new_mode:
            message = f"release commit changed the file mode of {relative}"
            raise ArchiveError(message)
        before = _json_at(repo, verified, relative)
        after = _json_at(repo, commit, relative)
        before.pop("version", None)
        after.pop("version", None)
        if before != after:
            message = f"release commit changed {relative} beyond the version value"
            raise ArchiveError(message)


def check_bundle(repo: Path, tree: Path, verified: str) -> None:
    for relative in BUNDLE_FILES:
        expected = hashlib.sha256(git_bytes(repo, "cat-file", "blob", f"{verified}:{relative}"))
        try:
            actual = hashlib.sha256((tree / relative).read_bytes())
        except OSError as exc:
            message = f"{relative} is missing from the archive"
            raise ArchiveError(message) from exc
        if actual.hexdigest() != expected.hexdigest():
            message = f"{relative} changed after verification"
            raise ArchiveError(message)


def check_inventory(tree: Path, home: Path) -> None:
    result = run_python(
        home,
        [
            *PAGE_FLAGS,
            str(tree / "scripts/validate_plugins.py"),
            "--runtime-files",
            str(tree / PLUGIN),
        ],
    )
    if result.returncode:
        message = f"runtime inventory failed: {tail(result)}"
        raise ArchiveError(message)


def check_page(repo: Path, tree: Path, verified: str, home: Path) -> None:
    result = run_python(home, [*PAGE_FLAGS, "-c", PAGE_PROBE, str(tree / SKILL)])
    if result.returncode:
        message = f"react page failed its integrity check: {tail(result)}"
        raise ArchiveError(message)
    try:
        served = json.loads(result.stdout.strip().splitlines()[-1])["sha256"]
    except (IndexError, KeyError, ValueError) as exc:
        message = f"react page probe returned no digest: {tail(result)}"
        raise ArchiveError(message) from exc
    expected = hashlib.sha256(git_bytes(repo, "cat-file", "blob", f"{verified}:{BUNDLE_FILES[0]}"))
    if served != expected.hexdigest():
        message = "react page integrity check passed on bytes other than the verified document"
        raise ArchiveError(message)


def check_launch(tree: Path, home: Path) -> None:
    result = run_python(home, [*LAUNCH_FLAGS, str(tree / SKILL / "server.py"), "--diagnose"])
    if result.returncode:
        message = f"archived launcher failed --diagnose: {tail(result)}"
        raise ArchiveError(message)


def verify_archive(repo: Path, commit: str, verified: str, version: str) -> Report:
    """Run every check against `git archive <commit>`; raise ArchiveError on the first failure."""
    if not SEMVER.fullmatch(version):
        message = f"version {version!r} is not strict semver"
        raise ArchiveError(message)
    commit = full_sha(repo, "commit", commit)
    verified = full_sha(repo, "verified", verified)
    scratch = Path(tempfile.mkdtemp(prefix="compass-release-archive-"))
    report = Report()
    try:
        archive = scratch / "release.tar"
        build_archive(repo, commit, archive)
        tree = scratch / "tree"
        tree.mkdir()
        extract_archive(archive, tree)
        home = scratch / "home"
        home.mkdir()
        paths = verified_manifest_paths(repo, verified, scratch)
        check_versions(tree, paths, version)
        report.checks.append("versions")
        check_changes(repo, commit, verified, paths)
        report.checks.append("changes")
        check_bundle(repo, tree, verified)
        report.checks.append("bundle")
        check_inventory(tree, home)
        report.checks.append("inventory")
        check_page(repo, tree, verified, home)
        report.checks.append("page")
        check_launch(tree, home)
        report.checks.append("launch")
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--repo", type=Path, default=Path())
    parser.add_argument("--commit", required=True)
    parser.add_argument("--verified", required=True)
    parser.add_argument("--version", required=True)
    args = parser.parse_args(argv)
    try:
        report = verify_archive(args.repo, args.commit, args.verified, args.version)
    except ArchiveError as exc:
        print(annotation(f"release archive proof failed: {exc}"))
        return 1
    print(f"Release archive proof passed: {', '.join(report.checks)}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
