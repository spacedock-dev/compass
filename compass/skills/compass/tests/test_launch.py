"""`launch.py`: what someone with an old `python3` sees, and what nobody else notices.

Every hook, the MCP server and the documented `server.py` start go through the launcher,
so it is the one file that must run on an interpreter too old for the rest of Compass.
"""

from __future__ import annotations

import ast
import contextlib
import importlib.util
import json
import os
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from .support import SERVER_PATH

# Launchers, uv and scripts run as real processes, and their starts and exits are waited for.
REAL_TIME_TESTS = True

SKILL = SERVER_PATH.parent
PLUGIN_ROOT = SKILL.parents[1]
REPO = PLUGIN_ROOT.parent
LAUNCHER = SKILL / "launch.py"
SEAM = "COMPASS_LAUNCH_ASSUME_PYTHON"
OLD = "3.9.6"
SYSTEM_PYTHON = Path("/usr/bin/python3")
SESSION_START = json.dumps({"hook_event_name": "SessionStart", "session_id": "s1"}).encode()
POST_TOOL = json.dumps({"hook_event_name": "PostToolUse", "session_id": "s1"}).encode()

# Stands in for any target: records who ran it, with what argv and stdin.
TARGET_SOURCE = """\
import os, sys
with open(os.environ["TARGET_LOG"], "w") as log:
    log.write(sys.executable + "\\n" + repr(sys.argv[1:]) + "\\n")
sys.stdout.write("stdin:" + sys.stdin.read())
sys.exit(int(os.environ.get("TARGET_EXIT", "0")))
"""


class LauncherTest(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.bin = (
            self.root / "bin"
        )  # PATH for the launcher; uv appears only if a test puts it here
        self.bin.mkdir()
        self.log = self.root / "target.log"
        self.uv_log = self.root / "uv.log"

    def target(self, name: str = "event_hook.py") -> Path:
        path = self.root / name
        path.write_text(TARGET_SOURCE, encoding="utf-8")
        return path

    def fake_uv(self, body: str) -> None:
        """A `uv` that records its argv, then runs `body` (shell)."""
        script = self.bin / "uv"
        script.write_text(
            f'#!/bin/sh\necho "$@" >> "{self.uv_log}"\n{body}\n',
            encoding="utf-8",
        )
        script.chmod(script.stat().st_mode | stat.S_IEXEC)

    def finds_this_interpreter(self) -> None:
        self.fake_uv(f'echo "{sys.executable}"')

    def run_launcher(
        self,
        target: Path,
        *args: str,
        stdin: bytes = b"",
        assume: str | None = OLD,
        python: str = sys.executable,
        exit_code: int = 0,
        timeout: float = 30,
        cwd: Path | None = None,
    ) -> subprocess.CompletedProcess[bytes]:
        env = {
            "PATH": str(self.bin),
            "TARGET_LOG": str(self.log),
            "TARGET_EXIT": str(exit_code),
            "HOME": str(self.root),
        }
        if assume is not None:
            env[SEAM] = assume
        return subprocess.run(
            [python, str(LAUNCHER), str(target), *args],
            input=stdin,
            capture_output=True,
            env=env,
            timeout=timeout,
            check=False,
            cwd=cwd,
        )

    def logged(self) -> list[str]:
        return self.log.read_text(encoding="utf-8").splitlines()


class FileShapeTest(unittest.TestCase):
    def test_the_launcher_parses_as_python_3_6(self) -> None:
        source = LAUNCHER.read_text(encoding="utf-8")
        ast.parse(source, filename=str(LAUNCHER), feature_version=(3, 6))

    def test_the_launcher_has_no_future_import_and_no_annotations_syntax_to_rely_on(self) -> None:
        tree = ast.parse(LAUNCHER.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "__future__":
                self.fail("an old interpreter must be able to run the file as written")

    def test_ruff_holds_every_copy_of_the_launcher_to_the_old_grammar(self) -> None:
        text = (REPO / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn("[tool.ruff.per-file-target-version]", text)
        for copy in (
            "launch.py",
            "compass-gemini/hooks/launch.py",
            "compass-droid/hooks/launch.py",
        ):
            self.assertIn(copy, text)

    def test_every_shipped_copy_is_the_same_bytes(self) -> None:
        for root in ("compass-gemini", "compass-droid"):
            copy = REPO / root / "hooks" / "launch.py"
            self.assertEqual(LAUNCHER.read_bytes(), copy.read_bytes(), root)


class AtOrAboveTheFloorTest(LauncherTest):
    def test_someone_on_a_new_python_has_the_payload_argv_and_exit_status_passed_through(
        self,
    ) -> None:
        target = self.target()
        done = self.run_launcher(
            target, "claude", "9999", stdin=POST_TOOL, assume=None, exit_code=7
        )
        self.assertEqual(7, done.returncode)
        self.assertEqual(b"stdin:" + POST_TOOL, done.stdout)
        self.assertEqual(b"", done.stderr)
        self.assertEqual([sys.executable, "['claude', '9999']"], self.logged())

    def test_the_script_runs_as_the_main_module_so_dataclasses_and_type_hints_resolve(
        self,
    ) -> None:
        script = self.root / "server.py"
        script.write_text(
            "from __future__ import annotations\n"
            "import sys, typing\n"
            "from dataclasses import dataclass, fields\n"
            "from typing import ClassVar\n"
            "@dataclass\n"
            "class A:\n"
            "    x: int = 1\n"
            "    y: ClassVar[int] = 3\n"
            "typing.get_type_hints(A)\n"
            "assert [f.name for f in fields(A)] == ['x']\n"
            "assert sys.modules['__main__'].__file__.endswith('server.py')\n",
            encoding="utf-8",
        )
        done = self.run_launcher(script, assume=None)
        self.assertEqual((0, b""), (done.returncode, done.stderr))

    def test_a_missing_script_exits_2_like_python_does_and_agy_still_gets_its_object(self) -> None:
        done = self.run_launcher(self.root / "nope.py", assume=None)
        self.assertEqual(2, done.returncode)
        self.assertNotIn(b"Traceback", done.stderr)
        done = self.run_launcher(self.root / "agy_hook.py", assume=None)
        self.assertEqual((2, b"{}\n"), (done.returncode, done.stdout))

    def test_someone_on_a_new_python_never_triggers_a_uv_lookup(self) -> None:
        self.finds_this_interpreter()
        self.run_launcher(self.target(), stdin=POST_TOOL, assume=None)
        self.assertFalse(self.uv_log.exists())


class BelowTheFloorWithoutUvTest(LauncherTest):
    def test_someone_whose_python3_is_3_9_sees_the_floor_sentence_once_at_session_start(
        self,
    ) -> None:
        done = self.run_launcher(self.target(), "claude", stdin=SESSION_START)
        self.assertNotEqual(0, done.returncode)
        lines = done.stderr.decode().splitlines()
        self.assertEqual(1, len(lines), lines)
        self.assertIn("Python 3.12 or newer", lines[0])
        self.assertIn(OLD, lines[0])
        self.assertIn(sys.executable, lines[0])
        self.assertIn("uv python install 3.12", lines[0])
        self.assertEqual(b"", done.stdout)
        self.assertFalse(self.log.exists(), "the target must not run on an old interpreter")

    def test_the_sentence_leads_stderr_for_every_harness_that_names_its_start_event_the_same(
        self,
    ) -> None:
        for harness in ("claude", "codex", "gemini", "droid"):
            with self.subTest(harness):
                done = self.run_launcher(self.target(), harness, stdin=SESSION_START)
                self.assertNotEqual(0, done.returncode)
                self.assertTrue(done.stderr.decode().startswith("Compass needs Python 3.12"))

    def test_someone_whose_python3_is_3_9_hears_nothing_on_every_later_event(self) -> None:
        done = self.run_launcher(self.target(), "claude", stdin=POST_TOOL)
        self.assertEqual(0, done.returncode)
        self.assertEqual(b"", done.stderr)
        self.assertEqual(b"", done.stdout)
        self.assertFalse(self.log.exists())

    def test_a_payload_that_is_not_json_is_treated_as_a_later_event(self) -> None:
        for payload in (b"", b"not json", b"[1,2]", b'{"hook_event_name": 3}'):
            with self.subTest(payload):
                done = self.run_launcher(self.target(), "claude", stdin=payload)
                self.assertEqual((0, b""), (done.returncode, done.stderr))

    def test_the_antigravity_hook_never_complains_because_it_has_no_session_start_event(
        self,
    ) -> None:
        done = self.run_launcher(self.target("agy_hook.py"), "PostToolUse", stdin=POST_TOOL)
        self.assertEqual((0, b""), (done.returncode, done.stderr))

    def test_the_antigravity_hook_still_prints_its_empty_object_when_nothing_can_run_it(
        self,
    ) -> None:
        # SECURITY.md: agy_hook.py prints exactly `{}` on every path.
        for payload in (POST_TOOL, SESSION_START, b"", b"not json"):
            with self.subTest(payload):
                done = self.run_launcher(self.target("agy_hook.py"), "PostToolUse", stdin=payload)
                self.assertEqual((0, b"{}\n"), (done.returncode, done.stdout))
        self.fake_uv('echo "/nonexistent/python3.12"')
        done = self.run_launcher(self.target("agy_hook.py"), stdin=POST_TOOL)
        self.assertEqual((0, b"{}\n"), (done.returncode, done.stdout))

    def test_the_mcp_server_and_server_py_say_the_sentence_and_fail_whatever_arrives(self) -> None:
        for name in ("mcp_server.py", "server.py"):
            with self.subTest(name):
                done = self.run_launcher(self.target(name), "--port", "4553", stdin=POST_TOOL)
                self.assertNotEqual(0, done.returncode)
                self.assertTrue(done.stderr.decode().startswith("Compass needs Python 3.12"))
                self.assertFalse(self.log.exists())


@unittest.skipUnless(shutil.which("uv") and os.name == "posix", "needs a real uv and /bin/sh")
class UvDoesNotExecuteTheProjectTest(LauncherTest):
    def test_a_venv_planted_in_or_above_the_working_directory_is_never_run(self) -> None:
        shutil.copy(shutil.which("uv") or "", self.bin / "uv")
        project = self.root / "project"
        venv_bin = project / ".venv" / "bin"
        venv_bin.mkdir(parents=True)
        (project / ".venv" / "pyvenv.cfg").write_text("home = /nowhere\n", encoding="utf-8")
        marker = self.root / "PLANTED_VENV_RAN"
        for name in ("python", "python3"):
            fake = venv_bin / name
            fake.write_text(f"#!/bin/sh\n/usr/bin/touch '{marker}'\nexit 1\n", encoding="utf-8")
            fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
        (project / "uv.toml").write_text('python-preference = "only-system"\n', encoding="utf-8")
        for cwd in (project, project / "deeper"):
            cwd.mkdir(exist_ok=True)
            with self.subTest(cwd=cwd.name):
                self.run_launcher(self.target(), stdin=POST_TOOL, cwd=cwd)
                self.assertFalse(marker.exists(), "uv executed a file from the project tree")


class BelowTheFloorWithUvTest(LauncherTest):
    def test_someone_with_uv_and_a_new_python_installed_has_the_hook_run_there_unchanged(
        self,
    ) -> None:
        self.finds_this_interpreter()
        done = self.run_launcher(self.target(), "claude", "9999", stdin=SESSION_START, exit_code=3)
        self.assertEqual(3, done.returncode)
        self.assertEqual(b"stdin:" + SESSION_START, done.stdout)
        self.assertEqual(b"", done.stderr)
        self.assertEqual([sys.executable, "['claude', '9999']"], self.logged())

    def test_the_uv_lookup_cannot_download_or_read_the_project(self) -> None:
        self.finds_this_interpreter()
        self.run_launcher(self.target(), stdin=POST_TOOL)
        asked = self.uv_log.read_text(encoding="utf-8").split()
        self.assertEqual(["python", "find"], asked[:2])
        self.assertIn("--no-python-downloads", asked)
        self.assertIn("--no-project", asked)
        self.assertIn("--no-config", asked, "a project's uv.toml is repository-controlled")
        self.assertIn("--system", asked, "without it uv executes a .venv found in or above cwd")
        self.assertIn(">=3.12", asked)
        self.assertNotIn("run", asked, "`uv run` would create a .venv in the user's project")

    def test_a_later_event_with_uv_is_forwarded_too(self) -> None:
        self.finds_this_interpreter()
        done = self.run_launcher(self.target(), "codex", stdin=POST_TOOL)
        self.assertEqual(b"stdin:" + POST_TOOL, done.stdout)

    def test_the_mcp_server_keeps_its_stdin_when_uv_finds_a_python(self) -> None:
        self.finds_this_interpreter()
        done = self.run_launcher(self.target("mcp_server.py"), stdin=b'{"jsonrpc":"2.0"}\n')
        self.assertEqual(b'stdin:{"jsonrpc":"2.0"}\n', done.stdout)

    def test_uv_that_finds_nothing_leaves_someone_with_the_sentence(self) -> None:
        self.fake_uv("exit 2")
        done = self.run_launcher(self.target(), stdin=SESSION_START)
        self.assertNotEqual(0, done.returncode)
        self.assertTrue(done.stderr.decode().startswith("Compass needs Python 3.12"))
        self.assertFalse(self.log.exists())

    def test_uv_that_prints_a_path_that_does_not_exist_leaves_someone_with_the_sentence(
        self,
    ) -> None:
        self.fake_uv('echo "/nonexistent/python3.12"')
        done = self.run_launcher(self.target(), stdin=SESSION_START)
        self.assertNotEqual(0, done.returncode)
        self.assertTrue(done.stderr.decode().startswith("Compass needs Python 3.12"))

    def test_a_uv_that_hangs_is_abandoned(self) -> None:
        # The uv here sleeps 30 s, so a launcher that waited for it outlives the 20 s limit and
        # fails. That limit only tells abandoned from waited; the budget is the test below. The
        # sleep is named by path: the launcher's PATH is the fixture's bin alone, and a bare
        # `sleep` there was not found, so the uv this test meant to hang exited at once.
        sleep = shutil.which("sleep")
        assert sleep is not None
        self.fake_uv(f"exec {sleep} 30")
        done = self.run_launcher(self.target(), stdin=SESSION_START, timeout=20)
        self.assertNotEqual(0, done.returncode)
        self.assertTrue(done.stderr.decode().startswith("Compass needs Python 3.12"))

    def test_the_uv_lookup_is_bounded_well_inside_a_hooks_five_second_budget(self) -> None:
        # Decided on the bound handed to the lookup, not on a stopwatch round a cold interpreter,
        # which on a loaded runner measures the runner.
        spec = importlib.util.spec_from_file_location("compass_launch_under_test", LAUNCHER)
        assert spec is not None
        assert spec.loader is not None
        launch = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(launch)
        seen: list[object] = []

        def run(*_args: object, **kwargs: object) -> object:
            seen.append(kwargs.get("timeout"))
            raise subprocess.TimeoutExpired("uv", 0)

        with (
            mock.patch.object(shutil, "which", return_value="/opt/uv"),
            mock.patch.object(subprocess, "run", run),
        ):
            self.assertIsNone(launch.find_new_python())
        self.assertEqual([launch.UV_TIMEOUT_SECONDS], seen)
        self.assertLessEqual(launch.UV_TIMEOUT_SECONDS, 2)

    @unittest.skipUnless(os.name == "posix", "process groups")
    def test_ctrl_c_lets_a_server_that_needs_a_second_to_shut_down_finish_cleanly(self) -> None:
        self.finds_this_interpreter()
        ready, done_mark = self.root / "ready", self.root / "shut-down"
        script = self.root / "server.py"
        script.write_text(
            "import signal, sys, time\n"
            "def stop(*_):\n"
            "    time.sleep(1)\n"
            f"    open({str(done_mark)!r}, 'w').close()\n"
            "    sys.exit(0)\n"
            "signal.signal(signal.SIGINT, stop)\n"
            f"open({str(ready)!r}, 'w').close()\n"
            "time.sleep(60)\n",
            encoding="utf-8",
        )
        proc = subprocess.Popen(
            [sys.executable, str(LAUNCHER), str(script)],
            env={"PATH": str(self.bin), "HOME": str(self.root), SEAM: OLD},
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
        # Two interpreters and a shell start before `ready`; a busy runner can take seconds.
        deadline = time.monotonic() + 30
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertTrue(ready.exists(), "the server never installed its handler")
        os.killpg(proc.pid, signal.SIGINT)
        stderr = proc.communicate(timeout=30)[1]
        self.assertEqual(0, proc.returncode, stderr)
        self.assertTrue(done_mark.exists(), "the child was killed instead of shutting down")
        self.assertNotIn(b"Traceback", stderr)

    @unittest.skipIf(sys.platform == "win32", "Windows has no SIGTERM to forward")
    def test_stopping_the_launcher_on_an_old_python_also_stops_the_script_it_started(self) -> None:
        self.finds_this_interpreter()
        pid_file = self.root / "child.pid"
        script = self.root / "server.py"
        script.write_text(
            "import os, time\n"
            f"open({str(pid_file)!r}, 'w').write(str(os.getpid()))\n"
            "time.sleep(60)\n",
            encoding="utf-8",
        )
        proc = subprocess.Popen(
            [sys.executable, str(LAUNCHER), str(script)],
            env={"PATH": str(self.bin), "HOME": str(self.root), SEAM: OLD},
            stderr=subprocess.PIPE,
        )
        child_pid = 0
        try:
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                if pid_file.exists() and pid_file.read_text(encoding="utf-8"):
                    child_pid = int(pid_file.read_text(encoding="utf-8"))
                    break
                time.sleep(0.05)
            self.assertTrue(child_pid, "the script never started")
            proc.send_signal(signal.SIGTERM)  # the launcher alone, not its process group
            proc.wait(timeout=30)
            gone = False
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                try:
                    os.kill(child_pid, 0)
                except ProcessLookupError:
                    gone = True
                    break
                time.sleep(0.05)
            self.assertTrue(gone, "the script outlived the launcher")
            self.assertEqual(-signal.SIGTERM, proc.returncode)  # as if it had been exec'd
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()
            if child_pid:
                with contextlib.suppress(ProcessLookupError):
                    os.kill(child_pid, signal.SIGKILL)
            if proc.stderr:
                proc.stderr.close()

    @unittest.skipIf(sys.platform == "win32", "Windows has no signal exit status")
    def test_a_script_killed_with_sigkill_leaves_the_launcher_dying_of_it_with_no_traceback(
        self,
    ) -> None:
        self.finds_this_interpreter()
        script = self.root / "server.py"
        script.write_text(
            "import os, signal\nos.kill(os.getpid(), signal.SIGKILL)\n", encoding="utf-8"
        )
        done = self.run_launcher(script)
        self.assertEqual(-signal.SIGKILL, done.returncode, done.stderr)
        self.assertNotIn(b"Traceback", done.stderr)


@unittest.skipUnless(
    SYSTEM_PYTHON.exists()
    and subprocess.run(
        [str(SYSTEM_PYTHON), "-c", "import sys;sys.exit(sys.version_info >= (3, 12))"],
        check=False,
    ).returncode
    == 0,
    "needs a system python3 older than 3.12 at /usr/bin/python3",
)
class OnARealOldInterpreterTest(LauncherTest):
    def test_someone_with_a_real_old_python3_sees_the_sentence_with_no_seam_set(self) -> None:
        done = self.run_launcher(
            self.target(), "claude", stdin=SESSION_START, assume=None, python=str(SYSTEM_PYTHON)
        )
        self.assertNotEqual(0, done.returncode)
        lines = done.stderr.decode().splitlines()
        self.assertEqual(1, len(lines), lines)
        self.assertIn("Python 3.12 or newer", lines[0])
        self.assertIn("3.9", lines[0])

    def test_someone_with_a_real_old_python3_and_uv_gets_the_hook_run_by_the_interpreter_uv_found(
        self,
    ) -> None:
        self.finds_this_interpreter()
        done = self.run_launcher(
            self.target(), "claude", stdin=POST_TOOL, assume=None, python=str(SYSTEM_PYTHON)
        )
        self.assertEqual(0, done.returncode, done.stderr)
        self.assertEqual(b"stdin:" + POST_TOOL, done.stdout)
        self.assertEqual(sys.executable, self.logged()[0])


class EveryEntryPointGoesThroughTheLauncherTest(unittest.TestCase):
    HOOK_FILES = (
        PLUGIN_ROOT / "hooks" / "hooks.json",
        PLUGIN_ROOT / "hooks" / "codex-hooks.json",
        PLUGIN_ROOT / "hooks.json",
        REPO / "compass-gemini" / "hooks" / "hooks.json",
        REPO / "compass-droid" / "hooks" / "hooks.json",
    )

    def commands(self, node: object) -> list[str]:
        if isinstance(node, dict):
            found = [node["command"]] if isinstance(node.get("command"), str) else []
            for value in node.values():
                found.extend(self.commands(value))
            return found
        if isinstance(node, list):
            return [c for item in node for c in self.commands(item)]
        return []

    def test_every_hook_command_in_every_plugin_root_starts_the_launcher_first(self) -> None:
        for path in self.HOOK_FILES:
            commands = self.commands(json.loads(path.read_text(encoding="utf-8")))
            self.assertTrue(commands, path)
            for command in commands:
                with self.subTest(path=path.name, command=command):
                    self.assertRegex(command, r'^python3 "[^"]*/launch\.py" "[^"]*\.py" ')

    def test_the_mcp_server_starts_through_the_launcher(self) -> None:
        manifest = json.loads(
            (PLUGIN_ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8")
        )
        server = manifest["mcpServers"]["compass"]
        self.assertEqual("python3", server["command"])
        self.assertEqual(
            [
                "${CLAUDE_PLUGIN_ROOT}/skills/compass/launch.py",
                "${CLAUDE_PLUGIN_ROOT}/skills/compass/mcp_server.py",
            ],
            server["args"],
        )

    def test_no_other_manifest_declares_a_python_mcp_command(self) -> None:
        for path in REPO.glob("compass*/**/*.json"):
            if "node_modules" in path.parts or "web" in path.parts:
                continue
            text = path.read_text(encoding="utf-8")
            if "mcp_server.py" in text and path.name != "plugin.json":
                self.fail(f"{path} names mcp_server.py without the launcher")

    def test_the_documented_server_start_goes_through_the_launcher(self) -> None:
        text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn('python3 "<skill-dir>/launch.py" "<skill-dir>/server.py"', text)


if __name__ == "__main__":
    unittest.main()
