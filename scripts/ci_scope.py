#!/usr/bin/env python3
"""Decide which of the quality gate's lanes a pull request's changes can affect.

`quality-gate.yml` and `validate.yml` both run this before anything measurable, and each job
runs only when a lane it belongs to is on. There are three lanes:

- ``python``: ruff, mypy, the coverage run and the macOS legs. On when Python or what the Python
  suites assert on changed.
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
# What `pnpm test:dev` starts and the Vitest and build tests import. The page under `web/` is not
# here: it is built output, and a change to it runs the whole frontend lane.
RUNTIME = ("compass/skills/compass/server.py", "compass/skills/compass/compass_runtime/*")
WEB = "compass/skills/compass/compass_runtime/web/*"

# `docs/captures/README.md` is read through a path DocumentedCaptureFiguresTest composes from
# CAPTURES, which no literal scan finds. Composed reads need a reviewed entry here.
COMPOSED_PYTHON_READS = frozenset({"docs/captures/README.md"})

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
        }
        return {name: str(value).lower() for name, value in flags.items()}


EVERYTHING = Scope(python=True, frontend=True, contract=False, reasons=("every lane: fail open",))


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


def _documents_read(root: Path, tops: tuple[str, ...]) -> set[str]:
    """Documents a test or runtime source under `tops` names by literal path or cites by anchor.

    A literal scan, not dependency analysis: it finds `"docs/x.md"`, `'README.md'` and a
    `(../docs/x.md#anchor)` citation, and a composed path needs an entry in
    COMPOSED_PYTHON_READS. Raises on a source it cannot decode, so the caller fails open.
    """
    found: set[str] = set()
    for top in tops:
        for path in _sources(root, top):
            text = path.read_text(encoding="utf-8")
            found.update(LITERAL.findall(text))
            here = path.relative_to(root).parent.as_posix()
            for cited in CITATION.findall(text):
                joined = cited if cited.startswith("docs/") else posixpath.join(here, cited)
                found.add(posixpath.normpath(joined))
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


def frontend_documents(root: Path) -> set[str]:
    """Files the frontend reads outside its own tree: documents its sources cite, bundle inputs."""
    return _documents_read(root, ("frontend",)) | bundle_sources(root)


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
    (lambda path: _matches(path, GATE_WIRING), frozenset({PYTHON, FRONTEND})),
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
    return {PYTHON, FRONTEND}


def lanes(path: str, python_docs: set[str], frontend_docs: set[str]) -> set[str]:
    """The lanes one changed path turns on. Unknown paths turn on both full lanes.

    Who reads a file adds to what its location turns on, so a document a test reads is never
    prose, whatever its directory says.
    """
    read = {SUITES} if path in python_docs else set()
    if path in frontend_docs:
        read.add(FRONTEND)
    return read | _by_location(path)


def scope(
    paths: list[str], root: Path, documents: tuple[set[str], set[str]] | None = None
) -> Scope:
    """The lanes a set of changed paths turns on, read against the sources under `root`.

    `documents` is the (Python, frontend) document scan, when the caller already has it.
    """
    paths = [path for path in paths if path]
    if not paths:
        return EVERYTHING
    python_docs, frontend_docs = documents or (python_documents(root), frontend_documents(root))
    on: set[str] = set()
    reasons = []
    for path in paths:
        found = lanes(path, python_docs, frontend_docs)
        if _formats_python(root, path):
            found.add(LINT)
        on |= found
        reasons.append(f"{path}: {', '.join(sorted(found)) or 'prose'}")
    return Scope(
        python=PYTHON in on,
        frontend=FRONTEND in on,
        contract=CONTRACT in on and FRONTEND not in on,
        reasons=tuple(reasons),
        suites=SUITES in on,
        lint=LINT in on,
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
    """The scope of one workflow run. Every failure resolves to every lane on."""
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
