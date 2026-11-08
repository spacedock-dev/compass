"""Run the reader's installed-copy commands without reaching a real dashboard."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASH = shutil.which("bash")


def skill_snippets() -> list[str]:
    source = (ROOT / "HOW_TO_USE.md").read_text(encoding="utf-8")
    blocks = re.findall(r"^```bash\n(.*?)^```", source, re.MULTILINE | re.DOTALL)
    commands = [block for block in blocks if "$SKILL" in block or "SKILL=" in block]
    # The status example lives in a table rather than a fenced shell block.
    commands.extend(re.findall(r'`(python3 "\$SKILL/[^`]+)`', source))
    return commands


@unittest.skipUnless(os.name == "posix" and BASH, "The documented snippets use POSIX Bash")
class AReaderChoosesTheInstalledCopyTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="compass snippets ")
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.bin = self.home / "bin"
        self.bin.mkdir()
        self.calls = self.home / "calls.jsonl"
        # An allowlist of environment variables keeps inherited harness identities,
        # relocated stores and Python startup customizations out of these shells.
        self.env = {
            "HOME": str(self.home),
            "PATH": str(self.bin) + os.pathsep + os.defpath,
            "SNIPPET_CALLS": str(self.calls),
        }
        python = self.bin / "python3"
        python.symlink_to(sys.executable)
        for command in ("pi", "codex"):
            stub = self.bin / command
            stub.write_text(
                f"#!{sys.executable}\n"
                "import json, os, sys\n"
                "with open(os.environ['SNIPPET_CALLS'], 'a') as out:\n"
                "    out.write(json.dumps(sys.argv) + '\\n')\n",
                encoding="utf-8",
            )
            stub.chmod(0o755)

    def install(self, cache: str, version: str) -> Path:
        skill = self.home / cache / "example/compass" / version / "skills/compass"
        skill.mkdir(parents=True)
        (skill / "launch.py").write_text(
            "import json, os, sys\n"
            "with open(os.environ['SNIPPET_CALLS'], 'a') as out:\n"
            "    out.write(json.dumps(sys.argv) + '\\n')\n",
            encoding="utf-8",
        )
        (skill / "server.py").write_text("raise AssertionError('stub only')\n", encoding="utf-8")
        for filename in ("pi_extension.js", "opencode_plugin.js", "mcp_server.py"):
            (skill / filename).write_text("// selected copy\n", encoding="utf-8")
        return skill

    def run_snippet(self, snippet: str, answer: str = "") -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [BASH or "/bin/bash", "--noprofile", "--norc", "-c", snippet],
            cwd=self.home,
            env=self.env,
            input=answer,
            text=True,
            capture_output=True,
            check=False,
            timeout=10,
        )

    def recorded_calls(self) -> list[list[str]]:
        if not self.calls.exists():
            return []
        return [json.loads(line) for line in self.calls.read_text().splitlines()]

    def test_a_reader_runs_the_chosen_copy_regardless_of_cache_discovery_order(self) -> None:
        # A return to find | head -1 launches the wrong version in one of the orders.
        for cache in (".claude/plugins/cache", ".codex/plugins/cache", ".gemini/config/plugins"):
            for versions in (("old build", "new build"), ("new build", "old build")):
                with self.subTest(cache=cache, versions=versions):
                    for version in versions:
                        self.install(cache, version)
                    chosen = self.home / cache / "example/compass/old build/skills/compass"
                    result = self.run_snippet(skill_snippets()[0], str(chosen) + "\n")
                    calls = self.recorded_calls()
                    self.calls.unlink(missing_ok=True)
                    shutil.rmtree(self.home / cache)
                    self.assertEqual(0, result.returncode, result.stderr)
                    self.assertEqual(
                        [[str(chosen / "launch.py"), str(chosen / "server.py"), "--diagnose"]],
                        calls,
                        "The reader's choice must beat cache discovery order and version age",
                    )

    def test_a_reader_sees_candidates_without_launching_one_when_no_choice_is_made(self) -> None:
        candidates = [self.install(".claude/plugins/cache", v) for v in ("old", "new")]
        # A stale choice from an earlier shell session must not survive a refused selection.
        self.env["SKILL"] = str(candidates[0])
        for answer in ("", "\n"):
            with self.subTest(answer=answer):
                result = self.run_snippet(
                    skill_snippets()[0] + '\nprintf "remaining=%s" "${SKILL-unset}"\n', answer
                )
                self.assertEqual(
                    [], self.recorded_calls(), "Listing candidates must never launch a copy"
                )
                for candidate in candidates:
                    self.assertIn(str(candidate), result.stdout)
                self.assertIn("remaining=unset", result.stdout)
                self.assertIn("choose", (result.stdout + result.stderr).lower())

    def test_a_reader_cannot_run_a_copy_missing_either_neighboring_launcher(self) -> None:
        for missing in ("launch.py", "server.py"):
            with self.subTest(missing=missing):
                chosen = self.install(".claude/plugins/cache", missing)
                (chosen / missing).unlink()
                self.env["SKILL"] = str(chosen)
                result = self.run_snippet(skill_snippets()[0], str(chosen) + "\n")
                self.assertEqual([], self.recorded_calls(), "An incomplete copy must not run")
                self.assertNotEqual(0, result.returncode)
                self.assertIn("launch.py", result.stderr)
                self.assertIn("server.py", result.stderr)

    def test_a_reader_cannot_use_a_directory_named_like_a_launcher(self) -> None:
        chosen = self.install(".claude/plugins/cache", "broken")
        (chosen / "server.py").unlink()
        (chosen / "server.py").mkdir()
        result = self.run_snippet(skill_snippets()[0], str(chosen) + "\n")
        self.assertEqual([], self.recorded_calls())
        self.assertNotEqual(0, result.returncode)

    def test_a_reader_runs_every_skill_snippet_with_spaces_in_the_selected_path(self) -> None:
        chosen = self.install(".codex/plugins/cache", "active build")
        snippets = skill_snippets()
        self.assertGreaterEqual(len(snippets), 8, "Exercise fenced snippets and the table command")
        for snippet in snippets:
            with self.subTest(snippet=snippet):
                # Each example gets the same validated selection, never a real launcher.
                script = snippets[0] if snippet == snippets[0] else snippets[0] + "\n" + snippet
                result = self.run_snippet(script, str(chosen) + "\n")
                self.assertEqual(0, result.returncode, result.stderr)
                calls = self.recorded_calls()
                self.assertTrue(calls, "The selection must diagnose the chosen copy")
                for call in calls:
                    if Path(call[0]).name == "pi":
                        self.assertEqual(["-e", str(chosen / "pi_extension.js")], call[1:])
                    elif Path(call[0]).name == "codex":
                        self.assertEqual(
                            [
                                "mcp",
                                "add",
                                "compass",
                                "--env",
                                f"COMPASS_HOME={self.home}/.compass",
                                "--",
                                "python3",
                                str(chosen / "launch.py"),
                                str(chosen / "mcp_server.py"),
                            ],
                            call[1:],
                        )
                    else:
                        self.assertEqual(str(chosen / "launch.py"), call[0])
                        self.assertEqual(str(chosen / "server.py"), call[1])
                        self.assertIn(
                            call[2:],
                            [
                                ["--diagnose"],
                                ["--sessions", "waiting"],
                                ["--port", "4601", "--status"],
                                ["--port", "4553", "--stop"],
                            ],
                        )
                if "opencode_plugin.js" in snippet:
                    self.assertEqual(
                        "// selected copy\n",
                        (self.home / ".opencode/plugin/compass.js").read_text(encoding="utf-8"),
                    )
                self.calls.unlink()


if __name__ == "__main__":
    unittest.main()
