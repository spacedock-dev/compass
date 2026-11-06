#!/usr/bin/env python3
"""Decide which of the quality gate's lanes a pull request's changes can affect.

`quality-gate.yml` and `validate.yml` both run this before anything measurable, and each job
runs only when a lane it belongs to is on. There are six lanes:

- ``python``: ruff, mypy, the coverage run and the dashboard suite on the newest CPython (on macOS
  when ``platform`` is on, on Linux otherwise). On when Python or what the Python suites assert on
  changed.
- ``frontend``: Biome, strict types, Vitest under coverage, the bundle rebuild and Storybook. On
  when the frontend's sources, its toolchain or a document its tests read changed.
- ``python_suites``: the Python suites once on Linux, with no lint, types, coverage or macOS. On
  for data the Python tests read but no Python executes (a document, a fixture, a skill's
  Markdown), and with either full lane.
- ``lint``: ruff alone, which also formats the Python blocks inside Markdown. On with ``python``
  and for a Markdown file that holds one.
- ``contract``: the frontend tests that start or read the Python runtime (``pnpm test:dev``, the
  build tests and the Vitest files that name it). On when the runtime changed and the whole
  frontend lane is not already running.
- ``frontend_docs``: only the Vitest files that read the changed documents, named in
  ``frontend_docs_tests``. On for a document no other frontend file reads, when the whole frontend
  lane is not already running. A citation in any frontend file is read by the citation check
  (CITATION_CHECK), which resolves every one against the document's headings.

``platform`` is not a lane of its own: it says whether the macOS legs of the ``python`` and
``frontend`` lanes run. On for the reviewed PLATFORM_PATHS, the gate's wiring, an unknown path,
and every run that is not a pull request (a push to main, the nightly schedule, a manual dispatch).

The Python suites read nearly every file under ``frontend/`` (measured 2026-11-01 with an audit
hook: every tracked frontend file was opened by at least one test), so a frontend change also runs
those suites once on Linux. That is ``python_suites``, and it is the run ``validate.yml`` uses to
decide whether its own copy of the dashboard suite is the only one.

It FAILS OPEN. Anything it cannot compute, and any path it does not recognise, turns every lane
on: a wrong "off" skips a job that could catch a regression, and a wrong "on" costs a runner. A
change that touches only prose no test reads turns every lane off, and ``validate.yml``'s
unfiltered dashboard suite is then the only run, which is the backstop for a misread document.
"""

from __future__ import annotations

import argparse
import fnmatch
import os
import posixpath
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

PYTHON = "python"
FRONTEND = "frontend"
CONTRACT = "contract"
SUITES = "python_suites"
LINT = "lint"
FRONTEND_DOCS = "frontend_docs"
PLATFORM = "platform"

# Root files the frontend toolchain reads. A change to any of them can change what Biome, tsc,
# Vitest, the bundle or Storybook does.
JS_TOOLING = frozenset(
    {
        ".node-version",
        ".npmrc",
        "biome.json",
        "components.json",
        "package.json",
        "playwright.config.ts",
        "pnpm-lock.yaml",
        "pnpm-workspace.yaml",
        "vitest.config.mts",
    }
)
# Prose no linter parses. A document a test reads is found by the scans below first, so it never
# reaches this list; SECURITY.md, README.md and MANUAL.md are absent because dashboard tests open
# them by path.
PROSE = (
    "HOW_TO_USE.md",
    "AGENTS.md",
    "CLAUDE.md",
    "CONTRIBUTING.md",
    "COMPATIBILITY.md",
    "CODE_OF_CONDUCT.md",
    ".github/PULL_REQUEST_TEMPLATE.md",
    ".github/ISSUE_TEMPLATE/*",
    "docs/*.md",
)
# Workflows that wire up the gate's own jobs or the release's rebuild of the bundle. Any other
# workflow keeps the prose short path: `validate.yml`'s suite still runs on it, and actionlint has
# its own workflow.
GATE_WIRING = (
    ".github/workflows/quality-gate.yml",
    ".github/workflows/validate.yml",
    ".github/workflows/release.yml",
    ".github/workflows/release.yaml",
    ".github/workflows/frontend*.yml",
    ".github/workflows/frontend*.yaml",
    ".github/actions/*",
    "scripts/ci_scope.py",
)
# Data the Python tests read and nothing executes: it can break an assertion, not a lint, a type,
# the coverage figure or a platform. Checked before BACKEND, which holds code.
PYTHON_DATA = (
    "tests/*",
    "sample-session/*",
    ".agents/*",
    ".claude/*",
    ".gitignore",
    ".gitattributes",
    "*.md",
    "LICENSE",
    "NOTICE",
)
BACKEND = (
    "compass/*",
    "compass-gemini/*",
    "compass-droid/*",
    "scripts/*",
    "pyproject.toml",
    "requirements*.txt",
)
# Code whose behaviour differs between macOS and Linux, so a Linux run cannot stand in for it.
# Reviewed 2026-11-06 from a grep of the runtime, launchers and scripts for sys.platform, os.name,
# kqueue, waitid, osascript, darwin, signals and process groups, and from the macOS-only failures
# on record. Left out on purpose: `os.name` and `win32` branches (no CI runner takes them), and
# modules that take the platform as an argument (`config.platform_name` in http_api, aggregate,
# quota and observation; `platform.system()` defaults in claude_settings and reading_route), whose
# tests pass "darwin" explicitly on Linux ([D-4](docs/design-cross-platform.md#d-4)). The nightly
# run catches what this list misses.
PLATFORM_PATHS = (
    # The launcher and its two byte-identical copies forward signals to the server.
    "compass/skills/compass/launch.py",
    "compass-gemini/hooks/launch.py",
    "compass-droid/hooks/launch.py",
    # The exit watch (kqueue on 3.12, waitid on 3.13+) and process-group kills.
    "compass/skills/compass/compass_runtime/supervise.py",
    # The daemon's fork and setsid, and signal handling.
    "compass/skills/compass/compass_runtime/lifecycle.py",
    # File locks.
    "compass/skills/compass/compass_runtime/io.py",
    # osascript notifications.
    "compass/skills/compass/compass_runtime/notifications.py",
    # The owned development server `pnpm test:dev` starts and supervises.
    "compass/skills/compass/compass_runtime/frontend_dev.py",
    "frontend/dev/*",
    # Terminal automation, and the drivers that start harnesses in their own process groups.
    "scripts/capture_terminal_identity.py",
    "scripts/capture_focus_raise.py",
    "scripts/observe_journey.py",
    "scripts/ordinary_turn_driver.py",
    # Timing bounds that passed on Linux and failed on the slower macOS runners: the scrub's
    # (0.80 s, 1.20 s and 0.31 s, #745) and the footer's stalled-read deadline (0.352 s, #787).
    "compass/skills/compass/compass_runtime/records.py",
    "compass/skills/compass/compass_runtime/terminal_client.py",
    "compass/skills/compass/tests/test_records.py",
    "compass/skills/compass/tests/test_footer.py",
    # The shared test config takes sys.platform, so the macOS legs run every default test as darwin.
    "compass/skills/compass/tests/support.py",
    # What the macOS legs install: the lockfile's per-OS native bindings (esbuild, rolldown, biome,
    # lightningcss) and the Node that loads them, and the wheels requirements-validation.txt pins.
    ".node-version",
    ".npmrc",
    "package.json",
    "pnpm-lock.yaml",
    "pnpm-workspace.yaml",
    "requirements-validation.txt",
    # The tests of the above, which are what the macOS legs run.
    "compass/skills/compass/tests/test_supervise.py",
    "compass/skills/compass/tests/test_lifecycle.py",
    "compass/skills/compass/tests/test_launch.py",
    "compass/skills/compass/tests/test_launch_and_send_pins.py",
    "compass/skills/compass/tests/test_notifications.py",
    "compass/skills/compass/tests/test_frontend_dev.py",
    "scripts/tests/test_capture_terminal_identity.py",
    "scripts/tests/test_capture_focus_raise.py",
    "scripts/tests/test_ordinary_turn_driver.py",
)

# What `pnpm test:dev` starts and the Vitest and build tests import. The page under `web/` is not
# here: it is built output, and a change to it runs the whole frontend lane.
RUNTIME = ("compass/skills/compass/server.py", "compass/skills/compass/compass_runtime/*")
WEB = "compass/skills/compass/compass_runtime/web/*"

# `docs/captures/README.md` is read through a path DocumentedCaptureFiguresTest composes from
# CAPTURES, which no literal scan finds. Composed reads need a reviewed entry here.
COMPOSED_PYTHON_READS = frozenset({"docs/captures/README.md"})

# vitest.config.mts's include globs, held to it by test_ci_scope.
VITEST_FILES = ("frontend/**/*.test.ts", "frontend/**/*.test.tsx")
# The Vitest file that resolves every frontend citation against the cited document's headings.
CITATION_CHECK = "frontend/test/docCitations.test.ts"

JS_SUFFIXES = (".js", ".mjs", ".cjs", ".ts", ".mts")
SOURCE_SUFFIXES = frozenset({".py", ".ts", ".tsx", ".js", ".jsx", ".mts", ".mjs"})
_QUOTES = "\"'"
LITERAL = re.compile(
    "[" + _QUOTES + r"]((?:docs/[^" + _QUOTES + r"\r\n]+|[\w.-]+)\.md)[" + _QUOTES + "]"
)
CITATION = re.compile(r"\(((?:\.\./)*docs/[^)\s]+\.md)#")


@dataclass(frozen=True)
class Scope:
    """Which lanes are on, and why, one line per changed path."""

    python: bool
    frontend: bool
    contract: bool
    reasons: tuple[str, ...]

    suites: bool = False
    lint: bool = False
    frontend_docs_tests: tuple[str, ...] = ()
    platform: bool = False

    @property
    def python_suites(self) -> bool:
        """Whether the gate runs the Python suites at all, on any lane."""
        return self.python or self.frontend or self.suites

    def outputs(self) -> dict[str, str]:
        """The `$GITHUB_OUTPUT` lines, as names and `true`/`false`."""
        flags = {
            "python": self.python,
            "lint": self.python or self.lint,
            "frontend": self.frontend,
            "contract": self.contract,
            "python_suites": self.python_suites,
            "frontend_docs": bool(self.frontend_docs_tests),
        }
        found = {name: str(value).lower() for name, value in flags.items()}
        # One line, space-separated, for `vitest run`; repository paths hold no spaces.
        found["frontend_docs_tests"] = " ".join(self.frontend_docs_tests)
        found["platform"] = str(self.platform).lower()
        return found


EVERYTHING = Scope(
    python=True, frontend=True, contract=False, reasons=("every lane: fail open",), platform=True
)


def _matches(path: str, patterns: tuple[str, ...] | frozenset[str]) -> bool:
    # fnmatch's `*` crosses `/`, as a shell `case` glob does, so `docs/*.md` covers every depth.
    return any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns)


def _sources(root: Path, top: str) -> list[Path]:
    base = root / top
    if not base.exists():
        return []
    return sorted(
        path
        for path in base.rglob("*")
        if path.is_file()
        and path.suffix in SOURCE_SUFFIXES
        and "node_modules" not in path.relative_to(root).parts
    )


def _reads(root: Path, tops: tuple[str, ...]) -> dict[str, tuple[set[str], set[str]]]:
    """Each source under `tops` that reads a document: what it names, and what it cites.

    A literal scan, not dependency analysis: it finds `"docs/x.md"`, `'README.md'` and a
    `(../docs/x.md#anchor)` citation, and a composed path needs an entry in
    COMPOSED_PYTHON_READS. Raises on a source it cannot decode, so the caller fails open.
    """
    found: dict[str, tuple[set[str], set[str]]] = {}
    for top in tops:
        for path in _sources(root, top):
            text = path.read_text(encoding="utf-8")
            named = set(LITERAL.findall(text))
            here = path.relative_to(root).parent.as_posix()
            cited = {
                posixpath.normpath(cite if cite.startswith("docs/") else posixpath.join(here, cite))
                for cite in CITATION.findall(text)
            }
            if named or cited:
                found[path.relative_to(root).as_posix()] = (named, cited)
    return found


def _documents_read(root: Path, tops: tuple[str, ...]) -> set[str]:
    """Documents a test or runtime source under `tops` names by literal path or cites by anchor."""
    found: set[str] = set()
    for named, cited in _reads(root, tops).values():
        found |= named | cited
    return found


def python_documents(root: Path) -> set[str]:
    """Documents the Python suites, or the runtime citations they check, read."""
    found = _documents_read(
        root,
        ("compass/skills/compass/tests", "scripts/tests", "compass/skills/compass/compass_runtime"),
    )
    return found | COMPOSED_PYTHON_READS


def bundle_sources(root: Path) -> set[str]:
    """The files `pnpm build` hashes into `react.integrity.json`, read from the builder itself.

    A change to any of them makes `pnpm build:check` fail until the bundle is rebuilt, wherever it
    lives; `.gitattributes` is one no location rule would send to the frontend lane. Raises when the
    list cannot be found, so the caller fails open.
    """
    source = (root / "frontend/build/package.mjs").read_text(encoding="utf-8")
    web = re.search(r"^const WEB = '([^']+)';", source, re.MULTILINE)
    body = re.search(r"async function authoredSources\(root\) \{(.*?)\];", source, re.DOTALL)
    if web is None or body is None:
        message = "frontend/build/package.mjs no longer lists its authored sources where expected"
        raise ValueError(message)
    found = set(re.findall(r"'([^'\n]+)'", body.group(1)))
    found |= {
        f"{web.group(1)}/{name}" for name in re.findall(r"`\$\{WEB\}/([^`]+)`", body.group(1))
    }
    if not found:
        message = "frontend/build/package.mjs lists no authored sources"
        raise ValueError(message)
    return found


def is_vitest_file(path: str) -> bool:
    """Whether `vitest run` collects this repository path."""
    return any(fnmatch.fnmatchcase(path, pattern) for pattern in VITEST_FILES)


@dataclass(frozen=True)
class FrontendReads:
    """Files the frontend reads outside its own tree, by what has to run when one changes.

    `whole` runs the whole lane: the bundle's inputs, and a document some file Vitest does not
    collect reads (a story, a proof, a build script), which no one Vitest file can stand for.
    `tests` maps every other document to the Vitest files that read it.
    """

    whole: frozenset[str]
    tests: dict[str, frozenset[str]]

    def __contains__(self, path: object) -> bool:
        return path in self.whole or path in self.tests


def frontend_documents(root: Path) -> FrontendReads:
    """What the frontend reads outside its own tree, and which of its files read it."""
    whole = set(bundle_sources(root))
    tests: dict[str, set[str]] = {}
    # Without the check a citation has no Vitest reader, so the whole lane stands in for one.
    check = (root / CITATION_CHECK).is_file()
    for source, (named, cited) in _reads(root, ("frontend",)).items():
        for document in named:
            if is_vitest_file(source):
                tests.setdefault(document, set()).add(source)
            else:
                whole.add(document)
        for document in cited:
            if check:
                tests.setdefault(document, set()).add(CITATION_CHECK)
            else:
                whole.add(document)
    return FrontendReads(
        whole=frozenset(whole),
        tests={doc: frozenset(found) for doc, found in tests.items() if doc not in whole},
    )


# ruff format reads these fences in every Markdown file but docs/plans (pyproject.toml).
PYTHON_FENCE = re.compile(r"^\s*```\s*(?:python3?|py|pyi)\b", re.MULTILINE)


def _formats_python(root: Path, path: str) -> bool:
    if not path.endswith(".md") or fnmatch.fnmatchcase(path, "docs/plans/*"):
        return False
    try:
        text = (root / path).read_text(encoding="utf-8")
    except FileNotFoundError:
        return False  # deleted: nothing left to format
    return PYTHON_FENCE.search(text) is not None


def _plugin_markdown(path: str) -> bool:
    return path.endswith(".md") and path.startswith(
        ("compass/", "compass-gemini/", "compass-droid/")
    )


def _script_javascript(path: str) -> bool:
    # Nothing ties a script's JavaScript to the frontend toolchain, but nothing stops it either.
    return path.startswith("scripts/") and path.endswith(JS_SUFFIXES)


# First match wins. The order is the decision: the gate's own wiring before prose, the built page
# and the runtime before the rest of the plugin, data before the code patterns that contain it.
RULES: tuple[tuple[Callable[[str], bool], frozenset[str]], ...] = (
    (lambda path: _matches(path, GATE_WIRING), frozenset({PYTHON, FRONTEND, PLATFORM})),
    (lambda path: _matches(path, PROSE), frozenset()),
    (lambda path: fnmatch.fnmatchcase(path, ".github/workflows/*"), frozenset()),
    # A Python test backend under frontend/test is ruff- and mypy-checked like any other.
    (
        lambda path: path.startswith("frontend/") and path.endswith(".py"),
        frozenset({PYTHON, FRONTEND}),
    ),
    (lambda path: path.startswith("frontend/"), frozenset({FRONTEND})),
    (
        lambda path: path in JS_TOOLING or fnmatch.fnmatchcase(path, "tsconfig*.json"),
        frozenset({FRONTEND}),
    ),
    (lambda path: fnmatch.fnmatchcase(path, WEB), frozenset({PYTHON, FRONTEND})),
    (lambda path: _matches(path, RUNTIME), frozenset({PYTHON, CONTRACT})),
    (_script_javascript, frozenset({PYTHON, FRONTEND})),
    # Python anywhere is linted and typed, whatever directory of data it sits in.
    (lambda path: path.endswith((".py", ".pyi")), frozenset({PYTHON})),
    (_plugin_markdown, frozenset({SUITES})),
    (lambda path: _matches(path, PYTHON_DATA), frozenset({SUITES})),
    (lambda path: _matches(path, BACKEND), frozenset({PYTHON})),
)


def _by_location(path: str) -> set[str]:
    for applies, found in RULES:
        if applies(path):
            return set(found)
    return {PYTHON, FRONTEND, PLATFORM}


def lanes(path: str, python_docs: set[str], frontend_docs: FrontendReads) -> set[str]:
    """The lanes one changed path turns on. Unknown paths turn on both full lanes and macOS.

    Who reads a file adds to what its location turns on, so a document a test reads is never
    prose, whatever its directory says.
    """
    read = {SUITES} if path in python_docs else set()
    if path in frontend_docs.whole:
        read.add(FRONTEND)
    elif path in frontend_docs.tests:
        read.add(FRONTEND_DOCS)
    if _matches(path, PLATFORM_PATHS):
        read.add(PLATFORM)
    return read | _by_location(path)


def scope(
    paths: list[str], root: Path, documents: tuple[set[str], FrontendReads] | None = None
) -> Scope:
    """The lanes a set of changed paths turns on, read against the sources under `root`.

    `documents` is the (Python, frontend) document scan, when the caller already has it.
    """
    paths = [path for path in paths if path]
    if not paths:
        return EVERYTHING
    python_docs, frontend_docs = documents or (python_documents(root), frontend_documents(root))
    on: set[str] = set()
    tests: set[str] = set()
    reasons = []
    for path in paths:
        found = lanes(path, python_docs, frontend_docs)
        if _formats_python(root, path):
            found.add(LINT)
        on |= found
        tests |= frontend_docs.tests.get(path, frozenset())
        reasons.append(f"{path}: {', '.join(sorted(found)) or 'prose'}")
    return Scope(
        python=PYTHON in on,
        frontend=FRONTEND in on,
        contract=CONTRACT in on and FRONTEND not in on,
        reasons=tuple(reasons),
        suites=SUITES in on,
        lint=LINT in on,
        # The whole lane runs every Vitest file already.
        frontend_docs_tests=() if FRONTEND in on else tuple(sorted(tests)),
        platform=PLATFORM in on,
    )


def changed_paths(base: str, head: str) -> list[str] | None:
    """The paths a pull request changes against its merge base, or None when Git cannot say."""

    def git(*args: str) -> str | None:
        result = subprocess.run(  # noqa: S603 - fixed git argv, no shell
            ["git", *args],  # noqa: S607 - git from PATH, as the workflow's checkout does
            capture_output=True,
            text=True,
            check=False,
        )
        return result.stdout if result.returncode == 0 else None

    merge_base = git("merge-base", base, head)
    if not merge_base or not merge_base.strip():
        return None
    # --no-renames lists a move's old path too: something may still read the file it left.
    diff = git("diff", "--name-only", "--no-renames", merge_base.strip(), head)
    return diff.splitlines() if diff else None


def decide(event: str, base: str, head: str, root: Path) -> Scope:
    """The scope of one workflow run. Every failure resolves to every lane on.

    Anything but a pull request (a push to main, the nightly schedule, a manual dispatch) runs
    everything, macOS included: that is the safety net for what a pull request's lanes skipped.
    """
    if event != "pull_request" or not base or not head:
        return EVERYTHING
    try:
        paths = changed_paths(base, head)
        return scope(paths, root) if paths else EVERYTHING
    except (OSError, UnicodeDecodeError, ValueError):
        return EVERYTHING


def main(argv: list[str] | None = None) -> int:
    """Print the lanes; append them to `$GITHUB_OUTPUT` when it is set."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--event", default=os.environ.get("EVENT", ""))
    parser.add_argument("--base", default=os.environ.get("BASE_SHA", ""))
    parser.add_argument("--head", default=os.environ.get("HEAD_SHA", ""))
    parser.add_argument("--root", type=Path, default=Path())
    parser.add_argument(
        "--paths", nargs="*", help="classify these paths instead of asking Git (for a dry run)"
    )
    args = parser.parse_args(argv)
    if args.paths is not None:
        try:
            result = scope(args.paths, args.root)
        except (OSError, UnicodeDecodeError, ValueError):
            result = EVERYTHING
    else:
        result = decide(args.event, args.base, args.head, args.root)
    for line in result.reasons:
        print(line)
    lines = [f"{name}={value}" for name, value in result.outputs().items()]
    print("\n".join(lines))
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with Path(output).open("a", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
