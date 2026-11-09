"""A person can inspect candidate metadata without disclosing session words."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from typing import TYPE_CHECKING, Any
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import codex_case_candidates as candidates

if TYPE_CHECKING:
    from tests.codex_source_support import ROOT, rollout
else:
    from codex_source_support import ROOT, rollout


class CandidatePrivacyTest(unittest.TestCase):
    def test_a_person_sees_each_first_line_size_and_whether_it_is_session_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = rollout(Path(folder))
            head = json.loads(path.read_text().splitlines()[0])
            head["payload"]["cwd"] = "PRIVATE-MARKER" + "x" * 70000
            for body, parses in (
                (json.dumps(head) + "\n", True),
                ("", False),
                ("PRIVATE-MARKER not-json\n", False),
                ('{"type":"legacy"}\n', False),
            ):
                with self.subTest(parses=parses, size=len(body)):
                    path.write_text(body)
                    row = candidates.inventory(Path(folder))[0]
                    self.assertEqual(row["head_bytes"], len(body.encode()))
                    self.assertIs(row["head_is_session_meta"], parses)
                    self.assertNotIn("PRIVATE-MARKER", json.dumps(row))

    def test_a_person_gets_a_closed_refusal_for_malformed_inventory_item_types(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = rollout(Path(folder))
            kinds: tuple[Any, ...] = ([], {"PRIVATE-CONTENT-MARKER": []})
            for kind in kinds:
                with self.subTest(shape=type(kind).__name__):
                    path.write_text(
                        json.dumps(
                            {
                                "type": "event_msg",
                                "payload": {
                                    "type": "item_completed",
                                    "item": {"type": kind},
                                },
                            }
                        )
                        + "\n"
                    )
                    with mock.patch("builtins.print") as printed:
                        self.assertEqual(
                            candidates.main(
                                [
                                    "--root",
                                    folder,
                                    "--output",
                                    str(Path(folder) / "inventory.jsonl"),
                                ]
                            ),
                            1,
                        )
                    self.assertIn("inventory-source-unconfirmed", str(printed.call_args_list))
                    for private in (folder, "PRIVATE-", "Traceback", "TypeError"):
                        self.assertNotIn(private, str(printed.call_args_list))
                    self.assertFalse((Path(folder) / "inventory.jsonl").exists())

    def test_a_person_gets_only_closed_metadata_and_hashed_aliases(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = rollout(Path(folder))
            rows = candidates.inventory(Path(folder))
            self.assertEqual(len(rows), 1)
            row = rows[0]
            self.assertEqual(row["human"], 1)
            self.assertEqual(row["turns"], 1)
            self.assertEqual(row["failed"], 1)
            self.assertTrue(row["fail_then_pass"])
            text = json.dumps(rows)
            for private in (str(path), "Please repair", "pytest", "synthetic/project", "answer-a"):
                self.assertNotIn(private, text)

    def test_a_person_cannot_write_the_inventory_into_the_repository(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            rollout(Path(folder))
            output = ROOT / "docs/screenshots/synthetic-candidate-mutation.json"
            self.addCleanup(output.unlink, missing_ok=True)
            with self.assertRaisesRegex(ValueError, "outside-repository"):
                candidates.inventory(Path(folder), output=output)

    def test_a_person_never_sees_free_form_vendor_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = rollout(Path(folder))
            raw = path.read_text().replace('"cli"', '"PRIVATE-PROJECT-TITLE"')
            path.write_text(raw)
            self.assertNotIn("PRIVATE-PROJECT-TITLE", json.dumps(candidates.summarize_shape(path)))
