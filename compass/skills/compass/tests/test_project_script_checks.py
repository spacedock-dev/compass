"""A project's own check scripts: when `pnpm typecheck` or `make test` reads as a check.

[DEC-29](docs/design-reading-a-session.md#dec-29-a-commands-result-is-evidence-by-tier-and-a-command-that-cannot-fail-never-passes)
rules the tiers, and the 2026-10-27 amendment under it says how a declared script counts. Every
repository, script and path here is synthetic.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import json
import os
import shutil
import subprocess
import time
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from compass_runtime import (
    diagnostics,
    git_status,
    live_estimate,
    project_context,
    project_scripts,
    session_source,
)

from . import support
from .test_claude_checks import ClaudeChecksTestCase

GIT = shutil.which("git")
BEFORE_THE_SESSION = "2026-09-01T00:00:00Z"
AFTER_THE_SESSION = "2026-10-20T00:00:00Z"


def git(root: Path, *args: str, when: str = BEFORE_THE_SESSION) -> None:
    environment = {
        **os.environ,
        "GIT_AUTHOR_DATE": when,
        "GIT_COMMITTER_DATE": when,
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_SYSTEM": os.devnull,
    }
    subprocess.run(
        [
            GIT or "git",
            "-c",
            "user.email=dev@example.test",
            "-c",
            "user.name=Dev",
            "-c",
            "commit.gpgsign=false",
            *args,
        ],
        cwd=root,
        env=environment,
        check=True,
        capture_output=True,
    )


def package(**scripts: str) -> str:
    return json.dumps({"name": "widgets", "scripts": scripts})


@unittest.skipIf(GIT is None, "git is not on PATH")
class ProjectScriptTestCase(ClaudeChecksTestCase):
    def setUp(self) -> None:
        super().setUp()
        project_scripts.reset()
        self.addCleanup(project_scripts.reset)
        git(self.cwd, "init", "-q")

    def fresh_repo(self) -> None:
        """A new repository in the same folder, for a subtest that commits again."""
        project_scripts.reset()
        shutil.rmtree(self.cwd / ".git")
        git(self.cwd, "init", "-q")

    def commit(self, files: dict[str, str], *, when: str = BEFORE_THE_SESSION) -> None:
        for name, text in files.items():
            (self.cwd / name).write_text(text, encoding="utf-8")
        git(self.cwd, "add", "-A")
        git(self.cwd, "commit", "-q", "-m", "base", when=when)

    def titles(self, subject: str = "check") -> list[str]:
        return [e["title"] for e in self.read()[0] if e["subject"] == subject]

    def ran(self, command: str, *, is_error: bool = False) -> None:
        self.session.bash(command, "output", is_error=is_error)


class ADeclaredScriptReadsAsACheck(ProjectScriptTestCase):
    def test_a_typecheck_script_whose_body_is_a_runner_is_a_check_with_its_result(self) -> None:
        self.commit({"package.json": package(typecheck="tsc --noEmit")})
        self.ran("pnpm typecheck")
        check = self.only_check()
        self.assertEqual(("pnpm typecheck", "passed"), (check["title"], check["result"]))
        self.assertEqual([], self.titles("command"))

    def test_a_failing_declared_script_is_a_failed_check(self) -> None:
        self.commit({"package.json": package(lint="eslint .")})
        self.ran("pnpm lint", is_error=True)
        self.assertEqual("failed", self.only_check()["result"])

    def test_no_git_stops_the_read_so_the_script_is_a_command_again(self) -> None:
        self.config = dataclasses.replace(self.config, git_probe_enabled=False)
        self.commit({"package.json": package(typecheck="tsc --noEmit")})
        self.ran("pnpm typecheck")
        self.assertEqual([], self.titles())
        self.assertEqual(["pnpm typecheck"], self.titles("command"))

    def test_every_package_manager_spelling_of_a_declared_script_counts(self) -> None:
        self.commit({"package.json": package(typecheck="tsc --noEmit")})
        for command in ("npm run typecheck", "pnpm run typecheck", "yarn typecheck"):
            with self.subTest(command=command):
                self.ran(command)
        self.assertEqual(3, len(self.checks()))

    def test_a_chain_of_runners_and_a_script_that_names_another_script_count(self) -> None:
        self.commit(
            {
                "package.json": package(
                    lint="eslint .",
                    typecheck="tsc --noEmit",
                    check="pnpm lint && pnpm run typecheck",
                    **{"test:unit": "vitest run && mypy ."},
                )
            }
        )
        for command in ("pnpm check", "pnpm test:unit"):
            self.ran(command)
        self.assertEqual({"pnpm check", "pnpm test:unit"}, set(self.titles()))

    def test_a_body_that_is_biome_storybook_or_gradle_counts(self) -> None:
        self.commit(
            {
                "package.json": package(
                    lint="biome check --error-on-warnings",
                    **{"check:ci": "biome ci ."},
                    **{"test:stories": "storybook test", "test:sb": "test-storybook --ci"},
                    **{"test:java": "./gradlew check", "test:g": "gradle test"},
                )
            }
        )
        for name in ("lint", "check:ci", "test:stories", "test:sb", "test:java", "test:g"):
            self.ran(f"pnpm run {name}")
        self.assertEqual(6, len(self.checks()))

    def test_a_make_target_and_a_just_recipe_count_the_same_way(self) -> None:
        self.commit(
            {
                "Makefile": ".PHONY: lint test-all check-all\nlint:\n\truff check .\n"
                "test-all:\n\t@pytest -q\ncheck-all: lint test-all\n",
                "justfile": "typecheck:\n    mypy .\n",
            }
        )
        for command in ("make lint", "make check-all", "make -s test-all", "just typecheck"):
            self.ran(command)
        self.assertEqual(
            {"make lint", "make check-all", "make -s test-all", "just typecheck"},
            set(self.titles()),
        )

    def test_scripts_that_name_each_other_in_a_circle_never_count_and_never_loop(self) -> None:
        self.commit(
            {"package.json": package(**{"test:a": "pnpm run test:b", "test:b": "pnpm run test:a"})}
        )
        self.ran("pnpm run test:a")
        self.ran("pnpm run test:b")
        self.assertEqual([], self.titles())

    def test_a_hook_script_that_is_not_a_check_withdraws_its_script(self) -> None:
        self.commit({"package.json": package(lint="eslint .", prelint="node scripts/seed.js")})
        self.ran("pnpm run lint")
        self.assertEqual([], self.titles())


class ANameOrABodyThatIsNotACheckNeverCounts(ProjectScriptTestCase):
    def test_a_fixer_an_always_zero_body_and_a_deploy_never_count(self) -> None:
        self.commit(
            {
                "package.json": package(
                    format="biome format --write",
                    verify="exit 0",
                    deploy="vercel deploy --prod",
                    **{
                        "lint:fix": "eslint --fix .",
                        "test:watch": "vitest",
                        "check:publish": "tsc --noEmit && npm publish",
                        "typecheck": "tsc --noEmit || true",
                        "build:clean": "tsc --build --clean",
                    },
                )
            }
        )
        for name in (
            "format",
            "verify",
            "deploy",
            "lint:fix",
            "test:watch",
            "check:publish",
            "typecheck",
            "build:clean",
        ):
            self.ran(f"pnpm run {name}")
        self.assertEqual([], self.titles())
        self.assertEqual(8, len(self.titles("command")))

    def test_a_body_rule_refuses_what_a_name_rule_would_let_through(self) -> None:
        self.commit(
            {
                "package.json": package(
                    **{
                        "lint": "eslint --fix .",
                        "check": "ruff check --fix .",
                        "test:e": "exit 0",
                        "test:a": "ruff check . > out.txt",
                        "test:b": "pytest -q && ./push.sh",
                        "test:c": "jest -u",
                        "test:d": "pytest --snapshot-update",
                        "lint:a": "rubocop -A",
                        "lint:b": "ruff check --fix-only .",
                        "typecheck": "tsc --noEmit --watch",
                    }
                )
            }
        )
        for name in (
            "lint",
            "check",
            "test:e",
            "test:a",
            "test:b",
            "test:c",
            "test:d",
            "lint:a",
            "lint:b",
            "typecheck",
        ):
            self.ran(f"pnpm run {name}")
        self.assertEqual([], self.titles())

    def test_a_body_that_fixes_biome_or_updates_storybook_snapshots_never_counts(self) -> None:
        self.commit(
            {
                "package.json": package(
                    **{
                        "lint:a": "biome check --apply",
                        "lint:b": "biome check --apply-unsafe",
                        "lint:c": "biome check --unsafe",
                        "test:a": "storybook test --update-snapshot",
                        "test:b": "test-storybook --update-snapshot",
                    }
                )
            }
        )
        for name in ("lint:a", "lint:b", "lint:c", "test:a", "test:b"):
            self.ran(f"pnpm run {name}")
        self.assertEqual([], self.titles())

    def test_a_warning_filter_in_a_body_is_not_a_writing_argument(self) -> None:
        self.commit({"package.json": package(**{"test:w": "python -m pytest -W error"})})
        self.ran("npm run test:w")
        self.assertEqual(["npm run test:w"], self.titles())

    def test_a_body_with_a_redirect_a_subshell_or_a_substitution_does_not_count(self) -> None:
        self.commit(
            {
                "package.json": package(
                    **{
                        "test:a": "vitest run > out.log",
                        "test:b": "(vitest run)",
                        "test:c": "vitest run $(rm -rf dist)",
                        "test:d": "vitest run; echo done",
                        "test:e": "vitest run | tee out.log",
                    }
                )
            }
        )
        for name in ("test:a", "test:b", "test:c", "test:d", "test:e"):
            self.ran(f"pnpm run {name}")
        self.assertEqual([], self.titles())

    def test_make_targets_that_deploy_clean_or_ignore_failure_do_not_count(self) -> None:
        self.commit(
            {
                "Makefile": "test-all:\n\t-pytest -q\nlint:\n\truff check $(DIR)\n"
                "build-all: clean\n\ttsc -b\nclean:\n\trm -rf dist\n"
                "deploy:\n\tpytest -q\n\t./push.sh\n",
            }
        )
        for target in ("test-all", "lint", "build-all", "clean", "deploy"):
            self.ran(f"make {target}")
        self.assertEqual([], self.titles())

    def test_a_writing_argument_a_filter_and_a_variable_override_do_not_count(self) -> None:
        self.commit(
            {
                "package.json": package(typecheck="tsc --noEmit"),
                "Makefile": "lint:\n\truff check .\n",
            }
        )
        for command in (
            "pnpm typecheck --fix",
            "pnpm --filter app typecheck",
            "pnpm -r run typecheck",
            "make lint RUFF_ARGS=--fix",
            "make -C sub lint",
        ):
            self.ran(command)
        self.assertEqual([], self.titles())

    def test_an_option_after_the_name_or_a_steering_variable_leaves_the_script_a_command(
        self,
    ) -> None:
        self.commit(
            {
                "package.json": package(typecheck="tsc --noEmit"),
                "Makefile": ".PHONY: lint\nlint:\n\truff check .\n",
            }
        )
        refused = (
            "npm run typecheck --prefix sub",
            "npm run typecheck --workspaces",
            "npm run typecheck -ws",
            "npm run typecheck --script-shell=/usr/bin/true",
            "pnpm typecheck --filter a",
            "pnpm typecheck --dir sub",
            "pnpm typecheck -- --fix",
            "npm_config_script_shell=/usr/bin/true npm run typecheck",
            "env NPM_CONFIG_PREFIX=sub npm run typecheck",
            "MAKEFLAGS=-n make lint",
            "MAKE=true make lint",
        )
        for command in refused:
            self.ran(command)
        self.assertEqual([], self.titles())

    def test_a_steering_variable_set_earlier_in_the_same_call_leaves_the_script_a_command(
        self,
    ) -> None:
        self.commit(
            {
                "package.json": package(typecheck="tsc --noEmit"),
                "Makefile": ".PHONY: lint\nlint:\n\truff check .\n",
            }
        )
        refused = (
            "env MAKEFLAGS=-n make lint",
            "export MAKEFLAGS=-n; make lint",
            "export MAKEFLAGS=-n && make lint",
            "MAKEFLAGS=-n; make lint",
            "declare -x MAKEFLAGS=-n && make lint",
            "MAKEFLAGS=n make lint",
            "GNUMAKEFLAGS=-n make lint",
            "MFLAGS=-n make lint",
            "MAKEFILES=other.mk make lint",
            "export npm_config_script_shell=/usr/bin/true; npm run typecheck",
            "export NPM_CONFIG_PREFIX=sub && pnpm typecheck",
            "make MAKEFLAGS=-n lint",
        )
        for command in refused:
            self.ran(command)
        self.assertEqual([], self.titles())

    def test_a_make_option_that_stops_the_recipe_running_leaves_the_target_a_command(self) -> None:
        self.commit({"Makefile": ".PHONY: lint\nlint:\n\truff check .\n"})
        for command in (
            "make -n lint",
            "make --dry-run lint",
            "make --just-print lint",
            "make --recon lint",
            "make -q lint",
            "make --question lint",
            "make -t lint",
            "make --touch lint",
            "make -sn lint",
            "make lint -n",
        ):
            self.ran(command)
        self.assertEqual([], self.titles())

    def test_a_linter_told_to_exit_zero_is_not_a_check_in_a_declared_body(self) -> None:
        for body in (
            "ruff check . --exit-zero",
            "pylint src --exit-zero",
            "flake8 . --exit-zero",
            "bandit -r src --exit-zero",
            "golangci-lint run --issues-exit-code=0",
            "golangci-lint run --issues-exit-code 0",
            "eslint . || true",
            "mypy . || true",
            "uv run ruff check --exit-zero .",
        ):
            with self.subTest(body=body):
                project_scripts.reset()
                self.commit({"package.json": package(lint=body)})
                self.ran("pnpm lint")
                self.assertEqual([], self.titles())

    def test_a_linter_that_exits_nonzero_on_findings_still_counts(self) -> None:
        self.commit({"package.json": package(lint="golangci-lint run --issues-exit-code=2")})
        self.ran("pnpm lint")
        self.assertEqual(["pnpm lint"], self.titles())

    def test_an_exit_zero_flag_in_a_reader_listed_command_never_counts(self) -> None:
        reason, _program = project_context.listed_entry_refusal("ruff check . --exit-zero")
        self.assertTrue(reason)

    def test_an_argument_forwarded_after_a_double_dash_still_counts(self) -> None:
        self.commit({"package.json": package(typecheck="tsc")})
        self.ran("npm run typecheck -- --noEmit")
        self.assertEqual(["npm run typecheck -- --noEmit"], self.titles())

    def test_a_script_the_file_does_not_declare_is_not_guessed_from_its_name(self) -> None:
        self.commit({"package.json": package(typecheck="tsc --noEmit")})
        self.ran("pnpm lint")
        self.assertEqual([], self.titles())

    def test_a_command_in_a_subfolder_runs_that_folders_scripts_and_is_not_read(self) -> None:
        self.commit({"package.json": package(typecheck="tsc --noEmit")})
        (self.cwd / "packages" / "app").mkdir(parents=True)
        self.ran(f"cd {self.cwd / 'packages' / 'app'} && pnpm typecheck")
        self.assertEqual([], self.titles())


class AClosedListNameTheProjectDeclaresIsJudgedByItsBody(ProjectScriptTestCase):
    """`pnpm test` is the usual runner until the project declares a `test` of its own."""

    NAMES = (
        ("test", "pnpm test"),
        ("test", "npm test"),
        ("test", "npm run test"),
        ("test", "yarn test"),
        ("test:stories", "pnpm test:stories"),
        ("test:stories", "pnpm run test:stories"),
        ("test:stories", "yarn test:stories"),
    )

    def declare(self, body: str) -> None:
        self.commit({"package.json": package(**{"test": body, "test:stories": body})})

    def test_a_body_that_is_not_a_check_makes_the_invocation_an_ordinary_command(self) -> None:
        for body in ("echo skipped", "true", "storybook test -u", "biome check --apply"):
            with self.subTest(body=body):
                project_scripts.reset()
                self.declare(body)
                for _script, command in self.NAMES:
                    self.ran(command)
                self.assertEqual([], self.titles())

    def test_a_call_with_options_the_body_can_still_decide_reads_by_the_body(self) -> None:
        self.declare("echo skipped")
        for command in (
            "pnpm test --reporter x",
            "pnpm test --run",
            "pnpm test:stories --foo",
            "npm test -- --watch",
            "npm test -- --run",
            "npm run test -- -u",
            "yarn test --coverage",
        ):
            with self.subTest(command=command):
                self.ran(command)
        self.assertEqual([], self.titles())

    def test_a_call_that_selects_another_package_keeps_the_closed_list(self) -> None:
        self.declare("echo skipped")
        selecting = ("pnpm test --filter web", "npm test --workspace web")
        for command in selecting:
            self.ran(command)
        self.assertEqual(sorted(selecting), sorted(self.titles()))

    def test_a_body_that_is_a_runner_still_counts(self) -> None:
        self.declare("vitest run")
        for _script, command in self.NAMES:
            self.ran(command)
        self.assertEqual(sorted(command for _script, command in self.NAMES), sorted(self.titles()))

    def test_without_a_declared_script_of_that_name_the_closed_list_stands(self) -> None:
        self.commit({"package.json": package(lint="eslint .")})
        self.ran("pnpm test")
        self.ran("pnpm test:stories")
        self.assertEqual(["pnpm test", "pnpm test:stories"], sorted(self.titles()))

    def test_with_no_declarations_read_the_closed_list_stands(self) -> None:
        self.config = dataclasses.replace(self.config, git_probe_enabled=False)
        self.commit({"package.json": package(test="echo skipped")})
        self.ran("npm test")
        self.assertEqual(["npm test"], self.titles())


class ASessionThatChangedADeclaringFileDeclaresNothing(ProjectScriptTestCase):
    def test_a_package_json_the_session_edited_declares_nothing(self) -> None:
        self.commit({"package.json": package(typecheck="tsc --noEmit")})
        self.session.edit(self.file("package.json"))
        self.ran("pnpm typecheck")
        self.assertEqual([], self.titles())

    def test_a_write_to_a_declaring_file_withdraws_only_its_own_kind(self) -> None:
        self.commit(
            {"package.json": package(typecheck="tsc --noEmit"), "justfile": "check:\n    mypy .\n"}
        )
        self.session.write(self.file("package.json"), package(typecheck="tsc --noEmit"))
        self.ran("pnpm typecheck")
        self.ran("just check")
        self.assertEqual(["just check"], self.titles())

    def test_a_file_changed_by_a_shell_command_differs_from_the_commit_and_declares_nothing(
        self,
    ) -> None:
        self.commit({"package.json": package(typecheck="tsc --noEmit")})
        (self.cwd / "package.json").write_text(package(typecheck="echo ok"), encoding="utf-8")
        self.ran("pnpm typecheck")
        self.assertEqual([], self.titles())
        self.assertEqual(
            project_scripts.EDITED_REASON,
            {p["file"]: p["reason"] for p in project_scripts.problems()}[
                os.path.join(os.path.realpath(self.cwd), "package.json")
            ],
        )

    def test_a_commit_made_after_the_session_began_is_never_the_base(self) -> None:
        self.commit({"package.json": package(lint="eslint .")})
        self.commit(
            {"package.json": package(lint="eslint .", typecheck="tsc")}, when=AFTER_THE_SESSION
        )
        self.ran("pnpm typecheck")
        self.assertEqual([], self.titles())

    def test_a_repository_with_nothing_before_the_session_declares_nothing(self) -> None:
        self.commit({"package.json": package(typecheck="tsc --noEmit")}, when=AFTER_THE_SESSION)
        self.ran("pnpm typecheck")
        self.assertEqual([], self.titles())


class MakeReadsOnlyTheFirstMakefileItFinds(ProjectScriptTestCase):
    def test_a_target_only_the_shadowed_makefile_declares_does_not_count(self) -> None:
        self.commit(
            {
                "GNUmakefile": ".PHONY: lint\nlint:\n\truff check .\n",
                "Makefile": ".PHONY: lint test-all\nlint:\n\techo no\ntest-all:\n\tpytest -q\n",
            }
        )
        self.ran("make lint")
        self.ran("make test-all")
        self.assertEqual(["make lint"], self.titles())

    def test_the_first_file_wins_even_where_the_later_one_declares_the_target_as_a_check(
        self,
    ) -> None:
        self.commit(
            {
                "GNUmakefile": ".PHONY: lint\nlint:\n\techo done\n",
                "Makefile": ".PHONY: lint\nlint:\n\truff check .\n",
            }
        )
        self.ran("make lint")
        self.assertEqual([], self.titles())

    def test_a_makefile_make_would_now_read_first_withdraws_every_target(self) -> None:
        self.commit({"Makefile": ".PHONY: lint\nlint:\n\truff check .\n"})
        (self.cwd / "GNUmakefile").write_text(".PHONY: lint\nlint:\n\ttrue\n", encoding="utf-8")
        self.ran("make lint")
        self.assertEqual([], self.titles())


class ALaterEditToTheFileDoesNotWithdrawADeclarationItDidNotChange(ProjectScriptTestCase):
    def package_with(self, dependency: str, **scripts: str) -> str:
        return json.dumps(
            {"name": "widgets", "dependencies": {"left-pad": dependency}, "scripts": scripts}
        )

    def test_a_dependency_bump_keeps_the_declared_checks(self) -> None:
        self.commit({"package.json": self.package_with("1.0.0", typecheck="tsc --noEmit")})
        (self.cwd / "package.json").write_text(
            self.package_with("2.0.0", typecheck="tsc --noEmit"), encoding="utf-8"
        )
        self.ran("pnpm typecheck")
        self.assertEqual(["pnpm typecheck"], self.titles())

    def test_a_changed_script_body_drops_that_script_and_keeps_the_others(self) -> None:
        self.commit(
            {"package.json": self.package_with("1.0.0", typecheck="tsc --noEmit", lint="eslint .")}
        )
        (self.cwd / "package.json").write_text(
            self.package_with("1.0.0", typecheck="tsc --noEmit && true", lint="eslint ."),
            encoding="utf-8",
        )
        self.ran("pnpm typecheck")
        self.ran("pnpm lint")
        self.assertEqual(["pnpm lint"], self.titles())

    def test_a_hook_added_after_the_base_withdraws_the_script_it_wraps(self) -> None:
        self.commit({"package.json": self.package_with("1.0.0", lint="eslint .")})
        (self.cwd / "package.json").write_text(
            self.package_with("1.0.0", lint="eslint .", prelint="node scripts/seed.js"),
            encoding="utf-8",
        )
        self.ran("pnpm lint")
        self.assertEqual([], self.titles())

    def test_a_script_that_names_a_changed_script_is_withdrawn_with_it(self) -> None:
        self.commit(
            {
                "package.json": self.package_with(
                    "1.0.0", lint="eslint .", check="pnpm lint && tsc --noEmit"
                )
            }
        )
        (self.cwd / "package.json").write_text(
            self.package_with("1.0.0", lint="eslint . --fix", check="pnpm lint && tsc --noEmit"),
            encoding="utf-8",
        )
        self.ran("pnpm check")
        self.assertEqual([], self.titles())

    def test_a_makefile_comment_edit_keeps_its_targets_and_a_changed_recipe_drops_one(self) -> None:
        self.commit(
            {
                "Makefile": ".PHONY: lint test-all\nlint:\n\truff check .\ntest-all:\n\tpytest -q\n",
            }
        )
        (self.cwd / "Makefile").write_text(
            "# a note\n.PHONY: lint test-all\nlint:\n\truff check .\ntest-all:\n\tpytest -q || true\n",
            encoding="utf-8",
        )
        self.ran("make lint")
        self.ran("make test-all")
        self.assertEqual(["make lint"], self.titles())

    def test_a_session_write_to_the_file_still_drops_every_script_in_it(self) -> None:
        self.commit({"package.json": self.package_with("1.0.0", typecheck="tsc --noEmit")})
        self.session.write(
            self.file("package.json"), self.package_with("2.0.0", typecheck="tsc --noEmit")
        )
        (self.cwd / "package.json").write_text(
            self.package_with("2.0.0", typecheck="tsc --noEmit"), encoding="utf-8"
        )
        self.ran("pnpm typecheck")
        self.assertEqual([], self.titles())

    def test_a_working_file_that_will_not_parse_declares_nothing(self) -> None:
        self.commit({"package.json": self.package_with("1.0.0", typecheck="tsc --noEmit")})
        (self.cwd / "package.json").write_text("{", encoding="utf-8")
        self.ran("pnpm typecheck")
        self.assertEqual([], self.titles())


class ALaterEditOutsideTheRecipesWithdrawsAMakefileOrJustfile(ProjectScriptTestCase):
    MAKEFILE = ".PHONY: lint\nlint:\n\truff check .\n"
    JUSTFILE = "typecheck:\n    mypy .\n"

    def rewritten(self, name: str, committed: str, working: str, command: str) -> list[str]:
        self.commit({name: committed})
        (self.cwd / name).write_text(working, encoding="utf-8")
        self.ran(command)
        return self.titles()

    def test_a_directive_added_to_a_makefile_withdraws_its_targets(self) -> None:
        for working in (
            ".IGNORE:\n" + self.MAKEFILE,
            self.MAKEFILE + ".IGNORE:\n",
            "MAKEFLAGS += -n\n" + self.MAKEFILE,
            "export PATH := /tmp/fake:$(PATH)\n" + self.MAKEFILE,
            "SHELL_X = y\n" + self.MAKEFILE,
            "  .IGNORE:\n" + self.MAKEFILE,
            self.MAKEFILE + " .IGNORE:\n",
            self.MAKEFILE + "  MAKEFLAGS += -n\n",
            self.MAKEFILE + "%: .SHELLFLAGS = -c 'exit 0;'\n",
        ):
            with self.subTest(working=working):
                self.fresh_repo()
                self.assertEqual(
                    [], self.rewritten("Makefile", self.MAKEFILE, working, "make lint")
                )

    def test_a_directive_added_to_a_justfile_withdraws_its_recipes(self) -> None:
        for working in (
            "export PATH := '/tmp/fake'\n" + self.JUSTFILE,
            "set allow-duplicate-recipes\n" + self.JUSTFILE + "typecheck:\n    true\n",
            "alias tc := typecheck\n" + self.JUSTFILE,
        ):
            with self.subTest(working=working):
                self.fresh_repo()
                self.assertEqual(
                    [], self.rewritten("justfile", self.JUSTFILE, working, "just typecheck")
                )

    def test_a_new_target_a_comment_or_a_phony_name_keeps_the_others(self) -> None:
        working = "# a note\n.PHONY: lint docs\nlint:\n\truff check .\ndocs:\n\tmkdocs build\n"
        self.assertEqual(
            ["make lint"], self.rewritten("Makefile", self.MAKEFILE, working, "make lint")
        )

    def test_a_new_recipe_keeps_a_justfile_check(self) -> None:
        working = "# note\n" + self.JUSTFILE + "docs:\n    mkdocs build\n"
        self.assertEqual(
            ["just typecheck"], self.rewritten("justfile", self.JUSTFILE, working, "just typecheck")
        )

    def test_a_crlf_checkout_keeps_the_check(self) -> None:
        working = self.MAKEFILE.replace("\n", "\r\n")
        self.commit({"Makefile": self.MAKEFILE})
        (self.cwd / "Makefile").write_bytes(working.encode())
        self.ran("make lint")
        self.assertEqual(["make lint"], self.titles())


class ATopLevelKeyOtherThanDependenciesWithdrawsAPackageFile(ProjectScriptTestCase):
    def package_with(self, **top: Any) -> str:
        return json.dumps({"name": "widgets", "scripts": {"typecheck": "tsc --noEmit"}, **top})

    def test_a_dependency_or_version_bump_keeps_the_check(self) -> None:
        self.commit({"package.json": self.package_with(version="1.0.0", dependencies={"a": "1"})})
        (self.cwd / "package.json").write_text(
            self.package_with(version="1.1.0", dependencies={"a": "2"}, devDependencies={"b": "1"}),
            encoding="utf-8",
        )
        self.ran("pnpm typecheck")
        self.assertEqual(["pnpm typecheck"], self.titles())

    def test_tool_configuration_added_after_the_base_withdraws_every_script(self) -> None:
        for extra in (
            {"jest": {"passWithNoTests": True}},
            {"eslintConfig": {"ignorePatterns": ["*"]}},
        ):
            with self.subTest(extra=extra):
                self.fresh_repo()
                self.commit({"package.json": self.package_with()})
                (self.cwd / "package.json").write_text(self.package_with(**extra), encoding="utf-8")
                self.ran("pnpm typecheck")
                self.assertEqual([], self.titles())


class AnExitZeroFlagIsRefusedWhereverItIsWritten(ProjectScriptTestCase):
    def test_ruff_short_flag_in_a_declared_body_is_refused(self) -> None:
        for body in ("ruff check -e .", "ruff check . -e", "uv run ruff check -e ."):
            with self.subTest(body=body):
                project_scripts.reset()
                self.commit({"package.json": package(lint=body)})
                self.ran("pnpm lint")
                self.assertEqual([], self.titles())

    def test_the_short_flag_on_another_tool_is_not_an_exit_zero(self) -> None:
        self.commit({"package.json": package(lint="eslint -e .")})
        self.ran("pnpm lint")
        self.assertEqual(["pnpm lint"], self.titles())

    def test_a_forwarded_exit_zero_argument_is_refused(self) -> None:
        self.commit({"package.json": package(lint="ruff check .")})
        for command in (
            "pnpm lint -- --exit-zero",
            "npm run lint -- --exit-zero",
            "pnpm lint -- --issues-exit-code=0",
            "pnpm lint -- --issues-exit-code 0",
            "pnpm lint -- -e",
        ):
            self.ran(command)
        self.assertEqual([], self.titles())

    def test_a_forwarded_path_argument_still_counts(self) -> None:
        self.commit({"package.json": package(lint="ruff check")})
        self.ran("pnpm lint -- src")
        self.assertEqual(["pnpm lint -- src"], self.titles())

    def test_a_listed_ruff_short_flag_is_refused(self) -> None:
        reason, _program = project_context.listed_entry_refusal("ruff check -e .")
        self.assertTrue(reason)


class AFileMakeWouldReadFirstAppearingInsideTheCacheWindow(ProjectScriptTestCase):
    def test_a_gnumakefile_added_after_a_load_withdraws_the_targets(self) -> None:
        self.commit({"Makefile": ".PHONY: lint\nlint:\n\truff check .\n"})
        at = 1_790_000_000.0
        first = project_scripts.load(str(self.cwd), at)
        assert first is not None
        self.assertIn("lint", first.make)
        (self.cwd / "GNUmakefile").write_text("lint:\n\ttrue\n", encoding="utf-8")
        again = project_scripts.load(str(self.cwd), at)
        assert again is not None
        self.assertEqual({}, dict(again.make))
        self.assertIn(("Makefile", project_scripts.SHADOWED_REASON), again.skipped)


class AFileThatIsLaterRepairedIsNoLongerReported(ProjectScriptTestCase):
    def test_a_repaired_file_clears_its_entry_and_the_path_is_shown_from_home(self) -> None:
        first = dt.datetime(2026, 9, 1, 12, tzinfo=dt.UTC).timestamp()
        later = dt.datetime(2026, 9, 3, tzinfo=dt.UTC).timestamp()
        self.commit({"package.json": "{"})
        project_scripts.load(str(self.cwd), first)
        self.assertEqual(
            [project_scripts.PARSE_REASON], [p["reason"] for p in project_scripts.problems()]
        )
        self.commit(
            {"package.json": package(typecheck="tsc --noEmit")}, when="2026-09-02T00:00:00Z"
        )
        project_scripts.load(str(self.cwd), later)
        self.assertEqual([], project_scripts.problems())

    def test_a_file_removed_from_the_commit_clears_its_entry(self) -> None:
        first = dt.datetime(2026, 9, 1, 12, tzinfo=dt.UTC).timestamp()
        later = dt.datetime(2026, 9, 3, tzinfo=dt.UTC).timestamp()
        self.commit({"package.json": "{", "justfile": "test:\n    pytest\n"})
        project_scripts.load(str(self.cwd), first)
        self.assertEqual(1, len(project_scripts.problems()))
        git(self.cwd, "rm", "-q", "package.json")
        git(self.cwd, "commit", "-q", "-m", "drop", when="2026-09-02T00:00:00Z")
        project_scripts.load(str(self.cwd), later)
        self.assertEqual([], project_scripts.problems())

    def test_a_path_under_home_is_shown_from_home(self) -> None:
        self.commit({"package.json": "{"})
        project_scripts.load(str(self.cwd), 1_790_000_000.0)
        home = os.path.dirname(os.path.realpath(self.cwd))
        (problem,) = project_scripts.problems(home)
        self.assertEqual(f"~/{self.cwd.name}/package.json", problem["file"])
        (elsewhere,) = project_scripts.problems("/nowhere/else")
        self.assertEqual(
            os.path.join(os.path.realpath(self.cwd), "package.json"), elsewhere["file"]
        )

    def test_diagnose_asks_for_the_paths_from_the_configured_home(self) -> None:
        with mock.patch.object(project_scripts, "problems", return_value=[]) as problems:
            support.diagnose()
        problems.assert_called_once()
        (home,) = problems.call_args.args
        self.assertTrue(home)


class AFileOverTheLineCapSaysSo(unittest.TestCase):
    def test_a_justfile_and_a_makefile_over_the_line_count_have_their_own_reason(self) -> None:
        lines = "\n" * (project_scripts.MAX_LINES + 1)
        for name in ("justfile", "Makefile"):
            with self.subTest(name=name):
                self.assertEqual(
                    (None, project_scripts.LINES_REASON),
                    project_scripts._parse(name, lines.encode()),
                )
        self.assertNotEqual(project_scripts.LINES_REASON, project_scripts.SIZE_REASON)
        self.assertIn("lines", project_scripts.LINES_REASON)


class AnUnreadableDeclaringFileAddsNothingAndIsReported(ProjectScriptTestCase):
    def reasons(self) -> dict[str, str]:
        return {Path(p["file"]).name: p["reason"] for p in project_scripts.problems()}

    def test_a_committed_symlink_is_refused(self) -> None:
        (self.cwd / "real.json").write_text(package(typecheck="tsc --noEmit"), encoding="utf-8")
        os.symlink("real.json", self.cwd / "package.json")
        git(self.cwd, "add", "-A")
        git(self.cwd, "commit", "-q", "-m", "link", when=BEFORE_THE_SESSION)
        self.ran("pnpm typecheck")
        self.assertEqual([], self.titles())
        self.assertEqual(project_scripts.LINK_REASON, self.reasons()["package.json"])

    def test_a_file_replaced_by_a_symlink_after_the_commit_is_refused(self) -> None:
        self.commit({"package.json": package(typecheck="tsc --noEmit")})
        (self.cwd / "package.json").unlink()
        (self.cwd / "elsewhere.json").write_text(package(typecheck="tsc"), encoding="utf-8")
        os.symlink("elsewhere.json", self.cwd / "package.json")
        self.ran("pnpm typecheck")
        self.assertEqual([], self.titles())
        self.assertEqual(project_scripts.LINK_REASON, self.reasons()["package.json"])

    @unittest.skipUnless(hasattr(os, "mkfifo"), "no FIFOs on this platform")
    def test_a_fifo_in_the_work_tree_is_refused_without_being_opened(self) -> None:
        self.commit({"package.json": package(typecheck="tsc --noEmit")})
        (self.cwd / "package.json").unlink()
        os.mkfifo(self.cwd / "package.json")
        self.ran("pnpm typecheck")
        self.assertEqual([], self.titles())
        self.assertEqual(project_scripts.SPECIAL_REASON, self.reasons()["package.json"])

    def test_an_oversized_file_is_refused(self) -> None:
        padding = "x" * (project_scripts.MAX_FILE_BYTES + 10)
        self.commit({"package.json": package(typecheck="tsc --noEmit", padding=padding)})
        self.ran("pnpm typecheck")
        self.assertEqual([], self.titles())
        self.assertEqual(project_scripts.SIZE_REASON, self.reasons()["package.json"])

    def test_an_unparseable_file_is_refused(self) -> None:
        self.commit({"package.json": '{"scripts": {"typecheck": "tsc --noEmit"'})
        self.ran("pnpm typecheck")
        self.assertEqual([], self.titles())
        self.assertEqual(project_scripts.PARSE_REASON, self.reasons()["package.json"])

    def test_a_makefile_with_an_include_is_not_followed(self) -> None:
        self.commit({"Makefile": "include more.mk\nlint:\n\truff check .\n"})
        self.ran("make lint")
        self.assertEqual([], self.titles())
        self.assertEqual(project_scripts.FEATURE_REASON, self.reasons()["Makefile"])

    def test_a_good_file_beside_a_bad_one_still_counts(self) -> None:
        self.commit({"package.json": "{", "justfile": "test:\n    pytest -q\n"})
        self.ran("just test")
        self.assertEqual(["just test"], self.titles())


class ADeclaredCheckStillAgesEarlierPasses(ProjectScriptTestCase):
    def press(self) -> Any:
        self.session.save(self.path)
        return project_context.claude_check_press(self.config, str(self.path))

    def test_a_declared_script_after_a_pass_marks_it_as_changed_since(self) -> None:
        self.commit({"package.json": package(typecheck="tsc --noEmit")})
        self.ran("pytest -q")
        self.assertEqual(frozenset(), self.press().changed_after)
        self.ran("pnpm typecheck")
        self.assertEqual(
            {("toolu_001", "pytest -q")}, {(i, t) for i, t in self.press().changed_after}
        )

    def test_the_declared_script_keeps_its_own_pass(self) -> None:
        self.commit({"package.json": package(typecheck="tsc --noEmit")})
        self.ran("pnpm typecheck")
        self.assertEqual(frozenset(), self.press().changed_after)


class EveryReaderOfTheTranscriptAgrees(ProjectScriptTestCase):
    def test_the_source_page_and_the_live_replay_class_it_as_the_published_fact_does(self) -> None:
        self.commit({"package.json": package(typecheck="tsc --noEmit")})
        self.ran("pnpm typecheck")
        self.session.save(self.path)
        page = session_source.read(self.config, str(self.path), "claude", "root")
        kinds = {entry.title: entry.kind for entry in page.entries}
        self.assertEqual("check", kinds["pnpm typecheck"])
        replayed = live_estimate._replay(
            self.config,
            str(self.path),
            "root",
            live_estimate.saved_intent({}),
            0,
            None,
        )
        tally = replayed.final_tally
        assert tally is not None
        self.assertEqual((1, 0), (len(tally.runs), len(tally.commands)))


class TheResultIsReadLikeAnyCheck(ProjectScriptTestCase):
    def test_the_check_line_is_the_sessions_own_command_and_never_the_scripts_body(self) -> None:
        self.commit(
            {"package.json": package(typecheck="tsc --noEmit --project tsconfig.secret.json")}
        )
        self.ran("pnpm typecheck")
        entries, _scan = self.read()
        self.assertNotIn("tsconfig.secret", json.dumps(entries))


class TheParsersAreBoundedInTime(unittest.TestCase):
    def refusal(self, name: str, text: str) -> tuple[Any, float]:
        started = time.monotonic()
        result = project_scripts._parse(name, text.encode())
        return result, time.monotonic() - started

    def test_a_long_whitespace_line_is_refused_quickly_in_each_declaring_file(self) -> None:
        for name in ("justfile", "Makefile"):
            with self.subTest(name=name):
                result, seconds = self.refusal(name, "a" + " " * 5000 + "x\n")
                self.assertEqual((None, project_scripts.LINE_REASON), result)
                self.assertLess(seconds, 1.0)

    def test_a_long_logical_line_made_of_continuations_is_refused(self) -> None:
        text = "lint:\n" + "".join("\tpytest \\\n" for _ in range(1000))
        result, _seconds = self.refusal("Makefile", text)
        self.assertEqual((None, project_scripts.LINE_REASON), result)

    def test_a_file_of_blank_lines_parses_quickly(self) -> None:
        _result, seconds = self.refusal("Makefile", "\n" * 4000)
        self.assertLess(seconds, 1.0)

    def test_too_many_scripts_and_too_many_lines_are_refused(self) -> None:
        many = "".join(f"t{i}:\n    pytest\n" for i in range(project_scripts.MAX_SCRIPTS + 1))
        self.assertEqual(
            (None, project_scripts.COUNT_REASON), project_scripts._parse("justfile", many.encode())
        )
        lines = "\n" * (project_scripts.MAX_LINES + 1)
        self.assertEqual(
            (None, project_scripts.LINES_REASON), project_scripts._parse("justfile", lines.encode())
        )


class ASlowGitReadsNothing(ProjectScriptTestCase):
    def test_a_runner_past_the_deadline_makes_the_load_return_none(self) -> None:
        self.commit({"package.json": package(typecheck="tsc --noEmit")})

        def slow(*_args: Any, **_kwargs: Any) -> Any:
            raise subprocess.TimeoutExpired("git", 5)

        self.assertIsNone(project_scripts.load(str(self.cwd), 1_790_000_000.0, runner=slow))


class ACachedLoadIsCheckedAgainstTheWorkTree(ProjectScriptTestCase):
    def test_a_shell_edit_inside_the_cache_window_withdraws_the_declarations(self) -> None:
        self.commit({"package.json": package(typecheck="tsc --noEmit")})
        at = 1_790_000_000.0
        first = project_scripts.load(str(self.cwd), at)
        assert first is not None
        self.assertEqual(frozenset({"package.json"}), first.files)
        (self.cwd / "package.json").write_text(package(typecheck="tsc --noEmit && true"))
        again = project_scripts.load(str(self.cwd), at)
        assert again is not None
        self.assertEqual(frozenset(), again.files)
        self.assertIn(("package.json", project_scripts.EDITED_REASON), again.skipped)


class AReplaceRefDoesNotForgeTheBase(ProjectScriptTestCase):
    def test_a_replace_ref_pointing_a_blob_at_an_edited_blob_leaves_the_file_untrusted(
        self,
    ) -> None:
        self.commit({"package.json": package(typecheck="tsc --noEmit")})
        old = subprocess.run(
            [GIT or "git", "rev-parse", "HEAD:package.json"],
            cwd=self.cwd,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        edited = package(typecheck="tsc --noEmit && true")
        (self.cwd / "package.json").write_text(edited)
        new = subprocess.run(
            [GIT or "git", "hash-object", "-w", "package.json"],
            cwd=self.cwd,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        git(self.cwd, "replace", old, new)
        loaded = project_scripts.load(str(self.cwd), 1_790_000_000.0)
        assert loaded is not None
        self.assertEqual(frozenset(), loaded.files)
        self.assertIn(("package.json", project_scripts.EDITED_REASON), loaded.skipped)


class DiagnoseSaysWhyAFileWasSkipped(ProjectScriptTestCase):
    def test_the_rendering_names_the_file_and_the_reason_and_nothing_from_it(self) -> None:
        self.commit({"package.json": '{"scripts": {"typecheck": "tsc --noEmit-FAKE-BODY"'})
        self.ran("pnpm typecheck")
        self.read()
        text = "\n".join(diagnostics._project_script_lines(project_scripts.problems()))
        self.assertIn("Project scripts not read as checks", text)
        self.assertIn("package.json", text)
        self.assertIn(project_scripts.PARSE_REASON, text)
        self.assertNotIn("FAKE-BODY", text)


class TheCommittedFileRead(ProjectScriptTestCase):
    def read_committed(self, at: str = "2026-09-24T00:00:00+00:00") -> Any:
        return git_status.read_committed(
            str(self.cwd),
            dt.datetime.fromisoformat(at).timestamp(),
            project_scripts.DECLARING_FILES,
            max_bytes=project_scripts.MAX_FILE_BYTES,
            timeout_sec=10.0,
        )

    def test_a_folder_that_is_not_a_repository_reads_nothing(self) -> None:
        shutil.rmtree(self.cwd / ".git")
        self.assertIsNone(self.read_committed())

    def test_a_mode_other_than_a_regular_file_is_listed_without_content(self) -> None:
        (self.cwd / "real.json").write_text("{}", encoding="utf-8")
        os.symlink("real.json", self.cwd / "package.json")
        git(self.cwd, "add", "-A")
        git(self.cwd, "commit", "-q", "-m", "link")
        found = self.read_committed()
        (entry,) = found.entries
        self.assertEqual(("package.json", "120000", None), (entry.name, entry.mode, entry.content))

    def test_the_commit_is_the_newest_one_no_later_than_the_given_time(self) -> None:
        self.commit({"package.json": package(lint="eslint .")})
        self.commit({"package.json": package(lint="eslint . --quiet")}, when=AFTER_THE_SESSION)
        found = self.read_committed()
        (entry,) = found.entries
        self.assertIn(b'eslint ."', entry.content or b"")

    def test_a_name_outside_the_closed_pattern_is_never_handed_to_git(self) -> None:
        self.commit({"package.json": "{}"})
        self.assertIsNone(
            git_status.read_committed(
                str(self.cwd), 1.8e9, ("--output=x",), max_bytes=10, timeout_sec=5.0
            )
        )


class TheDeclarationParsers(unittest.TestCase):
    def test_make_reads_targets_prerequisites_and_inline_recipes(self) -> None:
        scripts = project_scripts._parse_make(
            "FOO := 1\n.PHONY: test build\ntest: build ; pytest -q\nbuild:\n\ttsc -b \\\n\t  --noEmit\n"
        )
        assert scripts is not None
        self.assertEqual(("pytest -q",), scripts["test"].lines)
        self.assertEqual(("build",), scripts["test"].needs)
        self.assertEqual(("tsc -b  --noEmit",), scripts["build"].lines)

    def test_make_drops_a_target_defined_twice_with_recipes(self) -> None:
        scripts = project_scripts._parse_make("test:\n\tpytest -q\ntest:\n\truff check .\n")
        self.assertEqual({}, scripts)

    def test_just_drops_parameterised_and_shebang_recipes(self) -> None:
        scripts = project_scripts._parse_just(
            "test target:\n    pytest {{target}}\nlint:\n    ruff check .\n"
            "script:\n    #!/usr/bin/env bash\n    pytest\n[private]\nhelper:\n    mypy .\n"
            "[confirm]\nrisky:\n    pytest\n"
        )
        assert scripts is not None
        self.assertEqual({"lint", "helper"}, set(scripts))

    def test_a_non_phony_target_without_prerequisites_is_a_file_name_not_a_check(self) -> None:
        scripts = project_scripts._parse_make(
            "test:\n\tpytest -q\n.PHONY: lint\nlint:\n\truff check .\nall: lint\n\tmypy .\n"
        )
        assert scripts is not None
        self.assertEqual({"lint", "all"}, set(scripts))

    def test_a_make_comment_after_the_colon_is_not_a_prerequisite(self) -> None:
        scripts = project_scripts._parse_make(".PHONY: test\ntest: ## Run tests\n\tpytest -q\n")
        assert scripts is not None
        self.assertEqual((), scripts["test"].needs)
        self.assertEqual(("pytest -q",), scripts["test"].lines)
        refused = project_scripts._parse_make(".PHONY: t\nt: a # $(X)\n\tpytest\n")
        self.assertEqual({}, refused)

    def test_a_format_script_that_only_checks_counts_and_a_bare_format_does_not(self) -> None:
        for name, lines, expected in (
            ("format:check", ("prettier --check .",), True),
            ("format:check", ("prettier --write .",), False),
            ("format", ("prettier --check .",), False),
        ):
            with self.subTest(name=name, lines=lines):
                self.assertIs(expected, project_context._script_name_ok(name, lines))

    def test_a_script_name_needs_a_check_verb_and_no_fixing_word(self) -> None:
        for name, expected in (
            ("typecheck", True),
            ("test:stories", True),
            ("build:check", True),
            ("lint", True),
            ("format", False),
            ("dev", False),
            ("db:reset", False),
            ("deploy", False),
            ("test:watch", False),
            ("lint:fix", False),
        ):
            with self.subTest(name=name):
                self.assertIs(expected, project_context._script_name_ok(name))

    def test_a_tally_made_without_declarations_reads_a_declared_script_as_a_command(self) -> None:
        call = project_context._ShellCall(0.0, "/w", {"command": "pnpm typecheck"})
        self.assertEqual([], call.checks)


if __name__ == "__main__":
    unittest.main()
