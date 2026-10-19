"""The committed sample session and its fixture: nothing private, and nothing broken.

These run on the files in the repository, so a regeneration that lets a leak through, or breaks the
chain of records, fails here before it is reviewed.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
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


def git(*args: str) -> str | None:
    """The repository's own git output, or None when there is no history to ask."""
    if not shutil.which("git"):
        return None
    result = subprocess.run(
        ["git", "-C", str(ROOT), *args],  # noqa: S607
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout if result.returncode == 0 else None


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

    def test_no_quoted_hash_names_a_commit_in_this_repository(self) -> None:
        # A commit's date and time zone are public, so one resolving hash undoes the time shift.
        if git("rev-parse", "--verify", "HEAD") is None:
            self.skipTest("no git history to resolve hashes against")
        for path in SESSIONS:
            with self.subTest(file=path.name):
                text = path.read_text(encoding="utf-8")
                self.assertEqual({}, ss.resolving_commits(text, ROOT))

    def test_the_milestone_names_no_branch_from_this_repository(self) -> None:
        branches = {str(r["gitBranch"]) for r in self.records(MILESTONE) if r.get("gitBranch")}
        self.assertEqual(
            set(), {b for b in branches if not re.fullmatch(r"main|work/branch-[a-z]", b)}
        )
        refs = git("for-each-ref", "--format=%(refname:lstrip=2)", "refs/heads", "refs/remotes")
        if refs is None:
            self.skipTest("no git history to compare branch names against")
        known = {ref.split("/", 1)[1] if ref.startswith("origin/") else ref for ref in refs.split()}
        self.assertEqual(set(), (branches - {"main"}) & known)

    def test_the_project_key_is_the_hash_of_the_samples_own_path(self) -> None:
        # The key is an unsalted hash of the repository path (sessions._project_identity_key), so
        # the real path's key would confirm the real path to anyone who guessed it.
        records = self.records(MILESTONE)
        cwds = {r["cwd"] for r in records if r.get("cwd")}
        own = {hashlib.blake2b(c.encode(), digest_size=12).hexdigest() for c in cwds}
        keys = set(re.findall(r"git:([0-9a-f]{24})", MILESTONE.read_text(encoding="utf-8")))
        self.assertTrue(keys)
        self.assertEqual(set(), keys - own)

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
