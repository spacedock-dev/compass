"""The migration inventory follows shipped behavior throughout the refactor."""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]


class AContributorCannotForgetAnExistingReaderContractTest(unittest.TestCase):
    def test_every_shipped_part_and_reader_state_has_a_migration_owner(self) -> None:
        # Keep this dependency visible to the docs-only gate's literal inventory.
        self.assertTrue((ROOT / "docs/design-reader-state.md").is_file())
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts/frontend_inventory.py")],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(0, result.returncode, result.stderr)


class TheLiveMonitorDeparturesAreRecordedAndTheGoldensAreNot(unittest.TestCase):
    """The switch's new hint and dropped key depart from two recordings, which are never re-recorded."""

    def test_both_departures_are_recorded_in_the_design_record(self) -> None:
        text = (ROOT / "docs/design-frontend-migration.md").read_text(encoding="utf-8")
        section = text.split("## Held to recorded answers", 1)[1].split("\n## ", 1)[0]
        entry = section.split("2026-10-23, the Live monitor switch drives a lease", 1)[1].split(
            "\n\n2026-", 1
        )[0]
        for named in (
            "frontend/test/golden/e2e/drift-parity.json",
            "frontend/test/golden/e2e/storage-conformance.json",
            "compass.next.live-estimate:",
            "no model call",
        ):
            self.assertIn(named, entry)

    def test_neither_golden_was_re_recorded(self) -> None:
        golden = ROOT / "frontend/test/golden/e2e"
        self.assertIn("with no model call", (golden / "drift-parity.json").read_text("utf-8"))
        # The recording spells the family with the prefix the page had when it was recorded.
        self.assertIn(
            "next.live-estimate:", (golden / "storage-conformance.json").read_text("utf-8")
        )

    def test_the_retired_key_is_no_longer_a_storage_family_the_codec_owns(self) -> None:
        keys = (ROOT / "frontend/src/storage/keys.ts").read_text(encoding="utf-8")
        self.assertNotIn("live-estimate", keys)


if __name__ == "__main__":
    unittest.main()
