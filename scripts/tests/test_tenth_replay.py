"""The tenth Claude Code qualification's recorded answers, replayed through the corrected producer.

In-sample, and only that. The four guards this replays (an outcome-line departure needs recorded
work, a `consistent` needs a write or a passing check where the window holds a write, a Goal is
`consistent` only beside consistent lines, and a claim is not "not shown" past a run with no
recorded result) were derived from these same thirty readings. That they would have cleared them
is what they were built to do, and says nothing about a fresh run's answers
([DEC-17](docs/design-reading-a-session.md#amended-2026-10-30-owner-a-verdict-on-words-alone-gives-way-to-the-record)).

No model is called and no process starts: each repeat's resolved answers come back from a fake,
and `subprocess.Popen` raises. The scorer keeps resolved criteria rather than raw replies. A judged
answer's resolved token is the model's own and its published cites are a subset of what it cited,
so replaying them reproduces every judged outcome; an abstained answer replays as `unverifiable`,
and every guard here only demotes, so it cannot move.

The fake also holds the prompt bytes: each of the ten cases, built by this tree, must send exactly
the prompt the tenth packet froze, so the marks transfer unchanged.

The packet and the run's material are private and stay out of Git (SECURITY.md, "The abstention
check"). The test reads them where `COMPASS_TENTH_REPLAY_EVIDENCE` (the tenth packet's and run's
evidence folder) and `COMPASS_TENTH_REPLAY_HOME` (the packet's home) point, and skips where they
are absent. It prints counts only, never case text.
"""

from __future__ import annotations

import json
import os
import sys
import unittest
from collections import Counter
from pathlib import Path
from typing import Any
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import mark_abstention as mark
import score_abstention as score

_EVIDENCE = Path(os.environ.get("COMPASS_TENTH_REPLAY_EVIDENCE", "/nonexistent"))
_HOME = Path(
    os.environ.get(
        "COMPASS_TENTH_REPLAY_HOME",
        str(Path.home() / ".compass" / "qualification-tenth-2026-10-30"),
    )
)
_PACKET = _EVIDENCE / "tenth-packet-2026-10-30" / "private"
_RUN = _EVIDENCE / "tenth-run-2026-10-30" / "private"
# The reviewed source context the tenth packet was frozen against, by the digest it was sealed with.
_REVIEWED_DIGEST = "416e13568dc76147615dc1d3a98985749426080c081b25f536febc0655af25da"
_PRESENT = all(
    path.exists()
    for path in (
        _PACKET / "prompts.json",
        _PACKET / "reviewed-source-context-relocated-v2.json",
        *(_RUN / f"batch-{batch}-material.json" for batch in range(4)),
        _HOME / "abstention-cases.json",
        _HOME / "abstention-marks.json",
        _HOME / "abstention-rubric.json",
    )
)


@unittest.skipUnless(_PRESENT, "the tenth packet and run material are private and not present")
class TheTenthRunsAnswersUnderTheCorrectedProducer(unittest.TestCase):
    """Result 10 failed on five readings in repeats 2 and 3. Replayed here, none fails."""

    def test_no_reading_fails_and_every_prompt_is_the_one_the_tenth_froze(self) -> None:
        with mock.patch.dict(os.environ, {"COMPASS_HOME": str(_HOME)}):
            grades, failing, mismatched, prompted = self._replay()
        self.assertEqual([], mismatched, "a prompt differs from the tenth packet's")
        self.assertEqual(10, len(prompted))
        self.assertEqual([], failing)
        # Recorded, result 10 graded 68 correct, 2 false reassurances, 2 false alarms, 8 missed
        # departures and 16 over-abstentions. In-sample, see above.
        self.assertEqual(
            {"correct": 72, "missed-departure": 9, "over-abstention": 15}, dict(grades)
        )

    def _replay(self) -> tuple[Counter[str], list[tuple[str, int]], list[str], set[str]]:
        config_mod, reading, _records = score._runtime()
        from compass_runtime import reading_route  # noqa: PLC0415 - reached as `score` reaches it

        config = config_mod.build_runtime_config(
            environ=os.environ,
            platform_name=sys.platform,
            os_name=os.name,
            launcher_path=Path(score._SKILL, "server.py"),
            observer_model_enabled=True,
            claude_reading_model=config_mod.CLAUDE_READING_DEFAULT_MODEL,
        )
        resolver = mark.ReviewedExports(
            str(_PACKET / "reviewed-source-context-relocated-v2.json"), _REVIEWED_DIGEST
        )
        corpus = score.Corpus(
            cases=mark._load(str(_HOME / "abstention-cases.json")),
            marks=mark._load(str(_HOME / "abstention-marks.json")),
            marks_bytes=(_HOME / "abstention-marks.json").read_bytes(),
            rubric=mark._load(str(_HOME / "abstention-rubric.json")),
        )
        packet = dict(corpus.cases)
        marks = mark._marks(dict(corpus.marks))
        rubric = score._rubric_entries(corpus.rubric)
        prompts = json.loads((_PACKET / "prompts.json").read_bytes())
        destination = reading_route.destination("claude")
        label = score.reading_label("claude")
        token = {v: k for k, v in reading.RESULT_BY_TOKEN.items()}
        token.update({v: k for k, v in reading.CLAIMS_RESULT_BY_TOKEN.items()})
        token[reading.RESULT_GOAL_UNCLEAR] = "goal_unclear"
        answers: dict[tuple[str, int], dict[str, Any]] = {}
        for batch in range(4):
            material = json.loads((_RUN / f"batch-{batch}-material.json").read_bytes())
            for attempt in material["material"]["attempts"]:
                answers[(attempt["case"], attempt["repeat"])] = {
                    q: v["reader_answer"] for q, v in attempt["questions"].items()
                }
        self.assertEqual(30, len(answers))
        mismatched: list[str] = []
        prompted: set[str] = set()

        def fake(case_id: str, repeat: int) -> Any:
            row = prompts[case_id]

            def model(prompt: str, **_kw: Any) -> tuple[str, str]:
                prompted.add(case_id)
                if prompt != row["prompt"]:
                    mismatched.append(case_id[:8])
                out = {}
                for question in row["constraints"]:
                    answer = answers[(case_id, repeat)][question]
                    result = token.get(answer["result"], "unverifiable")
                    judged = result != "unverifiable"
                    detail = "x" if result in ("departure", "not_reached") else ""
                    out[question] = {
                        "result": result,
                        "cites": list(answer["cites"]) if judged else [],
                        "detail": answer.get("detail") or detail,
                    }
                return json.dumps(out), "ok"

            return model

        grades: Counter[str] = Counter()
        failing: list[tuple[str, int]] = []
        cases = {case["id"]: case for case in packet["cases"]}
        # The guards live in `reading.py`, one of the parser-stamped files, and the scorer fix in
        # `score_abstention.py`, which the reviewed-export receipts bind as intake code. So this
        # tree's stamps are not the ones the tenth froze under, and every case would be refused
        # before its prompt. The retry re-freezes; here both stamps are held to the packet's own,
        # and the prompt check above is what shows the cases still read the same.
        (stamp,) = {case["parser"] for case in packet["cases"]}
        (intake,) = {
            case["reviewed_export"]["intake_code_sha256"]
            for case in packet["cases"]
            if "reviewed_export" in case
        }
        with (
            mock.patch("subprocess.Popen", side_effect=AssertionError("no process")),
            mock.patch.object(mark, "parser_digest", return_value=stamp),
            mock.patch.object(mark, "intake_code_digest", return_value=intake),
        ):
            for case_id, repeat in sorted(answers, key=lambda key: (key[1], key[0])):
                case = cases[case_id]
                record = score.score_case(
                    config,
                    case,
                    case["row_snapshot"],
                    case["producer_facts"],
                    marks[case_id],
                    model=fake(case_id, repeat),
                    now=case["captured_at"],
                    revision=mark.case_revision(case),
                    tool_output=score._tool_output(case, destination, label, packet),
                    read_agent_words=True,
                    reviewed_exports=resolver,
                )
                judged = score.rubric_case(
                    rubric[case_id], record, case_id, case_origin=case.get("origin")
                )
                grades.update(judged["judgement"].values())
                if score._repeat_classification(record, judged, "replay") != "usable":
                    failing.append((case_id[:8], repeat))
        return grades, failing, mismatched, prompted


if __name__ == "__main__":
    unittest.main()
