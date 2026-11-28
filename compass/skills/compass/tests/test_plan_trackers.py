"""Offline coverage for the plan tracker worker and its supervised CLI boundary."""

from __future__ import annotations

import errno
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
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
        while result.reason == tracker_cli.Reason.REFRESHING and time.monotonic() < stop:
            time.sleep(0.005)
            result = read()
        self.assertNotEqual(tracker_cli.Reason.REFRESHING, result.reason)
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
            self.assertEqual(
                {
                    **self.environ,
                    "PATH": str(self.root),
                    "GH_PROMPT_DISABLED": "1",
                    "GH_NO_UPDATE_NOTIFIER": "1",
                    "NO_COLOR": "1",
                    "NoDefaultCurrentDirectoryInExePath": "1",
                }.keys()
                - {
                    "GH_HOST",
                    "GH_REPO",
                    "GH_TOKEN",
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


class TrackerRefreshTest(TrackerTestCase):
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

    def test_disable_and_reenable_discards_the_superseded_in_flight_result(self) -> None:
        entered = threading.Event()
        release = threading.Event()

        def blocked(argv: list[str], **options: Any) -> subprocess.CompletedProcess[bytes]:
            if self.runner.call_count == 1:
                entered.set()
                self.assertTrue(release.wait(3.0))
                return self.complete(argv, **options)
            options["stdout"].write(b'{"complete":true}')
            return subprocess.CompletedProcess(argv, 0)

        self.runner.side_effect = blocked
        try:
            self.snapshot()
            self.assertTrue(entered.wait(3.0))
            self.assertEqual(tracker_cli.Reason.DISABLED, self.snapshot(enabled=False)[0].reason)
            self.assertEqual(tracker_cli.Reason.REFRESHING, self.snapshot()[0].reason)
            self.assertEqual(1, self.runner.call_count)
        finally:
            release.set()
        read = self.result(lambda: self.snapshot()[0])
        self.assertEqual(tracker_refresh.TrackerData(goals=(), lanes=()), read.data)
        self.assertEqual(2, self.runner.call_count)

    def test_an_old_settings_load_cannot_restore_a_removed_source(self) -> None:
        first_fetch = self.refresh.begin_fetch()
        second_fetch = self.refresh.begin_fetch()
        self.assertEqual((), self.refresh.observe("", (), enabled=False, fetch=second_fetch))
        (stale,) = self.refresh.observe("one", (SOURCE,), enabled=True, fetch=first_fetch)
        self.assertIsNone(stale.data)
        self.runner.assert_not_called()

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

    def test_only_admitted_fetch_with_declaration_starts_tracker_even_with_git_off(self) -> None:
        app = self.application()
        self.assertEqual(200, request(app)[0])
        self.runner.assert_not_called()
        self.declare()
        self.assertEqual(403, request(app, headers="Forwarded: for=192.0.2.1\r\n")[0])
        self.assertEqual(403, request(app, peer="192.0.2.1")[0])
        self.runner.assert_not_called()
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

    def test_run_wide_off_switches_start_zero_tracker_processes(self) -> None:
        self.declare()
        for flag, status in (("--no-plan", 404), ("--no-plan-trackers", 200)):
            with self.subTest(flag=flag):
                self.assertEqual(status, request(self.application(flag))[0])
                self.runner.assert_not_called()

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


def tracker_source_digest(root: Path) -> str:
    plan = settings.load(str(root)).settings
    assert plan is not None
    return plan.digest
