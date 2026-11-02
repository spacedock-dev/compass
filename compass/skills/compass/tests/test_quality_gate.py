"""Exercise the shipped detector step with controlled Git diff inputs."""

from __future__ import annotations

import functools
import importlib.util
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[4]
BASH = shutil.which("bash")
SCOPE = Path("scripts/ci_scope.py")

# Git's two read results are the only fixtures; the step and the classification are the shipped
# ones, so a change to either reaches these tests.
FAKE_GIT = """#!/bin/sh
case "$1" in
  merge-base) echo fixture-base ;;
  diff) printf '%s\\n' "$CHANGED" ;;
  *) exit 1 ;;
esac
"""


@functools.cache
def _ci_scope() -> Any:
    """The shipped detector module, loaded from the repository as the workflow runs it."""
    spec = importlib.util.spec_from_file_location("ci_scope_under_test", ROOT / SCOPE)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # its dataclass resolves annotations through sys.modules
    spec.loader.exec_module(module)
    return module


@functools.cache
def _repository_documents() -> Any:
    """The document scan of this repository, read once for every in-process case."""
    module = _ci_scope()
    return (module.python_documents(ROOT), module.frontend_documents(ROOT))


def detect_in_process(changed: str) -> dict[str, str]:
    """The lanes `scripts/ci_scope.py` decides for these paths, without starting Bash or Python.

    Each shell round trip costs about 0.9 s, so the many-path cases call the same `scope`
    function the script's entry point calls; `detect` keeps one real run of the shipped step per
    class, and the test beside it compares the two.
    """
    paths = changed.splitlines()
    return dict(_ci_scope().scope(paths, ROOT, documents=_repository_documents()).outputs())


def detect_step() -> str:
    workflow = yaml.safe_load((ROOT / ".github/workflows/quality-gate.yml").read_text())
    return str(
        next(
            step["run"]
            for step in workflow["jobs"]["changes"]["steps"]
            if step.get("id") == "detect"
        )
    )


@unittest.skipUnless(BASH, "the Actions detector needs bash")
class QualityGateDetectorTest(unittest.TestCase):
    def detect(
        self, changed: str, *, root: Path = ROOT, python: str | None = None
    ) -> dict[str, str]:
        """The lanes the shipped step writes to `$GITHUB_OUTPUT` for one changed-path list."""
        with tempfile.TemporaryDirectory(prefix="bld-hyg-gate-") as tmp:
            bin_dir = Path(tmp) / "bin"
            bin_dir.mkdir()
            git = bin_dir / "git"
            git.write_text(FAKE_GIT)
            git.chmod(0o755)
            if python is not None:
                fake = bin_dir / "python3"
                fake.write_text(python)
                fake.chmod(0o755)
            if root != ROOT:
                (root / SCOPE).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy(ROOT / SCOPE, root / SCOPE)
            output = Path(tmp) / "output"
            subprocess.run(
                [BASH or "bash", "-c", detect_step()],
                cwd=root,
                env={
                    **os.environ,
                    "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
                    "EVENT": "pull_request",
                    "BASE_SHA": "base",
                    "HEAD_SHA": "head",
                    "CHANGED": changed,
                    "GITHUB_OUTPUT": str(output),
                },
                capture_output=True,
                text=True,
                check=True,
                timeout=30,
            )
            return dict(line.split("=", 1) for line in output.read_text().split())

    def test_content_dependencies_run_the_python_suites(self) -> None:
        for name in (
            "captures/README.md",
            "design-event-driven-observation.md",
            "design-reader-state.md",
            "promise-map.md",
        ):
            with self.subTest(name=name):
                self.assertEqual("true", detect_in_process("docs/" + name)["python_suites"])
        for name in ("README.md", "SECURITY.md"):
            with self.subTest(name=name):
                self.assertEqual("true", detect_in_process(name)["python_suites"])

    def test_the_shipped_step_agrees_with_the_in_process_call(self) -> None:
        """The one real run of the workflow step the in-process cases stand in for."""
        for changed in ("docs/promise-map.md", "docs/" + "design-harness-registry.md", "README.md"):
            with self.subTest(changed=changed):
                self.assertEqual(detect_in_process(changed), self.detect(changed))

    def test_documents_only_the_citation_checker_reads_run_the_python_suites(self) -> None:
        """A doc reached only through a runtime citation link is still a dependency.

        Separate from the case above because these arrive by a different route
        and the first arm cannot fail on them: none of its five names is
        cited-only, so dropping the citation derivation from the detector left
        that test green. Measured when the checker landed: nine documents were
        reachable this way and absent from the deny list.

        The names are derived here for the same reason the detector derives
        them. Hard-coding `design-daemon.md` would pass for as long as that one
        citation happens to exist, which is a property of today's comments
        rather than of the rule.
        """
        runtime = Path("compass/skills/compass/compass_runtime")
        cited = {
            match.group(1)
            for path in runtime.rglob("*")
            if path.is_file() and path.suffix in {".py", ".js", ".css", ".html"}
            for match in re.finditer(
                r"\((docs/[^)]+\.md)#", path.read_text(encoding="utf-8", errors="replace")
            )
        }
        self.assertTrue(cited, "no runtime citation links found, so this asserts nothing")
        for name in sorted(cited):
            with self.subTest(name=name):
                self.assertEqual("true", detect_in_process(name)["python_suites"])

    def test_unasserted_prose_runs_no_lane(self) -> None:
        self.assertEqual(
            {
                "python": "false",
                "lint": "false",
                "frontend": "false",
                "contract": "false",
                "python_suites": "false",
            },
            self.detect("docs/" + "design-harness-registry.md"),
        )

    def test_unknown_diff_fails_open(self) -> None:
        found = self.detect("")
        self.assertEqual(("true", "true"), (found["python"], found["frontend"]))

    def test_a_detector_that_cannot_run_turns_every_lane_on(self) -> None:
        found = self.detect("docs/" + "design-harness-registry.md", python="#!/bin/sh\nexit 1\n")
        self.assertEqual(
            {
                "python": "true",
                "lint": "true",
                "frontend": "true",
                "contract": "false",
                "python_suites": "true",
            },
            found,
        )
