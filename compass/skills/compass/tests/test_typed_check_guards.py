"""A typed closed-list runner is a check only when nothing in the call can stop it running or
failing: the same guards a declared or listed script already meets.

The shell examples are parsed rather than executed, and no text comes from an operator's session.
"""

from __future__ import annotations

from compass_runtime import project_context

from .test_claude_checks import ClaudeChecksTestCase, Transcript


class TypedCheckGuardCase(ClaudeChecksTestCase):
    def listed(self, command: str) -> list[dict[str, object]]:
        self.session = Transcript(self.cwd)
        self.session.bash(command, "ok", is_error=False)
        return self.checks()

    def assert_ordinary(self, *commands: str) -> None:
        for command in commands:
            with self.subTest(command=command):
                self.assertEqual([], self.listed(command))

    def assert_check(self, *commands: str) -> None:
        for command in commands:
            with self.subTest(command=command):
                self.assertEqual(1, len(self.listed(command)))


class ATypedLinterToldToExitZeroIsAnOrdinaryCommand(TypedCheckGuardCase):
    def test_ruff_with_its_exit_zero_switch_in_either_spelling(self) -> None:
        self.assert_ordinary(
            "ruff check . --exit-zero", "uv run ruff check --exit-zero .", "ruff check -e ."
        )

    def test_pylint_with_exit_zero(self) -> None:
        self.assert_ordinary("pylint src --exit-zero")

    def test_flake8_with_exit_zero(self) -> None:
        self.assert_ordinary("flake8 . --exit-zero")

    def test_golangci_lint_with_an_issues_exit_code_of_zero(self) -> None:
        self.assert_ordinary(
            "golangci-lint run --issues-exit-code=0", "golangci-lint run --issues-exit-code 0"
        )

    def test_a_package_script_forwarded_an_exit_zero_switch(self) -> None:
        self.assert_ordinary("npm test -- --exit-zero")

    def test_the_same_linters_without_the_switch_still_count(self) -> None:
        self.assert_check(
            "ruff check .",
            "pylint src",
            "flake8 .",
            "golangci-lint run",
            "golangci-lint run --issues-exit-code=2",
            "pytest -e",
        )

    def test_a_chain_does_not_pass_on_the_linter_that_cannot_fail(self) -> None:
        self.assertEqual([], self.listed("ruff check . --exit-zero && echo done"))


class ATypedRunThatRunsNothingIsAnOrdinaryCommand(TypedCheckGuardCase):
    def test_pytest_collecting_listing_or_describing_itself(self) -> None:
        self.assert_ordinary(
            "pytest --collect-only",
            "pytest --co -q",
            "python3 -m pytest --collect-only tests/",
            "pytest --version",
            "pytest --help",
            "pytest --fixtures",
            "pytest --markers",
        )

    def test_pytest_flags_that_mean_something_else_to_it_still_count(self) -> None:
        self.assert_check("pytest -m slow tests", "pytest -x", "pytest -n 4", "pytest -l")

    def test_cargo_building_without_running(self) -> None:
        self.assert_ordinary("cargo test --no-run", "cargo test -- --list", "cargo test --help")
        self.assert_check("cargo test -p core", "cargo test -- --nocapture")

    def test_gradle_dry_runs_and_excluded_tasks(self) -> None:
        self.assert_ordinary(
            "./gradlew check --dry-run",
            "./gradlew check -m",
            "./gradlew check -x test",
            "./gradlew check --exclude-task test",
            "gradle test -xtest",
            "./gradlew test -xtest",
            "gradle test --dry-run",
            "./gradlew check --version",
        )
        self.assert_check("./gradlew check", "./gradlew build --offline")

    def test_make_dry_runs_before_or_after_the_target(self) -> None:
        self.assert_ordinary(
            "make test -n",
            "make -n test",
            "make check --dry-run",
            "make test --just-print",
            "make test --recon",
            "make test -sn",
            "make test --version",
        )
        self.assert_check("make test", "make test -j4", "make test -s", "make test -k")

    def test_mvn_skipping_its_tests_only_on_the_test_goal(self) -> None:
        self.assert_ordinary("mvn test -DskipTests", "mvn test --version")
        self.assert_check("mvn test -q", "mvn package -DskipTests")

    def test_go_printing_or_listing_instead_of_running(self) -> None:
        self.assert_ordinary("go test -n ./...", "go build -n ./...", "go test -list . ./...")
        self.assert_check("go test -run TestX ./...", "go test ./...")

    def test_javascript_runners_listing_or_describing_themselves(self) -> None:
        self.assert_ordinary(
            "jest --listTests",
            "jest --showConfig",
            "vitest --version",
            "mocha --dry-run",
            "mocha --list-reporters",
            "eslint --help",
            "tsc --version",
        )
        self.assert_check("mocha --reporter dot", "jest --coverage", "tsc --noEmit")

    def test_ruby_php_and_c_runners_listing_what_they_would_run(self) -> None:
        self.assert_ordinary(
            "rspec --dry-run", "phpunit --list-tests", "ctest -N", "ctest --show-only"
        )
        self.assert_check("rspec spec", "phpunit tests", "ctest -j4")

    def test_tox_nox_dotnet_and_swift_listing_or_not_running(self) -> None:
        self.assert_ordinary(
            "tox --notest", "tox -l", "nox --list", "dotnet test --list-tests", "swift test -l"
        )
        self.assert_check("tox -e py312", "nox -s tests", "dotnet test", "swift test")

    def test_package_runners_given_a_run_nothing_long_flag(self) -> None:
        self.assert_ordinary(
            "npm test -- --collect-only",
            "pnpm test -- --listTests",
            "pnpm run test -- --dry-run",
            "yarn test --no-run",
            "npm run test -- --list-tests",
        )
        self.assert_check("npm test", "pnpm run test -- --coverage")

    def test_every_closed_list_runner_decides_its_run_nothing_flags(self) -> None:
        names = {
            *project_context._CHECK_WORDS,
            *(pair[0] for pair in project_context._CHECK_PAIRS),
            *(triple[0] for triple in project_context._CHECK_TRIPLES),
            *(flagged[0] for flagged in project_context._CHECK_FLAGGED),
        }
        decided = set(project_context._RUN_NOTHING_FLAGS) | project_context._NO_RUN_NOTHING_FLAGS
        undecided = {name for name in names if project_context._runner_key([name]) not in decided}
        self.assertEqual(set(), undecided)


class AnAssignedEnvironmentVariableMakesATypedCheckAnOrdinaryCommand(TypedCheckGuardCase):
    def test_an_inline_assignment_of_each_steering_variable(self) -> None:
        self.assert_ordinary(
            "PATH=/tmp/fake:$PATH pytest",
            "NODE_OPTIONS=--require=x npm test",
            "BASH_ENV=/tmp/x pnpm test",
            "ENV=/tmp/x npm run test",
            "SHELL=/bin/true npm test",
            "PYTEST_ADDOPTS=--collect-only pytest",
            "TOX_ADDOPTS=-n tox",
            "env NODE_OPTIONS=x yarn test",
            "env -u HOME PATH=/x pytest",
            "env -u A -u B NODE_OPTIONS=x pytest",
            "env --unset HOME PYTEST_ADDOPTS=--co pytest",
            "env --unset=HOME PATH=/x pytest",
        )

    def test_an_appended_assignment_is_an_assignment(self) -> None:
        self.assert_ordinary(
            "export PYTEST_ADDOPTS+=--co; pytest",
            "PYTEST_ADDOPTS+=--co; pytest",
            "PATH+=:/x; pytest",
            "export PATH+=:/x; pytest",
            "PATH+=:/x pytest",
            "export MAKEFLAGS+=-n; make test",
        )

    def test_an_assignment_exported_earlier_in_the_same_call(self) -> None:
        self.assert_ordinary(
            "export PATH=/tmp/x:$PATH; pytest",
            "export NODE_OPTIONS=x && npm test",
            "declare -x BASH_ENV=x; pnpm test",
            "PYTEST_ADDOPTS=-k x; pytest",
            "export PATH=/tmp/x:$PATH; echo hi; pytest",
        )

    def test_the_package_manager_and_make_families_refuse_a_typed_runner_too(self) -> None:
        self.assert_ordinary(
            "npm_config_script_shell=/usr/bin/true npm test",
            "npm_config_script_shell=/usr/bin/true npm run test",
            "npm_config_script_shell=/usr/bin/true pnpm test",
            "npm_config_script_shell=/usr/bin/true pnpm run test",
            "YARN_ENABLE_SCRIPTS=0 yarn test",
            "export npm_config_script_shell=/usr/bin/true; npm test",
            "MAKEFLAGS=-n make test",
        )

    def test_a_steering_variable_assigned_after_the_check_does_not_reach_it(self) -> None:
        self.assert_check("pytest; export PATH=x")

    def test_an_env_wrapper_that_sets_nothing_steering_leaves_the_check(self) -> None:
        self.assert_check(
            "env FOO=1 pytest", "env -u HOME pytest", "env -u HOME FOO=1 pytest", "env -i pytest"
        )

    def test_steering_looking_text_that_is_not_an_assignment_before_the_check(self) -> None:
        self.assert_check(
            "echo PATH=x; pytest",
            "grep SHELL=x file; pytest",
            "docker run -e PATH=x img true; pytest",
            "echo ENV; pytest",
        )

    def test_other_assignments_before_a_check_are_not_steering(self) -> None:
        self.assert_check("FORCE_COLOR=1 pnpm test", "CI=1 npm test", "export CI=1; pytest")

    def test_a_declared_script_meets_the_same_refusal(self) -> None:
        for assignment in ("PATH=x", "NODE_OPTIONS=x", "BASH_ENV=x", "PYTEST_ADDOPTS=--co"):
            with self.subTest(assignment=assignment):
                self.assertTrue(project_context._steers_a_script((assignment, "pnpm", "lint")))
        self.assertFalse(project_context._steers_a_script(("echo", "PATH=x", "pnpm", "lint")))


class ASteeringVariableRefusesOnlyTheRunnersItCanReach(TypedCheckGuardCase):
    def test_each_family_still_refuses_its_own_runner(self) -> None:
        self.assert_ordinary(
            "MAKEFLAGS=-n make test",
            "MAKEOVERRIDES=x make test",
            "MAKE=true make test",
            "MAKEFILES=x make test",
            "npm_config_script_shell=/usr/bin/true npm test",
            "npm_config_script_shell=/usr/bin/true pnpm test",
            "npm_config_script_shell=/usr/bin/true yarn test",
            "YARN_ENABLE_SCRIPTS=0 yarn test",
            "export npm_config_script_shell=/usr/bin/true; npm test",
        )

    def test_a_family_variable_does_not_reach_a_direct_runner(self) -> None:
        self.assert_check(
            "npm_config_loglevel=silent pytest",
            "YARN_ENABLE_SCRIPTS=0 pytest",
            "JUST_ROOT=x pytest",
            "MAKEFLAGS=-j4 pytest",
            "MAKEFLAGS=-n pytest",
            "MAKE=x cargo test",
            "npm_config_loglevel=silent go test ./...",
            "export JUST_ROOT=x; pytest",
            "env JUST_ROOT=x pytest",
            "env -u HOME npm_config_x=1 pytest",
        )

    def test_a_family_variable_reaches_a_script_runner_that_could_start_its_runner(self) -> None:
        self.assert_ordinary(
            "MAKEFLAGS=-n npm test",
            "MAKEFLAGS=-n pnpm test",
            "npm_config_script_shell=/usr/bin/true make test",
            "JUST_ROOT=x make test",
            "MAKEFILES=x tox",
            "YARN_ENABLE_SCRIPTS=0 npm test",
        )

    def test_a_harmless_make_flag_keeps_make_counting(self) -> None:
        self.assert_check(
            "MAKEFLAGS=-j4 make test",
            'MAKEFLAGS="-j4 -s" make test',
            "MAKEFLAGS=-k make test",
            "MAKEFLAGS=--no-print-directory make test",
            "GNUMAKEFLAGS=--no-print-directory make test",
            "MFLAGS=-w make test",
            "MAKEFLAGS=sw make test",
            "export MAKEFLAGS=-j4; make test",
        )

    def test_a_make_flag_that_changes_what_runs_still_refuses_make(self) -> None:
        self.assert_ordinary(
            "MAKEFLAGS=-n make test",
            "MAKEFLAGS=-i make test",
            "MAKEFLAGS=-q make test",
            "MAKEFLAGS=-t make test",
            "MAKEFLAGS=ni make test",
            'MAKEFLAGS="-j4 -n" make test',
            "MAKEFLAGS='--eval=x' make test",
            "MAKEFLAGS='-- SHELL=/bin/true' make test",
            "MAKEFLAGS=$FLAGS make test",
            "MAKEFLAGS+=-n make test",
            "MAKEFLAGS=-j4 MAKEFILES=x make test",
        )

    def test_a_make_flag_stays_refused_before_a_package_manager_whatever_its_value(self) -> None:
        self.assert_ordinary("MAKEFLAGS=-j4 npm test", "export MAKEFLAGS=-j4; pnpm test")

    def test_an_inline_assignment_steers_only_its_own_segment(self) -> None:
        self.assertEqual(2, len(self.listed("MAKEFLAGS=-j4 make test && pytest")))
        self.assert_check(
            "npm_config_x=1 npm test; pytest",
            "MAKEFLAGS=-n make test && pytest",
            "echo NPM_CONFIG_X=1; pytest",
            "env JUST_ROOT=x make test; pytest",
        )

    def test_an_export_still_steers_every_later_segment(self) -> None:
        self.assert_ordinary(
            "export npm_config_x=1; npm test",
            "export MAKEFLAGS=-n; make test",
            "MAKEFLAGS=-n; make test",
        )
        self.assertEqual(1, len(self.listed("export npm_config_x=1; pytest; npm test")))

    def test_an_argument_assignment_steers_only_make(self) -> None:
        self.assert_ordinary("make test MAKEFLAGS=-n", "make MAKEFLAGS=-n test")
        self.assert_check("echo MAKEFLAGS=-n; pytest", "pytest MAKEFLAGS=-n", "make test FOO=1")

    def test_the_owner_environment_variables_still_refuse_before_any_check(self) -> None:
        self.assert_ordinary(
            "PATH=/tmp/x pytest",
            "PATH=/tmp/x make test && pytest",
            "NODE_OPTIONS=--require=x pytest",
            "BASH_ENV=/tmp/x pytest",
            "ENV=/tmp/x pytest",
            "SHELL=/bin/true pytest",
            "PYTEST_ADDOPTS=--co pytest",
            "TOX_ADDOPTS=-n pytest",
            "PATH+=:/x pytest",
            "env -u HOME PATH=/x pytest",
            "export PATH=/tmp/x; pytest",
        )

    def test_a_steered_make_call_is_published_as_an_ordinary_command(self) -> None:
        self.session = Transcript(self.cwd)
        self.session.bash("MAKEFLAGS=-n make test", "ok", is_error=False)
        events = self.read()[0]
        self.assertEqual(["command"], [event["subject"] for event in events])
        self.assertEqual("passed", events[0]["result"])

    def test_a_harmless_make_flag_is_published_as_a_check(self) -> None:
        self.session = Transcript(self.cwd)
        self.session.bash("MAKEFLAGS=-j4 make test", "ok", is_error=False)
        events = self.read()[0]
        self.assertEqual(["check"], [event["subject"] for event in events])
        self.assertEqual("make test", events[0]["title"])

    def test_vitest_run_list_is_a_filter_not_the_list_subcommand(self) -> None:
        self.assert_check("vitest run list", "vitest run tests/list", "vitest --root x run list")
        self.assert_ordinary("vitest list", "vitest list --filesOnly", "vitest --root x list")

    def test_a_pytest_option_value_is_not_a_flag(self) -> None:
        self.assert_check("pytest -k '--co'", "pytest -m '--collect-only'")
        self.assert_ordinary("pytest -k x --co", "pytest -k=x --collect-only")
