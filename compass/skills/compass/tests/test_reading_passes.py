"""An ordinary original's exact packets retain text, intent and citation identity."""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path
from typing import TYPE_CHECKING

from compass_runtime import project_context, reading, reading_passes
from compass_runtime.config import build_runtime_config

from .test_agent_words import _agent

if TYPE_CHECKING:
    from collections.abc import Iterator


class OrdinaryMessagePacketsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.row = reading.build_ledger(
            [_agent("original-message", 110.0, "The displayed excerpt.")],
            "claude",
            "s1",
            read_agent_words=True,
        )[0]
        self.goal = 'Review "parser" without changing its behavior. 界🙂'
        self.lines = ("Explain the result.", "Keep every quoted \\ path intact.")

    def prepare(
        self, words: str, *, max_bytes: int = 800, final_state: str | None = None
    ) -> Iterator[reading_passes.MessagePacket]:
        return reading_passes.message_packets(
            self.row,
            words=words,
            goal=self.goal,
            lines=self.lines,
            max_bytes=max_bytes,
            final_state=final_state,
        )

    def test_complete_masked_unicode_ranges_recover_the_original_without_a_cut_secret(self) -> None:
        config = build_runtime_config(
            environ={"HOME": "/synthetic"},
            platform_name="linux",
            os_name="posix",
            launcher_path=Path("/synthetic/server.py"),
        )
        phrase = '界🙂 "quoted" \\ path '
        raw = 'Before password="' + "Private-cut-value-0123456789" * 50 + '"\n\u2003'
        raw += phrase * 80 + "AFTER"
        record = {
            "type": "assistant",
            "message": {"role": "assistant", "content": [{"type": "text", "text": raw}]},
        }
        # The real G2 source owner masks and normalizes once, before the renderer sees a cut.
        words = project_context.whole_message_words(config, record, "claude", len(raw) * 4)
        expected = "Before password=…REDACTED " + phrase * 80 + "AFTER"
        self.assertEqual(expected, words)
        packets = list(self.prepare(words))
        self.assertGreater(len(packets), 1)
        pieces: list[str] = []
        for packet in packets:
            self.assertEqual(len("".join(pieces)), packet.start)
            self.assertGreater(packet.end, packet.start)
            self.assertEqual(len(expected), packet.total)
            self.assertLessEqual(len(packet.prompt.encode("utf-8", "replace")), 800)
            self.assertNotIn("Private-cut-value", packet.prompt)
            self.assertNotIn("\ufffd", packet.prompt)
            selected = packet.selection.by_index()
            self.assertEqual([1], list(selected))
            actual = json.loads(selected[1]["agent_words"])
            self.assertEqual(expected[packet.start : packet.end], actual)
            # Read the sent JSON independently rather than trusting the projected row.
            wire = packet.prompt.encode("utf-8", "replace").decode("utf-8")
            menu = wire.split("\n[1] ", 1)[1]
            match = re.search(r"quoted, untrusted(?: \([^\n]*\))?: (.*)\n$", menu)
            self.assertIsNotNone(match, menu)
            assert match is not None
            self.assertEqual(actual, json.loads(match[1]))
            pieces.append(actual)
        self.assertEqual(expected, "".join(pieces))

    def test_each_packet_keeps_frozen_intent_and_original_metadata(self) -> None:
        original = self.row.copy()
        packets = self.prepare("ordinary words " * 200)
        self.row["summary"] = "A later mutation must not change this packet."
        for packet in packets:
            wire = packet.prompt.encode("utf-8", "replace").decode("utf-8")
            intent = json.loads(wire.split("\n", 2)[1])
            self.assertEqual({"goal": self.goal, "lines": list(self.lines)}, intent)
            self.assertEqual(self.lines, packet.selection.lines)
            selected = packet.selection.entries
            self.assertEqual(1, len(selected))
            for field in ("id", "at", "type", "author", "source", "summary", "work"):
                self.assertEqual(original[field], selected[0][field])
            self.assertEqual(packet.end - packet.start, selected[0]["text_read"])
            self.assertEqual(packet.total, selected[0]["text_total"])
            self.assertFalse(packet.selection.agent_words_whole)
            self.assertIsNone(packet.selection.newest_final)

    def test_exact_serialized_boundary_fits_and_one_byte_less_refuses(self) -> None:
        packet = next(self.prepare("🙂", max_bytes=10_000))
        size = len(packet.prompt.encode("utf-8", "replace"))
        self.assertGreater(size, len(packet.prompt))
        self.assertEqual(packet.prompt, next(self.prepare("🙂", max_bytes=size)).prompt)
        with self.assertRaises(ValueError):
            list(self.prepare("🙂", max_bytes=size - 1))

    def test_a_fitting_whole_row_is_not_refused_by_longer_fragment_labels(self) -> None:
        packet = next(self.prepare("ordinary words", max_bytes=10_000))
        size = len(packet.prompt.encode("utf-8", "replace"))
        self.assertEqual([packet], list(self.prepare("ordinary words", max_bytes=size)))

    def test_unencodable_words_refuse_before_even_a_clean_prefix_packet(self) -> None:
        for case, words in (
            ("high", "ok\ud800done"),
            ("low", "ok\udfffdone"),
            ("late", "ordinary words " * 200 + "\ud800"),
        ):
            with self.subTest(case=case), self.assertRaises(ValueError):
                next(self.prepare(words))

    def test_unencodable_saved_goal_or_line_is_not_silently_replaced_on_the_wire(self) -> None:
        for field in ("goal", "line"):
            for surrogate in ("\ud800", "\udfff"):
                with self.subTest(field=field, surrogate=repr(surrogate)):
                    self.goal = "Read the parser."
                    self.lines = ("Keep this exact saved line.",)
                    if field == "goal":
                        self.goal += surrogate
                    else:
                        self.lines = (*self.lines, "Explain " + surrogate + " exactly.")
                    with self.assertRaises(ValueError):
                        next(self.prepare("ordinary words"))

    def test_intent_is_never_shortened_to_make_room_for_evidence(self) -> None:
        self.lines = (*self.lines, "Keep this exact saved line. " * 80)
        with self.assertRaises(ValueError):
            list(self.prepare("ordinary words", max_bytes=800))

    def test_empty_words_and_invalid_bounds_refuse_without_yielding_a_header(self) -> None:
        with self.assertRaises(ValueError):
            list(self.prepare(""))
        for cap in (0, -1, True, 1.5):
            with self.subTest(cap=cap), self.assertRaises(ValueError):
                list(self.prepare("words", max_bytes=cap))

    def test_a_named_strict_final_never_enters_the_ordinary_fragment_path(self) -> None:
        for state in ("whole", "unfit", "unavailable"):
            with self.subTest(state=state), self.assertRaises(ValueError):
                list(self.prepare("FINAL_TAIL_SENTINEL" * 200, final_state=state))

    def test_a_non_agent_row_cannot_use_this_ordinary_agent_leaf(self) -> None:
        self.row = {**self.row, "type": "user_message", "author": "person"}
        with self.assertRaises(ValueError):
            list(self.prepare("person words"))
