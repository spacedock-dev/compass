#!/usr/bin/env python3
"""Run the pre-PR checks the lanes of this change can fail, one run per repository at a time.

`scripts/ci_scope.py` decides which of the quality gate's lanes the diff against the merge base
with `origin/main` (or `--base`) touches, the working tree and untracked files included. This
runs the local commands of those lanes from AGENTS.md's "Pre-PR Checks" list and prints every
command it skips with the reason. `--all` runs that whole list, which stays the canonical record;
`scripts/tests/test_pre_pr.py` holds the two equal. `--dry-run` prints the plan and runs nothing.

Coverage is opt-in (`--coverage`): CI enforces both thresholds, and a coverage run of the Python
suites is several times slower than a plain one on Pythons without `sysmon`.

A run holds a lock in the git common directory, so a second worktree's run waits for the first
instead of contending with it: concurrent suites manufacture port, lifecycle and timeout failures
(AGENTS.md, "Parallel Work").
"""

from __future__ import annotations

import argparse
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import IO, TYPE_CHECKING

if sys.platform == "win32":
    import msvcrt
else:
    import fcntl

import ci_scope

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASE = "origin/main"
LOCK_NAME = "compass-pre-pr.lock"

RUNNER = "python3 scripts/run_tests.py"
DASHBOARD_ARGS = "-s compass/skills/compass/tests -t ."
SCRIPTS_ARGS = "-s scripts/tests -t scripts/tests"
DASHBOARD_SUITE = f"{RUNNER} {DASHBOARD_ARGS}"
SCRIPTS_SUITE = f"{RUNNER} {SCRIPTS_ARGS}"
VALIDATE_TESTS = (
    "python3 -m unittest scripts/tests/test_validate_plugins.py scripts/tests/test_bump_version.py"
)
INSTALL = "python3 -m pip install -r requirements-validation.txt -r requirements-dev.txt"
REQUIREMENTS = frozenset({"requirements-validation.txt", "requirements-dev.txt"})
PLAYWRIGHT = "pnpm exec playwright install chromium"
VERSION_DIFF = (
    "git diff \"$(git merge-base {base} HEAD)\"..HEAD -- '*plugin.json' "
    "'*gemini-extension.json' | grep -E '^[+-].*\"version\"'"
)
# agy has been measured hanging for over ten minutes with no output; a hung validator must not
# hold the lock forever.
NATIVE_TIMEOUT = 180.0

KNOWN_OUTPUTS = frozenset(
    {
        "python",
        "lint",
        "frontend",
        "contract",
        "python_suites",
        "frontend_docs",
        "frontend_docs_tests",
        "platform",
    }
)


class ScopeError(Exception):
    """The diff could not be classified; the run fails open to every lane."""


@dataclass(frozen=True)
class Item:
    """One planned command: it runs when `reason` is None, and is reported skipped otherwise."""

    text: str
    reason: str | None = None
    argv: tuple[str, ...] = ()
    check: Callable[[], int] | None = None
    timeout: float | None = None


@dataclass(frozen=True)
class Lanes:
    """The detector's outputs, read as the booleans and the file list this runner acts on."""

    python: bool = False
    frontend: bool = False
    contract: bool = False
    suites: bool = False
    frontend_docs: bool = False
    frontend_docs_tests: tuple[str, ...] = ()
    platform: bool = False
    unknown: tuple[str, ...] = ()
    has_frontend_docs: bool = False

    @classmethod
    def read(cls, outputs: dict[str, str]) -> Lanes:
        def on(name: str) -> bool:
            return outputs.get(name, "false") == "true"

        unknown = tuple(
            sorted(
                name
                for name, value in outputs.items()
                if name not in KNOWN_OUTPUTS and value not in {"", "false"}
            )
        )
        return cls(
            python=on("python"),
            frontend=on("frontend"),
            contract=on("contract"),
            suites=on("python_suites"),
            frontend_docs=on("frontend_docs"),
            frontend_docs_tests=tuple(outputs.get("frontend_docs_tests", "").split()),
            platform=on("platform"),
            unknown=unknown,
            has_frontend_docs="frontend_docs" in outputs,
        )


EVERY_LANE = Lanes(python=True, frontend=True, suites=True)


@dataclass(frozen=True)
class Options:
    everything: bool
    coverage: bool
    requirements: bool
    base: str
    jobs: int | None
    which: Callable[[str], str | None]
    root: Path


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(  # noqa: S603 - fixed git argv, no shell
        ["git", *args],  # noqa: S607 - git from PATH
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        message = f"git {' '.join(args)}: {result.stderr.strip() or 'failed'}"
        raise ScopeError(message)
    return result.stdout


def changed_paths(base: str, root: Path = ROOT) -> list[str]:
    """Every path that differs from the merge base: commits, staged and unstaged edits, new files.

    A pre-PR run checks the tree about to be committed, so uncommitted work counts.
    """
    merge_base = _git(root, "merge-base", base, "HEAD").strip()
    # --no-renames lists a move's old path too, as ci_scope does: something may still read it.
    tracked = _git(root, "diff", "--name-only", "--no-renames", merge_base).splitlines()
    untracked = _git(root, "ls-files", "--others", "--exclude-standard").splitlines()
    return sorted({path for path in (*tracked, *untracked) if path})


def classify(base: str, root: Path = ROOT) -> tuple[dict[str, str], list[str], list[str]]:
    """The detector's outputs for this change, its one-line reason per path, and the paths."""
    try:
        paths = changed_paths(base, root)
        result = ci_scope.scope(paths, root)
    except (OSError, UnicodeDecodeError, ValueError) as error:
        raise ScopeError(str(error)) from error
    return result.outputs(), list(result.reasons), paths


def _argv(text: str, options: Options) -> tuple[str, ...]:
    words = shlex.split(text)
    head = sys.executable if words[0] == "python3" else options.which(words[0]) or words[0]
    return (head, *words[1:])


def _version_check(base: str, root: Path) -> Callable[[], int]:
    def check() -> int:
        merge_base = _git(root, "merge-base", base, "HEAD").strip()
        # Against the working tree, not HEAD: an uncommitted bump fails version-guard once pushed.
        diff = _git(root, "diff", merge_base, "--", "*plugin.json", "*gemini-extension.json")
        moved = [line for line in diff.splitlines() if re.match(r'^[+-].*"version"', line)]
        for line in moved:
            print(f"    {line}")
        if moved:
            print("    A version field moved; the Release workflow owns them (AGENTS.md).")
        return 1 if moved else 0

    return check


def _runtime_vitest_files(root: Path) -> list[str]:
    # Derived the way quality-gate.yml's frontend-contract job derives them, so a new test that
    # names the runtime is picked up here without an edit.
    found = []
    for pattern in ("*.test.ts", "*.test.tsx"):
        for path in (root / "frontend").rglob(pattern):
            relative = path.relative_to(root)
            if "node_modules" in relative.parts:
                continue
            if "compass/skills/compass" in path.read_text(encoding="utf-8"):
                found.append(relative.as_posix())
    return sorted(found)


def _canonical(lanes: Lanes, options: Options) -> list[Item]:
    """AGENTS.md's list, in its order, each with the reason it is skipped for these lanes."""
    every = options.everything
    coverage = every or options.coverage
    no_coverage = "coverage is opt-in with --coverage; CI enforces the threshold"
    install = None if every or options.requirements else "no requirements file changed"
    frontend = None if every or lanes.frontend else "the frontend lane is off"
    pnpm_install = (
        None
        if every or lanes.frontend or lanes.contract or lanes.frontend_docs
        else "no frontend, contract or frontend-docs lane is on"
    )
    dev = None if every or lanes.frontend or lanes.contract else "no frontend or contract lane"
    suites = None if every or lanes.suites else "no Python suite lane is on"
    # Coverage of the dashboard suite alone, on a run without the suite lanes, would be a partial
    # figure measured against the whole-repository threshold.
    suite_coverage = coverage and suites is None
    coverage_step = None if suite_coverage else suites or no_coverage

    def frontend_coverage() -> str | None:
        return frontend or (None if coverage else no_coverage)

    def suite(text: str) -> str:
        if not suite_coverage:
            text = text.replace(" --coverage", "")
        if options.jobs is not None:
            text = f"{text} -j {options.jobs}"
        return text

    rows: list[tuple[str, str | None]] = [
        (INSTALL, install),
        ("ruff check .", None),
        ("ruff format --check .", None),
        ("mypy", None),
        ("python3 scripts/validate_plugins.py", None),
        ("python3 scripts/bump_version.py --current", None),
        (VERSION_DIFF.format(base=options.base), None),
        ("pnpm install --frozen-lockfile", pnpm_install),
        ("pnpm lint", frontend),
        ("pnpm typecheck", frontend),
        (f"pnpm test:styles --base {options.base}", frontend),
        ("pnpm test", frontend),
        ("pnpm test:coverage", frontend_coverage()),
        ("pnpm build:storybook", frontend),
        ("pnpm test:stories", frontend),
        ("pnpm test:dev", dev),
        ("pnpm build", frontend),
        ("pnpm build:check", frontend),
        (PLAYWRIGHT, frontend),
        ("coverage erase", coverage_step),
        # validate.yml runs the dashboard suite on a pull request the gate runs no Python suite on,
        # as the backstop for a document the detector misclassifies, so a run without one does too.
        (suite(f"{RUNNER} --coverage {DASHBOARD_ARGS}"), None),
        (suite(f"{RUNNER} --coverage {SCRIPTS_ARGS}"), suites),
        ("coverage combine", coverage_step),
        ("coverage report", coverage_step),
    ]
    items = []
    for text, reason in rows:
        if text.startswith("git diff"):
            check = _version_check(options.base, options.root) if reason is None else None
            items.append(Item(text, reason, check=check))
        else:
            items.append(Item(text, reason, _argv(text, options) if reason is None else ()))
    for text in ("claude plugin validate ./compass --strict", "agy plugin validate ./compass"):
        tool = text.split()[0]
        found = options.which(tool)
        reason = None if found else f"`{tool}` is not installed"
        items.append(Item(text, reason, _argv(text, options), timeout=NATIVE_TIMEOUT))
    return items


def _derived(lanes: Lanes, options: Options) -> dict[str, list[Item]]:
    """Commands outside the canonical list, keyed by the canonical command they follow."""
    # validate.yml runs these on every pull request; the scripts suite holds them otherwise.
    validate = Item(
        VALIDATE_TESTS,
        "the scripts suite runs them" if lanes.suites else None,
        _argv(VALIDATE_TESTS, options),
    )
    contract: list[Item] = []
    if lanes.contract:
        tests = sorted(
            path.relative_to(options.root).as_posix()
            for path in (options.root / "frontend/build").glob("*.test.mjs")
        )
        contract.append(
            Item(
                "node --test frontend/build/*.test.mjs",
                argv=(options.which("node") or "node", "--test", *tests),
            )
        )
        files = _runtime_vitest_files(options.root)
        text = f"pnpm exec vitest run {' '.join(files)}"
        if files:
            contract.append(Item(text, argv=_argv(text, options)))
        else:
            contract.append(Item("pnpm exec vitest run", check=_no_runtime_tests))
    else:
        contract.append(
            Item(
                "node --test frontend/build/*.test.mjs, and the Vitest files that name the runtime",
                "the contract lane is off"
                + (" (the frontend lane runs these)" if lanes.frontend else ""),
            )
        )
    if lanes.frontend_docs and lanes.frontend_docs_tests and not lanes.frontend:
        text = f"pnpm exec vitest run {' '.join(lanes.frontend_docs_tests)}"
        docs = Item(text, argv=_argv(text, options))
    else:
        if lanes.frontend:
            reason = "pnpm test runs every Vitest file"
        elif lanes.has_frontend_docs:
            reason = "no changed document is read by a frontend test"
        else:
            reason = "this ci_scope.py reports no frontend_docs lane"
        docs = Item("pnpm exec vitest run <the Vitest files that read a changed document>", reason)
    return {
        "python3 scripts/bump_version.py --current": [validate],
        "pnpm test:dev": [*contract, docs],
    }


def _no_runtime_tests() -> int:
    print("    No Vitest file names the runtime, so the derivation is broken.")
    return 1


def plan(
    outputs: dict[str, str],
    *,
    everything: bool = False,
    coverage: bool = False,
    requirements: bool = False,
    base: str = DEFAULT_BASE,
    jobs: int | None = None,
    which: Callable[[str], str | None] = shutil.which,
    root: Path = ROOT,
) -> list[Item]:
    """Every command this run considers, in order, each either to run or skipped with a reason."""
    lanes = Lanes.read(outputs)
    everything = everything or bool(lanes.unknown)
    options = Options(everything, coverage, requirements, base, jobs, which, root)
    canonical = _canonical(lanes, options)
    if everything:
        return canonical
    derived = _derived(lanes, options)
    # The canonical list installs the browser after the stories that need it; `--all` keeps that
    # order, held to AGENTS.md, and a lane run installs it first.
    browser = next(item for item in canonical if item.text == PLAYWRIGHT)
    items: list[Item] = []
    for item in canonical:
        if item is browser:
            continue
        if item.text == "pnpm build:storybook":
            items.append(browser)
        items.append(item)
        items.extend(derived.get(item.text, []))
    return items


def lock_path(root: Path = ROOT) -> Path:
    """The lock file, in the git common directory every worktree of this clone shares."""
    common = _git(root, "rev-parse", "--path-format=absolute", "--git-common-dir").strip()
    return Path(common) / LOCK_NAME


def _try_lock(handle: IO[str]) -> bool:
    try:
        if sys.platform == "win32":
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return False
    return True


def _unlock(handle: IO[str]) -> None:
    if sys.platform == "win32":
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _holder(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip() or "another run"
    except OSError:
        return "another run"


@contextmanager
def hold_lock(
    path: Path,
    *,
    on_wait: Callable[[str], object] | None = None,
    poll: float = 1.0,
    timeout: float | None = None,
) -> Iterator[None]:
    """Hold an exclusive lock on `path`, waiting for any other holder; released on any exit.

    Polls a non-blocking lock rather than blocking, so a wait can be announced once and bounded.
    The lock is the operating system's, so a run killed outright leaves nothing to clean up.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    deadline = None if timeout is None else time.monotonic() + timeout
    with path.open("a+", encoding="utf-8") as handle:
        announced = False
        while not _try_lock(handle):
            if not announced and on_wait is not None:
                on_wait(_holder(path))
            announced = True
            if deadline is not None and time.monotonic() >= deadline:
                message = f"{path} is still held by {_holder(path)}"
                raise TimeoutError(message)
            time.sleep(poll)
        try:
            handle.seek(0)
            handle.truncate()
            handle.write(f"pid {os.getpid()} in {Path.cwd()}\n")
            handle.flush()
            yield
        finally:
            _unlock(handle)


def _print_plan(items: list[Item]) -> None:
    # Aligned reasons read as a table; a long command still gets its reason on the same line.
    width = min(60, max((len(item.text) for item in items if item.reason), default=0))
    for item in items:
        if item.reason is None:
            print(f"run   {item.text}")
        else:
            print(f"skip  {item.text:<{width}}  ({item.reason})")


def _run(item: Item, root: Path) -> int:
    print(f"\n==> {item.text}", flush=True)
    if item.check is not None:
        try:
            return item.check()
        except ScopeError as error:
            print(f"    {error}")
            return 1
    env = dict(os.environ)
    # What the frontend's runtime tests start; CI sets it to the job's Python.
    env.setdefault("COMPASS_TEST_PYTHON", sys.executable)
    try:
        return subprocess.run(  # noqa: S603 - argv built from the fixed command list
            item.argv, cwd=root, env=env, check=False, timeout=item.timeout
        ).returncode
    except FileNotFoundError:
        print(f"    {item.argv[0]} was not found")
        return 127
    except subprocess.TimeoutExpired:
        print(f"    timed out after {item.timeout:.0f} s")
        return 124


def _execute(items: list[Item], root: Path) -> int:
    results: list[tuple[str, int, float]] = []
    try:
        for item in items:
            if item.reason is None:
                started = time.monotonic()
                code = _run(item, root)
                results.append((item.text, code, time.monotonic() - started))
    except KeyboardInterrupt:
        _summarize(results)
        raise
    return _summarize(results)


def _summarize(results: list[tuple[str, int, float]]) -> int:
    print("\nSummary")
    for text, code, seconds in results:
        print(f"  {'pass' if code == 0 else f'FAIL ({code})':<10} {seconds:7.1f}s  {text}")
    failed = sum(1 for _, code, _ in results if code != 0)
    print(f"{len(results) - failed} passed, {failed} failed")
    return 1 if failed else 0


def _ci_only(lanes: Lanes) -> list[str]:
    """The checks CI runs for these lanes that this runner does not, so none passes unannounced."""
    lines = []
    if lanes.platform or lanes.python:
        lines.append(
            "CI runs the macOS legs (platform-tests, platform-tests-current); not run here."
        )
    if lanes.suites:
        lines.append(
            "CI runs the direct-launch smoke (server.py --help, server.py --diagnose --json)"
            " on Python 3.12; not run here."
        )
    if lanes.frontend:
        lines.append("CI runs `pnpm build:preview`, the native preview build; not run here.")
    return lines


def main(
    argv: list[str] | None = None,
    classify: Callable[[str], tuple[dict[str, str], list[str], list[str]]] = classify,
) -> int:
    """Plan the run, print it, and unless `--dry-run` run it under the repository lock."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", default=DEFAULT_BASE, help="ref to diff against (origin/main)")
    parser.add_argument("--all", action="store_true", help="run the whole canonical list")
    parser.add_argument("--coverage", action="store_true", help="add the coverage runs")
    parser.add_argument("--dry-run", action="store_true", help="print the plan; run nothing")
    parser.add_argument("-j", "--jobs", type=int, help="workers for each Python suite")
    args = parser.parse_args(argv)

    outputs: dict[str, str] = {}
    requirements = False
    if args.all:
        print("--all: the whole canonical list in AGENTS.md, whatever changed.")
    else:
        try:
            outputs, reasons, paths = classify(args.base)
        except ScopeError as error:
            print(f"Could not classify the change ({error}); every lane is on.")
            outputs = {"python": "true", "lint": "true", "frontend": "true"}
            outputs["python_suites"] = "true"
            requirements = True
        else:
            requirements = bool(REQUIREMENTS.intersection(paths))
            print(f"Changes against the merge base with {args.base}:")
            for line in reasons:
                print(f"  {line}")
        lanes = Lanes.read(outputs)
        on = [name for name, value in outputs.items() if value == "true"]
        print(f"CI lanes on: {', '.join(on) or 'none (validate.yml still runs its suite)'}")
        if lanes.unknown:
            print(f"Unknown lanes {', '.join(lanes.unknown)}: running the whole list to be safe.")
        for line in _ci_only(lanes):
            print(line)
    items = plan(
        outputs,
        everything=args.all,
        coverage=args.coverage,
        requirements=requirements,
        base=args.base,
        jobs=args.jobs,
    )
    print()
    _print_plan(items)
    if args.dry_run:
        return 0

    path = lock_path()
    try:
        with hold_lock(path, on_wait=lambda who: print(f"\nWaiting for {path} ({who}) ...")):
            return _execute(items, ROOT)
    except KeyboardInterrupt:
        print("\nInterrupted; the lock is released.")
        return 130


if __name__ == "__main__":
    sys.exit(main())
