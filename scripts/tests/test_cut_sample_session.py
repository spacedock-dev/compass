"""Cutting a sample's stretch out of a session: the right records, and a chain that stays whole."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cut_sample_session as cut


def rec(uuid: str, parent: str | None, kind: str = "user", **extra: Any) -> dict[str, Any]:
    return {"type": kind, "uuid": uuid, "parentUuid": parent, **extra}


RECORDS = [
    rec("a", None),
    rec("b", "a", "assistant"),
    rec("c", "b", "attachment"),
    rec("d", "c", "user"),
    {"type": "bridge-session", "sessionId": "s"},
    rec("e", "d", "system", subtype="stop_hook_summary"),
    rec("f", "e", "assistant"),
    rec("g", "f", "system", subtype="compact_boundary"),
    {"type": "pr-link", "prNumber": "1"},
    rec("h", "g", "assistant"),
]


class CutTest(unittest.TestCase):
    def test_it_keeps_the_stretch_and_only_the_kinds_the_page_reads(self) -> None:
        out = cut.cut(RECORDS, "b", "h")
        self.assertEqual(["b", "d", "f", "g", None, "h"], [record.get("uuid") for record in out])

    def test_a_record_whose_parent_was_dropped_joins_the_nearest_kept_ancestor(self) -> None:
        out = {record.get("uuid"): record for record in cut.cut(RECORDS, "b", "h")}
        self.assertEqual("b", out["d"]["parentUuid"])
        self.assertEqual("d", out["f"]["parentUuid"])
        self.assertEqual("g", out["h"]["parentUuid"])

    def test_the_first_record_keeps_its_parent_before_the_cut_for_the_sanitizer_to_null(
        self,
    ) -> None:
        self.assertEqual("a", cut.cut(RECORDS, "b", "h")[0]["parentUuid"])

    def test_it_refuses_an_unknown_or_reversed_range(self) -> None:
        with self.assertRaises(SystemExit):
            cut.cut(RECORDS, "b", "zz")
        with self.assertRaises(SystemExit):
            cut.cut(RECORDS, "h", "b")


if __name__ == "__main__":
    unittest.main()
