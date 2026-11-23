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
    deliveries,
    departures,
    levels,
    live_monitor,
    notifications,
    project_context,
    reading,
    summary_jobs,
)
from compass_runtime import annotations as annotation_store

from .support import make_runtime

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


def _follow_ups() -> dict[str, str]:
    raised: departures.Check = {
        "harness": "claude",
        "sid": "s1",
        "at": 100.0,
        "constraint": "TYPED GOAL",
        "clause": "Ship the queue",
        "reading": "The queue was skipped.",
        "evidence": "turn transcript",
        "revision": 1,
        "cutoff": 100.0,
        "cutoff_text": "Read the latest turn.",
        "withdrawn": False,
    }
    again: departures.Check = {**raised, "at": 200.0, "cutoff": 200.0}
    quiet: departures.Check = {**again, "constraint": "", "clause": ""}
    return {
        "no later check": departures.published([raised], "claude", "s1")[0]["follow_up"],
        "later check did not raise": departures.published([raised, quiet], "claude", "s1")[0][
            "follow_up"
        ],
        "later check raised again": departures.published([raised, again], "claude", "s1")[1][
            "follow_up"
        ],
    }


def _sentences() -> dict[str, str]:
    _, state = make_runtime()
    state.annotations_trusted = False
    return {
        **reading.WITHHELD,
        **aggregate._BOARD_EXPLANATIONS,
        "idle without events": reading.withheld_sentence(
            reading.WITHHELD_IDLE_UNKNOWN, {"harness": "claude", "acquisition": "poll"}
        ),
        **{f"discard {key}": text for key, text in annotation_store.DISCARD_SENTENCES.items()},
        "annotation store unreadable": annotation_store.store_notice(state),
        "browser reported before raise": deliveries.browser_lane_why(100.0, 200.0),
        "browser reported after raise": deliveries.browser_lane_why(300.0, 200.0),
        "browser unreported": deliveries.browser_lane_why(0.0, 200.0),
        **_follow_ups(),
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


def _first_layer_sizes() -> dict[str, str]:
    reason = reading.WITHHELD_CONTEXT_LIMIT
    return {**_disclosures(), reason: reading.WITHHELD[reason]}


class FirstLayerWordsTest(unittest.TestCase):
    def test_reader_sentences_use_the_glossary(self) -> None:
        for slot, text in _sentences().items():
            with self.subTest(slot=slot):
                self.assertEqual([], _retired(text), text)

    def test_a_retired_control_planted_in_a_reader_constant_is_caught(self) -> None:
        with mock.patch.object(levels, "LIVE_SOURCE_LINE", "Press Analyze drift to try again."):
            self.assertIn("Analyze drift", _retired(_sentences()["live estimate"]))

    def test_omitted_producer_branches_catch_planted_control_names_and_tracker_keys(self) -> None:
        planted = "Press Analyze drift for DRC-1234."
        cases = (
            (deliveries, "BROWSER_LANE_REPORTED", "browser reported before raise"),
            (deliveries, "BROWSER_LANE_LATER", "browser reported after raise"),
            (deliveries, "BROWSER_LANE_UNREPORTED", "browser unreported"),
            (annotation_store, "STORE_UNREADABLE", "annotation store unreadable"),
            (departures, "FOLLOW_UP_NO_LATER_CHECK", "no later check"),
            (departures, "FOLLOW_UP_NOT_RAISED_AGAIN", "later check did not raise"),
            (departures, "FOLLOW_UP_RAISED_AGAIN", "later check raised again"),
        )
        for module, constant, slot in cases:
            with self.subTest(constant=constant), mock.patch.object(module, constant, planted):
                published = _sentences().get(slot, "")
                self.assertIn("Analyze drift", _retired(published))
                self.assertRegex(published, PUBLIC_TRACKER_TOKENS)

        # The payload reads the already assembled discard vocabulary.
        with mock.patch.dict(annotation_store.DISCARD_SENTENCES, {"armed": planted}):
            published = _sentences().get("discard armed", "")
            self.assertIn("Analyze drift", _retired(published))
            self.assertRegex(published, PUBLIC_TRACKER_TOKENS)

    def test_reader_sentences_carry_no_tracker_provenance(self) -> None:
        for slot, text in _sentences().items():
            with self.subTest(slot=slot):
                self.assertNotRegex(text, PUBLIC_TRACKER_TOKENS)

    def test_first_layer_sizes_use_reader_units(self) -> None:
        for name, text in _first_layer_sizes().items():
            with self.subTest(name=name):
                self.assertFalse(_binary_units(text), text)

    def test_a_binary_unit_planted_in_a_disclosure_is_caught(self) -> None:
        with mock.patch.object(summary_jobs, "disclosure", return_value="Sends at most 16 KiB."):
            self.assertTrue(_binary_units(_disclosures()["summary"]))

    def test_a_binary_unit_planted_in_the_context_limit_refusal_is_caught(self) -> None:
        reason = reading.WITHHELD_CONTEXT_LIMIT
        planted = reading.WITHHELD[reason].replace("16 KB", "16 KiB")
        with mock.patch.dict(reading.WITHHELD, {reason: planted}):
            self.assertTrue(_binary_units(_first_layer_sizes().get(reason, "")))

    def test_dec_26_quotes_the_current_analysis_source(self) -> None:
        record = (ROOT / "docs/design-reading-a-session.md").read_text()
        decision = record.split("## DEC-26:", 1)[1].split("\n## ", 1)[0]
        first_item = decision.split("\n1. ", 1)[1].split("\n2. ", 1)[0]
        self.assertIn(
            f'"{levels.ANALYSIS_SOURCE_LINE.format(time="<time>")}"', " ".join(first_item.split())
        )
