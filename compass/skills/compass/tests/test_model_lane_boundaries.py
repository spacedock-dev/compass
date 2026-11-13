"""What every model lane hands its CLI child, and what it refuses before starting one.

Five lanes start Claude Code (Analyze, goal find, unasked checks, summaries and the Live monitor)
and two start Codex (goal lines and readings). Each test drives a lane's own entry point and
watches the runner it would spawn with, so a lane that skips the shared check turns red here.
"""

from __future__ import annotations

import dataclasses
import inspect
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any, ClassVar
from unittest import mock

from compass_runtime import (
    goal_find,
    live_monitor,
    observer,
    reading_policy,
    summary_jobs,
    supervise,
)
from compass_runtime import reading as runtime_reading

from .support import make_config

POSIX_ONLY = unittest.skipIf(sys.platform == "win32", "ownership and mode bits are POSIX")


def _config() -> Any:
    state_dir = Path(tempfile.mkdtemp())
    return dataclasses.replace(make_config(), state_dir=state_dir, observer_model_enabled=True)


class _Spawns:
    """A runner that records what it was handed and writes an empty JSON reply."""

    def __init__(self) -> None:
        self.calls: list[tuple[list[str], dict[str, Any], dict[str, Any]]] = []

    def __call__(self, command: list[str], **kwargs: Any) -> Any:
        cwd = Path(kwargs["cwd"])
        seen = {
            "exists": cwd.is_dir(),
            "mode": stat.S_IMODE(cwd.stat().st_mode) if cwd.is_dir() else None,
            "entries": sorted(os.listdir(cwd)) if cwd.is_dir() else None,
        }
        self.calls.append((list(command), kwargs, seen))
        stdout = kwargs.get("stdout")
        if stdout is not None and hasattr(stdout, "write"):
            stdout.write(b"{}")
        return subprocess.CompletedProcess(command, 0, "", "")


class ClaudeChildEnvironmentIsAnAllowlist(unittest.TestCase):
    KEPT: ClassVar[dict[str, str]] = {
        "PATH": "/usr/bin",
        "HOME": "/Users/r",
        "USER": "r",
        "LOGNAME": "r",
        "SHELL": "/bin/zsh",
        "TMPDIR": "/var/tmp",
        "LANG": "en_US.UTF-8",
        "LC_ALL": "en_US.UTF-8",
        "TZ": "UTC",
        "ANTHROPIC_API_KEY": "test-key-not-real",
        "ANTHROPIC_BASE_URL": "https://gateway.invalid",
        "CLAUDE_CODE_USE_BEDROCK": "1",
        "CLAUDE_CODE_OAUTH_TOKEN": "test-token-not-real",
        "AWS_PROFILE": "work",
        "AWS_REGION": "us-east-1",
        "HTTPS_PROXY": "http://proxy.invalid:3128",
        "https_proxy": "http://proxy.invalid:3128",
        "NO_PROXY": "localhost",
        "NODE_EXTRA_CA_CERTS": "/etc/ssl/corp.pem",
        "NODE_USE_SYSTEM_CA": "1",
        "CLAUDE_CODE_CERT_STORE": "system",
        "CLAUDE_CODE_CUSTOM_OAUTH_URL": "https://login.invalid",
        "AZURE_CLIENT_ID": "test-client-not-real",
        "CLAUDE_CODE_GIT_BASH_PATH": "C:/Program Files/Git/bin/bash.exe",
        "API_TIMEOUT_MS": "600000",
        "GCE_METADATA_HOST": "metadata.invalid",
    }
    DROPPED = (
        "NODE_OPTIONS",
        "OTEL_EXPORTER_OTLP_ENDPOINT",
        "OTEL_SERVICE_NAME",
        "CLAUDE_CODE_ENABLE_TELEMETRY",
        "CLAUDE_CODE_SHELL_PREFIX",
        "BASH_ENV",
        "PYTHONPATH",
        "SOME_TOOL_TOKEN",
        "CLAUDECODE",
        "CLAUDE_CODE_SESSION_ID",
        "CLAUDE_CODE_MESSAGING_SOCKET",
    )

    def test_only_what_sign_in_and_the_endpoint_need_reaches_the_child(self) -> None:
        environ = {**self.KEPT, **dict.fromkeys(self.DROPPED, "x")}
        child = observer.claude_environment(environ)
        for name, value in self.KEPT.items():
            with self.subTest(kept=name):
                self.assertEqual(value, child.get(name))
        for name in self.DROPPED:
            with self.subTest(dropped=name):
                self.assertNotIn(name, child)
        self.assertEqual("1", child["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"])

    @POSIX_ONLY
    def test_a_config_folder_is_handed_on_only_when_it_is_verified(self) -> None:
        folder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, folder, True)
        child = observer.claude_environment({"CLAUDE_CONFIG_DIR": str(folder)})
        self.assertEqual(str(folder), child.get("CLAUDE_CONFIG_DIR"))
        folder.chmod(0o777)
        self.assertNotIn(
            "CLAUDE_CONFIG_DIR", observer.claude_environment({"CLAUDE_CONFIG_DIR": str(folder)})
        )
        self.assertNotIn(
            "CLAUDE_CONFIG_DIR", observer.claude_environment({"CLAUDE_CONFIG_DIR": "relative"})
        )


@POSIX_ONLY
class EveryClaudeLaneRefusesSettingsThatMoveTheCall(unittest.TestCase):
    """A remote cache naming a shell helper: every lane refuses before anything is spawned."""

    def setUp(self) -> None:
        self.folder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.folder, True)
        self.config = _config()
        self.addCleanup(shutil.rmtree, self.config.state_dir, True)
        patcher = mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": str(self.folder)})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.runner = _Spawns()
        self.which = mock.Mock(return_value="/usr/local/bin/claude")

    def settings(self, document: dict[str, Any]) -> None:
        (self.folder / "remote-settings.json").write_text(json.dumps(document), encoding="utf-8")

    def reading_model(self, *, analyze: bool) -> runtime_reading.ClaudeReadingModel:
        return runtime_reading.ClaudeReadingModel(
            self.config, runner=self.runner, binary_resolver=self.which, analyze=analyze
        )

    def test_with_harmless_settings_each_lane_still_starts_its_child(self) -> None:
        self.settings({"channelsEnabled": True})
        self.assertEqual("ok", self.reading_model(analyze=False)("p", output_cap_bytes=64)[1])
        with live_monitor.prepare(
            self.config, runner=self.runner, binary_resolver=self.which
        ) as prepared:
            self.assertEqual("ok", prepared("p", output_cap_bytes=64)[1])
        self.assertEqual(2, len(self.runner.calls))

    def test_analyze_refuses_before_spawning(self) -> None:
        self.settings({"apiKeyHelper": "/never/run"})
        self.assertEqual(
            ("", "context-config"), self.reading_model(analyze=True)("p", output_cap_bytes=64)
        )
        self.assertEqual([], self.runner.calls)

    def test_goal_find_refuses_before_the_charge_with_a_reason_of_its_own(self) -> None:
        # Goal find builds this model with `analyze` off (`http_api._goal_find_session`), behind
        # a GuardedModel whose preflight asks the settings check before anything is charged.
        self.settings({"forceLoginGatewayUrl": "https://gateway.invalid"})
        model = self.reading_model(analyze=False)
        self.assertEqual(observer.SETTINGS_REFUSED, model.settings_refusal())
        self.assertEqual(("", "context-config"), model("p", output_cap_bytes=64))
        guarded = reading_policy.GuardedModel(self.config, model, time.time, provider="claude")
        prompt = goal_find.Prompt(1, "f1", 0.0, None, "ship the parser")
        result = goal_find.find([prompt], guarded, goal_cap=200)
        self.assertFalse(result.called, "a refused press must not be charged")
        self.assertEqual(goal_find.WHY_SETTINGS_REFUSED, result.why)
        self.assertFalse(guarded.reserved)
        self.assertEqual([], self.runner.calls)

    def test_the_unasked_lane_refuses_unspent_with_a_reason_of_its_own(self) -> None:
        self.settings({"apiKeyHelper": "/never/run"})
        model = self.reading_model(analyze=False)
        guarded = reading_policy.GuardedModel(
            self.config, model, time.time, provider="claude", unasked=True
        )
        self.assertEqual(("", observer.SETTINGS_REFUSED), guarded("p", output_cap_bytes=64))
        self.assertEqual(
            (runtime_reading.WITHHELD_SETTINGS_REFUSED, False),
            runtime_reading._call_failed(model, observer.SETTINGS_REFUSED),
        )
        self.assertEqual([], self.runner.calls)

    def test_analyze_keeps_its_own_admission_reasons(self) -> None:
        self.settings({"apiKeyHelper": "/never/run"})
        self.assertEqual("", self.reading_model(analyze=True).settings_refusal())

    def test_a_summary_refuses_before_the_charge_and_the_spawn(self) -> None:
        self.settings({"awsAuthRefresh": "/never/run"})
        application = SimpleNamespace(config=self.config)
        job = SimpleNamespace(reason="")
        model = summary_jobs.ClaudeSummaryModel(application, job)  # type: ignore[arg-type]
        self.assertEqual(observer.SETTINGS_REFUSED, model.settings_refusal())
        self.assertIn(observer.SETTINGS_REFUSED, summary_jobs.PRODUCER_STOPS)
        with (
            mock.patch("shutil.which", return_value="/usr/local/bin/claude"),
            mock.patch.object(supervise, "run") as run,
        ):
            self.assertEqual(("", "context-config"), model("p", output_cap_bytes=64))
        run.assert_not_called()

    def test_the_live_monitor_refuses_before_spawning(self) -> None:
        self.settings({"env": {"OTEL_LOG_USER_PROMPTS": "1"}})
        with (
            self.assertRaises(observer.ClaudePreparationError) as raised,
            live_monitor.prepare(self.config, runner=self.runner, binary_resolver=self.which),
        ):
            self.fail("prepared a monitor call under settings that export telemetry")
        self.assertEqual(observer.SETTINGS_REFUSED, raised.exception.status)
        self.assertEqual([], self.runner.calls)

    def test_a_conflict_beside_a_helper_still_refuses_every_lane(self) -> None:
        for document in (
            {"apiKeyHelper": "/never/run", "fallbackModel": "claude-sonnet-5"},
            {"forceLoginGatewayUrl": "https://gateway.invalid", "env": {"DISABLE_COMPACT": "0"}},
            {"env": {"OTEL_LOG_TOOL_DETAILS": "1"}, "switchModelsOnFlag": True},
        ):
            with self.subTest(document=document):
                self.settings(document)
                self.assertEqual(
                    "context-config", observer.claude_lane_refusal("claude-sonnet-5-5")
                )

    def test_settings_that_change_after_preparation_stop_the_launch(self) -> None:
        self.settings({"channelsEnabled": True})
        with observer.prepare_claude_exec(
            self.config, runner=self.runner, binary_resolver=self.which
        ) as prepared:
            self.settings({"gcpAuthRefresh": "/never/run"})
            self.assertEqual(("", "context-config"), prepared("p", output_cap_bytes=64))
        self.assertEqual([], self.runner.calls)

    def test_a_config_folder_another_account_could_write_refuses_every_lane(self) -> None:
        self.settings({"channelsEnabled": True})
        self.folder.chmod(0o777)
        for analyze in (False, True):
            with self.subTest(analyze=analyze):
                status = self.reading_model(analyze=analyze)("p", output_cap_bytes=64)[1]
                self.assertEqual("context-config", status)
        self.assertEqual([], self.runner.calls)


class CodexRunsInAnEmptyFolderWithAnAllowlistedEnvironment(unittest.TestCase):
    def setUp(self) -> None:
        self.config = _config()
        self.addCleanup(shutil.rmtree, self.config.state_dir, True)
        self.runner = _Spawns()

    def run_codex(self, runner: Any = None, which: str | None = "/usr/bin/codex") -> str:
        return observer.codex_exec(
            self.config,
            "p",
            output_cap_bytes=64,
            runner=runner or self.runner,
            binary_resolver=mock.Mock(return_value=which),
        )[1]

    def test_the_child_starts_in_a_fresh_owner_only_folder_outside_the_state_dir(self) -> None:
        self.assertEqual("ok", self.run_codex())
        _command, kwargs, seen = self.runner.calls[0]
        cwd = kwargs["cwd"]
        self.assertTrue(seen["exists"])
        self.assertEqual([], seen["entries"])
        if sys.platform != "win32":
            self.assertEqual(0o700, seen["mode"])
        root = observer.reading_workdir_root()
        self.assertIsNotNone(root)
        self.assertEqual(os.path.realpath(str(root)), os.path.dirname(os.path.realpath(cwd)))
        self.assertNotEqual(os.path.realpath(self.config.state_dir), os.path.realpath(cwd))
        self.assertFalse(os.path.exists(cwd), "the folder outlived the call")

    def test_the_folder_is_removed_after_a_timeout_too(self) -> None:
        folders: list[str] = []

        def times_out(command: list[str], **kwargs: Any) -> Any:
            folders.append(kwargs["cwd"])
            raise subprocess.TimeoutExpired(command, 1)

        self.assertEqual("failed", self.run_codex(times_out))
        self.assertEqual(1, len(folders))
        self.assertFalse(os.path.exists(folders[0]))

    def test_no_folder_that_could_name_the_account_means_no_call(self) -> None:
        with mock.patch.object(observer, "reading_workdir_root", return_value=None):
            self.assertEqual("failed", self.run_codex())
        self.assertEqual([], self.runner.calls)

    def test_mcp_servers_are_requested_empty(self) -> None:
        self.run_codex()
        command = self.runner.calls[0][0]
        values = [command[i + 1] for i, item in enumerate(command[:-1]) if item == "--config"]
        self.assertIn("mcp_servers={}", values)

    def test_the_child_gets_the_allowlisted_environment(self) -> None:
        with mock.patch.dict(
            os.environ,
            {"NODE_OPTIONS": "--require x", "OTEL_EXPORTER_OTLP_ENDPOINT": "http://c.invalid"},
        ):
            self.run_codex()
            expected = observer.codex_environment(os.environ)
        env = self.runner.calls[0][1]["env"]
        self.assertEqual(expected, env)
        self.assertNotIn("NODE_OPTIONS", env)
        self.assertNotIn("OTEL_EXPORTER_OTLP_ENDPOINT", env)

    def test_a_relative_codex_is_never_started(self) -> None:
        self.assertEqual("unavailable", self.run_codex(which="bin/codex"))
        self.assertEqual([], self.runner.calls)

    @POSIX_ONLY
    def test_a_refused_codex_reading_is_not_charged(self) -> None:
        folder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, folder, True)
        folder.chmod(0o777)
        model = runtime_reading.CodexReadingModel(
            self.config, runner=self.runner, binary_resolver=lambda _name: "/usr/bin/codex"
        )
        self.assertEqual("", model.settings_refusal())
        for patch in (
            mock.patch.dict(os.environ, {"CODEX_HOME": str(folder)}),
            mock.patch.object(observer, "reading_workdir_root", return_value=None),
        ):
            with self.subTest(patch=patch), patch:
                # Codex is installed; what refuses is this machine's set-up, said as such and
                # never as "the Codex CLI was not found".
                self.assertTrue(model.available())
                self.assertEqual(observer.SETTINGS_REFUSED, model.settings_refusal())
                guarded = reading_policy.GuardedModel(
                    self.config, model, time.time, provider="codex"
                )
                self.assertEqual(("", observer.SETTINGS_REFUSED), guarded("p", output_cap_bytes=64))
                self.assertFalse(guarded.reserved)
                self.assertEqual(
                    (runtime_reading.WITHHELD_SETTINGS_REFUSED, False),
                    runtime_reading._call_failed(model, observer.SETTINGS_REFUSED),
                )
        self.assertEqual([], self.runner.calls)

    @POSIX_ONLY
    def test_with_no_path_set_codex_is_looked_up_on_the_default_path(self) -> None:
        here = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, here, True)
        program = here / "codex"
        program.write_text("#!/bin/sh\n")
        program.chmod(0o700)
        environ = {key: value for key, value in os.environ.items() if key != "PATH"}
        with (
            mock.patch.dict(os.environ, environ, clear=True),
            mock.patch.object(os, "defpath", str(here)),
        ):
            self.assertEqual(str(program), observer.codex_binary("codex"))

    @POSIX_ONLY
    def test_a_goal_line_refused_by_this_machines_set_up_says_so(self) -> None:
        folder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, folder, True)
        folder.chmod(0o777)
        caller = observer.CodexGoalModel(
            self.config,
            runner=self.runner,
            binary_resolver=lambda _name: "/usr/bin/codex",
            consent=True,
            session_key="codex:one",
        )
        with (
            mock.patch.object(
                reading_policy,
                "status",
                return_value={"consent": True, "off": False, "reason": ""},
            ),
            mock.patch.dict(os.environ, {"CODEX_HOME": str(folder)}),
        ):
            self.assertIsNone(caller("a transcript tail", "stage"))
        self.assertEqual(observer.SETTINGS_REFUSED, caller.status)
        self.assertEqual([], self.runner.calls)

    @POSIX_ONLY
    def test_a_relative_path_entry_is_skipped_when_codex_is_looked_up(self) -> None:
        here = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, here, True)
        for folder in ("rel", "abs"):
            program = here / folder / "codex"
            program.parent.mkdir()
            program.write_text("#!/bin/sh\n")
            program.chmod(0o700)
        cwd = os.getcwd()
        os.chdir(here)
        self.addCleanup(os.chdir, cwd)
        with mock.patch.dict(os.environ, {"PATH": f"rel{os.pathsep}{here / 'abs'}"}):
            self.assertEqual(str(here / "abs" / "codex"), observer.codex_binary("codex"))

    def test_every_codex_lookup_defaults_to_the_rooted_resolver(self) -> None:
        from compass_runtime import (  # noqa: PLC0415
            reading_long_coordinator,
            reading_long_execution,
            reading_long_reconcile,
            reading_long_worker,
            reading_route,
        )

        # The long-reading modules pass their resolver down unset; the slot guard, which may
        # import the observer, turns unset into the rooted lookup.
        for function in (
            reading_long_worker.run_maps,
            reading_long_reconcile.finish,
            reading_long_coordinator.launch,
        ):
            with self.subTest(function=function.__qualname__):
                default = inspect.signature(function).parameters["binary_resolver"].default
                self.assertIsNone(default)
        self.assertIs(observer.codex_binary, reading_long_execution.resolver(None))
        named = mock.Mock()
        self.assertIs(named, reading_long_execution.resolver(named))
        which = mock.Mock(return_value=None)
        with mock.patch.object(observer, "codex_binary", which):
            reading_route.resolve("codex", environ={}, root=Path("/nonexistent"))
        self.assertTrue(which.called)

    @POSIX_ONLY
    def test_a_codex_home_another_account_could_write_is_never_used(self) -> None:
        folder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, folder, True)
        folder.chmod(0o777)
        with mock.patch.dict(os.environ, {"CODEX_HOME": str(folder)}):
            self.assertEqual("failed", self.run_codex())
        self.assertEqual([], self.runner.calls)

    def test_codex_environment_keeps_sign_in_and_drops_the_rest(self) -> None:
        environ = {
            "PATH": "/usr/bin",
            "HOME": "/Users/r",
            "OPENAI_API_KEY": "test-key-not-real",
            "HTTPS_PROXY": "http://proxy.invalid:3128",
            "SSL_CERT_FILE": "/etc/ssl/corp.pem",
            "NODE_USE_SYSTEM_CA": "1",
            "CODEX_CA_CERTIFICATE": "/etc/ssl/corp.pem",
            "NODE_OPTIONS": "--require x",
            "OTEL_EXPORTER_OTLP_ENDPOINT": "http://c.invalid",
            "SOME_TOOL_TOKEN": "x",
            "CLAUDECODE": "1",
        }
        child = observer.codex_environment(environ)
        for name in (
            "PATH",
            "HOME",
            "OPENAI_API_KEY",
            "HTTPS_PROXY",
            "SSL_CERT_FILE",
            "NODE_USE_SYSTEM_CA",
            "CODEX_CA_CERTIFICATE",
        ):
            with self.subTest(kept=name):
                self.assertEqual(environ[name], child.get(name))
        for name in (
            "NODE_OPTIONS",
            "OTEL_EXPORTER_OTLP_ENDPOINT",
            "SOME_TOOL_TOKEN",
            "CLAUDECODE",
        ):
            with self.subTest(dropped=name):
                self.assertNotIn(name, child)


if __name__ == "__main__":
    unittest.main()
