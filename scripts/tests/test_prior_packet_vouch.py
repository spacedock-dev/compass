"""A stop the stores no longer hold may be vouched by the committed packet that held it.

Orchestrator decision, 2026-10-30 (the owner may overrule): two of the ninth packet's recorded
cases were vouched by history observations that both stores have since rolled past, and their
transcripts' nearest Stop records are about 100 seconds from the stop, against a millisecond
tolerance. A case vouched in a committed, ledger-chained packet may be re-frozen at that same
recorded stop when the transcript still holds the same bytes up to the capture, by the prior
packet's own prefix digest. Anything else refuses.
"""

from __future__ import annotations

import hashlib
import json
import sys
import unittest
from pathlib import Path
from typing import TYPE_CHECKING, Any
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import mark_abstention
import score_abstention

if TYPE_CHECKING:
    from tests import test_abstention_claude as claude
else:
    import test_abstention_claude as claude

# The recorded-case fixture's module guard: never the real spend ledger.
setUpModule = claude.setUpModule
tearDownModule = claude.tearDownModule


class APriorCommittedPacketVouchesItsOwnStop(claude._RecordedCaseFixture):
    GENERATION = 9

    def setUp(self) -> None:
        super().setUp()
        self.path = self.transcript()
        # The prior freeze: the history store then held the stop.
        prior = self.freeze(self.path, self.stop(self.start + 20))
        self.assertEqual("history", prior["lifecycle_from"])
        size = prior["transcript_bytes"]
        prior["production_reading"] = {
            "prefix_digest": hashlib.sha256(Path(self.path).read_bytes()[:size]).hexdigest()
        }
        self.prior_body: dict[str, Any] = {"v": 5, "cases": [prior]}
        self.packet = Path(self.temp.name, "prior", "abstention-cases.json")
        self.packet.parent.mkdir()
        self.write_packet()

    def write_packet(self) -> None:
        self.packet.write_text(json.dumps(self.prior_body))
        self.digest = mark_abstention.cases_digest(self.prior_body)

    def frz(
        self, observations: list[dict[str, Any]], prior_packet: str = "", **entry: Any
    ) -> dict[str, Any]:
        base = {
            "harness": "claude",
            "sid": claude.CLAUDE_SID,
            "project": "p",
            "captured_at": self.start + 30,
            "row": {"state": "idle", "finished_at": self.start + 20},
            "intent": {"goal": claude.GOAL, "lines": [{"text": claude.LINE_ONE}]},
            "transcript": self.path,
            **entry,
        }
        with mock.patch.object(mark_abstention, "CLAUDE_PROJECTS_ROOT", str(self.root)):
            return mark_abstention.freeze_case(
                self.config, base, [], observations=observations, ends=[],
                prior_packet=prior_packet,
            )  # fmt: skip

    def committed(self, digest: str) -> int:
        return self.GENERATION if digest == self.digest else 0

    def refreeze(self, **entry: Any) -> dict[str, Any]:
        # Today: no store reaches the stop, and the transcript holds no Stop record at it.
        with mock.patch.object(mark_abstention, "committed_packet", self.committed):
            return self.frz([], prior_packet=str(self.packet), **entry)

    def test_the_committed_packet_vouches_the_same_stop(self) -> None:
        case = self.refreeze()
        self.assertEqual("recorded", case["origin"])
        self.assertEqual([], case["unconfirmed"])
        self.assertEqual("prior-packet", case["lifecycle_from"])
        self.assertEqual(
            {"generation": self.GENERATION, "packet": str(self.packet)}, case["prior_vouch"]
        )

    def test_the_scorer_rechecks_it_and_names_where_it_came_from(self) -> None:
        case = self.refreeze()
        index = {claude.CLAUDE_SID[:8]: self.path}
        with (
            mock.patch.object(mark_abstention, "committed_packet", self.committed),
            mock.patch.object(mark_abstention, "CLAUDE_PROJECTS_ROOT", str(self.root)),
        ):
            vouch = mark_abstention.make_vouch(
                observations=[], ends=[], index=index, config=self.config
            )
            self.assertNotIn("lifecycle-unconfirmed", vouch(case))
            self.assertEqual("prior-packet", vouch.lifecycle(case))
            Path(self.path).write_bytes(b"x" + Path(self.path).read_bytes()[1:])
            self.assertIn("lifecycle-unconfirmed", vouch(case))
            self.assertIsNone(vouch.lifecycle(case))

    def test_any_byte_changed_before_the_capture_refuses(self) -> None:
        raw = Path(self.path).read_bytes()
        Path(self.path).write_bytes(raw[:10] + bytes([raw[10] ^ 1]) + raw[11:])
        case = self.refreeze()
        self.assertEqual("synthetic", case["origin"])
        self.assertIn("lifecycle-unconfirmed", case["unconfirmed"])
        self.assertNotIn("prior_vouch", case)

    def test_a_packet_that_is_not_committed_refuses(self) -> None:
        self.prior_body["cases"][0]["title"] = "edited after commit"
        self.packet.write_text(json.dumps(self.prior_body))
        case = self.refreeze()
        self.assertEqual("synthetic", case["origin"])
        self.assertNotIn("prior_vouch", case)

    def test_an_absent_committed_packet_refuses(self) -> None:
        self.packet.unlink()
        case = self.refreeze()
        self.assertEqual("synthetic", case["origin"])
        self.assertIn("lifecycle-unconfirmed", case["unconfirmed"])

    def test_another_stop_or_capture_or_an_unvouched_prior_refuses(self) -> None:
        prior = self.prior_body["cases"][0]
        for name, change in (
            ("stop", {"row": {"state": "idle", "finished_at": self.start + 21}}),
            ("capture", {"captured_at": self.start + 31}),
        ):
            with self.subTest(name=name):
                self.assertEqual("synthetic", self.refreeze(**change)["origin"])
        for field, bad in (("origin", "synthetic"), ("unconfirmed", ["lifecycle-unconfirmed"])):
            with self.subTest(field=field):
                saved = prior[field]
                prior[field] = bad
                self.write_packet()
                self.assertEqual("synthetic", self.refreeze()["origin"])
                prior[field] = saved
                self.write_packet()

    def test_a_stop_a_store_still_holds_never_needs_it(self) -> None:
        with mock.patch.object(mark_abstention, "committed_packet", self.committed):
            case = self.frz(self.stop(self.start + 20), prior_packet=str(self.packet))
        self.assertEqual("history", case["lifecycle_from"])
        self.assertNotIn("prior_vouch", case)


class TheSummaryDisclosesAPriorPacketStop(unittest.TestCase):
    def test_the_summary_and_report_count_it_apart_from_the_transcript(self) -> None:
        recorded = claude._rubric_record("supported-departure", "claude", {"goal": "correct"})
        recorded["id"] = "a" * 16
        summary = score_abstention.summarize(
            [], marks={}, marks_bytes=b"", now=1.0, rubric_records=[recorded],
            binding=claude.BINDING, prior_packet_stops={"a" * 16},
        )  # fmt: skip
        self.assertEqual(1, summary["counts"]["recorded_on_prior_packet"])
        self.assertEqual(0, summary["counts"]["recorded_on_transcript_stop"])
        report = "\n".join(score_abstention.render(summary))
        self.assertIn("recorded on a stop a committed packet vouched for", report)
