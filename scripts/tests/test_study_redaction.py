"""Redaction at the qualification display, scoring and Google approval boundaries."""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from typing import TYPE_CHECKING, Any
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
if TYPE_CHECKING:
    from tests.codex_source_support import command, config, entry, rollout, write
else:
    from codex_source_support import command, config, entry, rollout, write

import abstention_ledger
import codex_case_sources as sources
import mark_abstention as marker
import score_abstention as scorer
from compass_runtime import project_context, records

GOOGLE: dict[str, Any] = {
    "purpose": "blind-marking",
    "recipients": ["marker-a", "marker-b"],
    "model": "gemini-3.8-flash-medium",
    "effort": "medium",
    "call_ceiling": 2,
}


class StudyRedactionTest(unittest.TestCase):
    def setUp(self) -> None:
        private = tempfile.TemporaryDirectory()
        self.addCleanup(private.cleanup)
        self.home = Path(private.name).resolve()
        self.config = config(self.home)
        root = self.home / "codex/sessions"
        self.path = rollout(root / "2026/11/07")
        self.spec = entry(root, self.path)

    def score_explanation(self) -> dict[str, Any]:
        value = "FakePass99"
        rows = [json.loads(line) for line in self.path.read_text().splitlines()]
        rows[-2:-2] = [
            command(4.5, 1, f"curl -u alice:{value} https://example.test"),
            command(4.6, 1, "python3 -m pytest tests/test_example.py"),
        ]
        write(self.path, rows)
        self.spec["intent"]["goal"] = "Make tests/test_example.py pass."
        case = sources.freeze_case(self.config, self.spec)
        self.assertNotIn(value, json.dumps(case))
        body = {"v": marker.FORMAT_CODEX}

        def model(_prompt: str, **_kwargs: Any) -> tuple[str, str]:
            return json.dumps(
                {
                    "goal": {
                        "result": "departure",
                        "cites": [4],
                        "detail": f"It used {value} and edited the wrong file.",
                    }
                }
            ), "ok"

        return scorer.score_case(
            self.config,
            case,
            case["row_snapshot"],
            case["producer_facts"],
            {},
            model=model,
            now=case["captured_at"],
            revision=marker.case_revision(case),
            tool_output=scorer._tool_output(case, "OpenAI", "Codex", body),
        )

    def test_scored_explanation_masks_a_bare_value_from_a_sealed_check(self) -> None:
        detail = self.score_explanation()["criteria"]["goal"]["detail"]
        self.assertEqual("It used …REDACTED and edited the wrong file.", detail)

    def test_scored_explanation_is_withheld_when_the_check_scrub_is_partial(self) -> None:
        with mock.patch.object(project_context, "MASKED_VALUES_MAX", 0):
            detail = self.score_explanation()["criteria"]["goal"]["detail"]
        self.assertEqual(marker._reading().SCRUB_WITHHELD_DETAIL, detail)

    def test_hand_typed_goal_and_both_line_forms_are_masked(self) -> None:
        self.spec["intent"].update(
            goal="Review Authorization: Bearer MadeUpGoal99",
            lines=[
                "Use x-api-key: MadeUpLine99",
                {"text": "Use x-api-key: MadeUpObject99", "source": "typed"},
            ],
        )
        case = sources.freeze_case(self.config, self.spec)
        body = {"v": marker.FORMAT_CODEX}
        self.assertEqual(
            {
                **self.spec["intent"],
                "goal": "Review Authorization: Bearer …REDACTED",
                "lines": [
                    "Use x-api-key: …REDACTED",
                    {"text": "Use x-api-key: …REDACTED", "source": "typed"},
                ],
            },
            case["intent"],
        )
        # The screen and mark questions also accept a previously frozen private revision.
        legacy = {**case, "intent": self.spec["intent"]}
        with contextlib.redirect_stdout(io.StringIO()) as screen:
            marker._show_intent_case(body, legacy, "1/1")
        payloads = [
            screen.getvalue().encode(),
            *(
                marker._mark_question(body, legacy, name).encode()
                for name in ("goal", "line_1", "line_2")
            ),
        ]
        for value in (b"MadeUpGoal99", b"MadeUpLine99", b"MadeUpObject99"):
            self.assertNotIn(value, b"".join(payloads))
        self.assertEqual(4, len(marker.prepare_google_send(payloads, **GOOGLE)["payload_digests"]))

    def test_google_inventory_accepts_only_the_redacted_screen_bytes(self) -> None:
        raw = b"Evidence\n  Authorization: Bearer FakeTok99xx\n"
        with self.assertRaises(abstention_ledger.LedgerError):
            marker.prepare_google_send([raw], **GOOGLE)
        with self.assertRaises(abstention_ledger.LedgerError):
            marker.prepare_google_send([b"\xff"], **GOOGLE)
        expected = "Evidence\n  Authorization: Bearer …REDACTED\n".encode()
        screened = marker.redact_google_screen(raw)
        self.assertEqual(expected, screened)
        manifest = marker.prepare_google_send([screened], **GOOGLE)
        self.assertEqual([hashlib.sha256(screened).hexdigest()], manifest["payload_digests"])
        receipt = self.home / "approval.json"
        marker.approve_google_send(receipt, manifest)
        with self.assertRaises(abstention_ledger.LedgerError):
            marker.consume_google_send(receipt, [raw], **GOOGLE)
        marker.consume_google_send(receipt, [screened], **GOOGLE)

    def test_google_screen_with_a_wrapped_header_is_ready_for_approval(self) -> None:
        raw = b"Evidence\n('Proxy-Authorization', 'Future-Scheme MadeUpToken99')\nEnd of screen.\n"
        screened = marker.redact_google_screen(raw)
        self.assertNotIn(b"MadeUpToken99", screened)
        self.assertIn(b"End of screen.", screened)
        self.assertEqual(
            [hashlib.sha256(screened).hexdigest()],
            marker.prepare_google_send([screened], **GOOGLE)["payload_digests"],
        )

    def test_opening_request_is_masked_before_the_screen_clips_it(self) -> None:
        case = sources.freeze_case(self.config, self.spec)
        case["asked_for"] = "Check " * 39 + "ghp_" + "MadeUp42" * 5 + " afterwards"
        with contextlib.redirect_stdout(io.StringIO()) as screen:
            marker._show_intent_case({"v": marker.FORMAT_CODEX}, case, "1/1")
        self.assertNotIn("MadeUp42", screen.getvalue())
        self.assertIn("Opening request (review context):", screen.getvalue())
        self.assertIn(records.SECRET_MARKER, screen.getvalue())

    def test_study_text_matches_the_runtime_redaction_corpus(self) -> None:
        # Same spellings as the authorization and records redaction tests.
        for raw in (
            "curl -H Authorization:Basic\\ dXNlcjpwYXNz https://example.test",
            "Authorization:\\ Basic\\ dXNlcjpzM2NyZXRwYXNzd29yZA==",
            "Authorization: Bearer FakeTok99xx",
            "curl -u alice:FakePass99 https://example.test",
            "Authorization\u200b: Bearer FakeTok99xx",
            "Authorization: Bearer\nFakeTok99xx",
        ):
            with self.subTest(raw=raw):
                masked = records.mask_prose(raw)
                self.assertEqual(
                    masked,
                    " ".join(marker.redact_google_screen(raw.encode()).decode().split()),
                )
                intent = sources._redact_intent(self.config, {"goal": raw, "lines": [raw]})
                self.assertEqual(masked, " ".join(intent["goal"].split()))
                self.assertEqual(masked, " ".join(intent["lines"][0].split()))
