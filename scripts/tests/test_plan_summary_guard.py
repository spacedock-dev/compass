"""The session summary hook starts no program, opens no socket and writes nothing.

It lives here rather than beside the dashboard's security tests because it watches the hook with a
Python audit hook, and no shipped file may name one (`test_owned_observer`).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "compass" / "skills" / "compass"
# The dashboard tests are the `tests` package under the skill folder, the name mypy gives them.
sys.path.insert(0, str(ROOT))

from tests.support import make_config  # noqa: E402
from tests.test_history import stub_application  # noqa: E402
from tests.test_plan_publish import request  # noqa: E402
from tests.test_plan_readers import PlanRepoTestCase  # noqa: E402
from tests.test_project_script_checks import GIT  # noqa: E402


@unittest.skipIf(GIT is None or os.name == "nt", "Needs Git and POSIX directory descriptors")
class PlanSummaryPrimitiveTest(PlanRepoTestCase):
    def test_summary_spawns_nothing_opens_no_socket_and_writes_nothing(self) -> None:

        # Committed sources and Git on PATH, so a summary that ran Git could.
        self.write_sources(
            {
                "goals": "## Goals\n- G1: Float the model\n",
                "tracker": "| Item | Lane | Status |\n| --- | --- | --- |\n| Hull | hull | fixed |\n",
            }
        )
        self.configure(summary={"enabled": True}, tracker={"lane_column": "Lane"})
        (self.briefs / "hull.md").write_text(
            "## Goal\nFloat the model.\n\n*Serves*: G1\n", encoding="utf-8"
        )
        config = make_config(state_home=str(self.home), state_dir=self.home)
        self.assertEqual(request(stub_application(config, [], []))[0], 200)
        uv = self.root / "uv"
        uv.touch()
        uv.chmod(0o700)
        guard = """
import os
import sys

def watch(event, args):
    write = event == "open" and args[2] & (os.O_WRONLY | os.O_RDWR | os.O_CREAT)
    if write or event.startswith("socket.") or event in {
        "subprocess.Popen", "os.exec", "os.fork", "os.mkdir",
        "os.posix_spawn", "os.remove", "os.rename", "os.system",
    }:
        print(f"Plan summary attempted {event}", file=sys.stderr)
        raise RuntimeError(event)

sys.pycache_prefix = sys.argv.pop(1)
sys.argv = sys.argv[1:]
with open(sys.argv[0], "rb") as launcher:
    code = compile(launcher.read(), sys.argv[0], "exec")
sys.addaudithook(watch)
exec(code, {"__name__": "__main__", "__file__": sys.argv[0]})
"""
        for version, delivers in (("3.12", True), ("3.11", False)):
            with self.subTest(version=version):
                result = subprocess.run(
                    [
                        sys.executable,
                        "-c",
                        guard,
                        str(self.root / "pycache"),
                        str(ROOT / "launch.py"),
                        str(ROOT / "plan_summary_hook.py"),
                    ],
                    env={
                        **os.environ,
                        "COMPASS_LAUNCH_ASSUME_PYTHON": version,
                        "COMPASS_HOME": str(self.home),
                        "COMPASS_LANE": "hull",
                        "PATH": os.pathsep.join((str(self.root), os.path.dirname(str(GIT)))),
                    },
                    input=json.dumps(
                        {"hook_event_name": "SessionStart", "cwd": str(self.hull)}
                    ).encode(),
                    capture_output=True,
                    timeout=10,
                    check=False,
                )
                self.assertEqual((result.returncode, result.stderr), (0, b""))
                if delivers:
                    self.assertIn(b"Float the model.", result.stdout)
                    self.assertIn(b"Lane state: Done", result.stdout)
                else:
                    self.assertEqual(result.stdout, b"")
