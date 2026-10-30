"""The qualification study's private state stays in the home it was written to.

The rename moved the default store to `~/.compass` and left every ledger, epoch and
packet of the Claude Code qualification under `~/.cargento`. A ledger path that
followed the default home read an empty ledger there: a fork, refused only because the
committed chain no longer matched. The study's ledgers are pinned to their fixed path
instead, and an absent one still fails closed. Each child process gets a synthetic
account home from a patched password database, so nothing here reads the real one.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]

CHILD = r"""
import json, os, pwd, sys, types
scripts, canonical = sys.argv[1:]
sys.path.insert(0, scripts)
pwd.getpwuid = lambda _uid: types.SimpleNamespace(pw_dir=canonical, pw_name='synthetic_account')
import abstention_ledger as ledger
import analyze_campaign as campaign
import drift_replay as replay
import mark_abstention as marker
import claude_route_verification as route
committed = {'first': 'f' * 32, 'calls': 68, 'head': 'a' * 64}
decoy = os.path.join(canonical, '.compass', 'drc-4666-spend.json')
before = open(decoy, 'rb').read() if os.path.exists(decoy) else None
try:
    native = ledger.read(ledger.LEDGER_PATH)['calls']
    read_error = ''
except ledger.LedgerError as error:
    native, read_error = None, str(error)
print(json.dumps({
    'native': ledger.LEDGER_PATH,
    'shared': campaign.LEDGER_PATH,
    'qualification': campaign.QUALIFICATION_PATH,
    'replay': campaign.REPLAY_PATH,
    'replay_ledger': replay.LEDGER_PATH,
    'store_home': marker.STORE_HOME,
    'route_state': str(route.STATE_PATH),
    'route_private': str(route.PRIVATE_DIR),
    'route_activation': str(route.ACTIVATION_PATH),
    'native_calls': native,
    'read_error': read_error,
    'begins_with_committed': ledger.begins_with(ledger.LEDGER_PATH, committed),
    'decoy_unchanged': before == (open(decoy, 'rb').read() if os.path.exists(decoy) else None),
}))
"""


def _ledger(calls: int) -> dict[str, Any]:
    return {
        "v": 1,
        "calls": [
            {
                "id": f"{n:032x}",
                "at": 1.0,
                "case": "0" * 16,
                "producer": "claude",
                "status": "ok",
                "marks_digest": "b" * 64,
                "inputs_digest": "c" * 64,
            }
            for n in range(calls)
        ],
        "runs": [],
    }


@unittest.skipIf(os.name == "nt", "the account home comes from pwd, POSIX only")
class StudyLedgersArePinnedToTheirHomeTest(unittest.TestCase):
    def child(self, canonical: Path, **environ: str) -> dict[str, Any]:
        result = subprocess.run(
            [sys.executable, "-B", "-c", CHILD, str(ROOT / "scripts"), str(canonical)],
            cwd=canonical,
            env={**os.environ, "HOME": str(canonical), "PYTHONDONTWRITEBYTECODE": "1", **environ},
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        observed: dict[str, Any] = json.loads(result.stdout.strip().splitlines()[-1])
        return observed

    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="study-home-")
        self.addCleanup(temporary.cleanup)
        self.canonical = Path(temporary.name, "account").resolve()
        self.canonical.mkdir()

    def test_every_study_ledger_is_under_the_fixed_study_home(self) -> None:
        study = self.canonical / ".cargento"
        observed = self.child(self.canonical, COMPASS_HOME=str(self.canonical / "packet"))
        self.assertEqual(str(study / "drc-4666-spend.json"), observed["native"])
        self.assertEqual(observed["native"], observed["qualification"])
        self.assertEqual(str(study / "analyze-closure-spend.json"), observed["shared"])
        self.assertEqual(str(study / "drift-replay" / "spend.json"), observed["replay"])
        self.assertEqual(observed["replay"], observed["replay_ledger"])
        # The freeze still reads the live dashboard store, where new sessions are observed.
        self.assertEqual(str(self.canonical / ".compass"), observed["store_home"])

    def test_neither_home_nor_the_store_override_moves_them(self) -> None:
        moved = self.child(
            self.canonical,
            HOME=str(self.canonical / "elsewhere"),
            COMPASS_HOME=str(self.canonical / ".compass"),
        )
        # The route ledger and its activation receipt belong to the same study.
        for key in (
            "native",
            "shared",
            "replay",
            "replay_ledger",
            "route_state",
            "route_private",
            "route_activation",
        ):
            with self.subTest(key=key):
                self.assertTrue(moved[key].startswith(str(self.canonical / ".cargento")), moved)

    def test_an_absent_study_home_fails_closed_and_never_reads_the_compass_home(self) -> None:
        # A populated ledger in the default home is exactly the fork the pin closes:
        # it must be neither read nor written, and the study must refuse as today.
        decoy = self.canonical / ".compass" / "drc-4666-spend.json"
        decoy.parent.mkdir()
        decoy.write_text(json.dumps(_ledger(68)))
        observed = self.child(self.canonical)
        self.assertEqual([], observed["native_calls"], observed)
        self.assertIs(False, observed["begins_with_committed"])
        self.assertIs(True, observed["decoy_unchanged"])
        self.assertFalse((self.canonical / ".cargento").exists())

    def test_an_unreadable_study_ledger_refuses_rather_than_reading_as_empty(self) -> None:
        study = self.canonical / ".cargento"
        study.mkdir()
        (study / "drc-4666-spend.json").write_text("{not json")
        observed = self.child(self.canonical)
        self.assertIsNone(observed["native_calls"])
        self.assertIn("cannot be read", observed["read_error"])
        self.assertIs(False, observed["begins_with_committed"])

    def test_the_study_home_ledger_is_the_one_read(self) -> None:
        study = self.canonical / ".cargento"
        study.mkdir()
        (study / "drc-4666-spend.json").write_text(json.dumps(_ledger(3)))
        observed = self.child(self.canonical)
        self.assertEqual(3, len(observed["native_calls"]))


if __name__ == "__main__":
    unittest.main()
