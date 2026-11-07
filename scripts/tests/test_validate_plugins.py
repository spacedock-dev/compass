"""Negative and rendering tests for the repository plugin validator."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, ClassVar
from unittest import mock

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import validate_plugins as validator


class ValidatorTests(unittest.TestCase):
    def write_temp(self, body: str, name: str = "fixture.yaml") -> Path:
        directory = Path(tempfile.mkdtemp(prefix="compass-validator-"))
        path = directory / name
        path.write_text(body)
        self.addCleanup(directory.rmdir)
        self.addCleanup(lambda: path.unlink(missing_ok=True))
        return path

    def copy_plugin(self) -> Path:
        """A complete installed copy of the plugin, outside the checkout."""
        destination = Path(tempfile.mkdtemp(prefix="compass-installed-")) / "compass"
        shutil.copytree(validator.ROOT / "compass", destination)
        self.addCleanup(shutil.rmtree, destination.parent, ignore_errors=True)
        return destination

    def test_a_complete_installed_copy_passes_the_runtime_inventory(self) -> None:
        validation = validator.Validation()

        validator.validate_runtime_files(self.copy_plugin(), validation)

        self.assertEqual([], validation.errors)

    def test_every_required_runtime_file_category_is_caught_when_missing(self) -> None:
        # One representative per category the plan names, each deleted only
        # inside its own temporary copy. The whole point of an explicit
        # inventory is that an omission is reported rather than inferred, so
        # each case asserts the precise relative path comes back.
        categories = {
            "launcher": "skills/compass/server.py",
            "hook forwarder": "skills/compass/notify_hook.py",
            "package initializer": "skills/compass/compass_runtime/__init__.py",
            "runtime module": "skills/compass/compass_runtime/cli.py",
            "collector": "skills/compass/compass_runtime/collectors/goose.py",
            "JavaScript adapter": "skills/compass/opencode_plugin.js",
            "frontend asset": "skills/compass/compass_runtime/web/react.html",
        }
        for category, relative in categories.items():
            with self.subTest(category=category):
                plugin_root = self.copy_plugin()
                (plugin_root / relative).unlink()
                validation = validator.Validation()

                validator.validate_runtime_files(plugin_root, validation)

                self.assertTrue(
                    any(relative in error and "is missing" in error for error in validation.errors),
                    f"{category} not reported: {validation.errors}",
                )

    def test_a_directory_where_a_runtime_file_belongs_is_rejected(self) -> None:
        # exists() would call this present, and the failure would then surface
        # as an ImportError from an installed copy instead of here.
        plugin_root = self.copy_plugin()
        target = plugin_root / "skills/compass/compass_runtime/config.py"
        target.unlink()
        target.mkdir()
        validation = validator.Validation()

        validator.validate_runtime_files(plugin_root, validation)

        self.assertTrue(
            any("must be a file, not a directory" in error for error in validation.errors),
            validation.errors,
        )

    def test_the_inventory_covers_every_shipped_runtime_file(self) -> None:
        # The inventory is hand-written so it can notice an omission, which means
        # it can also fall behind. Compare it against what the checkout actually
        # ships: a new runtime module or asset must be added here deliberately.
        skill = validator.ROOT / "compass" / "skills" / "compass"
        # Discovered rather than listed. The top-level scripts were named here by
        # hand, and adding `event_hook.py` beside them failed this test for the
        # right reason but in the wrong place: the inventory is the thing meant to
        # be deliberate, not this test's idea of what exists. `glob`, not `rglob`,
        # so `tests/` and `agents/` stay out.
        plugin_root = validator.ROOT / "compass"
        shipped = {
            path.relative_to(plugin_root).as_posix()
            for path in (*skill.glob("*.py"), *skill.glob("*.js"))
        }
        # Hook definitions count too. They are not read by the dashboard, but they
        # fail the same way: absent from an install, the harness registers no hooks
        # and reports no events, silently. Both locations, because the harnesses
        # disagree: Claude and Codex read files under `hooks/`, Antigravity reads a
        # root `hooks.json`.
        shipped |= {
            path.relative_to(plugin_root).as_posix()
            for path in (plugin_root / "hooks").glob("*.json")
        }
        shipped |= {path.name for path in plugin_root.glob("hooks.json") if path.is_file()}
        for path in (skill / "compass_runtime").rglob("*"):
            if not path.is_file() or "__pycache__" in path.parts:
                continue
            if path.suffix in {".py", ".html", ".css", ".js", ".b64", ".txt", ".json"}:
                shipped.add(path.relative_to(validator.ROOT / "compass").as_posix())

        self.assertEqual(sorted(shipped), sorted(validator.COMPASS_RUNTIME_FILES))

    def test_frontmatter_rejects_malformed_flow_yaml(self) -> None:
        path = self.write_temp(
            "---\nname: broken\ndescription: [unterminated\n---\nbody\n", "SKILL.md"
        )
        validation = validator.Validation()

        self.assertIsNone(validator.parse_frontmatter(path, validation))
        self.assertTrue(any("invalid frontmatter YAML" in error for error in validation.errors))

    def test_frontmatter_rejects_duplicate_keys(self) -> None:
        path = self.write_temp(
            "---\nname: first\nname: second\ndescription: Duplicate\n---\n", "SKILL.md"
        )
        validation = validator.Validation()

        self.assertIsNone(validator.parse_frontmatter(path, validation))
        self.assertTrue(any("duplicate key" in error for error in validation.errors))

    def test_openai_metadata_rejects_invalid_escape(self) -> None:
        path = self.write_temp(
            'interface:\n  display_name: "Bad\\qEscape"\n'
            '  short_description: "A sufficiently long description"\n'
            '  default_prompt: "Use $broken to help."\n',
            "openai.yaml",
        )
        validation = validator.Validation()

        self.assertIsNone(validator.parse_openai_metadata(path, validation))
        self.assertTrue(
            any("invalid agents/openai.yaml YAML" in error for error in validation.errors)
        )

    def test_catalog_estimate_includes_namespace_and_locator(self) -> None:
        path = validator.ROOT / "compass/skills/compass/SKILL.md"
        line = validator.render_catalog_estimate_line("compass", "compass", "Map agents.", path)

        self.assertEqual(
            line,
            "- compass:compass: Map agents. (file: compass/skills/compass/SKILL.md)",
        )
        self.assertEqual(validator.approx_token_count("12345"), 2)

    def test_frontmatter_rejects_non_string_license(self) -> None:
        path = self.write_temp(
            "---\nname: broken\ndescription: Broken\nlicense: [MIT]\n---\n", "SKILL.md"
        )
        validation = validator.Validation()

        validator.parse_frontmatter(path, validation)

        self.assertTrue(any("license must be a string" in error for error in validation.errors))

    def test_a_skill_may_pre_approve_its_own_launcher_commands_exactly(self) -> None:
        rule = 'Bash(python3 "${CLAUDE_SKILL_DIR}/launch.py" "${CLAUDE_SKILL_DIR}/server.py" '
        path = self.write_temp(
            "---\nname: ok\ndescription: Fine\n"
            f"allowed-tools: {rule}--sessions), {rule}--sessions waiting), {rule}--monitor --off)\n---\n",
            "SKILL.md",
        )
        validation = validator.Validation()

        validator.parse_frontmatter(path, validation)

        self.assertEqual([], validation.errors)

    def test_a_pre_approval_wider_than_one_exact_launcher_command_is_refused(self) -> None:
        launcher = 'python3 "${CLAUDE_SKILL_DIR}/launch.py" "${CLAUDE_SKILL_DIR}/server.py"'
        for rule in (
            # Measured on Claude Code 2.1.318: this glob also approved `python3 -c "<code>"`.
            "Bash(python3 *launch.py* *server.py* --sessions*)",
            f"Bash({launcher} --sessions:*)",
            f"Bash({launcher} --sessions*)",
            "Bash(python3 *)",
            'Bash(python3 "/home/me/launch.py" "/home/me/server.py" --sessions)',
            f"Bash({launcher} --sessions; rm -rf x)",
            f"Bash({launcher} --sessions --off)",
            f"Bash({launcher} --monitor --stop)",
            f"Bash({launcher} --monitor --off extra)",
            "Read",
            f"Bash({launcher} --sessions) Bash(python3 *)",
        ):
            with self.subTest(rule=rule):
                path = self.write_temp(
                    f"---\nname: wide\ndescription: Wide\nallowed-tools: '{rule}'\n---\n",
                    "SKILL.md",
                )
                validation = validator.Validation()

                validator.parse_frontmatter(path, validation)

                self.assertTrue(any("allowed-tools" in error for error in validation.errors), rule)

    def test_a_pre_approval_that_is_not_one_string_is_refused(self) -> None:
        path = self.write_temp(
            "---\nname: listy\ndescription: Listy\nallowed-tools: [Read]\n---\n", "SKILL.md"
        )
        validation = validator.Validation()

        validator.parse_frontmatter(path, validation)

        self.assertTrue(any("allowed-tools" in error for error in validation.errors))

    def test_the_shipped_skill_declares_every_distributed_license(self) -> None:
        path = validator.ROOT / "compass" / "skills" / "compass" / "SKILL.md"
        validation = validator.Validation()

        metadata = validator.parse_frontmatter(path, validation)

        self.assertEqual([], validation.errors)
        self.assertIsNotNone(metadata)
        assert metadata is not None
        self.assertEqual(
            validator.SHIPPED_SKILL_LICENSES[("compass", "compass")],
            metadata["license"],
        )

    def test_compass_rejects_an_incomplete_license_declaration(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plugin = Path(tmp) / "compass"
            skill = plugin / "skills" / "compass"
            skill.mkdir(parents=True)
            (skill / "SKILL.md").write_text(
                "---\nname: compass\ndescription: Map local agents.\nlicense: Apache-2.0\n---\n",
                encoding="utf-8",
            )
            validation = validator.Validation()

            with mock.patch.object(
                validator,
                "render_catalog_estimate_line",
                return_value="- compass:compass: Map local agents.",
            ):
                validator.validate_skills(plugin, validation)

        self.assertTrue(
            any(
                "frontmatter license must be 'Apache-2.0 AND OFL-1.1'" in error
                for error in validation.errors
            ),
            validation.errors,
        )

    def test_openai_metadata_rejects_invalid_optional_types(self) -> None:
        path = self.write_temp(
            "interface:\n"
            '  display_name: "Broken"\n'
            '  short_description: "A sufficiently long description"\n'
            "  icon_small: 123\n"
            '  default_prompt: "Use $broken to help."\n'
            "dependencies: bogus\n"
            "policy: 42\n",
            "openai.yaml",
        )
        validation = validator.Validation()

        validator.parse_openai_metadata(path, validation)

        self.assertTrue(any("icon_small" in error for error in validation.errors))
        self.assertTrue(
            any("dependencies must be a mapping" in error for error in validation.errors)
        )
        self.assertTrue(any("policy must be a mapping" in error for error in validation.errors))

    def test_antigravity_manifest_requires_runtime_marker_at_plugin_root(self) -> None:
        with tempfile.TemporaryDirectory(prefix="compass-validator-plugin-") as directory:
            plugin_root = Path(directory) / "fixture-plugin"
            nested_manifest = plugin_root / ".gemini-plugin/plugin.json"
            nested_manifest.parent.mkdir(parents=True)
            nested_manifest.write_text(
                '{"name":"fixture-plugin","version":"1.0.0","description":"Fixture"}\n'
            )
            validation = validator.Validation()

            with mock.patch.object(validator, "ROOT", Path(directory)):
                manifest = validator.validate_antigravity_manifest(plugin_root, validation)

            self.assertIsNone(manifest)
            self.assertTrue(
                any(
                    "plugin.json" in error and "cannot read file" in error
                    for error in validation.errors
                )
            )

    def test_the_gemini_extension_lives_in_its_own_root(self) -> None:
        # And specifically *not* in the plugin root. Sharing one root is what made
        # a Gemini session load Claude's hooks/hooks.json, warn about eight event
        # names it does not know, and run two hooks that failed: both harnesses
        # read `<root>/hooks/hooks.json` and neither lets that path be moved.
        gemini_root = validator.ROOT / validator.GEMINI_EXTENSION_ROOT
        self.assertTrue((gemini_root / "gemini-extension.json").is_file())
        for plugin_name in validator.PLUGIN_NAMES:
            with self.subTest(plugin=plugin_name):
                self.assertFalse(
                    (validator.ROOT / plugin_name / "gemini-extension.json").is_file(),
                    "the plugin root must not also be a Gemini extension",
                )

    def test_the_gemini_extension_is_self_contained(self) -> None:
        # `gemini extensions install` copies the directory and a git-URL install
        # clones it, so a hook command reaching outside this root would not resolve
        # once installed.
        gemini_root = validator.ROOT / validator.GEMINI_EXTENSION_ROOT
        for relative in validator.GEMINI_EXTENSION_FILES:
            with self.subTest(file=relative):
                self.assertTrue((gemini_root / relative).is_file())

    def test_antigravity_manifest_rejects_unknown_fields_and_name_mismatch(self) -> None:
        with tempfile.TemporaryDirectory(prefix="compass-validator-plugin-") as directory:
            plugin_root = Path(directory) / "fixture-plugin"
            plugin_root.mkdir()
            (plugin_root / "plugin.json").write_text(
                '{"name":"other-name","description":"Fixture","version":"1.0.0"}\n'
            )
            validation = validator.Validation()

            validator.validate_antigravity_manifest(plugin_root, validation)

            self.assertTrue(
                any(
                    "unsupported Antigravity manifest fields" in error
                    for error in validation.errors
                )
            )
            self.assertTrue(
                any("name must match the plugin directory" in error for error in validation.errors)
            )

    def test_gemini_extension_rejects_missing_version_and_bad_mcp_server(self) -> None:
        with tempfile.TemporaryDirectory(prefix="compass-validator-plugin-") as directory:
            plugin_root = Path(directory) / "fixture-plugin"
            plugin_root.mkdir()
            (plugin_root / "gemini-extension.json").write_text(
                '{"name":"fixture-plugin","description":"Fixture",'
                '"mcpServers":{"fixture":{"transport":"sse"}}}\n'
            )
            validation = validator.Validation()

            validator.validate_gemini_extension(plugin_root, "fixture-plugin", validation)

            self.assertTrue(
                any("version must be a non-empty string" in error for error in validation.errors)
            )
            self.assertTrue(any("needs a url or command" in error for error in validation.errors))

    def test_the_gemini_manifest_name_is_the_plugin_name_not_the_directory(self) -> None:
        # The extension installs and lists as `compass`, while its directory is
        # `compass-gemini` so its hooks file cannot collide with Claude's. Tying
        # the name to the directory would force one of those two to be wrong.
        with tempfile.TemporaryDirectory(prefix="compass-validator-plugin-") as directory:
            extension_root = Path(directory) / "compass-gemini"
            extension_root.mkdir()
            (extension_root / "gemini-extension.json").write_text(
                '{"name":"compass","description":"Fixture","version":"1.0.0"}\n'
            )
            validation = validator.Validation()

            validator.validate_gemini_extension(extension_root, "compass", validation)

            self.assertEqual(
                [],
                [error for error in validation.errors if "name must be" in error],
                "the directory name must not be required to match",
            )

    def test_the_droid_manifest_name_is_the_plugin_name_not_the_directory(self) -> None:
        with tempfile.TemporaryDirectory(prefix="compass-validator-plugin-") as directory:
            extension_root = Path(directory) / "compass-droid"
            (extension_root / ".factory-plugin").mkdir(parents=True)
            (extension_root / ".factory-plugin/plugin.json").write_text(
                '{"name":"compass","description":"Fixture"}\n'
            )
            validation = validator.Validation()

            validator.validate_droid_extension(extension_root, "compass", validation)

            self.assertEqual(
                [],
                [error for error in validation.errors if "name must be" in error],
                "the directory name must not be required to match",
            )

    def test_mcp_endpoint_parity_rejects_drift_and_missing_antigravity_config(self) -> None:
        with tempfile.TemporaryDirectory(prefix="compass-validator-plugin-") as directory:
            plugin_root = Path(directory) / "fixture-plugin"
            plugin_root.mkdir()
            (plugin_root / ".mcp.json").write_text(
                '{"mcpServers":{"fixture":{"type":"sse","url":"http://localhost:9090/sse"}}}\n'
            )
            gemini_manifest = {"mcpServers": {"fixture": {"url": "http://localhost:8081/sse"}}}
            validation = validator.Validation()

            validator.validate_mcp_endpoint_parity(plugin_root, gemini_manifest, None, validation)

            self.assertTrue(
                any(
                    "gemini-extension.json" in error and "must mirror" in error
                    for error in validation.errors
                )
            )
            self.assertTrue(
                any(
                    "mcp_config.json" in error and "must exist" in error
                    for error in validation.errors
                )
            )

    def test_mcp_endpoint_parity_rejects_runtime_endpoints_without_base(self) -> None:
        with tempfile.TemporaryDirectory(prefix="compass-validator-plugin-") as directory:
            plugin_root = Path(directory) / "fixture-plugin"
            plugin_root.mkdir()
            gemini_manifest = {"mcpServers": {"rogue": {"url": "http://localhost:9999/sse"}}}
            mcp_config = {"mcpServers": {"rogue": {"serverUrl": "http://localhost:9999/sse"}}}
            validation = validator.Validation()

            validator.validate_mcp_endpoint_parity(
                plugin_root, gemini_manifest, mcp_config, validation
            )

            self.assertTrue(
                any(
                    "gemini-extension.json" in error and "no .mcp.json to mirror" in error
                    for error in validation.errors
                )
            )
            self.assertTrue(
                any(
                    "mcp_config.json" in error and "no .mcp.json to mirror" in error
                    for error in validation.errors
                )
            )

    def test_antigravity_mcp_config_rejects_missing_or_blank_server_url(self) -> None:
        with tempfile.TemporaryDirectory(prefix="compass-validator-plugin-") as directory:
            plugin_root = Path(directory) / "fixture-plugin"
            plugin_root.mkdir()
            (plugin_root / "mcp_config.json").write_text(
                '{"mcpServers":{"fixture":{"url":"http://localhost:8081/sse"},"blank":{"serverUrl":"  "}}}\n'
            )
            validation = validator.Validation()

            validator.validate_antigravity_mcp_config(plugin_root, validation)

            self.assertTrue(
                any(
                    "'fixture' must define a non-empty serverUrl" in error
                    for error in validation.errors
                )
            )
            self.assertTrue(
                any(
                    "'blank' must define a non-empty serverUrl" in error
                    for error in validation.errors
                )
            )

            (plugin_root / "mcp_config.json").write_text('{"mcpServers":{}}\n')
            validation = validator.Validation()

            validator.validate_antigravity_mcp_config(plugin_root, validation)

            self.assertTrue(
                any("mcpServers must be a non-empty object" in error for error in validation.errors)
            )

    def test_mcp_endpoint_parity_accepts_matching_endpoints(self) -> None:
        with tempfile.TemporaryDirectory(prefix="compass-validator-plugin-") as directory:
            plugin_root = Path(directory) / "fixture-plugin"
            plugin_root.mkdir()
            (plugin_root / ".mcp.json").write_text(
                '{"mcpServers":{"fixture":{"type":"sse","url":"http://localhost:8081/sse"}}}\n'
            )
            gemini_manifest = {"mcpServers": {"fixture": {"url": "http://localhost:8081/sse"}}}
            mcp_config = {"mcpServers": {"fixture": {"serverUrl": "http://localhost:8081/sse"}}}
            validation = validator.Validation()

            validator.validate_mcp_endpoint_parity(
                plugin_root, gemini_manifest, mcp_config, validation
            )

            self.assertEqual(validation.errors, [])

    def test_a_bundled_hook_command_must_reference_a_script_that_ships(self) -> None:
        # This replaced a byte-parity rule between hooks/hooks.json and the root
        # hooks.json. Parity assumed one file could serve both Claude and
        # Antigravity, which stopped being true once the command named its
        # harness. The check that matters is the one parity never made: a hooks
        # file pointing at a missing script installs cleanly and reports nothing.
        command = 'python3 "${CLAUDE_PLUGIN_ROOT}/skills/compass/event_hook.py" claude'
        document = {
            "hooks": {"Stop": [{"matcher": "", "hooks": [{"type": "command", "command": command}]}]}
        }
        with tempfile.TemporaryDirectory(prefix="compass-validator-plugin-") as directory:
            plugin_root = Path(directory) / "fixture-plugin"
            (plugin_root / "hooks").mkdir(parents=True)
            (plugin_root / "skills/compass").mkdir(parents=True)
            (plugin_root / "hooks/hooks.json").write_text(json.dumps(document))

            validation = validator.Validation()
            validator.validate_hooks_adapter(plugin_root, validation)
            self.assertTrue(
                any(
                    "references missing skills/compass/event_hook.py" in e
                    for e in validation.errors
                ),
                validation.errors,
            )

            (plugin_root / "skills/compass/event_hook.py").write_text("#\n")
            validation = validator.Validation()
            validator.validate_hooks_adapter(plugin_root, validation)
            self.assertEqual([], validation.errors)

    def test_a_bundled_hooks_file_registering_nothing_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="compass-validator-plugin-") as directory:
            plugin_root = Path(directory) / "fixture-plugin"
            (plugin_root / "hooks").mkdir(parents=True)
            (plugin_root / "hooks/hooks.json").write_text('{"hooks": {}}')

            validation = validator.Validation()
            validator.validate_hooks_adapter(plugin_root, validation)

            self.assertTrue(any("registers no events" in e for e in validation.errors))

    def test_two_harnesses_may_bundle_different_hooks_files(self) -> None:
        # The whole point of dropping parity. Claude fires UserPromptSubmit and
        # SessionEnd; Antigravity fires PreInvocation and PostInvocation. A
        # mirrored file would also make Antigravity post as Claude, where the id
        # gets truncated by Claude's normalizer and matches no row.
        def document(event: str, harness: str) -> str:
            command = f'python3 "${{PLUGIN_ROOT}}/skills/compass/event_hook.py" {harness}'
            return json.dumps(
                {
                    "hooks": {
                        event: [{"matcher": "", "hooks": [{"type": "command", "command": command}]}]
                    }
                }
            )

        with tempfile.TemporaryDirectory(prefix="compass-validator-plugin-") as directory:
            plugin_root = Path(directory) / "fixture-plugin"
            (plugin_root / "hooks").mkdir(parents=True)
            (plugin_root / "skills/compass").mkdir(parents=True)
            (plugin_root / "skills/compass/event_hook.py").write_text("#\n")
            (plugin_root / "hooks/hooks.json").write_text(document("UserPromptSubmit", "claude"))
            (plugin_root / "hooks.json").write_text(document("PostInvocation", "antigravity"))

            validation = validator.Validation()
            validator.validate_hooks_adapter(plugin_root, validation)

            self.assertEqual([], validation.errors)

    def test_description_parity_rejects_drifted_manifests(self) -> None:
        validation = validator.Validation()

        validator.validate_description_parity(
            "fixture-plugin",
            {
                ".claude-plugin/plugin.json": "Long canonical description",
                "gemini-extension.json": "Short variant",
                "plugin.json": None,
            },
            validation,
        )

        self.assertTrue(any("description drift" in error for error in validation.errors))

        validation = validator.Validation()
        validator.validate_description_parity(
            "fixture-plugin",
            {
                ".claude-plugin/plugin.json": "Same description",
                "gemini-extension.json": "Same description",
                "plugin.json": None,
            },
            validation,
        )

        self.assertEqual(validation.errors, [])

    def test_claude_manifest_name_must_match_plugin_directory(self) -> None:
        with tempfile.TemporaryDirectory(prefix="compass-validator-plugin-") as directory:
            root = Path(directory)
            (root / ".agents/plugins").mkdir(parents=True)
            (root / ".agents/plugins/marketplace.json").write_text(
                '{"plugins":[{"name":"compass","source":{"source":"local","path":"./compass"}}]}\n'
            )
            (root / "compass/.claude-plugin").mkdir(parents=True)
            (root / "compass/.claude-plugin/plugin.json").write_text(
                '{"name":"wrong-plugin-name","version":"0.1.0","description":"Desc"}\n'
            )
            manifest = {"version": "0.1.0", "description": "Desc"}
            validation = validator.Validation()

            with mock.patch.object(validator, "ROOT", root):
                validator.validate_marketplaces(
                    {"compass": dict(manifest)},
                    {"compass": dict(manifest)},
                    {"compass": {"description": "Desc"}},
                    validation,
                )

            self.assertTrue(
                any(
                    ".claude-plugin/plugin.json" in error
                    and "name must match the plugin directory" in error
                    for error in validation.errors
                )
            )

    def test_error_labels_use_forward_slashes_on_every_platform(self) -> None:
        # resolve() rewrites 8.3 short names on Windows and /var -> /private/var
        # on macOS, so a path inside ROOT can still fail relative_to(). The
        # fallback must not leak native separators into the error text.
        with tempfile.TemporaryDirectory(prefix="compass-validator-label-") as directory:
            root = Path(directory)
            nested = root / "compass" / ".claude-plugin" / "plugin.json"
            nested.parent.mkdir(parents=True)
            nested.write_text("{}\n")
            validation = validator.Validation()
            with mock.patch.object(validator, "ROOT", root):
                validation.error(nested, "boom")
            # Inside a resolved ROOT: label is relative.
            self.assertEqual(["compass/.claude-plugin/plugin.json: boom"], validation.errors)

            # Outside ROOT: still forward slashes, never backslashes.
            outside = validator.Validation()
            with mock.patch.object(validator, "ROOT", root / "elsewhere"):
                outside.error(nested, "boom")
        self.assertEqual(1, len(outside.errors))
        self.assertNotIn("\\", outside.errors[0])
        self.assertIn("compass/.claude-plugin/plugin.json", outside.errors[0])

    def test_manifest_version_drift_is_rejected(self) -> None:
        """compass has no marketplace of its own any more (it is listed in
        spacedock-dev/marketplace), so parity is asserted straight across the
        three shipped manifests."""
        with tempfile.TemporaryDirectory(prefix="compass-validator-plugin-") as directory:
            root = Path(directory)
            (root / ".agents/plugins").mkdir(parents=True)
            (root / ".agents/plugins/marketplace.json").write_text(
                '{"plugins":[{"name":"compass","source":{"source":"local","path":"./compass"}}]}\n'
            )
            (root / "compass/.claude-plugin").mkdir(parents=True)
            (root / "compass/.claude-plugin/plugin.json").write_text(
                '{"name":"compass","version":"0.1.0","description":"Desc"}\n'
            )
            validation = validator.Validation()

            with mock.patch.object(validator, "ROOT", root):
                validator.validate_marketplaces(
                    {"compass": {"version": "9.9.9", "description": "Desc"}},
                    {"compass": {"version": "0.1.0", "description": "Desc"}},
                    {"compass": {"description": "Desc"}},
                    validation,
                )

            self.assertTrue(
                any("version fields are not in parity" in error for error in validation.errors)
            )

    def test_markdown_link_rejects_missing_bundled_resource(self) -> None:
        path = self.write_temp("Read [the bundled reference](../missing/file.md).\n", "SKILL.md")
        validation = validator.Validation()

        validator.validate_markdown_links(path, validation)

        self.assertTrue(any("Markdown link" in error for error in validation.errors))

    def test_validate_skills_reports_non_string_required_fields_without_crashing(self) -> None:
        with tempfile.TemporaryDirectory(prefix="compass-validator-plugin-") as directory:
            plugin_root = Path(directory) / "fixture-plugin"
            skill_root = plugin_root / "skills/broken"
            (skill_root / "agents").mkdir(parents=True)
            (skill_root / "SKILL.md").write_text(
                "---\nname: [broken]\ndescription: Broken fixture\n---\n"
            )
            (skill_root / "agents/openai.yaml").write_text(
                "interface:\n"
                '  display_name: "Broken"\n'
                '  short_description: "A sufficiently long description"\n'
                "  default_prompt: 42\n"
            )
            validation = validator.Validation()

            with mock.patch.object(validator, "ROOT", Path(directory)):
                validator.validate_skills(plugin_root, validation)

            self.assertTrue(any("name must use lowercase" in error for error in validation.errors))
            self.assertTrue(any("default_prompt" in error for error in validation.errors))

    def test_bundled_markdown_rejects_host_specific_skill_api(self) -> None:
        with tempfile.TemporaryDirectory(prefix="compass-validator-plugin-") as directory:
            plugin_root = Path(directory) / "fixture-plugin"
            skill_root = plugin_root / "skills/broken"
            (skill_root / "agents").mkdir(parents=True)
            (skill_root / "SKILL.md").write_text(
                "---\nname: broken\ndescription: Broken fixture\n---\n"
            )
            (skill_root / "reference.md").write_text(
                'Invoke Skill(skill="fixture:security-review", args="files").\n'
            )
            (skill_root / "agents/openai.yaml").write_text(
                "interface:\n"
                '  display_name: "Broken"\n'
                '  short_description: "A sufficiently long description"\n'
                '  default_prompt: "Use $broken to help."\n'
            )
            validation = validator.Validation()

            with mock.patch.object(validator, "ROOT", Path(directory)):
                validator.validate_skills(plugin_root, validation)

            self.assertTrue(any("Skill(skill=" in error for error in validation.errors))

    def build_repo_docs(self, root: Path) -> None:
        """Write a minimal but complete stand-in for the repository's prose docs."""
        (root / ".github").mkdir(parents=True, exist_ok=True)
        (root / "docs").mkdir(parents=True, exist_ok=True)
        for name in validator.ROOT_DOCS:
            (root / name).write_text("Placeholder.\n", encoding="utf-8")

    def test_repo_docs_reject_dangling_relative_link(self) -> None:
        with tempfile.TemporaryDirectory(prefix="compass-validator-docs-") as directory:
            # Resolve as the real ROOT is: on macOS a temp path is under
            # /var, a symlink to /private/var, and link containment is
            # checked against a resolved target.
            root = Path(directory).resolve()
            self.build_repo_docs(root)
            (root / "README.md").write_text("See [the guide](docs/absent.md).\n", encoding="utf-8")
            validation = validator.Validation()

            with mock.patch.object(validator, "ROOT", root):
                validator.validate_repo_docs(validation)

            self.assertTrue(
                any("docs/absent.md" in error for error in validation.errors), validation.errors
            )

    def test_repo_docs_reject_banned_loopback_spelling(self) -> None:
        with tempfile.TemporaryDirectory(prefix="compass-validator-docs-") as directory:
            # Resolve as the real ROOT is: on macOS a temp path is under
            # /var, a symlink to /private/var, and link containment is
            # checked against a resolved target.
            root = Path(directory).resolve()
            self.build_repo_docs(root)
            (root / "docs/design-example.md").write_text(
                "Open http://localhost:4553 to see it.\n", encoding="utf-8"
            )
            validation = validator.Validation()

            with mock.patch.object(validator, "ROOT", root):
                validator.validate_repo_docs(validation)

            self.assertTrue(
                any("127.0.0.1:4553" in error for error in validation.errors), validation.errors
            )

    def test_repo_docs_reject_a_missing_owned_document(self) -> None:
        with tempfile.TemporaryDirectory(prefix="compass-validator-docs-") as directory:
            # Resolve as the real ROOT is: on macOS a temp path is under
            # /var, a symlink to /private/var, and link containment is
            # checked against a resolved target.
            root = Path(directory).resolve()
            self.build_repo_docs(root)
            (root / "SECURITY.md").unlink()
            validation = validator.Validation()

            with mock.patch.object(validator, "ROOT", root):
                validator.validate_repo_docs(validation)

            self.assertTrue(
                any("SECURITY.md" in error for error in validation.errors), validation.errors
            )

    def slugs_for(self, body: str) -> set[str]:
        holder = tempfile.TemporaryDirectory(prefix="compass-validator-slug-")
        self.addCleanup(holder.cleanup)
        path = Path(holder.name).resolve() / "doc.md"
        path.write_text(body, encoding="utf-8")
        return validator.heading_slugs(path)

    def test_heading_slugs_match_github_anchoring(self) -> None:
        """Each case is an anchor GitHub accepts; rejecting one is a false failure."""
        cases: list[tuple[str, str, set[str]]] = [
            ("plain ATX", "## Pre-PR Checks\n", {"pre-pr-checks"}),
            ("repeated heading", "# Same\n# Same\n# Same\n", {"same", "same-1", "same-2"}),
            ("non-ASCII letters", "# Café résumé\n", {"café-résumé"}),
            ("underscores survive", "# server_py notes\n", {"server_py-notes"}),
            ("Setext", "Title Here\n==========\n", {"title-here"}),
            ("indented up to three spaces", "   # Indented\n", {"indented"}),
            ("inline link collapses", "# [Install](README.md)\n", {"install"}),
            ("explicit HTML anchor", '<a name="manual"></a>\n', {"manual"}),
            (
                "punctuation dropped, spacing kept",
                "## D-1 — Scan every root; never pick one\n",
                {"d-1--scan-every-root-never-pick-one"},
            ),
        ]
        for label, body, expected in cases:
            with self.subTest(case=label):
                self.assertEqual(expected, self.slugs_for(body))

    def test_heading_slugs_ignore_code_and_frontmatter(self) -> None:
        """A `#` inside a fence is a shell comment; treating it as a heading
        invents an anchor that silently satisfies a dangling link."""
        for label, body in [
            ("backtick fence", "```bash\n# not a heading\n```\n"),
            ("tilde fence", "~~~\n# not a heading\n~~~\n"),
            ("frontmatter", "---\nname: x\ndescription: y\n---\n"),
        ]:
            with self.subTest(case=label):
                self.assertEqual(set(), self.slugs_for(body))

    def test_markdown_links_accept_valid_commonmark(self) -> None:
        with tempfile.TemporaryDirectory(prefix="compass-validator-links-") as directory:
            root = Path(directory).resolve()
            (root / "real.md").write_text("# Heading\n", encoding="utf-8")
            for label, body in [
                ("quoted title", '[x](real.md "the title")\n'),
                ("parenthesised title", "[x](real.md (the title))\n"),
                ("angle-bracket destination", "[x](<real.md>)\n"),
                ("image", "![alt](real.md)\n"),
                ("link inside a tilde fence", "~~~\n[x](absent.md)\n~~~\n"),
                ("fragment on a resolving target", "[x](real.md#heading)\n"),
            ]:
                with self.subTest(case=label):
                    (root / "doc.md").write_text(body, encoding="utf-8")
                    validation = validator.Validation()

                    with mock.patch.object(validator, "ROOT", root):
                        validator.validate_markdown_links(root / "doc.md", validation)

                    self.assertEqual([], validation.errors)

    def test_markdown_links_still_reject_real_breakage(self) -> None:
        """The permissiveness above must not blunt the checks that matter."""
        with tempfile.TemporaryDirectory(prefix="compass-validator-links-") as directory:
            root = Path(directory).resolve()
            (root / "real.md").write_text("# Heading\n", encoding="utf-8")
            for label, body, fragment in [
                ("missing target", "[x](gone.md)\n", "does not exist"),
                ("escapes the repository", "[x](../../outside.md)\n", "escapes the repository"),
                ("dangling fragment", "[x](real.md#absent)\n", "anchor does not exist"),
                ("title does not excuse a miss", '[x](gone.md "t")\n', "does not exist"),
            ]:
                with self.subTest(case=label):
                    (root / "doc.md").write_text(body, encoding="utf-8")
                    validation = validator.Validation()

                    with mock.patch.object(validator, "ROOT", root):
                        validator.validate_markdown_links(root / "doc.md", validation)

                    self.assertTrue(
                        any(fragment in error for error in validation.errors), validation.errors
                    )

    def test_root_docs_lists_every_prose_doc_in_the_repository(self) -> None:
        """ROOT_DOCS is what decides coverage; a silent drop must fail here.

        Tracked files only: a gitignored export sitting at the repository
        root is a local artifact, not a prose doc the sync pass owns, and a
        filesystem glob failed here on any machine carrying one.
        CODE_OF_CONDUCT.md is excluded deliberately — it is verbatim upstream
        text that no sync pass may edit.
        """
        listing = subprocess.run(
            ["git", "-C", str(validator.ROOT), "ls-files", "*.md"],  # noqa: S607
            capture_output=True,
            text=True,
            check=True,
        )
        expected = {name for name in listing.stdout.splitlines() if name and "/" not in name} - {
            "CODE_OF_CONDUCT.md"
        }
        expected.add(".github/PULL_REQUEST_TEMPLATE.md")

        self.assertEqual(expected, set(validator.ROOT_DOCS))

    def test_repo_docs_reject_a_dangling_heading_anchor(self) -> None:
        with tempfile.TemporaryDirectory(prefix="compass-validator-docs-") as directory:
            root = Path(directory).resolve()
            self.build_repo_docs(root)
            (root / "AGENTS.md").write_text("## Pre-PR Checks\n", encoding="utf-8")
            (root / "README.md").write_text(
                "[gone](AGENTS.md#removed-heading) and [here](#nowhere)\n", encoding="utf-8"
            )
            validation = validator.Validation()

            with mock.patch.object(validator, "ROOT", root):
                validator.validate_repo_docs(validation)

            self.assertEqual(2, sum("anchor does not exist" in e for e in validation.errors))

    def test_repo_docs_accept_resolving_links_and_anchors(self) -> None:
        with tempfile.TemporaryDirectory(prefix="compass-validator-docs-") as directory:
            # Resolve as the real ROOT is: on macOS a temp path is under
            # /var, a symlink to /private/var, and link containment is
            # checked against a resolved target.
            root = Path(directory).resolve()
            self.build_repo_docs(root)
            (root / "docs/design-example.md").write_text("Rationale.\n", encoding="utf-8")
            (root / "AGENTS.md").write_text("## Pre-PR Checks\n", encoding="utf-8")
            (root / "README.md").write_text(
                "# Top\n"
                "See [design](docs/design-example.md) and [checks](AGENTS.md#pre-pr-checks)\n"
                "and [upstream](https://example.invalid/x.md) and [anchor](#top).\n",
                encoding="utf-8",
            )
            (root / ".github/PULL_REQUEST_TEMPLATE.md").write_text(
                "Run the suite in [AGENTS.md](../AGENTS.md#pre-pr-checks).\n", encoding="utf-8"
            )
            validation = validator.Validation()

            with mock.patch.object(validator, "ROOT", root):
                validator.validate_repo_docs(validation)

            self.assertEqual([], validation.errors)


class ReleasePublicNotesGateTest(unittest.TestCase):
    """A rejected generated body must fail before any release mutations."""

    def release_steps(self) -> list[dict[str, Any]]:
        path = validator.ROOT / ".github/workflows/release.yml"
        workflow: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8"))
        steps: list[dict[str, Any]] = workflow["jobs"]["release"]["steps"]
        return steps

    def test_resume_installs_validation_dependencies_before_the_public_note_gate(self) -> None:
        steps = self.release_steps()
        setup = [
            step
            for step in steps
            if "pip install" in str(step.get("run", ""))
            and "requirements-release.txt" in str(step.get("run", ""))
        ]
        self.assertEqual(1, len(setup))
        self.assertNotIn("if", setup[0], "Resumed releases also import the YAML validator")
        names = [str(step.get("name", "")) for step in steps]
        for name in [
            "Prepare and validate the public release notes",
            "Write the version bump commit",
        ]:
            self.assertLess(steps.index(setup[0]), names.index(name))

    @unittest.skipIf(
        os.name == "nt", "Release workflow uses POSIX Bash and executable script fixtures"
    )
    def test_dirty_generated_notes_prevent_publication_and_channel_mutations(self) -> None:
        steps = self.release_steps()
        names = [str(step.get("name", "")) for step in steps]
        prepared = next(
            (
                step
                for step in steps
                if step.get("name") == "Prepare and validate the public release notes"
            ),
            None,
        )
        self.assertIsNotNone(prepared, "Release notes need a pre-publication gate")
        assert prepared is not None
        for name in [
            "Write the version bump commit",
            "Push the release commit to main",
            "Move the tag onto the release commit",
            "Advance the stable branch",
            "Publish the GitHub Release",
        ]:
            self.assertLess(names.index(str(prepared["name"])), names.index(name))
        selected = [
            step
            for step in steps
            if step is prepared
            or step.get("name")
            in {
                "Move the tag onto the release commit",
                "Advance the stable branch",
                "Publish the GitHub Release",
            }
        ]
        for body, existing, lookup, expected in [
            ("A linear scan; see GitHub pull request12.", "", "normal", 0),
            ("Generated title has DRC-123.", "", "normal", 1),
            ("Generated title has DRC-123.", "Existing public notes.", "normal", 0),
            ("Clean generated notes.", "Existing private DRC-123 notes.", "normal", 1),
            ("GENERATION_ERROR", "", "normal", 7),
            ("Clean generated notes.", "Existing private DRC-123 notes.", "transient", 1),
            ("Clean generated notes.", "", "forbidden", 1),
            ("Clean generated notes.", "Existing public notes.", "malformed", 1),
            ("Clean generated notes.", "Existing public notes.", "invalid-body", 1),
            ("Clean generated notes.", "", "malformed404", 1),
        ]:
            with self.subTest(body=body), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                binary = root / "bin"
                binary.mkdir()
                gh = binary / "gh"
                gh.write_text(
                    "#!" + sys.executable + "\n"
                    "import json,os,sys\nfrom pathlib import Path\n"
                    "args=sys.argv[1:]\n"
                    "if args[0]=='api' and '--include' in args:\n"
                    " assert args[-1]=='repos/example/project/releases/tags/v9.9.9'\n"
                    " mode=os.environ['LOOKUP_MODE']\n"
                    " if mode=='transient': sys.exit(7)\n"
                    " if mode=='forbidden':\n"
                    "  print('HTTP/2.0 403 Forbidden\\nContent-Type: application/json\\n\\n{}'); sys.exit(1)\n"
                    " if mode=='malformed404':\n"
                    "  print('HTTP/2.0 404 Not Found\\n\\nnot-json'); sys.exit(1)\n"
                    " if mode=='malformed': print('HTTP/2.0 200 OK\\n\\nnot-json'); sys.exit(0)\n"
                    " if mode=='invalid-body': print('HTTP/2.0 200 OK\\n\\n'+json.dumps({'body':None})); sys.exit(0)\n"
                    " if not os.environ['EXISTING_BODY']:\n"
                    "  print('HTTP/2.0 404 Not Found\\nContent-Type: application/json\\n\\n'+json.dumps({'message':'Not Found'})); sys.exit(1)\n"
                    " print('HTTP/2.0 200 OK\\nContent-Type: application/json\\n\\n'+json.dumps({'body':os.environ['EXISTING_BODY']}))\n"
                    "elif args[0]=='api':\n"
                    " Path(os.environ['GENERATION_LOG']).write_text('generated')\n"
                    " if os.environ['GENERATED_BODY']=='GENERATION_ERROR': sys.exit(7)\n"
                    " assert args[1]=='repos/example/project/releases/generate-notes'\n"
                    " assert 'tag_name=v9.9.9' in args and 'target_commitish=source-receipt' in args\n"
                    " print(os.environ['GENERATED_BODY'])\n"
                    "elif args[:2]==['release','view']:\n"
                    " if not os.environ['EXISTING_BODY']: sys.exit(1)\n"
                    " print(os.environ['EXISTING_BODY'])\n"
                    "elif args[:2]==['release','create']:\n"
                    " assert '--notes-file' in args and '--generate-notes' not in args\n"
                    " body=Path(args[args.index('--notes-file')+1]).read_text()\n"
                    " Path(os.environ['PUBLISHED_FILE']).write_text(body)\n"
                    "else: sys.exit(9)\n",
                    encoding="utf-8",
                )
                gh.chmod(0o700)
                # The notes step calls the venv interpreter by explicit path.
                venv = root / "release-venv" / "bin"
                venv.mkdir(parents=True)
                (venv / "python").symlink_to(sys.executable)
                git = binary / "git"
                git.write_text(
                    '#!/bin/sh\nprintf "mutation\\n" >> "$MUTATION_LOG"\n', encoding="utf-8"
                )
                git.chmod(0o700)
                env = dict(
                    os.environ,
                    PATH=str(binary) + os.pathsep + os.environ["PATH"],
                    TAG="v9.9.9",
                    VERSION="9.9.9",
                    TARGET="source-receipt",
                    FINAL="a" * 40,
                    GITHUB_REPOSITORY="example/project",
                    RUNNER_TEMP=directory,
                    GITHUB_ENV=str(root / "env"),
                    GENERATED_BODY=body,
                    EXISTING_BODY=existing,
                    LOOKUP_MODE=lookup,
                    GENERATION_LOG=str(root / "generated"),
                    PUBLISHED_FILE=str(root / "published"),
                    MUTATION_LOG=str(root / "mutations"),
                )
                commands = [
                    str(step["run"]) + '\nset -a\n. "$GITHUB_ENV"\nset +a' for step in selected
                ]
                result = subprocess.run(
                    ["bash", "-euc", "\n".join(commands)],  # noqa: S607
                    cwd=validator.ROOT,
                    env=env,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(expected, result.returncode, result.stdout + result.stderr)
                if expected:
                    self.assertFalse((root / "published").exists())
                    self.assertFalse((root / "mutations").exists())
                else:
                    if existing:
                        self.assertFalse((root / "published").exists())
                    else:
                        self.assertEqual(body + "\n", (root / "published").read_text())
                    self.assertTrue((root / "mutations").exists())
                self.assertEqual(
                    lookup == "normal" and not bool(existing), (root / "generated").exists()
                )


class GitIgnoredPathsTest(unittest.TestCase):
    """Git paths must round-trip without quoting, locale or newline conversion."""

    def test_real_git_ignored_unicode_path_is_not_a_quoted_filename(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            subprocess.run(["git", "init", "-q", str(root)], check=True)  # noqa: S607
            (root / ".gitignore").write_text("private/\n", encoding="utf-8")
            private = root / "private"
            private.mkdir()
            ignored = private / "café.md"
            ignored.write_text("private development notes", encoding="utf-8")
            with mock.patch.object(validator, "ROOT", root):
                self.assertEqual({ignored}, validator._git_ignored([ignored]))

    def test_raw_nul_protocol_preserves_path_delimiters(self) -> None:
        paths = [Path("C:/Users/RUNNER/hidden.md"), Path("folder/a\nb.md"), Path("folder/a\rb.md")]
        encoded = b"\0".join(path.as_posix().encode("utf-8") for path in paths) + b"\0"

        def raw_git(args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
            self.assertIn("-z", args)
            self.assertEqual(encoded, kwargs["input"])
            return subprocess.CompletedProcess(args, 0, stdout=encoded, stderr=b"")

        with mock.patch.object(subprocess, "run", side_effect=raw_git):
            self.assertEqual(set(paths), validator._git_ignored(paths))

    def test_tracked_unicode_discovery_does_not_use_the_windows_locale(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            subprocess.run(["git", "init", "-q", str(root)], check=True)  # noqa: S607
            vendor = root / "node_modules"
            vendor.mkdir()
            tracked = vendor / "café.md"
            tracked.write_text("DRC-123", encoding="utf-8")
            real_run = subprocess.run

            def windows_git(args: list[str], **kwargs: Any) -> Any:
                if args == ["git", "ls-files", "-z"]:
                    raw = b"node_modules/caf\xc3\xa9.md\0"
                    if kwargs.get("text"):
                        raw_text = raw.decode(kwargs.get("encoding", "cp1252"))
                        return subprocess.CompletedProcess(args, 0, stdout=raw_text, stderr="")
                    return subprocess.CompletedProcess(args, 0, stdout=raw, stderr=b"")
                return real_run(args, **kwargs)

            validation = validator.Validation()
            with (
                mock.patch.object(validator, "ROOT", root),
                mock.patch.object(subprocess, "run", side_effect=windows_git),
            ):
                validator.validate_public_docs(validation)
            self.assertEqual(1, len(validation.errors), validation.errors)
            self.assertIn("node_modules/café.md:1", validation.errors[0])


class PublicDocumentationBoundaryTest(unittest.TestCase):
    """New public documents and raw link syntax must not leak tracker provenance."""

    def scan(self, root: Path) -> list[str]:
        validation = validator.Validation()
        with mock.patch.object(validator, "ROOT", root):
            validator.validate_public_docs(validation)
        return validation.errors

    def test_raw_public_text_rejects_brand_keys_and_hidden_links(self) -> None:
        samples = [
            "Use Linear.",
            "Use linear.",
            "LINEAR",
            "lInEaR",
            "linear issue tracker",
            "DRC-123",
            "drc-123",
            "```text\nDRC-123\n```",
            "[ticket][private]\n[private]: https://LINEAR.APP/team/item",
            '<a href="linear://item/123">details</a>',
            "<https://linear.app/team>",
            "`https://linear.app/team`",
            "<!-- DRC-123 -->",
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "notes.md"
            for sample in samples:
                with self.subTest(sample=sample):
                    path.write_text("Public heading\n" + sample, encoding="utf-8")
                    validation = validator.Validation()
                    validator.validate_public_text(path, validation)
                    self.assertTrue(validation.errors)
                    self.assertIn(
                        "notes.md:" + ("3" if sample.startswith(("```", "[ticket]")) else "2"),
                        validation.errors[0],
                    )
                    self.assertNotIn(sample, validation.errors[0])

    def test_public_math_prose_and_github_links_pass(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "notes.md"
            path.write_text(
                "A linear scan runs in linear time. linear interpolation is supported.\n"
                "A linear JSONL transcript differs from a tree.\n"
                "Cost is linear in the number of entries; use a linear combination.\n"
                "See [change](https://github.com/example/project/pull/12).\n",
                encoding="utf-8",
            )
            validation = validator.Validation()
            validator.validate_public_text(path, validation)
            self.assertEqual([], validation.errors)

    def test_new_unknown_markdown_and_plain_owned_notices_are_public(self) -> None:
        names = ["NEW.MD", "docs/new-guide.md", "misc/new-notes.md", "LICENSE", "NOTICE"]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in names:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("DRC-123", encoding="utf-8")
            errors = self.scan(root)
            self.assertEqual(len(names), len(errors), errors)
            for name in names:
                self.assertTrue(any(name in error for error in errors))

    def test_explicit_development_exceptions_and_public_overrides(self) -> None:
        allowed = [
            "AGENTS.md",
            "CLAUDE.md",
            "CONTRIBUTING.md",
            ".github/PULL_REQUEST_TEMPLATE.md",
            ".claude/skills/example/SKILL.md",
            "docs/plans/test.md",
            "docs/design-example.md",
            "docs/development-tracking.md",
            "docs/flaky-tests.md",
            "docs/captures/example/README.md",
            "docs/drift-replay/README.md",
            "docs/abstention/README.md",
            "docs/roadmap-burndown/README.md",
            "tests/annotated_sessions/example/annotation.md",
            "docs/evidence/intent-and-drift/COLD_STUDY_PROTOCOL.md",
            "docs/evidence/intent-and-drift/run-example.md",
        ]
        public = [
            "docs/promise-map.md",
            "docs/evidence/intent-and-drift/README.md",
            "docs/evidence/intent-and-drift/PROMPT.md",
            "docs/evidence/intent-and-drift/PARTICIPANT_KICKOFF.md",
            "docs/evidence/unknown.md",
            "compass/skills/example/docs/plans/guide.md",
            "compass-gemini/README.MD",
            "compass-droid/docs/design-example.md",
        ]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in allowed + public:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("DRC-123", encoding="utf-8")
            errors = self.scan(root)
            self.assertEqual(len(public), len(errors), errors)
            for name in public:
                self.assertTrue(any(name in error for error in errors), name)

    def test_private_ignored_directories_are_pruned_but_tracked_files_still_scanned(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "-q", str(root)], check=True)  # noqa: S607
            (root / ".gitignore").write_text("private/\ntracked.md\n", encoding="utf-8")
            private = root / "private"
            private.mkdir()
            (private / "hidden.md").write_text("DRC-123", encoding="utf-8")
            (private / "retained.MD").write_text("DRC-123", encoding="utf-8")
            vendor = root / "node_modules"
            vendor.mkdir()
            (vendor / "retained.md").write_text("DRC-123", encoding="utf-8")
            tracked = root / "tracked.md"
            tracked.write_text("DRC-123", encoding="utf-8")
            subprocess.run(
                [  # noqa: S607
                    "git",
                    "add",
                    "-f",
                    "tracked.md",
                    "private/retained.MD",
                    "node_modules/retained.md",
                ],
                cwd=root,
                check=True,
            )
            (root / "new.md").write_text("DRC-123", encoding="utf-8")
            errors = self.scan(root)
            self.assertEqual(4, len(errors), errors)
            self.assertTrue(any("tracked.md" in error for error in errors))
            self.assertTrue(any("retained.MD" in error for error in errors))
            self.assertTrue(any("new.md" in error for error in errors))
            self.assertFalse(any("hidden.md" in error for error in errors))

    def test_installed_skill_resources_are_checked_without_repository_discovery(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            skill = root / "skills/example"
            skill.mkdir(parents=True)
            (skill / "SKILL.md").write_text(
                "---\nname: example\ndescription: A portable example skill\n---\n", encoding="utf-8"
            )
            (skill / "reference.MD").write_text("DRC-123", encoding="utf-8")
            validation = validator.Validation()
            with mock.patch.object(validator, "ROOT", root):
                validator.validate_skills(root, validation)
            self.assertTrue(any("reference.MD:1" in error for error in validation.errors))

    def test_public_text_cli_rejects_malformed_arguments_without_repository_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "notes with spaces.md"
            path.write_text("Public release notes.", encoding="utf-8")
            script = validator.ROOT / "scripts/validate_plugins.py"
            for args in [
                ["--public-text"],
                ["--public-text", str(path), "extra"],
                ["extra", "--public-text", str(path)],
            ]:
                with self.subTest(args=args):
                    result = subprocess.run(
                        [sys.executable, str(script), *args],
                        cwd=directory,
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                    self.assertNotEqual(0, result.returncode)
                    self.assertNotIn("Validated ", result.stdout)
                    self.assertNotIn("Traceback", result.stderr)

    def test_public_text_cli_is_standalone_and_unreadable_input_refuses(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "notes.md"
            path.write_text("DRC-123", encoding="utf-8")
            script = validator.ROOT / "scripts/validate_plugins.py"
            bad = subprocess.run(
                [sys.executable, str(script), "--public-text", str(path)],
                cwd=directory,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(1, bad.returncode)
            self.assertIn("notes.md:1", bad.stdout)
            path.write_text("A linear scan; see GitHub pull request12.", encoding="utf-8")
            good = subprocess.run(
                [sys.executable, str(script), "--public-text", str(path)],
                cwd=directory,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(0, good.returncode, good.stdout + good.stderr)
            path.write_bytes(b"\xff")
            invalid = subprocess.run(
                [sys.executable, str(script), "--public-text", str(path)],
                cwd=directory,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(1, invalid.returncode)
            self.assertNotIn("Traceback", invalid.stderr)
            path.unlink()
            missing = subprocess.run(
                [sys.executable, str(script), "--public-text", str(path)],
                cwd=directory,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(1, missing.returncode)
            self.assertNotIn("Traceback", missing.stderr)


if __name__ == "__main__":
    unittest.main()


class BundledHooksSchemaTests(unittest.TestCase):
    """The two hook schemas Compass ships, which are not the same shape."""

    def _validate(self, document: object, *, ship_script: bool) -> list[str]:
        with tempfile.TemporaryDirectory(prefix="compass-hooks-schema-") as directory:
            plugin_root = Path(directory) / "plug"
            (plugin_root / "skills/compass").mkdir(parents=True)
            if ship_script:
                (plugin_root / "skills/compass/agy_hook.py").write_text("#\n")
            (plugin_root / "hooks.json").write_text(json.dumps(document))
            validation = validator.Validation()
            validator.validate_hooks_adapter(plugin_root, validation)
            return validation.errors

    def test_a_name_wrapped_antigravity_file_is_understood(self) -> None:
        # Antigravity's guide states that each top-level key is a hook NAME, with
        # the events one level inside it. This test previously asserted the
        # opposite -- that a file with event names at the top level was valid --
        # and that is how the shipped file came to be malformed: `agy plugin
        # validate` accepted it by counting keys without type-checking them, so
        # "Antigravity's own validator had just accepted it" was true and
        # meaningless. agy's runtime discards such a file. See
        # AntigravityHookNestingTests.
        document = {
            "compass": {
                "PostToolUse": [
                    {
                        "matcher": "",
                        "hooks": [
                            {
                                "type": "command",
                                "command": 'python3 "${PLUGIN_ROOT}/skills/compass/agy_hook.py"',
                            }
                        ],
                    }
                ]
            }
        }
        self.assertEqual([], self._validate(document, ship_script=True))
        self.assertTrue(
            any("agy_hook.py" in e for e in self._validate(document, ship_script=False))
        )

    def test_a_flat_handler_list_is_walked_too(self) -> None:
        # Antigravity uses both layouts in one file: tool-scoped events group their
        # handlers under a matcher, loop-scoped events list them directly. A walker
        # that understood only the grouped form would check nothing in the flat
        # half, so a missing script there would ship unnoticed.
        document = {
            "compass": {
                "PostInvocation": [
                    {
                        "type": "command",
                        "command": 'python3 "${PLUGIN_ROOT}/skills/compass/agy_hook.py"',
                    }
                ]
            }
        }
        self.assertEqual([], self._validate(document, ship_script=True))
        self.assertTrue(
            any("agy_hook.py" in e for e in self._validate(document, ship_script=False)),
            "a flat handler's command went unchecked",
        )


class HookVocabularyTests(unittest.TestCase):
    """No bundled hooks file may register another harness's event names.

    The guard exists because the failure was real, not hypothetical. Before Gemini
    got its own extension root, a Gemini session loading Claude's `hooks/hooks.json`
    printed eight `Invalid hook event name` warnings, then ran the two names that do
    overlap and reported both as failed hooks. Nothing in the build noticed.
    """

    def _errors(self, relative: str, document: dict[str, Any], tmp: Path) -> list[str]:
        path = tmp / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(document), encoding="utf-8")
        validation = validator.Validation()
        with mock.patch.object(validator, "ROOT", tmp):
            validator.validate_hook_vocabulary(validation)
        return [str(message) for message in validation.errors]

    @staticmethod
    def _gemini_document(event: str = "BeforeAgent", harness: str = "gemini") -> dict[str, Any]:
        return {
            "hooks": {
                event: [
                    {
                        "matcher": "",
                        "hooks": [
                            {
                                "type": "command",
                                "command": (
                                    'python3 "${extensionPath}/hooks/event_hook.py" ' + harness
                                ),
                            }
                        ],
                    }
                ]
            }
        }

    def test_a_name_the_harness_knows_passes(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            self.assertEqual(
                [],
                self._errors("compass-gemini/hooks/hooks.json", self._gemini_document(), tmp),
            )

    def test_a_foreign_event_name_is_rejected(self) -> None:
        # `UserPromptSubmit` is Claude's name for the same moment. Gemini skips it.
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            errors = self._errors(
                "compass-gemini/hooks/hooks.json",
                self._gemini_document(event="UserPromptSubmit"),
                tmp,
            )
            self.assertTrue(
                any("UserPromptSubmit" in message for message in errors),
                f"a foreign event name went unreported: {errors}",
            )

    def test_a_foreign_harness_argument_is_rejected(self) -> None:
        # The other half of the same bug: the file could carry Gemini's event names
        # and still post them to Claude's route, where Claude's normalizer
        # truncates the id to eight characters and it matches no row.
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            errors = self._errors(
                "compass-gemini/hooks/hooks.json",
                self._gemini_document(harness="claude"),
                tmp,
            )
            self.assertTrue(
                any("wrong route" in message for message in errors),
                f"a foreign harness argument went unreported: {errors}",
            )

    @staticmethod
    def _droid_document(event: str = "SessionStart", harness: str = "droid") -> dict[str, Any]:
        return {
            "hooks": {
                event: [
                    {
                        "matcher": "",
                        "hooks": [
                            {
                                "type": "command",
                                "command": (
                                    'python3 "${DROID_PLUGIN_ROOT}/hooks/event_hook.py" ' + harness
                                ),
                            }
                        ],
                    }
                ]
            }
        }

    def test_a_name_the_droid_harness_knows_passes(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            self.assertEqual(
                [],
                self._errors("compass-droid/hooks/hooks.json", self._droid_document(), tmp),
            )

    def test_a_foreign_droid_event_name_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            errors = self._errors(
                "compass-droid/hooks/hooks.json",
                self._droid_document(event="UserPromptSubmit"),
                tmp,
            )
            self.assertTrue(
                any("UserPromptSubmit" in message for message in errors),
                f"a foreign event name went unreported: {errors}",
            )

    def test_a_foreign_droid_harness_argument_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            errors = self._errors(
                "compass-droid/hooks/hooks.json",
                self._droid_document(harness="claude"),
                tmp,
            )
            self.assertTrue(
                any("wrong route" in message for message in errors),
                f"a foreign harness argument went unreported: {errors}",
            )

    def test_every_bundled_hooks_file_in_the_repository_satisfies_its_vocabulary(self) -> None:
        # The shipped files themselves, not a fixture: this is what would have
        # failed before the split.
        validation = validator.Validation()
        validator.validate_hook_vocabulary(validation)
        self.assertEqual([], [str(message) for message in validation.errors])


class DuplicatedScriptTests(unittest.TestCase):
    """A script that ships twice stays byte-identical in both places."""

    def test_the_shipped_copies_match_today(self) -> None:
        validation = validator.Validation()
        validator.validate_duplicated_scripts(validation)
        self.assertEqual([], [str(message) for message in validation.errors])

    def test_drift_between_the_copies_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            for copy_relative, source_relative in validator.DUPLICATED_SCRIPTS:
                for relative, body in ((source_relative, "one"), (copy_relative, "two")):
                    path = tmp / relative
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(body, encoding="utf-8")
            validation = validator.Validation()
            with mock.patch.object(validator, "ROOT", tmp):
                validator.validate_duplicated_scripts(validation)
            self.assertEqual(
                len(validator.DUPLICATED_SCRIPTS),
                len(validation.errors),
                "each drifted copy must be reported",
            )


class RepositoryDevelopmentSkillTests(unittest.TestCase):
    """Claude owns repository skills; Codex reaches the same directories."""

    def _guard(self) -> Any:
        guard = getattr(validator, "validate_repository_skills", None)
        self.assertIsNotNone(guard, "the repository skill alias guard is missing")
        return guard

    def _write_skill(self, root: Path, name: str) -> Path:
        skill = root / ".claude/skills" / name
        (skill / "agents").mkdir(parents=True)
        (skill / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: Use when testing {name}.\n---\n\n# {name}\n",
            encoding="utf-8",
        )
        (skill / "agents/openai.yaml").write_text(
            "interface:\n"
            f'  display_name: "{name}"\n'
            '  short_description: "Repository development workflow skill"\n'
            f'  default_prompt: "Use ${name} for this repository workflow."\n',
            encoding="utf-8",
        )
        return skill

    def _link_skill(self, root: Path, name: str, target: Path | None = None) -> Path:
        aliases = root / ".agents/skills"
        aliases.mkdir(parents=True, exist_ok=True)
        alias = aliases / name
        alias.symlink_to(target or Path("../../.claude/skills") / name, target_is_directory=True)
        return alias

    def _errors(self, root: Path) -> list[str]:
        validation = validator.Validation()
        guard = self._guard()
        if guard is None:
            return []
        with mock.patch.object(validator, "ROOT", root):
            guard(validation)
        return [str(message) for message in validation.errors]

    def test_the_repository_skills_are_valid_codex_aliases_today(self) -> None:
        errors = self._errors(validator.ROOT)
        self.assertEqual([], errors)

    def test_an_empty_canonical_skill_tree_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="compass-repo-skills-") as directory:
            root = Path(directory)
            (root / ".claude/skills").mkdir(parents=True)

            errors = self._errors(root)

        self.assertTrue(any("no canonical repository skills" in error for error in errors), errors)

    def test_a_missing_codex_alias_is_reported(self) -> None:
        with tempfile.TemporaryDirectory(prefix="compass-repo-skills-") as directory:
            root = Path(directory)
            self._write_skill(root, "fixture")

            errors = self._errors(root)

        self.assertTrue(any("missing Codex alias" in error for error in errors), errors)

    def test_repository_skill_description_length_is_bounded(self) -> None:
        with tempfile.TemporaryDirectory(prefix="compass-repo-skills-") as directory:
            root = Path(directory)
            skill = self._write_skill(root, "fixture")
            (skill / "SKILL.md").write_text(
                f"---\nname: fixture\ndescription: {'x' * 301}\n---\n",
                encoding="utf-8",
            )
            self._link_skill(root, "fixture")

            errors = self._errors(root)

        self.assertTrue(any("maximum is 300" in error for error in errors), errors)

    def test_repository_skill_description_rejects_angle_brackets(self) -> None:
        with tempfile.TemporaryDirectory(prefix="compass-repo-skills-") as directory:
            root = Path(directory)
            skill = self._write_skill(root, "fixture")
            (skill / "SKILL.md").write_text(
                "---\nname: fixture\ndescription: Use when handling <placeholder>.\n---\n",
                encoding="utf-8",
            )
            self._link_skill(root, "fixture")

            errors = self._errors(root)

        self.assertTrue(any("angle-bracket" in error for error in errors), errors)

    def test_a_copy_is_rejected_in_place_of_a_symlink(self) -> None:
        with tempfile.TemporaryDirectory(prefix="compass-repo-skills-") as directory:
            root = Path(directory)
            canonical = self._write_skill(root, "fixture")
            alias = root / ".agents/skills/fixture"
            alias.parent.mkdir(parents=True)
            shutil.copytree(canonical, alias)

            errors = self._errors(root)

        self.assertTrue(any("must be a symlink" in error for error in errors), errors)

    def test_a_codex_alias_must_point_to_its_matching_claude_skill(self) -> None:
        with tempfile.TemporaryDirectory(prefix="compass-repo-skills-") as directory:
            root = Path(directory)
            self._write_skill(root, "fixture")
            self._write_skill(root, "other")
            self._link_skill(root, "fixture", Path("../../.claude/skills/other"))
            self._link_skill(root, "other")

            errors = self._errors(root)

        self.assertTrue(
            any("must target" in error and "fixture" in error for error in errors), errors
        )

    def test_repository_skills_require_openai_metadata(self) -> None:
        with tempfile.TemporaryDirectory(prefix="compass-repo-skills-") as directory:
            root = Path(directory)
            skill = self._write_skill(root, "fixture")
            (skill / "agents/openai.yaml").unlink()
            self._link_skill(root, "fixture")

            errors = self._errors(root)

        self.assertTrue(
            any("openai.yaml" in error and "required" in error for error in errors), errors
        )

    def test_repository_skills_validate_openai_metadata_content(self) -> None:
        with tempfile.TemporaryDirectory(prefix="compass-repo-skills-") as directory:
            root = Path(directory)
            skill = self._write_skill(root, "fixture")
            (skill / "agents/openai.yaml").write_text(
                "interface:\n"
                '  display_name: "Fixture"\n'
                '  short_description: "Too short"\n'
                '  default_prompt: "Run this repository workflow."\n',
                encoding="utf-8",
            )
            self._link_skill(root, "fixture")

            errors = self._errors(root)

        self.assertTrue(any("25 to 64 characters" in error for error in errors), errors)
        self.assertTrue(any("must mention $fixture" in error for error in errors), errors)

    def test_an_alias_without_a_canonical_skill_is_reported(self) -> None:
        with tempfile.TemporaryDirectory(prefix="compass-repo-skills-") as directory:
            root = Path(directory)
            self._link_skill(root, "orphan")

            errors = self._errors(root)

        self.assertTrue(any("has no canonical Claude skill" in error for error in errors), errors)


class AntigravityHookNestingTests(unittest.TestCase):
    """Antigravity's hooks file wraps its events in a name, and a flat one is dead.

    The guard exists because this shipped. Compass's root `hooks.json` put event
    names at the top level for the whole life of the Antigravity adapter, and three
    separate things that should have caught it did not: `agy plugin validate`
    reported `hooks: 5 processed` because it counts top-level keys without
    type-checking them, this validator read those keys as event names, and the
    design note wrote the difference down as a discovered fact. agy's runtime
    rejected the file on every session, visibly only in a log nobody reads.
    """

    def _errors(self, document: dict[str, Any], tmp: Path) -> list[str]:
        path = tmp / "compass/hooks.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(document), encoding="utf-8")
        validation = validator.Validation()
        with mock.patch.object(validator, "ROOT", tmp):
            validator.validate_antigravity_hook_nesting(validation)
        return [str(message) for message in validation.errors]

    def test_event_names_at_the_top_level_are_rejected(self) -> None:
        handler = {"type": "command", "command": 'python3 "./skills/compass/agy_hook.py" x'}
        with tempfile.TemporaryDirectory(prefix="compass-agy-nesting-") as directory:
            errors = self._errors({"PostInvocation": [handler]}, Path(directory))
        self.assertTrue(
            any("at the top level" in e and "PostInvocation" in e for e in errors), errors
        )

    def test_a_name_wrapped_file_is_accepted(self) -> None:
        handler = {"type": "command", "command": 'python3 "./skills/compass/agy_hook.py" x'}
        with tempfile.TemporaryDirectory(prefix="compass-agy-nesting-") as directory:
            errors = self._errors({"compass": {"PostInvocation": [handler]}}, Path(directory))
        self.assertEqual(errors, [])

    def test_a_file_with_no_named_hook_is_rejected(self) -> None:
        # An empty object parses and would silently load nothing.
        with tempfile.TemporaryDirectory(prefix="compass-agy-nesting-") as directory:
            errors = self._errors({}, Path(directory))
        self.assertTrue(any("registers no named hook" in e for e in errors), errors)

    def test_the_shipped_file_is_name_wrapped(self) -> None:
        """The regression this class exists for, asserted against the real file."""
        document = json.loads((validator.ROOT / "compass/hooks.json").read_text())
        self.assertTrue(document, "the shipped Antigravity hooks file is empty")
        for key, value in document.items():
            self.assertIsInstance(
                value, dict, f"top-level {key!r} must be a hook NAME mapping to its events"
            )


class PromiseParityTests(unittest.TestCase):
    """The promise map against the Visibility 2x2 board, both sides constructed.

    `validate_promise_parity` shipped with no test, and it is the check in this
    file whose two inputs are both hand-edited: a person writes
    `docs/promise-map.md`, and a board editing session writes
    `docs/visibility-2x2/items.json` through its own save endpoint. The check
    works — measured against four constructed divergences, all four rejected —
    so what follows is the missing evidence rather than a bug hunt, and the
    agreement case sits in the same class so no failure case can pass because
    its fixtures never parsed.

    Every path here reports through `validation.error`; nothing raises. The two
    keying decisions get their own tests because both are silent when wrong:
    the board is keyed POSITIONALLY as `P{i+1}`, so a column reorder renumbers
    every promise, and equality permits exactly one difference, the board's
    first character upper-cased.
    """

    PROMISES: ClassVar[dict[str, str]] = {
        "P1": "every session on this machine, across ten harnesses, on one screen",
        "P2": "for each live session, what it is doing now and what it plans next",
        "P3": "one queue of everything blocked on you",
        "P4": "your quota in one place across vendors",
        "P5": "nothing finishes invisibly",
    }

    COUNT_ERROR = "docs/visibility-2x2/items.json: 6 board columns against 5 promises in the map"

    def _map_body(self, promises: dict[str, str]) -> str:
        """The map as the regex in `validate_promise_parity` needs to read it.

        P2's promise is wrapped across two lines on purpose: the check
        whitespace-collapses the map side, and a fixture written all on one line
        would leave that collapse untested.
        """
        blocks = []
        for key, promise in promises.items():
            body = promise.replace(" and ", " and\n", 1) if key == "P2" else promise
            blocks.append(f"### {key}. A question a user asks?\n\n**We promise:** {body}\n")
        return "# Promise map\n\n" + "\n".join(blocks) + "\n"

    def _board(self, promises: dict[str, str]) -> dict[str, Any]:
        """The board as it renders each promise: standing alone, so capitalized."""
        columns = []
        for promise in promises.values():
            flat = " ".join(promise.split())
            columns.append({"promise": flat[:1].upper() + flat[1:]})
        return {"columns": columns}

    def run_case(self, map_body: str | None = None, board: object = None) -> list[str]:
        """Both files under a throwaway ROOT; `None` leaves that side absent."""
        with tempfile.TemporaryDirectory(prefix="compass-promise-parity-") as directory:
            root = Path(directory)
            (root / "docs/visibility-2x2").mkdir(parents=True)
            if map_body is not None:
                (root / "docs/promise-map.md").write_text(map_body, encoding="utf-8")
            if board is not None:
                (root / "docs/visibility-2x2/items.json").write_text(
                    json.dumps(board), encoding="utf-8"
                )
            validation = validator.Validation()
            with mock.patch.object(validator, "ROOT", root):
                validator.validate_promise_parity(validation)
            return [str(message) for message in validation.errors]

    def test_a_matching_pair_reports_nothing(self) -> None:
        errors = self.run_case(self._map_body(self.PROMISES), self._board(self.PROMISES))
        self.assertEqual([], errors)

    def test_a_board_copy_that_kept_the_lowercase_lead_in_is_rejected(self) -> None:
        # The permitted difference is exactly one character, in one direction. A
        # board copy pasted straight out of the map keeps the map's lowercase
        # opening, which is not the sentence the board renders.
        board = {"columns": [{"promise": p} for p in self.PROMISES.values()]}
        errors = self.run_case(self._map_body(self.PROMISES), board)
        self.assertEqual(5, len(errors), errors)
        self.assertTrue(all("disagrees with the promise map" in e for e in errors), errors)

    def test_a_diverging_promise_names_its_own_p_number(self) -> None:
        board = self._board(self.PROMISES)
        board["columns"][0]["promise"] = "A burn-rate projection per session"
        errors = self.run_case(self._map_body(self.PROMISES), board)
        self.assertEqual(1, len(errors), errors)
        self.assertIn("P1 disagrees with the promise map", errors[0])
        self.assertIn("docs/visibility-2x2/items.json", errors[0])

    def test_swapping_two_columns_is_caught_on_both(self) -> None:
        # Why the board is keyed positionally rather than by set membership.
        # Both promises are still present and still spelled correctly; only the
        # numbering moved, and a set comparison would call this file clean.
        board = self._board(self.PROMISES)
        board["columns"][0], board["columns"][1] = board["columns"][1], board["columns"][0]
        errors = self.run_case(self._map_body(self.PROMISES), board)
        self.assertEqual(2, len(errors), errors)
        self.assertIn("P1 disagrees", errors[0])
        self.assertIn("P2 disagrees", errors[1])

    def test_a_column_with_no_promise_key_is_rejected(self) -> None:
        board = self._board(self.PROMISES)
        board["columns"][2] = {"title": "Waiting"}
        errors = self.run_case(self._map_body(self.PROMISES), board)
        self.assertEqual(1, len(errors), errors)
        self.assertIn("P3 disagrees", errors[0])

    def test_an_extra_board_column_is_reported_as_a_count_and_masks_the_rest(self) -> None:
        # The count mismatch returns early, so this is the one divergence that
        # reports a single line however much else has drifted. The second edit
        # below would be its own message on a run where the counts agree.
        board = self._board(self.PROMISES)
        board["columns"].append({"promise": "A sixth column nobody promised"})
        board["columns"][0]["promise"] = "Also wrong, and invisible until the count agrees"
        errors = self.run_case(self._map_body(self.PROMISES), board)
        self.assertEqual([self.COUNT_ERROR], errors)

    def test_a_map_missing_one_p_number_blames_the_map(self) -> None:
        # Counts agree, so this reaches the per-column loop: five columns
        # against P1, P2, P4, P5, P6. The gap is the map's, and the message says
        # so rather than accusing the board.
        promises = {
            key: value
            for key, value in {**self.PROMISES, "P6": "a sixth promise"}.items()
            if key != "P3"
        }
        errors = self.run_case(self._map_body(promises), self._board(promises))
        self.assertTrue(any("the map has no P3 promise" in e for e in errors), errors)
        self.assertTrue(any(e.startswith("docs/promise-map.md:") for e in errors), errors)

    def test_a_two_digit_promise_number_is_invisible_to_the_regex(self) -> None:
        r"""`P\d` is single-digit, so `### P10.` is not a promise as far as this reads.

        Pinned deliberately rather than discovered later. The check still fails
        closed — the count mismatch catches it — but it reports the wrong side,
        blaming the board for a column the map does define. Whoever adds a tenth
        promise should widen the regex and delete this test.
        """
        promises = {**self.PROMISES, "P10": "a tenth promise the regex cannot see"}
        errors = self.run_case(self._map_body(promises), self._board(promises))
        self.assertEqual([self.COUNT_ERROR], errors)

    def test_a_missing_file_on_either_side_is_reported_once(self) -> None:
        for present in ("map", "board"):
            with self.subTest(present=present):
                errors = self.run_case(
                    self._map_body(self.PROMISES) if present == "map" else None,
                    self._board(self.PROMISES) if present == "board" else None,
                )
                self.assertEqual(1, len(errors), errors)
                self.assertIn("must both exist", errors[0])

    def test_a_board_without_a_columns_list_is_rejected(self) -> None:
        errors = self.run_case(self._map_body(self.PROMISES), {"columns": {"P1": "wrong shape"}})
        self.assertTrue(any("must carry a columns list" in e for e in errors), errors)

    def test_the_runtime_files_mode_never_reaches_this_check(self) -> None:
        # `--runtime-files` points at an installed copy with no repository
        # around it, where neither input exists. It short-circuits before any
        # repository check runs; a refactor that moved the short-circuit later
        # would make every installed-copy run report a missing promise map.
        with (
            mock.patch.object(validator, "check_installed_runtime", return_value=0) as installed,
            mock.patch.object(validator, "validate_promise_parity") as parity,
            mock.patch.object(sys, "argv", ["validate_plugins.py", "--runtime-files", "/nowhere"]),
        ):
            self.assertEqual(0, validator.main())
        installed.assert_called_once()
        parity.assert_not_called()

    def test_the_shipped_pair_agrees(self) -> None:
        """The regression this class exists for, asserted against the real files."""
        validation = validator.Validation()
        validator.validate_promise_parity(validation)
        self.assertEqual([], validation.errors)


@unittest.skipUnless(shutil.which("node"), "node is required for JavaScript adapter evidence")
class JavaScriptAdapterContractTest(unittest.TestCase):
    def test_a_missing_javascript_adapter_is_an_installed_runtime_failure(self) -> None:
        self.assertIn("skills/compass/opencode_plugin.js", validator.COMPASS_RUNTIME_FILES)

    def test_the_native_callback_proves_its_route_and_gate_pair(self) -> None:
        self.assertTrue(
            hasattr(validator, "exercise_js_adapter"), "JS callback derivation is absent"
        )
        path = validator.ROOT / "compass/skills/compass/opencode_plugin.js"
        observed = validator.exercise_js_adapter(path)
        self.assertEqual(["event"], observed["hooks"])
        self.assertEqual(
            ["input_requested", "input_resolved"],
            [r["body"]["event"] for r in observed["deliveries"]],
        )
        self.assertEqual({"/api/events/opencode"}, {r["path"] for r in observed["deliveries"]})

    def test_mutated_native_name_route_and_gate_mapping_are_rejected(self) -> None:
        directory = validator.ROOT / "compass/skills/compass"
        cases = (
            ("opencode_plugin.js", "permission.asked", "permission.ask"),
            ("opencode_plugin.js", "/api/events/opencode", "/api/events/pi"),
            ("opencode_plugin.js", "input_requested", "store_changed"),
            ("pi_extension.js", "ui_prompt_start", "ui_prompt_changed"),
            ("pi_extension.js", 'const HARNESS = "pi"', 'const HARNESS = "opencode"'),
            ("pi_extension.js", "input_requested", "store_changed"),
        )
        self.assertEqual([], validator.check_js_adapters(directory))
        for filename, before, after in cases:
            with self.subTest(mutation=after), tempfile.TemporaryDirectory() as tmp:
                for shipped in validator.JS_ADAPTERS:
                    shutil.copyfile(directory / shipped, Path(tmp) / shipped)
                mutated = Path(tmp) / filename
                mutated.write_text(mutated.read_text().replace(before, after))
                problems = validator.check_js_adapters(Path(tmp))
                self.assertTrue(any(filename in problem for problem in problems), problems)


class ScriptTestsDiscoveryContractTest(unittest.TestCase):
    def test_all_script_tests_are_discoverable(self) -> None:
        scripts_tests_dir = validator.ROOT / "scripts" / "tests"
        test_files = sorted(f.stem for f in scripts_tests_dir.glob("test_*.py"))
        self.assertTrue(
            len(test_files) >= 13, f"Expected at least 13 test modules, found {len(test_files)}"
        )

        loader = unittest.defaultTestLoader
        suite = loader.discover(str(scripts_tests_dir), top_level_dir=str(scripts_tests_dir))

        loaded_modules: set[str] = set()

        def _walk_suite(s: Any) -> None:
            for item in s:
                if isinstance(item, unittest.TestSuite):
                    _walk_suite(item)
                elif isinstance(item, unittest.TestCase):
                    loaded_modules.add(item.__class__.__module__)

        _walk_suite(suite)
        for mod in test_files:
            self.assertIn(mod, loaded_modules, f"Module {mod} was not discovered by unittest")

    def test_workflows_and_agents_use_discovery_not_hand_kept_lists(self) -> None:
        quality_gate_path = validator.ROOT / ".github" / "workflows" / "quality-gate.yml"
        quality_gate_text = quality_gate_path.read_text(encoding="utf-8")
        agents_path = validator.ROOT / "AGENTS.md"
        agents_text = agents_path.read_text(encoding="utf-8")

        # Must not contain hand-enumerated scripts.tests module lists
        self.assertNotIn("scripts.tests.test_bump_version", quality_gate_text)
        self.assertNotIn("scripts.tests.test_bump_version", agents_text)

        # Must use discovery for scripts/tests: `unittest discover` itself, or
        # scripts/run_tests.py, which repeats the same discover call per worker.
        discovery = (
            r"(unittest discover|scripts/run_tests\.py)( --\S+)* -s scripts/tests -t scripts/tests"
        )
        self.assertRegex(quality_gate_text, discovery)
        self.assertRegex(agents_text, discovery)
