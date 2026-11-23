"""Guard the reader prose at the producer boundaries."""

from __future__ import annotations

import re
import unittest
from functools import cache
from importlib import import_module
from pathlib import Path
from unittest import mock

from compass_runtime import (
    aggregate,
    levels,
    live_monitor,
    notifications,
    project_context,
    reading,
    summary_jobs,
)
from compass_runtime import annotations as annotation_store

# The scripts suite imports this as validate_plugins. Dynamic import keeps mypy
# from resolving the same file under a second module name.
PUBLIC_TRACKER_TOKENS: re.Pattern[str] = import_module(
    "scripts.validate_plugins"
).PUBLIC_TRACKER_TOKENS

ROOT = Path(__file__).resolve().parents[4]

# These glossary rows describe visual states, technical vocabulary or a prior design.
# Their "Replaces" cells are not retired names in ordinary sentences (e.g. "high").
_NON_CONTROL_ROWS = {
    "Off course",
    "Slightly off course",
    "Way off course",
    "Working",
    "Quiet",
    "Ended",
    "Active today",
    "Your AI allowance",
    "Needs you",
    "Helpers",
    "Agent",
}


@cache
def _retired_names() -> tuple[str, ...]:
    document = (ROOT / "docs/design-calm-compass.md").read_text()
    glossary = document.split("| Plain word | Replaces |", 1)[1].split("\n\n", 1)[0]
    words: set[str] = set()
    for line in glossary.splitlines()[2:]:
        plain, replaces, *_ = (cell.strip() for cell in line.split("|")[1:-1])
        if plain not in _NON_CONTROL_ROWS:
            words.update(word.removeprefix("Cost implied by ") for word in replaces.split(", "))
    return tuple(sorted(words))


def _retired(text: str) -> list[str]:
    return sorted(
        name
        for name in _retired_names()
        if re.search(rf"(?<![\w-]){re.escape(name)}(?![\w-])", text, re.IGNORECASE)
    )


def _disclosures() -> dict[str, str]:
    return {
        "monitor": live_monitor.disclosure("api.anthropic.com"),
        "monitor unnamed": live_monitor.disclosure(""),
        "monitor terminal": live_monitor.disclosure("api.anthropic.com", terminal=True),
        "goal summary": project_context.observer_disclosure(),
        "summary": summary_jobs.disclosure("Anthropic"),
    }


def _sentences() -> dict[str, str]:
    return {
        **reading.WITHHELD,
        **aggregate._BOARD_EXPLANATIONS,
        "idle without events": reading.withheld_sentence(
            reading.WITHHELD_IDLE_UNKNOWN, {"harness": "claude", "acquisition": "poll"}
        ),
        "discard offer": annotation_store.DISCARD_WHY,
        "direction unavailable": annotation_store.DIRECTION_UNAVAILABLE,
        "live estimate": levels.LIVE_SOURCE_LINE,
        "stored level": levels.ANALYSIS_SOURCE_LINE,
        "desktop waiting body": aggregate._wait_popup_body(
            {"project": "demo/app", "state_detail": ""}
        ),
        "waiting title": notifications.waiting_title("Claude Code"),
        "asking title": notifications.asking_title("Claude Code"),
        "departure title": notifications.departure_title("Claude Code"),
        "departure title without a harness": notifications.departure_title(""),
        **_disclosures(),
    }


def _binary_units(text: str) -> bool:
    return bool(re.search(r"\b(?:KiB|MiB|GiB)\b", text, re.IGNORECASE))


class FirstLayerWordsTest(unittest.TestCase):
    def test_reader_sentences_use_the_glossary(self) -> None:
        for slot, text in _sentences().items():
            with self.subTest(slot=slot):
                self.assertEqual([], _retired(text), text)

    def test_a_retired_control_planted_in_a_reader_constant_is_caught(self) -> None:
        with mock.patch.object(levels, "LIVE_SOURCE_LINE", "Press Analyze drift to try again."):
            self.assertIn("Analyze drift", _retired(_sentences()["live estimate"]))

    def test_reader_sentences_carry_no_tracker_provenance(self) -> None:
        for slot, text in _sentences().items():
            with self.subTest(slot=slot):
                self.assertNotRegex(text, PUBLIC_TRACKER_TOKENS)

    def test_what_is_sent_uses_reader_units(self) -> None:
        for name, text in _disclosures().items():
            with self.subTest(name=name):
                self.assertFalse(_binary_units(text), text)

    def test_a_binary_unit_planted_in_a_disclosure_is_caught(self) -> None:
        with mock.patch.object(summary_jobs, "disclosure", return_value="Sends at most 16 KiB."):
            self.assertTrue(_binary_units(_disclosures()["summary"]))

    def test_dec_26_quotes_the_current_analysis_source(self) -> None:
        record = (ROOT / "docs/design-reading-a-session.md").read_text()
        decision = record.split("## DEC-26:", 1)[1].split("\n## ", 1)[0]
        first_item = decision.split("\n1. ", 1)[1].split("\n2. ", 1)[0]
        self.assertIn(
            f'"{levels.ANALYSIS_SOURCE_LINE.format(time="<time>")}"', " ".join(first_item.split())
        )
