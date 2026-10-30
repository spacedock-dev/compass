"""The owner's acceptance of the Claude Code producer, 2026-10-02, held to the record.

The acceptance opens the producer without a pass. What keeps it honest is that
the committed record says so in the same file the gate rests on: every scored
Claude Code run is listed with its own verdict, read here from the result files
themselves, so the record cannot drop a failure or round one up. Nothing here
writes to `docs/abstention/`.
"""

from __future__ import annotations

import copy
import hashlib
import json
import sys
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
ABSTENTION = ROOT / "docs" / "abstention"
RECORD = ABSTENTION / "claude-acceptance.json"
SKILL = ROOT / "compass" / "skills" / "compass"
if str(SKILL) not in sys.path:
    sys.path.insert(0, str(SKILL))

from compass_runtime import annotations as annotation_store  # noqa: E402

# Results measured to the end under the owner's no-early-stop rule: `stopped` is false.
COMPLETE_MEASUREMENTS = (
    "claude-results-continuation-9.json",
    "claude-results-continuation-10.json",
)


def _load(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def _committed_results() -> list[str]:
    return sorted(path.name for path in ABSTENTION.glob("claude-results*.json"))


class TheAcceptanceIsRecordedAsAcceptedAndNeverAsPassedTest(unittest.TestCase):
    def setUp(self) -> None:
        self.record = _load(RECORD)

    def test_the_record_is_the_owners_acceptance_of_the_claude_code_producer(self) -> None:
        self.assertEqual("accepted", self.record["decision"])
        self.assertEqual("claude", self.record["producer"])
        self.assertEqual("owner", self.record["accepted_by"])
        self.assertEqual("2026-10-02", self.record["accepted_on"])
        self.assertNotIn(
            "passed",
            json.dumps(
                {
                    key: value
                    for key, value in self.record.items()
                    if key not in {"runs", "statement"}
                }
            ).casefold(),
        )

    def test_the_gate_the_runtime_reads_is_the_one_the_record_states(self) -> None:
        self.assertEqual(
            annotation_store.ABSTENTION_CHECK_ACCEPTED, annotation_store.CLAUDE_ABSTENTION_CHECK
        )
        self.assertEqual(self.record["decision"], annotation_store.CLAUDE_ABSTENTION_CHECK)

    def test_it_says_plainly_that_the_scored_runs_failed(self) -> None:
        statement = self.record["statement"]
        self.assertIn("failed", statement)
        self.assertIn("accepted", statement)
        self.assertIn("2026-10-02", statement)
        self.assertEqual("failed", self.record["qualification"])


class EveryScoredRunIsListedWithItsOwnVerdictTest(unittest.TestCase):
    def setUp(self) -> None:
        self.record = _load(RECORD)
        self.runs = self.record["runs"]

    def test_no_committed_claude_code_result_is_left_out(self) -> None:
        self.assertEqual(_committed_results(), sorted(run["result"] for run in self.runs))
        self.assertEqual(len(self.runs), self.record["scored_runs"])

    def test_each_listed_run_matches_the_file_it_names(self) -> None:
        for run in self.runs:
            with self.subTest(result=run["result"]):
                committed = _load(ABSTENTION / run["result"])
                repeated = committed.get("v") == 2
                parts = (
                    [repeat["summary"] for repeat in committed["repetitions"]]
                    if repeated
                    else [committed]
                )
                if repeated:
                    self.assertEqual("closure-three-repeats", committed["protocol"])
                    self.assertEqual([1, 2, 3], [r["repeat"] for r in committed["repetitions"]])
                rubric: dict[str, int] = {}
                for part in parts:
                    for name, count in part["rubric"]["counts"].items():
                        rubric[name] = rubric.get(name, 0) + count
                cases_key = "unique_cases" if repeated else "cases"
                failed = {case for part in parts for case in part["dec17"]["failed"]}
                self.assertEqual(committed["verdict"], run["verdict"])
                self.assertIn(run["verdict"], {"passed", "failed", "blocked"})
                self.assertEqual(committed["inputs_digest"], run["inputs_digest"])
                self.assertEqual(committed["marks_digest"], run["marks_digest"])
                self.assertEqual(committed["counts"][cases_key], run["cases"])
                self.assertEqual(len(failed), run["dec17_failed_cases"])
                self.assertEqual(rubric["correct"], run["correct"])
                self.assertEqual(
                    sum(v for k, v in rubric.items() if not k.startswith("unscored:")),
                    run["scored_constraints"],
                )
                self.assertEqual(committed["spend"], run["spend"])

    def test_the_blocked_opening_records_two_unusable_attempts_and_no_accuracy(self) -> None:
        by_result = {run["result"]: run for run in self.runs}
        name = "claude-results-continuation-5.json"
        self.assertIn(name, by_result)
        run = by_result[name]
        committed = _load(ABSTENTION / name)
        self.assertEqual("blocked", run["verdict"])
        self.assertEqual(1, run["cases"])
        self.assertEqual(0, run["correct"])
        self.assertEqual(0, run["scored_constraints"])
        self.assertEqual(0, run["dec17_failed_cases"])
        self.assertEqual({"charged": 32, "cap": 61}, run["spend"])
        self.assertEqual(
            {"unique_cases": 1, "registered_exposures": 1, "attempts": 2, "unusable_attempts": 2},
            committed["counts"],
        )
        self.assertTrue(committed["stopped"])
        for repetition in committed["repetitions"]:
            part = repetition["summary"]
            self.assertEqual(0, part["counts"]["reached_model"])
            self.assertEqual([], part["dec17"]["failed"])
            self.assertTrue(all(count == 0 for count in part["rubric"]["counts"].values()))
        self.assertIn("blocked", self.record["statement"])
        self.assertIn("no accuracy", self.record["statement"])

    def test_later_results_preserve_five_failures_the_blocked_run_and_owner_decision(self) -> None:
        self.assertGreaterEqual(self.record["scored_runs"], 7)
        expected = {
            "claude-results.json": "failed",
            "claude-results-continuation.json": "failed",
            **{f"claude-results-continuation-{n}.json": "failed" for n in (2, 3, 4)},
            "claude-results-continuation-5.json": "blocked",
            "claude-results-continuation-6.json": "failed",
        }
        self.assertEqual(
            expected,
            {run["result"]: run["verdict"] for run in self.runs if run["result"] in expected},
        )
        self.assertEqual(
            {
                "accepted_by": "owner",
                "accepted_on": "2026-10-02",
                "decision": "accepted",
                "producer": "claude",
                "qualification": "failed",
            },
            {
                key: self.record[key]
                for key in ("accepted_by", "accepted_on", "decision", "producer", "qualification")
            },
        )

    def test_all_six_prior_inventory_entries_remain_unchanged(self) -> None:
        original = json.dumps(self.runs[:6], sort_keys=True, separators=(",", ":")).encode()
        self.assertEqual(
            "73dcb748f715b91dee4c8e482faa5a2871a69d4b538d848bb0784a16e4032237",
            hashlib.sha256(original).hexdigest(),
        )

    def test_complete_measurement_preserves_all_nine_prior_inventory_entries(self) -> None:
        original = json.dumps(self.runs[:9], sort_keys=True, separators=(",", ":")).encode()
        self.assertEqual(
            "cf455ffcd8eb9d8cf2361078dc5e5197847f5fcc47ef435c75ea3a1576619a95",
            hashlib.sha256(original).hexdigest(),
        )
        self.assertGreaterEqual(self.record["scored_runs"], 10)
        self.assertEqual("claude-results-continuation-9.json", self.runs[9]["result"])

    def test_tenth_measurement_preserves_all_ten_prior_inventory_entries(self) -> None:
        original = json.dumps(self.runs[:10], sort_keys=True, separators=(",", ":")).encode()
        self.assertEqual(
            "bda3769cd0ea1ff45f1aa124b6f612383c172f98439b1c7fc0c9cb6a30d0f9f6",
            hashlib.sha256(original).hexdigest(),
        )
        self.assertEqual(11, self.record["scored_runs"])
        self.assertEqual("claude-results-continuation-10.json", self.runs[-1]["result"])

    def test_tenth_records_the_retired_case_and_its_measured_replacement(self) -> None:
        statement = self.record["statement"]
        self.assertIn("a3c76f898154b2fa", statement)
        self.assertIn("not re-measured", statement)
        self.assertIn("19f966db1f403710", statement)
        result = _load(ABSTENTION / "claude-results-continuation-10.json")
        for repetition in result["repetitions"]:
            self.assertNotIn("a3c76f898154b2fa", repetition["summary"]["cases"])
            self.assertIn("19f966db1f403710", repetition["summary"]["cases"])

    def test_complete_failed_measurement_is_not_an_early_stop_or_passing_qualification(
        self,
    ) -> None:
        result = _load(ABSTENTION / "claude-results-continuation-9.json")
        self.assertEqual("failed", result["verdict"])
        self.assertIs(False, result["stopped"])
        self.assertEqual({"charged": 68, "cap": 69}, result["spend"])
        self.assertEqual(30, result["counts"]["attempts"])
        self.assertEqual(0, result["counts"]["unusable_attempts"])
        self.assertEqual("failed", self.record["qualification"])
        self.test_spend_matches_each_run_and_a_repeated_failure_can_stop_before_the_cap()

    def test_completed_measurement_refuses_partial_or_erased_failure(self) -> None:
        name = "claude-results-continuation-9.json"
        original = _load(ABSTENTION / name)
        variants = []
        for field, value in (
            ("unique_cases", 9),
            ("registered_exposures", 29),
            ("attempts", 29),
            ("unusable_attempts", 1),
        ):
            changed = copy.deepcopy(original)
            changed["counts"][field] = value
            variants.append((field, changed))
        changed = copy.deepcopy(original)
        changed["repetitions"][1]["repeat"] = 1
        variants.append(("duplicate-repeat", changed))
        changed = copy.deepcopy(original)
        changed["repetitions"][2]["summary"]["counts"]["reached_model"] = 9
        variants.append(("missing-exposure", changed))
        changed = copy.deepcopy(original)
        for repetition in changed["repetitions"]:
            repetition["summary"]["cases"].pop(next(iter(repetition["summary"]["cases"])))
        variants.append(("missing-case-in-all-repeats", changed))
        changed = copy.deepcopy(original)
        changed["repetitions"][2]["summary"]["coverage"]["claude"]["kinds"] = 4
        variants.append(("missing-kind", changed))
        changed = copy.deepcopy(original)
        changed["repetitions"][1]["summary"]["rubric"]["counts"]["unscored:missing-expectation"] = 1
        variants.append(("unscored-question", changed))
        changed = copy.deepcopy(original)
        for repetition in changed["repetitions"]:
            repetition["summary"]["dec17"]["failed"] = []
        variants.append(("erased-failure", changed))
        changed = copy.deepcopy(original)
        changed["verdict"] = "passed"
        for repetition in changed["repetitions"]:
            repetition["summary"]["verdict"] = "passed"
        variants.append(("promoted-failure-to-pass", changed))
        changed = copy.deepcopy(original)
        changed["spend"]["charged"] = 69
        variants.append(("retry-spend-without-attempt", changed))
        real_load = _load
        for label, changed in variants:
            with (
                self.subTest(mutation=label),
                mock.patch(
                    __name__ + "._load",
                    side_effect=lambda path, body=changed: (
                        body if path.name == name else real_load(path)
                    ),
                ),
                self.assertRaises(AssertionError),
            ):
                self.test_spend_matches_each_run_and_a_repeated_failure_can_stop_before_the_cap()

    def test_complete_measurement_exception_never_changes_an_older_stop_requirement(self) -> None:
        name = "claude-results-continuation-8.json"
        changed = copy.deepcopy(_load(ABSTENTION / name))
        changed["stopped"] = False
        real_load = _load
        with (
            mock.patch(
                __name__ + "._load",
                side_effect=lambda path: changed if path.name == name else real_load(path),
            ),
            self.assertRaises(AssertionError),
        ):
            self.test_spend_matches_each_run_and_a_repeated_failure_can_stop_before_the_cap()

    def _assert_complete_failed_measurement(self, committed: dict[str, Any]) -> None:
        self.assertEqual(2, committed["v"])
        self.assertEqual("closure-three-repeats", committed["protocol"])
        self.assertEqual("failed", committed["verdict"])
        self.assertIs(False, committed["stopped"])
        self.assertEqual({"charged": 68, "cap": 69}, committed["spend"])
        self.assertEqual(
            {
                "unique_cases": 10,
                "registered_exposures": 30,
                "attempts": 30,
                "unusable_attempts": 0,
            },
            committed["counts"],
        )
        self.assertEqual([1, 2, 3], [row["repeat"] for row in committed["repetitions"]])
        failed_exposures = 0
        first_cases = set(committed["repetitions"][0]["summary"]["cases"])
        self.assertEqual(10, len(first_cases))
        for repetition in committed["repetitions"]:
            part = repetition["summary"]
            self.assertEqual("failed", part["verdict"])
            self.assertEqual(first_cases, set(part["cases"]))
            self.assertEqual(10, part["counts"]["cases"])
            self.assertEqual(10, part["counts"]["reached_model"])
            self.assertEqual(0, part["counts"]["withheld"])
            self.assertTrue(all(case["reached_model"] for case in part["cases"].values()))
            self.assertEqual(34, sum(len(case["marks"]) for case in part["cases"].values()))
            self.assertEqual(first_cases, set(part["rubric"]["cases"]))
            self.assertTrue(
                all(
                    case["admitted"] and case["scored"] and case["reached_model"]
                    for case in part["rubric"]["cases"].values()
                )
            )
            self.assertEqual(
                {"kinds": 5, "role": "scored", "missing": [], "not_produced": []},
                part["coverage"]["claude"],
            )
            counts = part["rubric"]["counts"]
            self.assertEqual(34, sum(counts.values()))
            self.assertTrue(
                all(count == 0 for key, count in counts.items() if key.startswith("unscored:"))
            )
            self.assertTrue(part["dec17"]["failed"])
            failed_exposures += len(part["dec17"]["failed"])
        self.assertEqual(7, failed_exposures)

    def _assert_complete_failed_tenth(self, committed: dict[str, Any]) -> None:
        self.assertEqual(2, committed["v"])
        self.assertEqual("closure-three-repeats", committed["protocol"])
        self.assertEqual("failed", committed["verdict"])
        self.assertIs(False, committed["stopped"])
        self.assertEqual({"charged": 98, "cap": 99}, committed["spend"])
        self.assertEqual(
            {
                "unique_cases": 10,
                "registered_exposures": 30,
                "attempts": 30,
                "unusable_attempts": 0,
            },
            committed["counts"],
        )
        self.assertEqual([1, 2, 3], [row["repeat"] for row in committed["repetitions"]])
        failed_exposures = 0
        first_cases = set(committed["repetitions"][0]["summary"]["cases"])
        self.assertEqual(10, len(first_cases))
        for repetition in committed["repetitions"]:
            part = repetition["summary"]
            self.assertEqual(first_cases, set(part["cases"]))
            self.assertEqual(10, part["counts"]["reached_model"])
            self.assertEqual(0, part["counts"]["withheld"])
            self.assertEqual(32, sum(len(case["marks"]) for case in part["cases"].values()))
            self.assertEqual(
                {"kinds": 5, "role": "scored", "missing": [], "not_produced": []},
                part["coverage"]["claude"],
            )
            counts = part["rubric"]["counts"]
            self.assertEqual(32, sum(counts.values()))
            self.assertTrue(
                all(count == 0 for key, count in counts.items() if key.startswith("unscored:"))
            )
            failed_exposures += len(part["dec17"]["failed"])
        # The first repeat had no semantic failure; the aggregate still fails on the later two.
        self.assertEqual(
            ["passed", "failed", "failed"],
            [r["summary"]["verdict"] for r in committed["repetitions"]],
        )
        self.assertEqual(4, failed_exposures)

    def test_login_repair_records_usable_answers_but_failed_qualification(self) -> None:
        by_result = {run["result"]: run for run in self.runs}
        name = "claude-results-continuation-6.json"
        self.assertIn(name, by_result)
        run = by_result[name]
        committed = _load(ABSTENTION / name)
        self.assertEqual("failed", run["verdict"])
        self.assertEqual(2, run["cases"])
        self.assertEqual(4, run["correct"])
        self.assertEqual(7, run["scored_constraints"])
        self.assertEqual(1, run["dec17_failed_cases"])
        self.assertEqual({"charged": 34, "cap": 63}, run["spend"])
        self.assertEqual(
            {"unique_cases": 2, "registered_exposures": 2, "attempts": 2, "unusable_attempts": 0},
            committed["counts"],
        )
        self.assertTrue(committed["stopped"])
        first = committed["repetitions"][0]["summary"]
        self.assertEqual(2, first["counts"]["reached_model"])
        self.assertEqual(4, first["rubric"]["counts"]["correct"])
        self.assertEqual(0, first["rubric"]["counts"]["false-reassurance"])
        self.assertEqual(1, first["rubric"]["counts"]["missed-departure"])
        self.assertEqual(2, first["rubric"]["counts"]["over-abstention"])
        for repetition in committed["repetitions"][1:]:
            part = repetition["summary"]
            self.assertEqual(0, part["counts"]["cases"])
            self.assertEqual({}, part["cases"])
            self.assertTrue(all(count == 0 for count in part["rubric"]["counts"].values()))

    def test_the_runs_are_in_the_order_they_were_scored(self) -> None:
        stamps = [_load(ABSTENTION / run["result"])["scored_at"] for run in self.runs]
        self.assertEqual(sorted(stamps), stamps)

    def test_spend_matches_each_run_and_a_repeated_failure_can_stop_before_the_cap(self) -> None:
        last = _load(ABSTENTION / self.runs[-1]["result"])
        self.assertEqual(last["spend"], self.record["spend"])
        if last.get("v") != 2:
            self.assertEqual(last["spend"]["cap"], last["spend"]["charged"])
        for run in self.runs:
            committed = _load(ABSTENTION / run["result"])
            if run["result"] == "claude-results-continuation-9.json":
                self._assert_complete_failed_measurement(committed)
            if run["result"] == "claude-results-continuation-10.json":
                self._assert_complete_failed_tenth(committed)
            spend = committed["spend"]
            self.assertLessEqual(spend["charged"], spend["cap"])
            if committed.get("v") != 2:
                continue
            if spend["charged"] < spend["cap"]:
                if committed["verdict"] == "blocked":
                    self.assertTrue(committed["stopped"])
                    self.assertEqual(2, committed["counts"]["attempts"])
                    self.assertEqual(2, committed["counts"]["unusable_attempts"])
                    self.assertTrue(
                        all(
                            not repeat["summary"]["dec17"]["failed"]
                            and not any(repeat["summary"]["rubric"]["counts"].values())
                            for repeat in committed["repetitions"]
                        )
                    )
                elif committed["verdict"] == "failed":
                    if run["result"] not in COMPLETE_MEASUREMENTS:
                        self.assertTrue(committed["stopped"])
                    self.assertTrue(
                        any(
                            repeat["summary"]["dec17"]["failed"]
                            or repeat["summary"]["rubric"]["counts"]["false-reassurance"]
                            for repeat in committed["repetitions"]
                        )
                    )
                else:
                    self.assertEqual("passed", committed["verdict"])
                    self.assertFalse(committed["stopped"])
                    self.assertEqual(30, committed["counts"]["registered_exposures"])
                    self.assertTrue(
                        all(
                            repeat["summary"]["verdict"] == "passed"
                            for repeat in committed["repetitions"]
                        )
                    )


if __name__ == "__main__":
    unittest.main()
