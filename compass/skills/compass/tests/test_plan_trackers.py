"""Offline coverage for the plan tracker worker and its supervised CLI boundary."""

from __future__ import annotations

import errno
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any
from unittest import mock

from compass_runtime import cli, diagnostics, state, supervise
from compass_runtime.plan import (
    model,
    publish,
    settings,
    tracker_cli,
    tracker_refresh,
    tracker_source,
)

from .support import SERVER_PATH
from .test_plan_publish import request

if TYPE_CHECKING:
    from collections.abc import Callable

DECLARATION = {"provider": "github", "kind": "milestone", "repo": "owner/repo", "number": 7}
SOURCE = tracker_source.declaration(DECLARATION)
MORE = tracker_source.declaration({**DECLARATION, "number": 8})
COMMAND = ("fake-read", "--repo", "github.com/owner/repo", "--number", "7")


class FakeClock:
    now = 100.0

    def __call__(self) -> float:
        return self.now


class FakeAdapter:
    """Test-only reader that accepts a deliberately small, explicit completeness witness."""

    def __call__(
        self, source: tracker_source.Declaration, child: tracker_cli.TrackerCLI
    ) -> tracker_refresh.TrackerData:
        assert isinstance(source, tracker_source.RepositoryDeclaration)
        result = child.read_json(
            ("fake-read", "--repo", f"github.com/{source.repo}", "--number", str(source.number))
        )
        if not isinstance(result, dict) or result.get("complete") is not True:
            raise tracker_cli.TrackerError(tracker_cli.Reason.UNREADABLE_OUTPUT)
        return tracker_refresh.TrackerData(
            goals=(model.Goal("goal", "Example", None, model.Origin(model.Source("fake", "", ""))),)
            if result.get("has_goal")
            else (),
            lanes=(),
        )


class TrackerTestCase(unittest.TestCase):
    def setUp(self) -> None:
        root = tempfile.TemporaryDirectory(dir="/tmp" if sys.platform == "darwin" else None)
        self.addCleanup(root.cleanup)
        self.root = Path(root.name).resolve()
        self.environ = {"PATH": str(self.root), "HOME": str(self.root)}
        self.binary = self.root / ("gh.exe" if os.name == "nt" else "gh")
        self.binary.touch(mode=0o700)
        self.clock = FakeClock()
        self.runner = mock.Mock(side_effect=self.complete)
        self.refresh = tracker_refresh.TrackerRefresh(
            adapters={"github": FakeAdapter()},
            environ=self.environ,
            clock=self.clock,
            runner=self.runner,
        )

    @staticmethod
    def complete(_argv: list[str], **options: Any) -> subprocess.CompletedProcess[bytes]:
        options["stdout"].write(b'{"complete":true,"has_goal":true}')
        return subprocess.CompletedProcess(_argv, 0)

    def snapshot(
        self,
        digest: str = "one",
        *,
        sources: tuple[tracker_source.Declaration, ...] = (SOURCE,),
        enabled: bool = True,
    ) -> tuple[tracker_refresh.Observation, ...]:
        return self.refresh.observe(digest, sources, enabled=enabled)

    def result(
        self, read: Callable[[], tracker_refresh.Observation]
    ) -> tracker_refresh.Observation:
        stop = time.monotonic() + 3.0
        result = read()
        while (
            result.reason == tracker_cli.Reason.REFRESHING or result.retrying
        ) and time.monotonic() < stop:
            time.sleep(0.005)
            result = read()
        self.assertNotEqual(tracker_cli.Reason.REFRESHING, result.reason)
        self.assertFalse(result.retrying)
        return result


class TrackerLauncherTest(TrackerTestCase):
    def child(self) -> tracker_cli.TrackerCLI:
        return tracker_cli.TrackerCLI(
            SOURCE,
            deadline=self.clock() + 8.0,
            clock=self.clock,
            environ=self.environ,
            runner=self.runner,
        )

    def test_fixed_argv_rooted_scrubbed_launch_in_private_empty_cwd_and_eof(self) -> None:
        self.environ.update(
            {
                "PATH": os.pathsep.join((".", "relative/bin", str(self.root), "")),
                "GH_HOST": "evil.invalid",
                "GH_REPO": "other/repo",
                "GH_TOKEN": "wrong-gh",
                "gh_telemetry": "1",
                "DEBUG": "1",
                "dEbUg": "1",
                "lInEaR_ApI_KeY": "synthetic-only",
                "gh_config_dir": "alt-config",
                "GITHUB_TOKEN": "wrong-github",
                "GITHUB_ENTERPRISE_TOKEN": "wrong-enterprise",
                "GIT_DIR": "elsewhere",
                "GIT_WORK_TREE": "elsewhere",
            }
        )
        workspaces = []

        def inspect(argv: list[str], **options: Any) -> subprocess.CompletedProcess[bytes]:
            self.assertEqual([str(self.binary), *COMMAND], argv)
            self.assertEqual(b"", options["input"])
            self.assertFalse(options["check"])
            self.assertEqual(8.0, options["timeout"])
            cwd = Path(options["cwd"])
            self.assertNotEqual(self.root, cwd)
            self.assertEqual([], list(cwd.iterdir()))
            if os.name != "nt":
                self.assertEqual(0, cwd.stat().st_mode & 0o077)
            workspaces.append(cwd)
            env = options["env"]
            self.assertEqual("0", env.get("GH_TELEMETRY"))
            self.assertFalse({"DEBUG", "gh_telemetry", "dEbUg"} & env.keys())
            self.assertEqual(
                {
                    **self.environ,
                    "PATH": str(self.root),
                    "GH_TELEMETRY": "0",
                    "GH_PROMPT_DISABLED": "1",
                    "GH_NO_UPDATE_NOTIFIER": "1",
                    "NO_COLOR": "1",
                    "NoDefaultCurrentDirectoryInExePath": "1",
                }.keys()
                - {
                    "GH_HOST",
                    "GH_REPO",
                    "GH_TOKEN",
                    "gh_telemetry",
                    "DEBUG",
                    "dEbUg",
                    "lInEaR_ApI_KeY",
                    "gh_config_dir",
                    "GITHUB_TOKEN",
                    "GITHUB_ENTERPRISE_TOKEN",
                    "GIT_DIR",
                    "GIT_WORK_TREE",
                },
                env.keys(),
            )
            self.assertEqual(str(self.root), env["PATH"])
            self.assertEqual(str(self.root), env["HOME"])
            self.assertEqual("1", env["GH_PROMPT_DISABLED"])
            self.assertEqual("1", env["GH_NO_UPDATE_NOTIFIER"])
            self.assertEqual("1", env["NoDefaultCurrentDirectoryInExePath"])
            self.assertEqual(
                ((options["stdout"].name, 256 * 1024), (options["stderr"].name, 8 * 1024)),
                options["output_limits"],
            )
            return self.complete(argv, **options)

        self.runner.side_effect = inspect
        self.assertEqual("goal", FakeAdapter()(SOURCE, self.child()).goals[0].id)
        self.assertFalse(workspaces[0].exists())

    def test_workspace_cli_ignores_global_key_and_ancestor_config(self) -> None:
        executable = shutil.which("linear")
        if executable is None:
            self.skipTest("Requires Linear CLI 3.1.0")
        isolated = {"PATH": str(self.root), "HOME": str(self.root)}
        version = subprocess.run(
            [executable, "--version"], env=isolated, capture_output=True, timeout=3, check=True
        )
        if version.stdout.strip() != b"linear 3.1.0":
            self.skipTest("Requires Linear CLI 3.1.0")

        shutil.copyfile(executable, self.root / ("linear.exe" if os.name == "nt" else "linear"))
        (self.root / ("linear.exe" if os.name == "nt" else "linear")).chmod(0o700)
        config = self.root / "config" / "linear"
        config.mkdir(parents=True)
        (config / "linear.toml").write_text('api_key = "synthetic-global"\n', encoding="utf-8")
        stored = config / "credentials.toml"
        stored.write_text('default = "other"\nother = "synthetic-other"\n', encoding="utf-8")
        isolated["XDG_CONFIG_HOME"] = str(config.parent)
        repository = self.root / "repo"
        (repository / ".git").mkdir(parents=True)
        local_errors = []

        def run_cli(argv: list[str], **options: Any) -> subprocess.CompletedProcess[bytes]:
            result = subprocess.run(
                argv,
                cwd=options["cwd"],
                env=options["env"],
                input=options["input"],
                capture_output=True,
                timeout=3,
                check=False,
            )
            options["stdout"].write(result.stdout)
            options["stderr"].write(result.stderr)
            error = result.stderr.lower()
            local_errors.append(b"project url" in error or b"an issue" in error)
            return result

        source = tracker_source.declaration(
            {"provider": "linear", "kind": "project", "workspace": "chosen", "project": "Example"}
        )
        # This reference fails locally after account selection, before the CLI can query anything.
        arguments = (
            "--workspace",
            "chosen",
            "--no-input",
            "project",
            "view",
            "https://linear.app/chosen/issue/TEST-1/sample",
            "--json",
            "--no-pager",
        )

        def read() -> tracker_cli.Reason:
            child = tracker_cli.TrackerCLI(
                source,
                deadline=self.clock() + 8.0,
                clock=self.clock,
                environ=isolated,
                runner=run_cli,
            )
            with self.assertRaises(tracker_cli.TrackerError) as raised:
                child.read_json(arguments)
            return raised.exception.reason

        with mock.patch.object(tempfile, "tempdir", str(repository)):
            self.assertEqual(tracker_cli.Reason.UNKNOWN_WORKSPACE, read())
            (repository / ".linear.toml").write_text("invalid = [toml\n", encoding="utf-8")
            self.assertEqual(tracker_cli.Reason.UNKNOWN_WORKSPACE, read())
            stored.write_text(
                'default = "other"\nother = "synthetic-other"\nchosen = "synthetic-chosen"\n',
                encoding="utf-8",
            )
            read()
        self.assertEqual([False, False, True], local_errors)

    def test_linear_launcher_refuses_unreviewed_viewer_argv_before_spawn(self) -> None:
        source = tracker_source.declaration(
            {"provider": "linear", "kind": "project", "workspace": "chosen", "project": "Example"}
        )
        (self.root / ("linear.exe" if os.name == "nt" else "linear")).touch(mode=0o700)
        child = tracker_cli.TrackerCLI(
            source,
            deadline=self.clock() + 8.0,
            clock=self.clock,
            environ=self.environ,
            runner=self.runner,
        )
        for args in (
            ("--workspace", "other", "api", "query { viewer { id } }"),
            ("--workspace", "chosen", "api", "query { viewer { id email } }"),
            ("--workspace", "chosen", "api", "query { viewer { id } }", "--help"),
            ("api", "query { viewer { id } }", "--workspace", "chosen"),
        ):
            with self.subTest(args=args), self.assertRaises(tracker_cli.TrackerError):
                child.read_json(args)
        self.assertEqual(0, self.runner.call_count)

    def test_missing_rooted_cli_starts_nothing(self) -> None:
        self.environ["PATH"] = "."
        with self.assertRaises(tracker_cli.TrackerError) as raised:
            self.child()
        self.assertEqual(tracker_cli.Reason.CLI_MISSING, raised.exception.reason)
        self.runner.assert_not_called()

    def test_all_calls_share_one_deadline_including_spawn_admission(self) -> None:
        child = self.child()
        child.read_json(COMMAND)
        self.clock.now = 106.0
        child.read_json(COMMAND)
        self.assertEqual(
            [8.0, 2.0], [call.kwargs["timeout"] for call in self.runner.call_args_list]
        )

        def expired_at_spawn(_argv: list[str], **options: Any) -> None:
            self.clock.now = 108.0
            options["before_spawn"]()
            self.fail("Expired command got through spawn admission")

        self.runner.side_effect = expired_at_spawn
        with self.assertRaises(tracker_cli.TrackerError) as raised:
            child.read_json(COMMAND)
        self.assertEqual(tracker_cli.Reason.TIMEOUT, raised.exception.reason)
        with self.assertRaises(tracker_cli.TrackerError):
            child.read_json(COMMAND)
        self.assertEqual(3, self.runner.call_count)

    def test_cli_refusals_are_closed_and_never_return_partial_stdout(self) -> None:
        cases = (
            (b"HTTP 401: Bad credentials", tracker_cli.Reason.SIGNED_OUT),
            (b"HTTP 403: API rate limit exceeded", tracker_cli.Reason.RATE_LIMITED),
            (b"HTTP 404: repository not found", tracker_cli.Reason.NOT_FOUND),
            (b"private stderr message", tracker_cli.Reason.CLI_FAILED),
        )
        for stderr, reason in cases:
            with self.subTest(reason=reason):

                def refuse(
                    argv: list[str], *, error: bytes = stderr, **options: Any
                ) -> subprocess.CompletedProcess[bytes]:
                    options["stdout"].write(b'{"complete":true}')
                    options["stderr"].write(error)
                    return subprocess.CompletedProcess(argv, 1)

                self.runner.side_effect = refuse
                with self.assertRaises(tracker_cli.TrackerError) as raised:
                    self.child().read_json(COMMAND)
                self.assertEqual(reason, raised.exception.reason)
                self.assertEqual(reason.value, str(raised.exception))

    def test_bad_json_and_both_post_run_caps_are_closed(self) -> None:
        cases = (
            (b'{"x": 1, "x": 2}', b"", tracker_cli.Reason.UNREADABLE_OUTPUT),
            (b'{"x": NaN}', b"", tracker_cli.Reason.UNREADABLE_OUTPUT),
            (b"\xff", b"", tracker_cli.Reason.UNREADABLE_OUTPUT),
            (b"x" * (256 * 1024 + 1), b"", tracker_cli.Reason.LIMIT_EXCEEDED),
            (b"[]", b"x" * (8 * 1024 + 1), tracker_cli.Reason.LIMIT_EXCEEDED),
        )
        for stdout, stderr, reason in cases:
            with self.subTest(reason=reason):

                def malformed(
                    argv: list[str], *, out: bytes = stdout, err: bytes = stderr, **options: Any
                ) -> subprocess.CompletedProcess[bytes]:
                    options["stdout"].write(out)
                    options["stderr"].write(err)
                    return subprocess.CompletedProcess(argv, 0)

                self.runner.side_effect = malformed
                with self.assertRaises(tracker_cli.TrackerError) as raised:
                    self.child().read_json(COMMAND)
                self.assertEqual(reason, raised.exception.reason)


@unittest.skipUnless(os.name == "posix", "Exercises POSIX process-group cleanup")
class TrackerRealChildTest(TrackerTestCase):
    # A real child and its descendant must die at the timeout and each active cap.
    REAL_TIME_TESTS = True

    def assert_group_stopped(self, stream: int | None, reason: tracker_cli.Reason) -> None:
        import fcntl  # noqa: PLC0415 - available only for the POSIX process-group proof

        self.binary.unlink()
        self.binary.symlink_to(sys.executable)
        marker = self.root / "descendant"
        program = """
import fcntl
import os
import shutil
import sys
import time

assert sys.stdin.buffer.read() == b''
read, write = os.pipe()
if os.fork() == 0:
    os.close(read)
    with open(sys.argv[1], 'w') as marker:
        fcntl.flock(marker, fcntl.LOCK_EX)
        os.write(marker.fileno(), b'ready')
        os.write(write, b'1')
        time.sleep(60)
    os._exit(0)
os.close(write)
assert os.read(read, 1) == b'1'
if sys.argv[2] != 'None':
    fd = int(sys.argv[2])
    while True:
        os.write(fd, b'x' * 4096)
        time.sleep(0.001)
time.sleep(60)
"""
        child = tracker_cli.TrackerCLI(
            SOURCE,
            deadline=time.monotonic() + (1.5 if stream is None else 5.0),
            environ=self.environ,
        )

        def helper_running(_pgid: int, _timeout: float) -> bool | None:
            # This controlled group has one helper. Its kernel lock lets the test observe its
            # exit even in sandboxes where the supervisor's native process-table probe is denied.
            try:
                with marker.open("rb") as handle:
                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return True
            except FileNotFoundError:
                return None
            return False

        started = time.monotonic()
        with (
            mock.patch.object(supervise, "_group_running", side_effect=helper_running),
            self.assertRaises(tracker_cli.TrackerError) as raised,
        ):
            child.read_json(("-c", program, str(marker), str(stream)))
        self.assertEqual(reason, raised.exception.reason)
        self.assertLess(time.monotonic() - started, 5.0)
        self.assertEqual(b"ready", marker.read_bytes())
        self.assertFalse(helper_running(0, 0))

    def test_supervisor_does_not_spawn_after_the_absolute_deadline(self) -> None:
        with (
            mock.patch.object(supervise, "_spawn") as spawn,
            self.assertRaises(subprocess.TimeoutExpired),
        ):
            supervise.run([str(self.binary)], deadline=time.monotonic() - 1, timeout=8)
        spawn.assert_not_called()

    def test_fake_cli_timeout_kills_the_process_group(self) -> None:
        self.assert_group_stopped(None, tracker_cli.Reason.TIMEOUT)

    def test_fake_cli_stdout_overflow_kills_the_process_group(self) -> None:
        self.assert_group_stopped(1, tracker_cli.Reason.LIMIT_EXCEEDED)

    def test_fake_cli_stderr_overflow_kills_the_process_group(self) -> None:
        self.assert_group_stopped(2, tracker_cli.Reason.LIMIT_EXCEEDED)

    def test_invalidation_cancels_live_child_before_or_after_spawn_callback(self) -> None:
        self.binary.unlink()
        self.binary.symlink_to(sys.executable)
        for late in (False, True):
            with self.subTest(late=late):
                self.assert_child_cancelled_on_invalidation(late=late)

    def assert_child_cancelled_on_invalidation(self, *, late: bool) -> None:
        production_run = supervise.run

        def read(
            _source: tracker_source.Declaration, child: tracker_cli.TrackerCLI
        ) -> tracker_refresh.TrackerData:
            child.read_json(("-c", "import time; time.sleep(60)"))
            return tracker_refresh.TrackerData((), ())

        registered = threading.Event()
        release = threading.Event()
        finished = threading.Event()
        groups: list[supervise.Group] = []

        def run(argv: list[str], **options: Any) -> subprocess.CompletedProcess[bytes]:
            on_spawn = options.pop("on_spawn", None)

            def register(group: supervise.Group) -> None:
                groups.append(group)
                if late:
                    registered.set()
                    self.assertTrue(release.wait(3.0))
                if on_spawn is not None:
                    on_spawn(group)
                registered.set()

            try:
                return production_run(argv, **options, on_spawn=register)
            finally:
                finished.set()

        refresh = tracker_refresh.TrackerRefresh(
            environ=self.environ, adapters={"github": read}, runner=run
        )
        with mock.patch.object(supervise, "_group_running", return_value=False):
            try:
                refresh.observe("one", (SOURCE,), enabled=True)
                self.assertTrue(registered.wait(3.0))
                (group,) = groups
                refresh.invalidate()
                release.set()
                self.assertTrue(finished.wait(1.0), "superseded child kept running")
                self.assertTrue(group.cancelled())
                self.assertFalse(group.running())
            finally:
                release.set()
                for group in groups:
                    group.cancel()
                self.assertTrue(finished.wait(3.0))


class TrackerSchedulingTest(unittest.TestCase):
    def test_other_provider_settles_while_four_github_reads_are_held(self) -> None:
        release = threading.Event()
        started = threading.Event()

        def blocked(
            _source: tracker_source.Declaration, _child: tracker_cli.TrackerCLI
        ) -> tracker_refresh.TrackerData:
            started.set()
            release.wait()
            raise tracker_cli.TrackerError(tracker_cli.Reason.TIMEOUT)

        def immediate(
            _source: tracker_source.Declaration, _child: tracker_cli.TrackerCLI
        ) -> tracker_refresh.TrackerData:
            raise tracker_cli.TrackerError(tracker_cli.Reason.UNKNOWN_WORKSPACE)

        linear = {
            "provider": "linear",
            "kind": "project",
            "workspace": "none",
            "project": "Example",
        }
        sources = tracker_source.declarations(
            [{**DECLARATION, "number": number} for number in range(1, 5)] + [linear]
        )
        refresh = tracker_refresh.TrackerRefresh(adapters={"github": blocked, "linear": immediate})

        def linear_reason() -> tracker_cli.Reason | None:
            return refresh.observe("same", sources, enabled=True)[-1].reason

        try:
            linear_reason()
            self.assertTrue(started.wait(3))
            stop = time.monotonic() + 1
            reason = linear_reason()
            while reason == tracker_cli.Reason.REFRESHING and time.monotonic() < stop:
                time.sleep(0.005)
                reason = linear_reason()
            self.assertEqual(tracker_cli.Reason.UNKNOWN_WORKSPACE, reason)
        finally:
            refresh.invalidate()
            release.set()


class TrackerRefreshTest(TrackerTestCase):
    def test_failures_wait_as_long_as_successes_before_trying_again(self) -> None:
        self.runner.return_value = subprocess.CompletedProcess([], 4)
        self.runner.side_effect = None
        self.snapshot()
        failure = self.result(lambda: self.snapshot()[0])
        self.assertEqual(tracker_cli.Reason.SIGNED_OUT, failure.reason)

        self.clock.now += tracker_refresh.FRESH_SECONDS - 0.001
        self.assertEqual(failure, self.snapshot()[0])
        self.runner.assert_called_once()

    def test_a_retry_keeps_the_last_failure_until_the_new_read_finishes(self) -> None:
        self.runner.return_value = subprocess.CompletedProcess([], 4)
        self.runner.side_effect = None
        self.snapshot()
        failure = self.result(lambda: self.snapshot()[0])
        self.assertEqual(tracker_cli.Reason.SIGNED_OUT, failure.reason)

        entered = threading.Event()
        release = threading.Event()

        def retry(argv: list[str], **options: Any) -> subprocess.CompletedProcess[bytes]:
            entered.set()
            if not release.wait(3):
                raise subprocess.TimeoutExpired(argv, options["timeout"])
            return self.complete(argv, **options)

        self.runner.side_effect = retry
        self.clock.now += tracker_refresh.FRESH_SECONDS
        try:
            (pending,) = self.snapshot()
            self.assertTrue(entered.wait(3))
            self.assertEqual(failure.reason, pending.reason)
            self.assertTrue(pending.retrying)
            self.assertEqual(pending, self.snapshot()[0])
            self.assertIsNone(pending.data)
            self.assertIsNone(pending.observed_at)
            self.assertEqual(2, self.runner.call_count)
        finally:
            release.set()
            observed = self.result(lambda: self.snapshot()[0])
        self.assertIsNotNone(observed.data)
        self.assertFalse(observed.retrying)

    def test_shutdown_keeps_an_expired_refusal_without_marking_it_as_retrying(self) -> None:
        self.runner.return_value = subprocess.CompletedProcess([], 4)
        self.runner.side_effect = None
        failure = self.result(lambda: self.snapshot()[0])
        self.assertEqual(tracker_cli.Reason.SIGNED_OUT, failure.reason)

        self.clock.now += tracker_refresh.FRESH_SECONDS
        with mock.patch.object(supervise, "_SHUTDOWN", threading.Event()):
            supervise.kill_all()
            self.assertEqual(failure, self.snapshot()[0])
            self.clock.now += 1
            self.assertEqual(failure, self.snapshot()[0])
            self.assertFalse(self.refresh._active)
            self.assertFalse(self.refresh._waiting)
        self.runner.assert_called_once()

    def test_only_one_off_thread_read_per_source_and_digest(self) -> None:
        entered = threading.Event()
        release = threading.Event()
        request_thread = threading.get_ident()

        def blocking(argv: list[str], **options: Any) -> subprocess.CompletedProcess[bytes]:
            if argv[-1] == "7":
                self.assertNotEqual(request_thread, threading.get_ident())
                entered.set()
                self.assertTrue(release.wait(3.0))
            return self.complete(argv, **options)

        self.runner.side_effect = blocking
        try:
            (pending,) = self.snapshot()
            self.assertEqual(tracker_cli.Reason.REFRESHING, pending.reason)
            self.assertIsNone(pending.data)
            self.assertTrue(entered.wait(3.0))
            first, _ = self.snapshot(sources=(SOURCE, MORE))
            self.assertEqual(pending, first)
            next_source = self.result(lambda: self.snapshot(sources=(SOURCE, MORE))[1])
            self.assertIsNotNone(next_source.data)
            self.assertEqual(["7", "8"], [call.args[0][-1] for call in self.runner.call_args_list])
        finally:
            release.set()
        first = self.result(lambda: self.snapshot()[0])
        self.assertEqual(1, len(first.data.goals) if first.data else None)

    def test_expired_partial_and_failed_results_are_null_and_complete_empty_is_measured(
        self,
    ) -> None:
        self.snapshot()
        observed = self.result(lambda: self.snapshot()[0])
        self.assertEqual(100.0, observed.observed_at)
        self.clock.now = 129.999
        self.assertEqual(observed, self.snapshot()[0])

        def partial(argv: list[str], **options: Any) -> subprocess.CompletedProcess[bytes]:
            options["stdout"].write(b'{"complete":false,"has_goal":true}')
            return subprocess.CompletedProcess(argv, 0)

        self.runner.side_effect = partial
        self.clock.now = 130.0
        (expired,) = self.snapshot()
        self.assertEqual(tracker_cli.Reason.REFRESHING, expired.reason)
        self.assertIsNone(expired.data)
        self.assertIsNone(expired.observed_at)
        incomplete = self.result(lambda: self.snapshot()[0])
        self.assertEqual(tracker_cli.Reason.UNREADABLE_OUTPUT, incomplete.reason)
        self.assertIsNone(incomplete.data)
        self.assertEqual(2, self.runner.call_count)

        def empty(argv: list[str], **options: Any) -> subprocess.CompletedProcess[bytes]:
            options["stdout"].write(b'{"complete":true}')
            return subprocess.CompletedProcess(argv, 0)

        self.runner.side_effect = empty
        self.clock.now += 30.0
        empty_result = self.result(lambda: self.snapshot()[0])
        self.assertEqual(tracker_refresh.TrackerData(goals=(), lanes=()), empty_result.data)
        self.assertIsNone(empty_result.reason)

        self.runner.side_effect = PermissionError(errno.EACCES, "fake CLI error")
        self.clock.now += 30.0
        refused = self.result(lambda: self.snapshot()[0])
        self.assertEqual(tracker_cli.Reason.CLI_FAILED, refused.reason)
        self.assertIsNone(refused.data)
        self.assertIsNone(refused.observed_at)

    def test_settings_changes_removal_and_disabling_discard_cached_values(self) -> None:
        self.assertIsNotNone(self.result(lambda: self.snapshot()[0]).data)
        (disabled,) = self.snapshot(enabled=False)
        self.assertEqual(tracker_cli.Reason.DISABLED, disabled.reason)
        self.assertIsNone(disabled.data)
        self.assertEqual(1, self.runner.call_count)
        for digest in ("one", "two"):
            (pending,) = self.snapshot(digest)
            self.assertEqual(tracker_cli.Reason.REFRESHING, pending.reason)
            self.assertIsNone(pending.data)

            def read_digest(name: str = digest) -> tracker_refresh.Observation:
                return self.snapshot(name)[0]

            self.assertIsNotNone(self.result(read_digest).data)
        self.assertEqual((), self.snapshot(sources=()))
        self.assertIsNone(self.snapshot("two")[0].data)
        self.result(lambda: self.snapshot("two")[0])
        self.assertEqual(4, self.runner.call_count)

    def test_reversions_run_one_current_replacement_without_another_fetch(self) -> None:
        for enabled in (False, True):
            with self.subTest(intermediate_enabled=enabled):
                self.assert_reversion_refreshes(intermediate_enabled=enabled)

    def assert_reversion_refreshes(self, *, intermediate_enabled: bool) -> None:
        self.runner.reset_mock()
        entered = threading.Event()
        release = threading.Event()
        replacement = threading.Event()
        replacement_can_finish = threading.Event()

        def blocked(argv: list[str], **options: Any) -> subprocess.CompletedProcess[bytes]:
            if self.runner.call_count == 1:
                entered.set()
                self.assertTrue(release.wait(3.0))
                return self.complete(argv, **options)
            replacement.set()
            self.assertTrue(replacement_can_finish.wait(3.0))
            options["stdout"].write(b'{"complete":true}')
            return subprocess.CompletedProcess(argv, 0)

        self.runner.side_effect = blocked
        try:
            self.snapshot()
            self.assertTrue(entered.wait(3.0))
            self.snapshot("two", enabled=intermediate_enabled)
            self.assertEqual(tracker_cli.Reason.REFRESHING, self.snapshot()[0].reason)
            self.assertEqual(1, self.runner.call_count)
            release.set()
            self.assertTrue(replacement.wait(3.0), "replacement needed another fetch")
            self.assertEqual(tracker_cli.Reason.REFRESHING, self.snapshot()[0].reason)
        finally:
            release.set()
            replacement_can_finish.set()
        read = self.result(lambda: self.snapshot()[0])
        self.assertEqual(tracker_refresh.TrackerData(goals=(), lanes=()), read.data)
        self.assertEqual(2, self.runner.call_count)
        self.refresh.invalidate()

    def test_worker_slots_and_queue_are_bounded_and_drain_without_another_fetch(self) -> None:
        release = threading.Event()
        all_slots = threading.Event()
        drained = threading.Event()
        sources = tuple(
            tracker_source.declaration({**DECLARATION, "number": number}) for number in range(1, 7)
        )

        def blocking(argv: list[str], **options: Any) -> subprocess.CompletedProcess[bytes]:
            if self.runner.call_count >= 4:
                all_slots.set()
            self.assertTrue(release.wait(3.0))
            if self.runner.call_count >= 6:
                drained.set()
            return self.complete(argv, **options)

        self.runner.side_effect = blocking
        try:
            pending = self.snapshot(sources=sources)
            self.assertEqual([tracker_cli.Reason.REFRESHING] * 6, [item.reason for item in pending])
            self.assertTrue(all_slots.wait(3.0))
            self.assertEqual(4, self.runner.call_count)
        finally:
            release.set()
        self.assertTrue(drained.wait(3.0))
        self.assertEqual(6, self.runner.call_count)

    def test_shutdown_discards_waiting_sources_without_starting_more_workers(self) -> None:
        release = threading.Event()
        workers: list[threading.Thread] = []
        sources = tuple(
            tracker_source.declaration({**DECLARATION, "number": number}) for number in range(1, 11)
        )
        thread_start = threading.Thread.start

        def start(thread: threading.Thread) -> None:
            workers.append(thread)
            if len(workers) <= 4:
                thread_start(thread)

        def blocked(argv: list[str], **options: Any) -> subprocess.CompletedProcess[bytes]:
            self.assertTrue(release.wait(3.0))
            return self.complete(argv, **options)

        self.runner.side_effect = blocked
        with (
            mock.patch.object(supervise, "_SHUTDOWN", threading.Event()),
            mock.patch.object(threading.Thread, "start", autospec=True, side_effect=start),
        ):
            self.snapshot(sources=sources)
            initial = tuple(workers)
            try:
                self.assertEqual(4, len(initial))
                supervise.kill_all()
            finally:
                release.set()
                for worker in initial:
                    worker.join(3.0)
                    self.assertFalse(worker.is_alive())
            self.snapshot("after shutdown", sources=sources)
            self.assertEqual(4, len(workers))
            self.assertFalse(self.refresh._waiting)

    def test_result_completed_after_the_deadline_is_withdrawn(self) -> None:
        def late(argv: list[str], **options: Any) -> subprocess.CompletedProcess[bytes]:
            self.clock.now += 8.0
            return self.complete(argv, **options)

        self.runner.side_effect = late
        read = self.result(lambda: self.snapshot()[0])
        self.assertEqual(tracker_cli.Reason.TIMEOUT, read.reason)
        self.assertIsNone(read.data)


@unittest.skipIf(os.name == "nt", "Plan settings require POSIX directory descriptors")
class TrackerEntryPointTest(TrackerTestCase):
    def application(self, *flags: str) -> Any:
        options = cli.build_parser().parse_args(["--no-git", *flags])
        config, _ = cli.build_runtime(options, started=0.0)
        config = replace(config, state_home=str(self.root))
        runtime = state.build_runtime_state(config, started=0.0)
        runtime.plan_trackers = self.refresh
        return SimpleNamespace(config=config, state=runtime)

    def declare(self) -> None:
        (self.root / "compass-plan.json").write_text(
            json.dumps({"version": 1, "trackers": [DECLARATION]}), encoding="utf-8"
        )

    def test_an_unstored_workspace_stays_visible_while_github_has_not_timed_out(self) -> None:
        github = {"provider": "github", "kind": "parent-issue", "repo": "owner/repo", "number": 7}
        linear = {
            "provider": "linear",
            "kind": "project",
            "workspace": "no-such-ws",
            "project": "Example",
        }
        (self.root / ("linear.exe" if os.name == "nt" else "linear")).touch(mode=0o700)
        (self.root / settings.FILENAME).write_text(
            json.dumps({"version": 1, "trackers": [github, linear]}), encoding="utf-8"
        )
        github_started = threading.Event()
        github_timeout = threading.Event()

        def run(argv: list[str], **options: Any) -> subprocess.CompletedProcess[bytes]:
            if argv[0] == str(self.binary):
                github_started.set()
                github_timeout.wait(3)
                raise subprocess.TimeoutExpired(argv, options["timeout"])
            options["stderr"].write(b"Workspace not found in credentials")
            return subprocess.CompletedProcess(argv, 4)

        self.refresh = tracker_refresh.TrackerRefresh(
            environ=self.environ,
            clock=self.clock,
            runner=run,
        )
        app = self.application()
        declarations = (tracker_source.declaration(github), tracker_source.declaration(linear))
        digest = tracker_source_digest(self.root)
        started = self.clock()
        try:
            request(app)
            self.assertTrue(github_started.wait(3))
            immediate = self.result(lambda: self.snapshot(digest, sources=declarations)[1])
            self.assertEqual(tracker_cli.Reason.UNKNOWN_WORKSPACE, immediate.reason)

            # The old failure cache had expired, but GitHub still had time on its deadline.
            self.clock.now = started + 6
            body = json.loads(request(app)[2])
            self.assertEqual(
                [("refreshing", "refreshing"), ("refused", "unknown-workspace")],
                [(source["state"], source["reason"]) for source in body["sources"]],
            )
            self.assertEqual([], body["goals"])
            self.assertEqual([], body["lanes"])
            self.assertIsNone(body["trackerRead"])
        finally:
            self.clock.now = started + tracker_refresh.REFRESH_SECONDS
            github_timeout.set()
            hung = self.result(lambda: self.snapshot(digest, sources=declarations)[0])
        self.assertEqual(tracker_cli.Reason.TIMEOUT, hung.reason)
        self.clock.now = started + 10
        body = json.loads(request(app)[2])
        self.assertEqual(
            [("refused", "timeout"), ("refused", "unknown-workspace")],
            [(source["state"], source["reason"]) for source in body["sources"]],
        )

    def test_only_admitted_fetch_with_declaration_starts_tracker_even_with_git_off(self) -> None:
        app = self.application()
        with mock.patch.object(threading.Thread, "start") as starts:
            self.assertEqual(200, request(app)[0])
            starts.assert_not_called()
        self.runner.assert_not_called()
        self.declare()
        started = threading.Event()

        def run(argv: list[str], **options: Any) -> subprocess.CompletedProcess[bytes]:
            started.set()
            return self.complete(argv, **options)

        self.runner.side_effect = run
        self.assertEqual(200, request(app)[0])
        self.assertTrue(started.wait(3.0))
        self.assertIsNotNone(
            self.result(
                lambda: self.refresh.observe(
                    tracker_source_digest(self.root), (SOURCE,), enabled=True
                )[0]
            ).data
        )
        self.runner.assert_called_once()

    def test_refused_requests_start_zero_tracker_threads(self) -> None:
        self.declare()
        for options in ({"headers": "Forwarded: for=192.0.2.1\r\n"}, {"peer": "192.0.2.1"}):
            with (
                self.subTest(options=options),
                mock.patch.object(threading.Thread, "start") as starts,
            ):
                app = self.application()
                app.state.plan_trackers = tracker_refresh.TrackerRefresh(environ=self.environ)
                status, _, _ = request(app, **options)
                starts.assert_not_called()
                self.assertEqual(403, status)

    def test_overlapping_fetches_cannot_launch_from_settings_older_than_a_deletion(self) -> None:
        self.declare()
        app = self.application()
        first_loading = threading.Event()
        second_requesting = threading.Event()
        second_loaded_old = threading.Event()
        deleted = threading.Event()
        first_returned = threading.Event()
        thread_start = threading.Thread.start
        real_load = settings.load

        def load(*args: Any, **kwargs: Any) -> settings.Loaded:
            if not second_requesting.is_set():
                first_loading.set()
                self.assertTrue(deleted.wait(3.0))
                return real_load(*args, **kwargs)
            loaded = real_load(*args, **kwargs)
            if loaded.settings is not None:
                second_loaded_old.set()
                self.assertTrue(first_returned.wait(3.0))
            return loaded

        def second() -> tuple[int, bytes, bytes]:
            second_requesting.set()
            return request(app)

        def start(thread: threading.Thread) -> None:
            if thread.name != "compass-plan-tracker":
                thread_start(thread)

        with (
            mock.patch.object(settings, "load", side_effect=load),
            mock.patch.object(
                threading.Thread, "start", autospec=True, side_effect=start
            ) as starts,
            ThreadPoolExecutor(2) as pool,
        ):
            first = pool.submit(request, app)
            try:
                self.assertTrue(first_loading.wait(3.0))
                later = pool.submit(second)
                self.assertTrue(second_requesting.wait(3.0))
                # Give an unserialized load time to retain the old settings before deletion.
                second_loaded_old.wait(0.25)
                (self.root / "compass-plan.json").unlink()
                deleted.set()
                self.assertEqual({"state": "not-configured"}, json.loads(first.result(3.0)[2]))
                first_returned.set()
                self.assertEqual({"state": "not-configured"}, json.loads(later.result(3.0)[2]))
                self.assertFalse(
                    any(
                        call.args[0].name == "compass-plan-tracker"
                        for call in starts.call_args_list
                    )
                )
            finally:
                deleted.set()
                first_returned.set()

    def test_run_wide_off_switches_start_zero_tracker_processes(self) -> None:
        self.declare()
        for flag, status in (("--no-plan", 404), ("--no-plan-trackers", 200)):
            with self.subTest(flag=flag):
                with mock.patch.object(threading.Thread, "start") as starts:
                    self.assertEqual(status, request(self.application(flag))[0])
                    starts.assert_not_called()
                self.runner.assert_not_called()

    def test_the_guide_keeps_a_sparse_mixed_plans_local_log_available(self) -> None:
        guide = (SERVER_PATH.parents[3] / "docs/how-to/05-plan-board.md").read_text(
            encoding="utf-8"
        )
        stopping = " ".join(guide.split("- Start Compass with ", 1)[1].split("\n\n", 1)[0].split())
        flag = stopping.split("`")[1]
        fixture = Path(__file__).parent / "fixtures/plan/stand-in.json"
        log = json.loads(fixture.read_bytes())["log"]
        event_log = self.root / "events.log"
        event_log.write_text("ask a1 Sample question?\n", encoding="utf-8")
        document = {"version": 1, "log": {**log, "path": str(event_log)}, "trackers": [DECLARATION]}
        path = self.root / settings.FILENAME
        path.write_text(json.dumps(document), encoding="utf-8")
        app = self.application(flag)
        body = json.loads(request(app)[2])
        self.assertEqual(body["state"], "ready")
        self.assertEqual([ask["text"] for ask in body["asks"]], ["Sample question?"])
        self.runner.assert_not_called()
        del document["trackers"]
        path.write_text(json.dumps(document), encoding="utf-8")
        self.assertEqual(
            json.loads(request(app)[2]), {"state": "refused", "reason": "malformed settings"}
        )
        self.assertIn("use the flag so the local log stays available", stopping)
        self.assertIn(
            "only if the remaining settings are valid as a standalone file plan", stopping
        )

    def test_diagnose_reports_each_declaration_and_rooted_cli_without_running_it(self) -> None:
        self.declare()
        with (
            mock.patch.dict(os.environ, self.environ, clear=True),
            mock.patch.object(supervise, "run") as default_runner,
        ):
            report = diagnostics._plan_report(self.application().state)
            disabled = diagnostics._plan_report(self.application("--no-plan-trackers").state)
            no_plan = diagnostics._plan_report(self.application("--no-plan").state)
            with mock.patch.dict(os.environ, {"PATH": "."}):
                missing = diagnostics._plan_report(self.application().state)
        self.assertEqual(
            [
                {
                    "provider": "github",
                    "kind": "milestone",
                    "executable": "gh",
                    "resolves": True,
                    "reason": None,
                    "measurement": None,
                }
            ],
            report["trackers"],
        )
        self.assertEqual("disabled", disabled["trackers"][0]["reason"])
        self.assertEqual([], no_plan["trackers"])
        self.assertEqual("cli-missing", missing["trackers"][0]["reason"])
        self.assertIn(
            "github milestone (gh): resolves, not measured",
            "\n".join(diagnostics._plan_lines(report)),
        )
        self.assertNotIn("owner/repo", json.dumps(report))
        default_runner.assert_not_called()
        self.runner.assert_not_called()

    def test_tracker_only_session_summary_stays_silent_and_local(self) -> None:
        doc = {"version": 1, "trackers": [DECLARATION], "summary": {"enabled": True}}
        (self.root / "compass-plan.json").write_text(json.dumps(doc), encoding="utf-8")
        with mock.patch.object(supervise, "run") as launch:
            self.assertEqual("", publish.session_summary(str(self.root), lane="goal"))
            self.assertEqual(
                "", publish.session_summary(str(self.root), lane=None, cwd=str(self.root))
            )
        launch.assert_not_called()

    def test_diagnose_names_invalid_ask_labels_without_echoing_them_or_reading_github(self) -> None:
        canary = "synthetic-privately-named-label"
        for invalid in (
            [],
            [""],
            ["   "],
            [canary, canary],
            ["x" * 129],
            [f"label-{n}" for n in range(33)],
            canary,
            None,
        ):
            with self.subTest(invalid=invalid):
                (self.root / settings.FILENAME).write_text(
                    json.dumps(
                        {"version": 1, "trackers": [{**DECLARATION, "ask_labels": invalid}]}
                    ),
                    encoding="utf-8",
                )
                report = diagnostics._plan_report(self.application().state)
                lines = "\n".join(diagnostics._plan_lines(report))
                self.assertIn("Plan settings", lines)
                self.assertIn("invalid tracker ask_labels", lines)
                self.assertNotIn(canary, lines)
                self.runner.assert_not_called()

    def test_invalid_workspace_tracker_ask_labels_are_refused_before_any_read(self) -> None:
        canary = "synthetic-privately-named-label"
        reason = settings.MALFORMED
        for kind, selector in (("project", {}), ("milestone", {"milestone": "Spring survey"})):
            for labels in ([canary, canary], [], None):
                with self.subTest(kind=kind, labels=labels):
                    source = {
                        "provider": "linear",
                        "kind": kind,
                        "workspace": "orchard-labs",
                        "project": "Orchard inventory",
                        "ask_labels": labels,
                        **selector,
                    }
                    (self.root / settings.FILENAME).write_text(
                        json.dumps({"version": 1, "trackers": [DECLARATION, source]}),
                        encoding="utf-8",
                    )
                    app = self.application()
                    with mock.patch.object(threading.Thread, "start") as starts:
                        report = diagnostics._plan_report(app.state)
                        status, _, body = request(app)
                    starts.assert_not_called()
                    self.runner.assert_not_called()
                    self.assertEqual([], report["trackers"])
                    lines = "\n".join(diagnostics._plan_lines(report))
                    self.assertIn("invalid tracker ask_labels", lines)
                    self.assertNotIn(canary, lines)
                    self.assertEqual(200, status)
                    self.assertEqual({"state": "refused", "reason": reason}, json.loads(body))


def tracker_source_digest(root: Path) -> str:
    plan = settings.load(str(root)).settings
    assert plan is not None
    return plan.digest
