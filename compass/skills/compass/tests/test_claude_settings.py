"""Applicable settings restrict Analyze without claiming a frozen CLI policy."""

from __future__ import annotations

import dataclasses
import importlib
import importlib.util
import inspect
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from compass_runtime import claude_settings, observer, reading_capacity, reading_route

from .support import make_config


class ClaudeSettingsTest(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.env = {"HOME": "/Users/r", "USER": "r"}

    def module(self) -> Any:
        self.assertIsNotNone(importlib.util.find_spec("compass_runtime.claude_settings"))
        return importlib.import_module("compass_runtime.claude_settings")

    def write(self, document: Any, path: str = "/etc/claude-code/managed-settings.json") -> Path:
        target = self.root / path.lstrip("/")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(document), encoding="utf-8")
        return target

    def resolve(self, model: str = "claude-sonnet-5-5", **kwargs: Any) -> Any:
        return self.module().resolve(
            model, environ=self.env, root=self.root, system="Linux", **kwargs
        )

    def test_no_observed_controls_is_direct_but_never_a_remote_policy_receipt(self) -> None:
        controls = self.resolve()
        self.assertEqual("direct", controls.deployment)
        self.assertEqual((), controls.window_limits)
        self.assertEqual("", controls.refusal)
        self.assertFalse(controls.policy_verified)

    def test_environment_main_drop_in_and_exact_model_windows_all_constrain(self) -> None:
        self.env["CLAUDE_CODE_MAX_CONTEXT_TOKENS"] = "900000"
        self.write(
            {"autoCompactWindow": 700_000, "env": {"CLAUDE_CODE_AUTO_COMPACT_WINDOW": "600000"}}
        )
        self.write(
            {
                "modelSettings": {
                    "claude-sonnet-5-5": {"autoCompactWindow": 200_000},
                    "claude-opus-5-5": {"autoCompactWindow": 100_000},
                }
            },
            "/etc/claude-code/managed-settings.d/10-limits.json",
        )
        controls = self.resolve()
        self.assertEqual("", controls.refusal)
        self.assertEqual(200_000, min(controls.window_limits))
        self.assertEqual({900_000, 700_000, 600_000, 200_000}, set(controls.window_limits))
        result = reading_capacity.assess(
            "small",
            system_prompt="system",
            provider="claude",
            model="claude-sonnet-5-5",
            deployment=controls.deployment,
            window_limits=controls.window_limits,
        )
        self.assertEqual(166_842, result.maximum_prompt_bytes)

    def test_disable_one_million_true_restricts_and_false_does_not(self) -> None:
        for flag, limits in (("1", (200_000,)), ("true", (200_000,)), ("0", ()), ("false", ())):
            with self.subTest(flag=flag):
                self.env["CLAUDE_CODE_DISABLE_1M_CONTEXT"] = flag
                self.assertEqual(limits, self.resolve().window_limits)

    def test_auto_and_irrelevant_fields_do_not_invent_restrictions(self) -> None:
        self.write(
            {
                "modelSettings": {
                    "claude-sonnet-5-5": {"autoCompactWindow": "auto", "effortLevel": "high"}
                },
                "companyAnnouncements": ["private"],
            }
        )
        self.assertEqual((), self.resolve().window_limits)

    def test_unknown_gateway_cloud_and_model_remapping_never_earn_expansion(self) -> None:
        for env, expected in (
            ({"ANTHROPIC_BASE_URL": "https://gateway.example"}, "gateway"),
            ({"CLAUDE_CODE_USE_BEDROCK": "1"}, "cloud"),
            ({"ANTHROPIC_UNIX_SOCKET": "/tmp/socket"}, "unknown"),
        ):
            with self.subTest(env=env):
                self.env.update(env)
                self.assertEqual(expected, self.resolve().deployment)
                for key in env:
                    del self.env[key]
        self.write({"modelOverrides": {"claude-sonnet-5-5": "private-target"}})
        controls = self.resolve()
        self.assertEqual("unknown", controls.deployment)
        self.assertEqual("", controls.refusal)
        self.assertNotIn("private-target", json.dumps(dataclasses.asdict(controls)))

    def test_bad_capacity_values_and_ambiguous_model_shapes_refuse(self) -> None:
        for value in (0, -1, True, 1.5, "200k", "1e6", "200000", None):
            with self.subTest(value=value):
                self.write({"autoCompactWindow": value})
                self.assertEqual("context-config", self.resolve().refusal)
        documents: tuple[dict[str, Any], ...] = (
            {"modelSettings": []},
            {"modelSettings": {"sonnet": {"autoCompactWindow": 200_000}}},
            {"modelSettings": {"claude-sonnet-5-5": None}},
            {"modelOverrides": []},
        )
        for document in documents:
            with self.subTest(document=document):
                self.write(document)
                self.assertEqual("context-config", self.resolve().refusal)

    def test_bad_environment_limits_refuse_instead_of_ignoring(self) -> None:
        for value in ("", "0", "-1", "200k", "NaN", "1_000_000", "9" * 100):
            with self.subTest(value=value):
                self.env["CLAUDE_CODE_MAX_CONTEXT_TOKENS"] = value
                self.assertEqual("context-config", self.resolve().refusal)

    def test_managed_compaction_and_fallback_conflicts_are_explicit(self) -> None:
        self.env["DISABLE_COMPACT"] = "0"
        self.assertEqual("", self.resolve().refusal)
        for document, reason in (
            ({"env": {"DISABLE_COMPACT": "0"}}, "compaction-policy-conflict"),
            ({"switchModelsOnFlag": True}, "fallback-policy-conflict"),
            ({"fallbackModel": "claude-opus-5"}, "fallback-policy-conflict"),
            ({"fallbackModel": ["claude-opus-5"]}, "fallback-policy-conflict"),
            ({"switchModelsOnFlag": "false"}, "context-config"),
        ):
            with self.subTest(document=document):
                self.write(document)
                self.assertEqual(reason, self.resolve().refusal)
        self.write(
            {"switchModelsOnFlag": False, "fallbackModel": [], "env": {"DISABLE_COMPACT": "1"}}
        )
        self.assertEqual("", self.resolve().refusal)

    def test_dynamic_and_remote_policy_cannot_be_certified_from_a_cache(self) -> None:
        for document in (
            {"policyHelper": {"path": "/never/run"}},
            {"forceRemoteSettingsRefresh": True},
            {"forceLoginGatewayUrl": "https://private"},
        ):
            with self.subTest(document=document):
                self.write(document)
                self.assertEqual("dynamic-policy", self.resolve().refusal)
        self.write({"forceRemoteSettingsRefresh": False})
        self.env["CLAUDE_CONFIG_DIR"] = "/custom"
        self.write({"autoCompactWindow": 180_000}, "/custom/remote-settings.json")
        controls = self.resolve()
        self.assertEqual("dynamic-policy", controls.refusal)
        self.assertIn(180_000, controls.window_limits)
        self.assertFalse(controls.policy_verified)

    def remote(self, document: Any) -> None:
        self.write(document, "/Users/r/.claude/remote-settings.json")

    def test_a_remote_settings_cache_holding_only_channels_enabled_lets_drift_analyze(self) -> None:
        self.remote({"channelsEnabled": True})
        controls = self.resolve()
        self.assertEqual("", controls.refusal)
        self.assertEqual("direct", controls.deployment)
        self.assertFalse(controls.policy_verified)

    def test_an_empty_remote_settings_cache_lets_drift_analyze(self) -> None:
        self.remote({})
        self.assertEqual("", self.resolve().refusal)

    def test_a_remote_settings_cache_with_a_key_that_can_change_the_model_still_refuses(
        self,
    ) -> None:
        for document in (
            {"modelOverrides": {"claude-sonnet-5-5": "other"}},
            {"forceRemoteSettingsRefresh": True},
            {"policyHelper": {"path": "/never/run"}},
            {"forceLoginMethod": "gateway"},
            {"forceLoginGatewayUrl": "https://private"},
            {"env": {"ANTHROPIC_MODEL": "claude-opus-4-1"}},
            {"model": "claude-opus-4-1"},
            {"availableModels": ["opus"]},
            {"someFutureKeyNobodyHasHeardOf": 1},
            {"channelsEnabled": True, "someFutureKeyNobodyHasHeardOf": 1},
        ):
            with self.subTest(document=document):
                self.remote(document)
                self.assertEqual("dynamic-policy", self.resolve().refusal)

    def test_the_harmless_keys_are_the_six_the_owner_ruling_names(self) -> None:
        ruling = (self.repo_root() / "docs/design-reading-a-session.md").read_text(encoding="utf-8")
        heading = "### Owner ruling 2026-11-06: a remote settings cache is dynamic only when"
        paragraph = ruling[ruling.index(heading) :].split("\n\n")
        (named,) = (text for text in paragraph if "`_REMOTE_HARMLESS`" in text)
        listed = named.split("`_REMOTE_HARMLESS`", 1)[1].split(")", 1)[0]
        self.assertEqual(
            set(re.findall(r"`([^`]+)`", listed)), set(claude_settings._REMOTE_HARMLESS)
        )

    def repo_root(self) -> Path:
        return Path(__file__).resolve().parents[4]

    def test_an_unreadable_remote_settings_cache_still_refuses(self) -> None:
        target = self.root / "Users/r/.claude/remote-settings.json"
        target.parent.mkdir(parents=True)
        target.write_text("{not json", encoding="utf-8")
        self.assertEqual("context-config", self.resolve().refusal)

    def test_unreadable_unknown_managed_sources_refuse(self) -> None:
        self.env["CLAUDE_CODE_MANAGED_SETTINGS_PATH"] = "/unknown"
        self.assertEqual("context-config", self.resolve().refusal)
        del self.env["CLAUDE_CODE_MANAGED_SETTINGS_PATH"]
        self.assertEqual(
            "context-config",
            self.module()
            .resolve("claude-sonnet-5-5", environ=self.env, root=self.root, system="Windows")
            .refusal,
        )
        self.write({}, "/Library/Managed Preferences/com.anthropic.claudecode.plist")
        self.assertEqual(
            "context-config",
            self.module()
            .resolve("claude-sonnet-5-5", environ=self.env, root=self.root, system="Darwin")
            .refusal,
        )

    def test_bounded_documents_and_duplicate_keys_refuse(self) -> None:
        path = self.write({})
        for text in (
            '{"autoCompactWindow":200000,"autoCompactWindow":1000000}',
            " " * (1_048_576 + 1),
            "[]",
            '{"env": {"DISABLE_COMPACT": false}}',
        ):
            with self.subTest(length=len(text)):
                path.write_text(text, encoding="utf-8")
                self.assertEqual("context-config", self.resolve().refusal)

    def test_original_destination_env_semantics_and_ignored_user_settings_remain(self) -> None:
        self.write(
            {
                "autoCompactWindow": "invalid",
                "env": {"ANTHROPIC_BASE_URL": "https://gateway.example"},
            }
        )
        self.write({"policyHelper": {"path": "/never"}}, "/Users/r/.claude/settings.json")
        self.assertEqual(
            "gateway.example",
            reading_route.destination("claude", environ=self.env, root=self.root, system="Linux"),
        )
        self.write({})
        self.assertEqual("", self.resolve().refusal)

    def test_unread_windows_policy_and_forced_agent_or_gateway_mode_refuse(self) -> None:
        self.env["WSL_DISTRO_NAME"] = "test"
        self.assertEqual("context-config", self.resolve().refusal)
        del self.env["WSL_DISTRO_NAME"]
        self.write({"agent": "configured-agent"})
        self.assertEqual("context-config", self.resolve().refusal)
        self.write({"forceLoginMethod": "gateway"})
        self.assertEqual("dynamic-policy", self.resolve().refusal)

    def test_date_suffix_keeps_canonical_lower_limit_without_known_model_promotion(self) -> None:
        self.write({"modelSettings": {"claude-sonnet-5-5": {"autoCompactWindow": 150_000}}})
        controls = self.resolve(model="claude-sonnet-5-5-20261101")
        self.assertEqual((150_000,), controls.window_limits)

    def test_relative_source_selectors_cannot_be_resolved_against_the_child_cwd(self) -> None:
        for key, value in (("HOME", "relative"), ("CLAUDE_CONFIG_DIR", "~/claude")):
            with self.subTest(key=key):
                original = self.env.copy()
                self.env[key] = value
                self.assertEqual("context-config", self.resolve().refusal)
                self.env = original

    def test_other_recognized_models_do_not_lower_the_selected_models_window(self) -> None:
        self.write({"modelSettings": {"claude-haiku-5-5": {"autoCompactWindow": 100_000}}})
        controls = self.resolve()
        self.assertEqual("", controls.refusal)
        self.assertEqual((), controls.window_limits)

    def test_nonregular_documents_and_excessive_source_enumeration_refuse(self) -> None:
        path = self.write({})
        path.unlink()
        path.mkdir()
        self.assertEqual("context-config", self.resolve().refusal)
        path.rmdir()
        for index in range(65):
            self.write({}, f"/etc/claude-code/managed-settings.d/{index}.json")
        self.assertEqual("context-config", self.resolve().refusal)


class AnalyzeClaudeExecutionTest(unittest.TestCase):
    def test_analyze_execution_controls_are_explicit_and_stdin_is_unchanged(self) -> None:
        self.assertIn("analyze", inspect.signature(observer.claude_exec).parameters)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            stub = root / "stub.py"
            stub.write_text(
                "import json, os, sys\nprint(json.dumps({'argv':sys.argv[1:], 'stdin':sys.stdin.read(), 'compact':os.environ.get('DISABLE_COMPACT')}))\n",
                encoding="utf-8",
            )
            config = dataclasses.replace(make_config(), state_dir=root / "state")

            def runner(command: list[str], **kwargs: Any) -> Any:
                self.assertFalse(kwargs.pop("check"))
                return subprocess.run([sys.executable, *command], check=False, **kwargs)

            module = importlib.import_module("compass_runtime.claude_settings")
            controls = module.Controls(deployment="direct")
            with (
                mock.patch.object(module, "resolve", return_value=controls),
                mock.patch.dict(os.environ, {"DISABLE_COMPACT": "0"}),
            ):
                for analyze in (False, True):
                    text, status = observer.claude_exec(
                        config,
                        "unchanged 界🙂",
                        output_cap_bytes=8192,
                        runner=runner,
                        binary_resolver=lambda _name: str(stub),
                        analyze=analyze,
                    )
                    self.assertEqual("ok", status)
                    captured = json.loads(text)
                    self.assertEqual("unchanged 界🙂", captured["stdin"])
                    self.assertEqual("1" if analyze else "0", captured["compact"])
                    argv = captured["argv"]
                    self.assertNotIn("--fallback-model", argv)
                    for flag in ("--restricted", "--safe-mode", "--strict-mcp-config"):
                        self.assertIn(flag, argv)
                    if analyze:
                        self.assertEqual(
                            {"switchModelsOnFlag": False},
                            json.loads(argv[argv.index("--settings") + 1]),
                        )
                    else:
                        self.assertNotIn("--settings", argv)
                self.assertEqual("0", os.environ["DISABLE_COMPACT"])

    def test_a_policy_change_after_preparation_refuses_before_the_runner(self) -> None:
        self.assertIn("analyze", inspect.signature(observer.prepare_claude_exec).parameters)
        module = importlib.import_module("compass_runtime.claude_settings")
        with tempfile.TemporaryDirectory() as directory:
            config = dataclasses.replace(make_config(), state_dir=Path(directory))
            runner = mock.Mock()
            with (
                mock.patch.object(
                    module,
                    "resolve",
                    side_effect=[
                        module.Controls(deployment="direct"),
                        module.Controls(refusal="fallback-policy-conflict"),
                    ],
                ),
                observer.prepare_claude_exec(
                    config,
                    runner=runner,
                    binary_resolver=lambda _name: "/synthetic/claude",
                    analyze=True,
                ) as prepared,
            ):
                self.assertEqual(("", "context-config"), prepared("words", output_cap_bytes=8192))
            runner.assert_not_called()

    def test_the_final_capacity_check_counts_the_actual_explicit_system_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = dataclasses.replace(make_config(), state_dir=Path(directory))
            runner = mock.Mock(return_value=subprocess.CompletedProcess([], 0))
            controls = claude_settings.Controls(deployment="direct", window_limits=(180_000,))
            with (
                mock.patch.object(claude_settings, "resolve", return_value=controls),
                observer.prepare_claude_exec(
                    config,
                    runner=runner,
                    binary_resolver=lambda _name: "/synthetic/claude",
                    system_prompt="界" * 40_000,
                    analyze=True,
                ) as prepared,
            ):
                self.assertEqual(("", "context-config"), prepared("small", output_cap_bytes=8192))
            runner.assert_not_called()
