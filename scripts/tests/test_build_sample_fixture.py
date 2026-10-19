"""The fixture builder's rewrites: they make a capture read the same on any day."""

from __future__ import annotations

import json
import re
import sys
import unittest
import urllib.parse
from pathlib import Path
from typing import Any
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import build_sample_fixture as bf

CAPTURED = 1_790_000_000.0


class RewriteTest(unittest.TestCase):
    def test_a_time_near_the_capture_moves_and_a_far_one_does_not(self) -> None:
        moved = bf.shift_numbers({"near": CAPTURED - 60, "far": CAPTURED - 86400}, CAPTURED, 1000)
        self.assertEqual({"near": CAPTURED - 1060, "far": CAPTURED - 86400}, moved)

    def test_small_numbers_and_booleans_are_left_alone(self) -> None:
        node = {"count": 7, "flag": True, "nested": [3, {"n": 1.5}]}
        self.assertEqual(node, bf.shift_numbers(node, CAPTURED, 1000))

    def test_the_session_id_is_renamed_in_keys_and_values(self) -> None:
        node = {"f7352072": ["claude:f7352072", {"sid": "f7352072"}]}
        self.assertEqual(
            {"sample": ["claude:sample", {"sid": "sample"}]},
            bf.rename(node, "f7352072", "sample"),
        )

    def test_a_duration_reads_in_the_servers_short_form(self) -> None:
        self.assertEqual(
            ["45s", "11m", "2h 5m", "3d 4h"],
            [
                bf.fmt_duration(s)
                for s in (45, 11 * 60 + 20, 2 * 3600 + 5 * 60, 3 * 86400 + 4 * 3600)
            ],
        )

    def test_the_last_record_is_the_latest_fact_time(self) -> None:
        context = {"semantic": {"facts": [{"at": 5}, {"at": 9.5}, {"at": None}, {}]}}
        self.assertEqual(9.5, bf.last_record_time(context))


class RecordPagesTest(unittest.TestCase):
    """The capture reads every record page back to the start, and keeps nothing of the server's cursors."""

    def serve(self, pages: list[dict[str, Any]]) -> list[str]:
        asked: list[str] = []
        cursors = {f"signed-{i}": page for i, page in enumerate(pages[1:], 1)}

        def fetch(_base: str, path: str, _body: object = None) -> dict[str, Any]:
            asked.append(path)
            before = urllib.parse.parse_qs(urllib.parse.urlsplit(path).query).get("before")
            return dict(cursors[before[0]] if before else pages[0])

        patcher = mock.patch.object(bf, "fetch", fetch)
        patcher.start()
        self.addCleanup(patcher.stop)
        return asked

    @staticmethod
    def page(n: int, *, last: bool) -> dict[str, Any]:
        return {
            "state": "ok",
            "entries": [{"fact_id": f"fact:{n}"}],
            "reached_start": last,
            "next": None if last else f"signed-{n + 1}",
        }

    def test_every_older_page_is_captured_under_a_cursor_of_its_own(self) -> None:
        asked = self.serve(
            [self.page(0, last=False), self.page(1, last=False), self.page(2, last=True)]
        )
        newest, older = bf.capture_record("http://x", "project=p&session=s")
        self.assertEqual(3, len(asked))
        self.assertTrue(all("limit=50" in path for path in asked))
        self.assertEqual("older-1", newest["next"])
        self.assertEqual(["older-1", "older-2"], list(older))
        self.assertEqual("older-2", older["older-1"]["next"])
        self.assertIsNone(older["older-2"]["next"])
        self.assertNotIn("signed", json.dumps([newest, older]))

    def test_a_one_page_record_has_no_older_pages(self) -> None:
        self.serve([self.page(0, last=True)])
        newest, older = bf.capture_record("http://x", "s")
        self.assertEqual({}, older)
        self.assertIsNone(newest["next"])

    def test_a_record_longer_than_the_page_can_resolve_is_refused(self) -> None:
        pages = [self.page(n, last=False) for n in range(bf.RECORD_MAX_PAGES + 1)]
        self.serve(pages)
        with self.assertRaises(SystemExit):
            bf.capture_record("http://x", "s")

    def test_a_page_that_is_not_ok_is_refused(self) -> None:
        self.serve([{**self.page(0, last=False), "state": "stale"}])
        with self.assertRaises(SystemExit):
            bf.capture_record("http://x", "s")


class PageConstantsTest(unittest.TestCase):
    def test_the_capture_reads_pages_the_way_the_page_does(self) -> None:
        source = (
            Path(__file__).resolve().parents[2] / "frontend" / "src" / "transport" / "record.ts"
        ).read_text(encoding="utf-8")

        def exported(name: str) -> int:
            match = re.search(rf"^export const {name} = (\d+);", source, re.MULTILINE)
            self.assertIsNotNone(match, name)
            return int(match.group(1)) if match else 0

        self.assertEqual(
            (exported("RECORD_PAGE_SIZE"), exported("RESOLVE_MAX_PAGES")),
            (bf.RECORD_PAGE_SIZE, bf.RECORD_MAX_PAGES),
        )


if __name__ == "__main__":
    unittest.main()
