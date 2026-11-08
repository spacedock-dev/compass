"""A person gets one shared vocabulary without losing the row's own facts."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from typing import Any

from compass_runtime import annotations as annotation_store
from compass_runtime import (
    footer_lines,
    terminal_client,
    terminal_project,
    terminal_sessions,
)
from compass_runtime.board_explanations import expand

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "scripts"))
import regen_client_fixtures as regen  # noqa: E402 - repository recorder


class BoardExplanationsTest(unittest.TestCase):
    def test_a_person_downloads_shared_words_once_on_a_long_history(self) -> None:
        scratch = regen.Scratch()
        self.addCleanup(scratch.close)
        rows = [
            regen.synthetic_row(
                "claude",
                f"{n:08x}",
                "synthetic-history",
                title=f"Synthetic task {n}",
                age=90000 + n,
            )
            for n in range(3750)
        ]
        with regen.guarded():
            rig = regen.Rig(scratch, "long-history", rows={"claude": rows})
            self.addCleanup(rig.close)
            for show_all in (False, True):
                full = rig.application.collect(show_all=show_all)
                before = json.dumps(full).encode()
                _, wire = rig.application.collect_json(show_all=show_all)
                payload = json.loads(wire)
                self.assertTrue("explanations" in payload, "shared vocabulary is absent")
                self.assertEqual(3750, len(payload["sessions"]))
                self.assertLess(len(wire), len(before) - 2_000_000)
                sentence = annotation_store.NO_GOAL_TYPED
                self.assertEqual(1, wire.decode().count(sentence))
                self.assertEqual(full["sessions"], expand(payload)["sessions"])
                client = terminal_client.get(
                    rig.port,
                    "/api/data" + ("?all=1" if show_all else ""),
                    cap=terminal_client.DATA_CAP_BYTES,
                )
                self.assertTrue(
                    full["sessions"] == client.data["sessions"],
                    "terminal client did not restore the server sentences",
                )
                self.assertEqual(
                    terminal_sessions.render_sessions(full),
                    terminal_sessions.render_sessions(client.data),
                )
                self.assertEqual(
                    terminal_project.derive(full, {}, label="synthetic-history"),
                    terminal_project.derive(client.data, {}, label="synthetic-history"),
                )
                self.assertEqual(
                    footer_lines.build(full, pid=1, now=regen.NOW),
                    footer_lines.build(client.data, pid=1, now=regen.NOW),
                )
                # Publication cannot turn the in-process collection or the focused answer into tokens.
                self.assertEqual(sentence, full["sessions"][0]["annotation_goal_why"])
                for path in ("/api/sessions", "/api/session?harness=claude&sid=00000000"):
                    answer = rig.send(regen.get(path))["body"]
                    self.assertNotIn("explanations", answer)
                    if "session" in answer:
                        self.assertEqual(sentence, answer["session"]["annotation_goal_why"])
                    else:
                        self.assertNotIn("annotation_goal_why", answer["sessions"][0])

    def test_a_person_keeps_absent_refused_mixed_prefix_and_eligible_answers(self) -> None:

        directory = ROOT / "frontend/test/fixtures/client-contract"

        def recorded(name: str) -> dict[str, Any]:
            body = json.loads((directory / (name + ".json")).read_text())["response"]["body"]
            assert isinstance(body, dict)
            return body

        full = expand(recorded("data-shared-explanations"))
        rows = {row["sid"]: row for row in full["sessions"]}
        absent, refused, mixed, eligible = (
            rows[sid] for sid in ("11111111", "22222222", "33333333", "44444444")
        )
        self.assertEqual("No goal typed for this session.", absent["annotation_goal_why"])
        self.assertEqual(
            "The notification service returned an error, so no banner was created.",
            refused["delivery_why"],
        )
        self.assertEqual(recorded("session-shared-explanations")["session"], mixed)
        self.assertTrue(mixed["delivery_mixed"])
        self.assertEqual(2, mixed["delivery_raises"])
        self.assertEqual(2, mixed["delivery_departure"]["delivery_raises"])
        self.assertIn("Earlier raises", mixed["delivery_mixed_why"])
        self.assertIn("eight-character identity prefix", mixed["delivery_binding_why"])
        self.assertTrue(eligible["reading_eligibility"]["ok"])
        self.assertIsNone(eligible["reading_eligibility"]["sentence"])

    def test_a_person_downloads_the_discard_record_only_once(self) -> None:
        scratch = regen.Scratch()
        self.addCleanup(scratch.close)
        with regen.guarded():
            rig = regen.Rig(scratch, "discard-words")
            self.addCleanup(rig.close)
            annotation_store.annotate(
                rig.config,
                rig.state,
                "claude",
                "a1b2c3d4",
                goal="Build the parser",
                now=regen.NOW - 600,
            )
            annotation_store.clear(rig.config, rig.state, "claude", "a1b2c3d4", now=regen.NOW - 60)
            _, wire = rig.application.collect_json(show_all=False)
            self.assertEqual(1, wire.decode().count(json.dumps(annotation_store.DISCARD_RECORD)))
            from_client = terminal_client.get(
                rig.port, "/api/data", cap=terminal_client.DATA_CAP_BYTES
            ).data
            self.assertEqual(
                annotation_store.DISCARD_RECORD, from_client["annotate_discard"]["record"]
            )
            row = next(row for row in from_client["sessions"] if row["sid"] == "a1b2c3d4")
            self.assertEqual(annotation_store.DISCARD_RECORD, row["annotation_discarded_why"])
