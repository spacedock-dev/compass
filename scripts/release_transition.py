#!/usr/bin/env python3
"""The Release workflow's decisions, as small functions a test can break.

Usage (each subcommand is one workflow step; see .github/workflows/release.yml):

    python3 scripts/release_transition.py resolve --tag v0.2.0 --github-output "$GITHUB_OUTPUT"
    python3 scripts/release_transition.py assert-head --expected <sha>
    python3 scripts/release_transition.py assert-checkout --mode fresh --target <sha> \
        --verified <sha> --tag v0.2.0
    python3 scripts/release_transition.py bump --tag v0.2.0
    python3 scripts/release_transition.py commit-bump --tag v0.2.0
    python3 scripts/release_transition.py final --mode fresh --target <sha>
    python3 scripts/release_transition.py push-bump | move-tag | advance-stable \
        --tag v0.2.0 --final <sha>
    python3 scripts/release_transition.py rehearse --repo <tmp clone> --tag v0.2.0 --dry-run

The decisions used to be inline shell in the workflow, where nothing could
exercise them: a `exit` inside an awk pipe under `pipefail` once broke resuming and
left a failed run on every release. Standard library only, because the
credential-free `resolve` job runs it before any dependency is installed.

Why the release is split around a target SHA. The frontend is verified (rebuilt and
compared, linted, tested) in a job that holds no credentials, and the version bump
is pushed by a job that holds the deploy key. `resolve` therefore fixes one commit
before anything runs. A fresh release's target is the main tip captured once; a
resumed release's target is the existing release commit. The verified job checks
out exactly that SHA, and the privileged job refuses to publish unless its own
checkout is that SHA, so a main that moved while the frontend was being verified
fails safely instead of publishing a tree nobody verified. Re-running resolves a new
target and verifies it.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import bump_version
import verify_release_archive

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

SEMVER = bump_version.SEMVER_RE
annotation = verify_release_archive.annotation
FULL_SHA = re.compile(r"^[0-9a-f]{40}$")
TRUTH_MANIFEST = bump_version.TRUTH.relative_to(bump_version.ROOT).as_posix()
TAG_GLOBS = ("v[0-9]*.[0-9]*.[0-9]*", "[0-9]*.[0-9]*.[0-9]*")
BOT_NAME = "github-actions[bot]"
BOT_EMAIL = "41898282+github-actions[bot]@users.noreply.github.com"
GIT = shutil.which("git") or "git"
MODES = ("fresh", "resume")
# A tracked file at the repository root on main. Its presence is the hold, its text is the
# reason and what lifts it, and removing it in a reviewed pull request lifts it. Read from
# main's tree rather than the checkout so that a stray file does not hold a release and
# deleting it from a checkout does not lift one.
HOLD_FILE = "RELEASE_HOLD"
PHASES = (
    "resolve",
    "verify",
    "checkout",
    "bump",
    "archive",
    "push-bump",
    "move-tag",
    "stable",
)


class ReleaseError(Exception):
    """A release precondition failed; the message is safe to print and says what to do."""


@dataclass(frozen=True)
class Resolution:
    tag: str
    version: str
    mode: str
    target: str
    release_commit: str
    main_tip: str
    # False when a higher release tag exists, so publishing this one must not take the
    # "Latest" badge from it: GitHub marks a new release latest unless told otherwise.
    latest: bool = True

    def outputs(self) -> dict[str, str]:
        return {
            "mode": self.mode,
            "version": self.version,
            "target": self.target,
            "latest": "true" if self.latest else "false",
        }


@dataclass(frozen=True)
class Outcome:
    mode: str
    target: str
    final: str
    last_phase: str


def run(argv: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    """Every command this module starts. Arguments are a list, never a shell string."""
    return subprocess.run(  # noqa: S603 -- argv is built here from validated values
        argv, capture_output=True, text=True, check=False, cwd=cwd
    )


def run_git(repo: Path, *args: str, check: bool = True) -> str:
    result = run([GIT, "-C", str(repo), *args])
    if check and result.returncode:
        message = f"git {args[0]} failed: {result.stderr.strip() or result.stdout.strip()}"
        raise ReleaseError(message)
    return result.stdout.strip() if not result.returncode else ""


def parse_tag(tag: str) -> tuple[str, tuple[int, int, int]]:
    """Return (version, numeric triple) for a `vX.Y.Z` or `X.Y.Z` tag, or refuse it."""
    version = tag.removeprefix("v")
    match = SEMVER.fullmatch(version)
    if not match:
        message = f"tag {tag!r} is not strict semver"
        raise ReleaseError(message)
    major, minor, patch = match.groups()
    return version, (int(major), int(minor), int(patch))


def _triple(tag: str) -> tuple[int, int, int] | None:
    try:
        return parse_tag(tag)[1]
    except ReleaseError:
        return None


def check_monotonic(tag: str, existing: list[str]) -> None:
    """No back-tagging: strictly greater than every other release tag, numerically."""
    new = parse_tag(tag)[1]
    for name in existing:
        if name == tag:
            continue
        old = _triple(name)
        if old is not None and old >= new:
            message = (
                f"tag {tag} is not strictly greater than existing release tag {name} "
                "- back-tagging is not allowed"
            )
            raise ReleaseError(message)


def check_unique_version(tag: str, existing: list[str]) -> None:
    """One release per version: `0.2.0` and `v0.2.0` would be two tags for one release.

    A fresh release already fails `check_monotonic` on the other spelling, which counts as
    an equal tag; a resume skips that check, so this asks for both modes, first.
    """
    new = parse_tag(tag)[1]
    for name in existing:
        if name != tag and _triple(name) == new:
            first, second = sorted((name, tag))
            message = (
                f"tags {first} and {second} name the same version; delete the one that was "
                "pushed by mistake before releasing"
            )
            raise ReleaseError(message)


def is_latest(tag: str, existing: list[str]) -> bool:
    """True unless another release tag is numerically higher."""
    new = parse_tag(tag)[1]
    return not any((old := _triple(name)) is not None and old > new for name in existing)


def find_release_commit(log: str, tag: str) -> str | None:
    """The newest commit whose subject is exactly `chore(release): <tag>`.

    Takes the text of `git log --format=%H<TAB>%s` so the whole log is read; the
    shell version stopped early inside a pipe and died of SIGPIPE under pipefail.
    """
    subject = release_subject(tag)
    for line in log.splitlines():
        sha, _, title = line.partition("\t")
        if title == subject and sha:
            return sha
    return None


def release_subject(tag: str) -> str:
    return f"chore(release): {tag}"


def manifest_version(repo: Path, rev: str) -> str | None:
    text = run_git(repo, "show", f"{rev}:{TRUTH_MANIFEST}", check=False)
    try:
        value = json.loads(text).get("version")
    except (ValueError, AttributeError):
        return None
    return value if isinstance(value, str) else None


def owned_manifest_paths() -> list[str]:
    """The bump script's own list, read in-process: no tree's code runs to answer it."""
    return [path.relative_to(bump_version.ROOT).as_posix() for path in bump_version.MANIFESTS]


def check_release_commit(repo: Path, commit: str) -> None:
    """Refuse a commit as a release commit unless the workflow's bump could have written it.

    A subject and a manifest version are text anyone can put in a pull request. The bump
    commit is also committed by the release bot, has exactly one parent, and changes the
    owned manifests' `version` values and nothing else. The diff rule is the archive
    proof's own, with the parent standing in for the verified commit.
    """
    parents = run_git(repo, "rev-list", "--parents", "-n", "1", commit).split()[1:]
    if len(parents) != 1:
        message = (
            f"commit {commit} has {len(parents)} parents; a release commit has exactly one "
            "parent - refusing to resume onto it"
        )
        raise ReleaseError(message)
    committer = run_git(repo, "log", "-1", "--format=%ce", commit)
    if committer != BOT_EMAIL:
        message = (
            f"commit {commit} was committed by {committer!r}, not the release bot "
            f"{BOT_EMAIL!r} - refusing to resume onto it"
        )
        raise ReleaseError(message)
    try:
        verify_release_archive.check_changes(repo, commit, parents[0], owned_manifest_paths())
    except verify_release_archive.ArchiveError as exc:
        message = f"commit {commit}: {exc} - refusing to resume onto it"
        raise ReleaseError(message) from exc


def require_sha(name: str, value: str) -> str:
    if not FULL_SHA.fullmatch(value):
        message = f"{name} {value!r} is not a full lowercase commit SHA"
        raise ReleaseError(message)
    return value


def assert_no_hold(repo: Path, main_ref: str) -> None:
    """Refuse while main carries the hold marker; refuse too when main cannot be read.

    Both a fresh release and a resume pass through `resolve`, and it runs before any
    verifier, credential or tag move, so that is where this stops all of them and leaves
    nothing to undo. `assert_checkout` asks again, because the verifiers run for up to
    twenty-five minutes and a hold merged in that window must still stop a resume.

    Asked with `git ls-tree`, which lists the entry or prints nothing and exits nonzero
    only when it cannot read the tree. `git cat-file -e` was tried first and rejected: it
    exits 1 for a missing blob and 128 for both an absent path and a fatal error, so a
    damaged repository read as "no hold", and a guard that fails open is not a guard.
    """
    result = run([GIT, "-C", str(repo), "ls-tree", "--name-only", main_ref, "--", HOLD_FILE])
    if result.returncode:
        message = (
            f"cannot read main to check for {HOLD_FILE}, so a hold cannot be ruled out "
            f"({result.stderr.strip() or 'git ls-tree failed'}); refusing to release"
        )
        raise ReleaseError(message)
    if result.stdout.strip():
        message = (
            f"releases are on hold: {HOLD_FILE} is present on main. Read it for the reason and "
            "for what lifts the hold; remove it in a reviewed pull request, then use Re-run all "
            "jobs on this run. Nothing was tagged, verified, pushed or published."
        )
        raise ReleaseError(message)


def resolve(repo: Path, tag: str, main_ref: str = "origin/main") -> Resolution:
    """Fix the commit this run releases, before anything is built or verified."""
    version, _ = parse_tag(tag)
    main_tip = run_git(repo, "rev-parse", "--verify", f"{main_ref}^{{commit}}")
    assert_no_hold(repo, main_tip)
    tag_commit = run_git(repo, "rev-parse", "--verify", f"refs/tags/{tag}^{{commit}}")
    if not is_ancestor(repo, tag_commit, main_tip):
        message = (
            f"tag {tag} ({tag_commit}) is not on main - release tags must be created on main. "
            "Tag the main tip with the next version instead."
        )
        raise ReleaseError(message)
    existing = run_git(repo, "tag", "-l", *TAG_GLOBS).split()
    check_unique_version(tag, existing)
    latest = is_latest(tag, existing)
    log = run_git(repo, "log", "--format=%H%x09%s", main_ref)
    release_commit = find_release_commit(log, tag)
    if release_commit:
        carried = manifest_version(repo, release_commit)
        if carried != version:
            message = (
                f"commit {release_commit} is titled '{release_subject(tag)}' but its manifests "
                f"carry '{carried or ''}' - refusing to resume onto it"
            )
            raise ReleaseError(message)
        check_release_commit(repo, release_commit)
        return Resolution(
            tag, version, "resume", release_commit, release_commit, main_tip, latest=latest
        )
    check_monotonic(tag, existing)
    return Resolution(tag, version, "fresh", main_tip, "", main_tip, latest=latest)


def assert_head(repo: Path, expected: str) -> None:
    require_sha("expected commit", expected)
    head = run_git(repo, "rev-parse", "HEAD")
    if head != expected:
        message = f"checked out {head} but the release target is {expected}"
        raise ReleaseError(message)


def is_ancestor(repo: Path, ancestor: str, descendant: str) -> bool:
    return (
        run([GIT, "-C", str(repo), "merge-base", "--is-ancestor", ancestor, descendant]).returncode
        == 0
    )


def assert_checkout(
    repo: Path,
    mode: str,
    target: str,
    tag: str,
    *,
    verified: str,
    main_ref: str = "origin/main",
) -> None:
    """Refuse to publish unless this checkout is the tree that was verified.

    Fresh: HEAD is the target. A main that advanced since `resolve` fails here; the
    bump commit may already be on main when this is a retry, so the message sends the
    operator to re-run ALL jobs, the only re-run that resolves a new target. Resume:
    the workflow has already detached onto the target, so main is judged through its
    own ref: it must still contain the release commit, which must carry the tag's
    version.
    """
    if mode not in MODES:
        message = f"unknown release mode {mode!r}"
        raise ReleaseError(message)
    require_sha("release target", target)
    if verified != target:
        message = (
            f"frontend verification covered {verified or 'nothing'} but the release target is "
            f"{target}; refusing to publish an unverified tree"
        )
        raise ReleaseError(message)
    version, _ = parse_tag(tag)
    # Read from main's own ref, as `resolve` does, and before anything else is judged.
    assert_no_hold(repo, run_git(repo, "rev-parse", "--verify", f"{main_ref}^{{commit}}"))
    head = run_git(repo, "rev-parse", "HEAD")
    if mode == "fresh":
        if head != target:
            message = (
                f"main is at {head}, not the {target} this run resolved and verified. "
                "Use Re-run all jobs on this run so resolve takes the new tip and the "
                "verifiers cover it; if the release commit is already on main, the re-run "
                "resumes it."
            )
            raise ReleaseError(message)
        return
    main_tip = run_git(repo, "rev-parse", "--verify", f"{main_ref}^{{commit}}")
    if not is_ancestor(repo, target, main_tip):
        message = f"release commit {target} is not on main ({main_tip}) - refusing to resume"
        raise ReleaseError(message)
    carried = manifest_version(repo, target)
    if carried != version:
        message = f"release commit {target} carries '{carried or ''}', not {version}"
        raise ReleaseError(message)
    check_release_commit(repo, target)


def bump(repo: Path, version: str) -> bool:
    """Write `version` to every owned field. False when the manifests already carry it."""
    current = run([sys.executable, str(repo / "scripts/bump_version.py"), "--current"], repo)
    if current.returncode:
        message = f"cannot read the current version: {current.stderr.strip()}"
        raise ReleaseError(message)
    if current.stdout.strip() == version:
        return False
    result = run([sys.executable, str(repo / "scripts/bump_version.py"), version], repo)
    if result.returncode:
        message = f"bump to {version} refused: {result.stderr.strip()}"
        raise ReleaseError(message)
    return True


def owned_paths(repo: Path) -> list[str]:
    result = run([sys.executable, str(repo / "scripts/bump_version.py"), "--paths"], repo)
    if result.returncode:
        message = f"cannot list the owned version paths: {result.stderr.strip()}"
        raise ReleaseError(message)
    return result.stdout.split()


def commit_bump(repo: Path, tag: str) -> str:
    """Commit the bump if there is one; return the commit the release publishes."""
    version, _ = parse_tag(tag)
    paths = owned_paths(repo)
    if not run_git(repo, "status", "--porcelain", "--", *paths):
        return run_git(repo, "rev-parse", "HEAD")
    run_git(repo, "add", "--", *paths)
    run_git(
        repo,
        "-c",
        f"user.name={BOT_NAME}",
        "-c",
        f"user.email={BOT_EMAIL}",
        "-c",
        "commit.gpgsign=false",
        "commit",
        "-s",
        "-m",
        release_subject(tag),
        "-m",
        f"Bump plugin version to {version} (tag-driven release).",
    )
    return run_git(repo, "rev-parse", "HEAD")


def final_commit(repo: Path, mode: str, target: str) -> str:
    """What the tag and `stable` will point at."""
    if mode == "resume":
        return require_sha("release target", target)
    head = run_git(repo, "rev-parse", "HEAD")
    if head != target and run_git(repo, "rev-parse", "HEAD^") != target:
        message = f"HEAD {head} is neither the verified target {target} nor its direct child"
        raise ReleaseError(message)
    return head


def push_bump(repo: Path, remote: str, final: str) -> None:
    """No --force: a rejected push means main moved, and a re-run resumes from the new tip."""
    require_sha("release commit", final)
    result = run([GIT, "-C", str(repo), "push", remote, f"{final}:refs/heads/main"])
    if result.returncode:
        message = f"pushing the release commit to main was rejected: {result.stderr.strip()[-400:]}"
        raise ReleaseError(message)


def move_tag(repo: Path, remote: str, tag: str, final: str) -> None:
    """So `git checkout <tag>` shows the released manifests; allowed by the deploy-key bypass."""
    parse_tag(tag)
    require_sha("release commit", final)
    # tag.gpgsign=false: a lightweight tag is what the releases carry, and a machine that
    # signs by default dies here with "no tag message?" instead of moving it.
    run_git(repo, "-c", "tag.gpgsign=false", "tag", "-f", tag, final)
    run_git(repo, "push", "--force", remote, f"refs/tags/{tag}")


def advance_stable(repo: Path, remote: str, final: str) -> str:
    """The marketplace's moving channel, which only ever moves forward.

    Pushed when `stable` is absent or an ancestor of the release commit (so a re-run
    re-points it to the same commit). Resuming an older release after a newer one
    finished would otherwise drag the channel backwards. If the remote branch cannot be
    fetched to compare, the push is refused rather than assumed safe.
    """
    require_sha("release commit", final)
    listed = run_git(repo, "ls-remote", "--heads", remote, "refs/heads/stable")
    current = listed.split()[0] if listed else ""
    if current:
        run_git(repo, "fetch", "-q", "--no-tags", remote, "refs/heads/stable")
        if not is_ancestor(repo, current, final):
            return (
                f"stable is at {current}, which is not an ancestor of {final}; "
                "not moving stable backwards"
            )
    run_git(repo, "push", "--force", remote, f"{final}:refs/heads/stable")
    return f"stable now at {final}"


def github_output(path: Path, values: Mapping[str, str]) -> None:
    """Append `key=value` lines; a value that could forge another line writes nothing at all."""
    for key, value in values.items():
        if "\n" in value or "\r" in value:
            message = f"output {key} would break the output file"
            raise ReleaseError(message)
    with path.open("a", encoding="utf-8") as handle:
        for key, value in values.items():
            handle.write(f"{key}={value}\n")


def is_local_remote(repo: Path, remote: str) -> bool:
    """Every fetch and push URL must be a local path: `pushurl` can differ from `url`."""
    urls = [
        *run_git(repo, "remote", "get-url", "--all", remote).splitlines(),
        *run_git(repo, "remote", "get-url", "--push", "--all", remote).splitlines(),
    ]
    return bool(urls) and all(
        url.startswith(("/", "file://")) or bool(re.match(r"^[A-Za-z]:[\\/]", url)) for url in urls
    )


class _Rehearsal:
    """One method per phase, so the order lives in PHASES and the failure points are named."""

    def __init__(
        self,
        repo: Path,
        tag: str,
        remote: str,
        verify: Callable[[Resolution], str] | None,
    ) -> None:
        self.repo, self.tag, self.remote, self.verify = repo, tag, remote, verify
        self.resolution: Resolution | None = None
        self.verified = ""
        self.final = ""

    @property
    def current(self) -> Resolution:
        if self.resolution is None:  # pragma: no cover -- resolve always runs first
            message = "rehearsal phase ran before resolve"
            raise ReleaseError(message)
        return self.resolution

    def fetch(self) -> None:
        run_git(self.repo, "fetch", "-q", self.remote, "main", "--tags", "--force")

    def phase_resolve(self) -> None:
        self.fetch()
        self.resolution = resolve(self.repo, self.tag, f"{self.remote}/main")
        self.final = self.resolution.target

    def phase_verify(self) -> None:
        self.verified = self.verify(self.current) if self.verify else self.current.target

    def phase_checkout(self) -> None:
        self.fetch()
        run_git(self.repo, "checkout", "-q", "--detach", f"{self.remote}/main")
        current = self.current
        if current.mode == "resume":
            run_git(self.repo, "checkout", "-q", "--detach", current.target)
        assert_checkout(
            self.repo,
            current.mode,
            current.target,
            self.tag,
            verified=self.verified,
            main_ref=f"{self.remote}/main",
        )

    def phase_bump(self) -> None:
        current = self.current
        if current.mode == "fresh":
            bump(self.repo, current.version)
            commit_bump(self.repo, self.tag)
        self.final = final_commit(self.repo, current.mode, current.target)

    def phase_archive(self) -> None:
        current = self.current
        try:
            verify_release_archive.verify_archive(
                self.repo, self.final, current.target, current.version
            )
        except verify_release_archive.ArchiveError as exc:
            raise ReleaseError(str(exc)) from exc

    def phase_push_bump(self) -> None:
        if self.current.mode == "fresh":
            push_bump(self.repo, self.remote, self.final)

    def phase_move_tag(self) -> None:
        move_tag(self.repo, self.remote, self.tag, self.final)

    def phase_stable(self) -> None:
        advance_stable(self.repo, self.remote, self.final)


def rehearse(
    repo: Path,
    tag: str,
    *,
    remote: str = "origin",
    dry_run: bool = False,
    stop_after: str | None = None,
    after: Mapping[str, Callable[[Resolution], None]] | None = None,
    verify: Callable[[Resolution], str] | None = None,
) -> Outcome:
    """The whole sequence in one process, against a repository whose remote is local.

    This is the reference order the workflow's jobs follow, kept executable so it can
    be run against a temporary repository with failures injected between phases
    (`after` maps a phase to a callable that may raise). It refuses a remote that is
    not a local path, so it cannot reach a real tag.
    """
    if not is_local_remote(repo, remote):
        message = "rehearsal refuses a remote that is not a local path"
        raise ReleaseError(message)
    hooks = dict(after or {})
    rehearsal = _Rehearsal(repo, tag, remote, verify)
    last = ""
    for phase in PHASES:
        getattr(rehearsal, f"phase_{phase.replace('-', '_')}")()
        last = phase
        if phase in hooks:
            hooks[phase](rehearsal.current)
        if phase == stop_after or (dry_run and phase == "archive"):
            break
    current = rehearsal.current
    return Outcome(current.mode, current.target, rehearsal.final, last)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--repo", type=Path, default=Path())
    commands = parser.add_subparsers(dest="command", required=True)

    def command(name: str, *flags: str, optional: tuple[str, ...] = ()) -> argparse.ArgumentParser:
        sub = commands.add_parser(name)
        for flag in flags:
            sub.add_argument(f"--{flag}", required=True)
        for flag in optional:
            sub.add_argument(f"--{flag}")
        return sub

    resolve_cmd = command("resolve", "tag", optional=("main-ref", "github-output"))
    resolve_cmd.set_defaults(main_ref="origin/main")
    command("assert-head", "expected")
    checkout = command("assert-checkout", "mode", "target", "tag")
    # Repeated: every credential-free job that checked something out reports its own
    # commit, and a publish needs all of them to be the target.
    checkout.add_argument("--verified", action="append", required=True)
    checkout.add_argument("--main-ref", default="origin/main")
    command("bump", "tag")
    command("commit-bump", "tag")
    command("final", "mode", "target")
    for name in ("push-bump", "move-tag", "advance-stable"):
        sub = command(name, "final", optional=("tag", "remote"))
        sub.set_defaults(remote="origin")
    rehearsal = command("rehearse", "tag")
    rehearsal.add_argument("--dry-run", action="store_true")
    return parser


def dispatch(args: argparse.Namespace) -> int:  # noqa: C901, PLR0912 -- one arm per subcommand
    repo: Path = args.repo
    match args.command:
        case "resolve":
            resolution = resolve(repo, args.tag, args.main_ref)
            for key, value in resolution.outputs().items():
                print(f"{key}={value}")
            if args.github_output:
                github_output(Path(args.github_output), resolution.outputs())
        case "assert-head":
            assert_head(repo, args.expected)
        case "assert-checkout":
            for verified in args.verified:
                assert_checkout(
                    repo,
                    args.mode,
                    args.target,
                    args.tag,
                    verified=verified,
                    main_ref=args.main_ref,
                )
        case "bump":
            version, _ = parse_tag(args.tag)
            print("bumped" if bump(repo, version) else "unchanged")
        case "commit-bump":
            print(commit_bump(repo, args.tag))
        case "final":
            print(final_commit(repo, args.mode, args.target))
        case "push-bump":
            push_bump(repo, args.remote, args.final)
        case "move-tag":
            if not args.tag:
                message = "move-tag needs --tag"
                raise ReleaseError(message)
            move_tag(repo, args.remote, args.tag, args.final)
        case "advance-stable":
            print(advance_stable(repo, args.remote, args.final))
        case "rehearse":
            outcome = rehearse(repo, args.tag, dry_run=args.dry_run)
            print(f"{outcome.mode} release of {args.tag}: stopped after {outcome.last_phase}")
        case _:  # pragma: no cover -- argparse rejects unknown subcommands
            return 2
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return dispatch(args)
    except ReleaseError as exc:
        print(annotation(str(exc)))
        return 1


if __name__ == "__main__":
    sys.exit(main())
