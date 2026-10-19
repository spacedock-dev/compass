"""The committed sample session and its fixture: nothing private, and nothing broken.

These run on the files in the repository, so a regeneration that lets a leak through, or breaks the
chain of records, fails here before it is reviewed.
"""

from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import sanitize_session as ss

ROOT = Path(__file__).resolve().parents[2]
SESSION = ROOT / "sample-session" / "example-session.jsonl"
# The longer session the next sample is made from (sample-session/README.md). It is held to the same
# checks from the day it is committed, before the page draws it.
MILESTONE = ROOT / "sample-session" / "milestone-session.jsonl"
SESSIONS = (SESSION, MILESTONE)
FIXTURE = ROOT / "frontend" / "src" / "sample" / "session.fixture.json"
README = ROOT / "sample-session" / "README.md"


class SampleSessionFilesTest(unittest.TestCase):
    def records(self, path: Path = SESSION) -> list[dict[str, Any]]:
        return [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def test_every_line_is_json_and_every_reference_resolves(self) -> None:
        for path in SESSIONS:
            with self.subTest(file=path.name):
                self.assert_references_resolve(self.records(path))

    def assert_references_resolve(self, records: list[dict[str, Any]]) -> None:
        uuids = {r["uuid"] for r in records if r.get("uuid")}
        for key in ss.REFERENCE_KEYS:
            for record in records:
                value = record.get(key)
                if value:
                    self.assertIn(value, uuids, key)
        uses, results = set(), set()
        for record in records:
            content = (record.get("message") or {}).get("content")
            for block in content if isinstance(content, list) else []:
                if block.get("type") == "tool_use":
                    uses.add(block["id"])
                if block.get("type") == "tool_result":
                    results.add(block["tool_use_id"])
        self.assertEqual(set(), results - uses)

    def test_it_is_one_session_with_no_thinking_and_one_root(self) -> None:
        for path in SESSIONS:
            with self.subTest(file=path.name):
                records = self.records(path)
                self.assertEqual(1, len({r["sessionId"] for r in records if r.get("sessionId")}))
                self.assertEqual(
                    1,
                    sum(
                        1
                        for r in records
                        if r.get("type") in {"user", "assistant"} and r.get("parentUuid") is None
                    ),
                )
                blob = path.read_text(encoding="utf-8")
                self.assertNotIn('"type":"thinking"', blob)
                self.assertNotIn('"type":"base64"', blob)

    def test_neither_file_matches_a_shape_of_a_leak(self) -> None:
        for path in (*SESSIONS, FIXTURE, README):
            text = path.read_text(encoding="utf-8")
            for label, pattern in ss.SWEEPS.items():
                with self.subTest(file=path.name, sweep=label):
                    self.assertEqual([], [m.group(0)[:50] for m in pattern.finditer(text)][:3])

    def test_the_only_identity_is_the_placeholder_one(self) -> None:
        placeholders = {SESSION: {"dev@example.com"}, MILESTONE: {"user@example.com"}}
        for path, emails in placeholders.items():
            with self.subTest(file=path.name):
                text = path.read_text(encoding="utf-8")
                # An address has a domain with a letter in it; `runner@4.1.11` is a package version.
                found = {
                    m
                    for m in re.findall(r"[\w.+-]+@[\w.-]+\.\w+", text)
                    if re.search(r"@.*[A-Za-z]", m)
                }
                self.assertEqual(emails, found)
                self.assertEqual({"/Users/dev"}, set(re.findall(r"/Users/[A-Za-z0-9._-]+", text)))

    def test_the_fixture_is_the_one_sample_session_at_its_own_id(self) -> None:
        fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
        rows = fixture["board"]["sessions"]
        self.assertEqual([("claude", "sample")], [(r["harness"], r["sid"]) for r in rows])
        blob = FIXTURE.read_text(encoding="utf-8")
        self.assertNotRegex(
            blob, r"\b17[89]\d{7}\.\d"
        )  # no wall-clock times from the day it was captured
        self.assertEqual(
            "high", fixture["context"]["sources"]["work"]["analysis_levels"][0]["level"]
        )
        self.assertEqual("high", fixture["context"]["sources"]["work"]["live_levels"][0]["level"])
        self.assertTrue(fixture["correction"]["ok"])

    def test_the_readme_says_what_was_changed_and_what_was_not(self) -> None:
        text = README.read_text(encoding="utf-8")
        for required in ("anonymized", "illustration", "shaping.json", "not a byte-for-byte"):
            self.assertIn(required, text)


if __name__ == "__main__":
    unittest.main()
