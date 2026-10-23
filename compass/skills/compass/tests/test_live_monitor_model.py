"""The Live monitor's model setting: an explicit Haiku id, apart from the reading floor.

[DEC-26](docs/design-reading-a-session.md#amended-2026-10-23-owner-the-live-level-comes-from-a-haiku-check)
pins the monitor to an explicit Haiku id in its own setting. The reading validator and its
Sonnet floor stay as they were.
"""

from __future__ import annotations

import dataclasses
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Any

from compass_runtime import cli, config, live_monitor, observer

from .support import make_config

HAIKU = "claude-haiku-5-5"


class TheMonitorValidatorAdmitsOnlyAnExplicitHaikuId(unittest.TestCase):
    def test_the_reading_validator_refuses_haiku_and_the_monitor_validator_accepts_it(
        self,
    ) -> None:
        for value in (HAIKU, "claude-haiku-5", "claude-haiku-5-5-20261001"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    config.validate_claude_reading_model(value)
                self.assertEqual(value, config.validate_claude_monitor_model(value))

    def test_a_floating_alias_is_refused_by_both_validators(self) -> None:
        for value in ("haiku", "latest", "default", "claude-haiku", "claude-haiku-latest", ""):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    config.validate_claude_reading_model(value)
                with self.assertRaises(ValueError):
                    config.validate_claude_monitor_model(value)

    def test_the_monitor_validator_refuses_everything_that_is_not_haiku(self) -> None:
        for value in (
            "claude-sonnet-5-5",
            "claude-opus-5-5",
            "claude-haiku-5-5 --tools Bash",
            "--model=claude-haiku-5-5",
            "claude-haiku-5-5\n--resume",
            "claude-haiku-5-5-20260230",
            "claude-haiku-5.5",
            "claude-haiku-05",
            "claude-haiku-5-0",
            "claude-haiku-3-5",
        ):
            with self.subTest(value=value), self.assertRaises(ValueError):
                config.validate_claude_monitor_model(value)

    def test_the_reading_floor_is_unchanged(self) -> None:
        self.assertEqual("claude-sonnet-5-5", make_config().claude_reading_model)
        self.assertEqual("claude-sonnet-5", config.validate_claude_reading_model("claude-sonnet-5"))

    def test_the_default_is_the_newest_released_explicit_haiku_id(self) -> None:
        self.assertEqual(HAIKU, config.CLAUDE_MONITOR_DEFAULT_MODEL)
        self.assertEqual(HAIKU, make_config().claude_monitor_model)

    def test_the_release_checklist_asks_about_a_newer_haiku_and_names_the_default(self) -> None:
        checklist = (
            Path(__file__).parents[4] / ".claude" / "skills" / "compass-release" / "SKILL.md"
        )
        pre_flight = (
            checklist.read_text(encoding="utf-8").split("## 1. Pre-flight")[1].split("\n## 2.")[0]
        )
        self.assertIn("CLAUDE_MONITOR_DEFAULT_MODEL", pre_flight)
        self.assertIn("newer Haiku", pre_flight)

    def test_a_bad_monitor_model_is_refused_when_the_config_is_built(self) -> None:
        with self.assertRaises(ValueError):
            config.build_runtime_config(
                environ={},
                platform_name="linux",
                os_name="posix",
                launcher_path=Path("server.py"),
                claude_monitor_model="claude-sonnet-5-5",
            )

    def test_the_command_line_pins_the_monitor_model(self) -> None:
        args = cli.build_parser().parse_args([])
        self.assertEqual(HAIKU, args.claude_monitor_model)
        args = cli.build_parser().parse_args(["--claude-monitor-model", "claude-haiku-5-5"])
        self.assertEqual("claude-haiku-5-5", args.claude_monitor_model)
        with self.assertRaises(SystemExit):
            cli.build_parser().parse_args(["--claude-monitor-model", "haiku"])


class TheMonitorsChildIsTheSameSupervisedEnvelopeOnItsOwnModel(unittest.TestCase):
    def _run(self, **changes: Any) -> tuple[list[str], dict[str, Any]]:
        seen: list[tuple[list[str], dict[str, Any]]] = []

        def runner(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[Any]:
            seen.append((argv, kwargs))
            kwargs["stdout"].write(b"{}")
            return subprocess.CompletedProcess(argv, 0)

        with tempfile.TemporaryDirectory() as home:
            cfg = dataclasses.replace(make_config(), state_dir=Path(home), **changes)
            with live_monitor.prepare(
                cfg, runner=runner, binary_resolver=lambda _name: "/synthetic/bin/claude"
            ) as prepared:
                self.assertEqual(("{}", "ok"), prepared("evidence", output_cap_bytes=64))
        return seen[0]

    def test_the_child_asks_for_the_pinned_haiku_with_no_tools_and_no_session(self) -> None:
        argv, kwargs = self._run()
        self.assertEqual(1, argv.count("--model"))
        self.assertEqual(HAIKU, argv[argv.index("--model") + 1])
        self.assertEqual("", argv[argv.index("--tools") + 1])
        for flag in ("--safe-mode", "--restricted", "--no-session-persistence"):
            self.assertIn(flag, argv)
        self.assertNotIn("--resume", argv)
        self.assertNotIn("--continue", argv)
        self.assertEqual(make_config().live_monitor_timeout_sec, kwargs["timeout"])

    def test_the_reading_runner_still_refuses_a_haiku_model(self) -> None:
        # `claude_exec` and `prepare_claude_exec` keep the reading floor when asked for none.
        with tempfile.TemporaryDirectory() as home:
            cfg = dataclasses.replace(make_config(), state_dir=Path(home))
            with observer.prepare_claude_exec(
                cfg, binary_resolver=lambda _name: "/synthetic/bin/claude"
            ) as prepared:
                self.assertEqual("claude-sonnet-5-5", prepared.model)
            with (
                self.assertRaises(observer.ClaudePreparationError),
                observer.prepare_claude_exec(
                    cfg,
                    model=HAIKU,
                    binary_resolver=lambda _name: "/synthetic/bin/claude",
                ),
            ):
                pass

    def test_provenance_names_the_pinned_model_and_its_own_policy(self) -> None:
        cfg = make_config()
        provenance = live_monitor.provenance(cfg)
        self.assertEqual(HAIKU, provenance["selected_model"])
        self.assertIsNone(provenance["resolved_model"])
        self.assertEqual(config.CLAUDE_MONITOR_MODEL_POLICY, provenance["model_policy"])
        self.assertEqual("claude", provenance["provider"])
        newer = live_monitor.provenance(
            dataclasses.replace(cfg, claude_monitor_model="claude-haiku-5-6")
        )
        self.assertNotEqual(provenance["envelope_digest"], newer["envelope_digest"])


if __name__ == "__main__":
    unittest.main()
