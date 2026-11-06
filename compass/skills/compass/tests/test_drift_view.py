"""The terminal's port of the Drift card's shape, held to the page.

`frontend/src/drift/terminalParity.test.ts` writes the expected views from the PAGE's own derivation and
checks the page against them; this module reads the same two files and checks that `drift_view` gives the
same answer for the same published JSON. The expected values must never be regenerated from the port: a
file the port wrote would agree with the port by construction and prove nothing.
"""

from __future__ import annotations

import gzip
import json
import unittest
from typing import Any

from compass_runtime import drift_view

from .support import SERVER_PATH

FIXTURES = SERVER_PATH.parents[3] / "frontend" / "test" / "fixtures"
NAMED: dict[str, Any] = json.loads((FIXTURES / "drift-parity.json").read_text(encoding="utf-8"))
GENERATED: dict[str, Any] = json.loads(
    gzip.decompress((FIXTURES / "drift-parity-generated.json.gz").read_bytes()).decode("utf-8")
)
BY_NAME: dict[str, dict[str, Any]] = {case["name"]: case for case in NAMED["cases"]}


def view(case: dict[str, Any]) -> dict[str, Any]:
    return drift_view.shape_view(case["session"], case["payload"], case["context"])


def lines(name: str) -> dict[str, dict[str, Any]]:
    return {line["key"]: line for line in view(BY_NAME[name])["lines"]}


class NamedCasesTest(unittest.TestCase):
    def test_every_rule_the_corpus_names_has_a_case_that_lists_it(self) -> None:
        listed = {rule for case in NAMED["cases"] for rule in case["rules"]}

        self.assertEqual([], [rule for rule in NAMED["rules"] if rule not in listed])

    def test_each_named_case_reads_as_the_page_reads_it(self) -> None:
        for case in NAMED["cases"]:
            with self.subTest(case["name"]):
                self.assertEqual(case["expected"], view(case))


class GeneratedCasesTest(unittest.TestCase):
    def test_the_seeded_set_covers_every_harness_the_page_reads(self) -> None:
        harnesses = {case["session"]["harness"] for case in GENERATED["cases"]}

        self.assertEqual({"claude", "codex", "pi"}, harnesses)
        self.assertGreater(len(GENERATED["cases"]), 100)

    def test_each_generated_case_reads_as_the_page_reads_it(self) -> None:
        wrong = [case["name"] for case in GENERATED["cases"] if case["expected"] != view(case)]

        self.assertEqual([], wrong)


class LaterDirectionTwinsTest(unittest.TestCase):
    """The twin set: one base reading that departs, and a person's message at a different point."""

    def test_a_person_s_unsettled_later_direction_turns_a_departure_into_cant_tell(self) -> None:
        goal = lines("a-later-direction-unsettled-demotes-the-departure")["goal"]

        self.assertEqual(("cant-tell", "baseline-open"), (goal["state"], goal["why"]))
        self.assertEqual(
            [], view(BY_NAME["a-later-direction-unsettled-demotes-the-departure"])["departures"]
        )

    def test_the_same_direction_once_settled_leaves_the_departure_standing(self) -> None:
        name = "a-later-direction-settled-lets-the-departure-stand"

        self.assertEqual("departs", lines(name)["goal"]["state"])
        self.assertEqual(["goal"], view(BY_NAME[name])["departures"])

    def test_a_direction_given_after_the_reading_does_not_demote_it(self) -> None:
        name = "a-later-direction-after-the-reading-leaves-the-departure"

        self.assertEqual("departs", lines(name)["goal"]["state"])

    def test_a_contradicted_claim_stays_a_departure_under_an_unsettled_direction(self) -> None:
        name = "a-later-direction-never-demotes-the-claims-row"

        self.assertEqual("departs", lines(name)["claims"]["state"])
        self.assertEqual([], view(BY_NAME[name])["departures"])

    def test_a_gate_decision_by_a_person_counts_as_a_direction(self) -> None:
        name = "a-person-s-gate-decision-is-a-later-direction"

        self.assertEqual("baseline-open", lines(name)["goal"]["why"])

    def test_a_correction_copied_from_compass_is_not_a_direction(self) -> None:
        name = "a-correction-copied-from-compass-is-not-a-later-direction"

        self.assertEqual("departs", lines(name)["goal"]["state"])

    def test_one_unsettled_message_of_two_is_enough_to_demote(self) -> None:
        self.assertEqual("cant-tell", lines("later-directions-two-one-settled")["goal"]["state"])
        self.assertEqual("departs", lines("later-directions-two-both-settled")["goal"]["state"])

    def test_a_codex_reading_is_demoted_by_the_same_direction(self) -> None:
        self.assertEqual("cant-tell", lines("codex-later-direction-unsettled")["goal"]["state"])


if __name__ == "__main__":
    unittest.main()
