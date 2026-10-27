"""Every fact subject through every consumer of a tool report.

[DEC-29](docs/design-reading-a-session.md#dec-29-a-commands-result-is-evidence-by-tier-and-a-command-that-cannot-fail-never-passes)
item 5: each consumer admits a subject from `reading.CONSUMER_SUBJECTS` and from nowhere else. This
runs the real consumer over a fact of each subject and holds it to its row, so a subject added to
the producer later fails here until someone chooses which consumers may read it.
"""

from __future__ import annotations

import unittest
from typing import TYPE_CHECKING, Any

from compass_runtime import history as runtime_history
from compass_runtime import (
    levels,
    live_monitor,
    project_context,
    reading,
    semantic_history,
)

from . import test_levels as lv
from .test_claude_checks import SHORT, ClaudeChecksTestCase

if TYPE_CHECKING:
    from collections.abc import Callable

ALL_SUBJECTS = ("check", "write", "pr", "skill", "launch", "command", "ci_command")
SESSION = {"harness": "claude", "sid": "s1"}


def fact(subject: str, result: str = "passed") -> dict[str, Any]:
    row: dict[str, Any] = {
        "fact_id": f"{subject}-1",
        "type": "tool_report",
        "subject": subject,
        "summary": "make deploy",
        "result": result if subject in reading.RESULT_SUBJECTS else "",
        "result_source": "flag" if subject in reading.RESULT_SUBJECTS else "",
        "at": lv.SAVE + 30,
        "before_last_change": False,
        "changed_after": False,
        "source_session": SESSION,
        "evidence": {"source": "Claude Bash call and paired result", "confidence": "exact"},
        "branch": {"harness": "claude", "sid": "s1", "record_id": f"call-{subject}"},
    }
    if subject == "write":
        row["summary"] = "docs/b.py"
    if subject == "pr":
        row.update(
            summary="acme/widgets#7",
            pr_repository="acme/widgets",
            pr_number=7,
            pr_url="https://github.com/acme/widgets/pull/7",
        )
    if subject == "skill":
        row["summary"] = "widget-skill"
    if subject == "ci_command":
        row["summary"] = "gh pr checks 7"
    return row


def work_floor(subject: str) -> bool:
    rows = reading.build_ledger([fact(subject)], "claude", "s1", tool_output={})
    return any(row["work"] for row in rows)


def check_supports(subject: str) -> bool:
    rows = reading.build_ledger([fact(subject)], "claude", "s1", tool_output={})
    return any(
        reading.check_supports(row, reading.RESULT_CONSISTENT, 0.0)
        or reading.check_supports(row, reading.RESULT_DEPARTURE, 0.0, recorded_write=True)
        for row in rows
    )


def live_level(subject: str) -> bool:
    base = [
        lv.check("base", lv.SAVE + 20, "passed"),
        lv.wrote("w1", lv.SAVE + 10, "src/a.py"),
    ]
    intent = lv.intent("Tests pass", goal="Change the files in src/")
    alone = levels.live_level(
        lv.evidence(base, lv.scan(passed=1, written_paths=1), cwd="/synthetic/project"), intent
    )
    counts: dict[str, Any] = {"written_paths": 2} if subject == "write" else {}
    if subject in ("command", "ci_command"):
        counts[f"{'ci' if subject == 'ci_command' else 'command'}_failed"] = 1
    failed = fact(subject, "failed")
    with_it = levels.live_level(
        lv.evidence([*base, failed], lv.scan(passed=1, **{"written_paths": 1, **counts})),
        intent,
    )
    return (alone.level, alone.reasons) != (with_it.level, with_it.reasons)


def analysis_level(subject: str) -> bool:
    alone = lv.analyze(lv.SUPPORTED, lv.PASSING)
    failed = fact(subject, "failed")
    with_it = lv.analyze(
        lv.SUPPORTED, lv.evidence([*lv.PASSING.facts, failed], dict(lv.PASSING.scan))
    )
    return (alone.level, alone.reasons) != (with_it.level, with_it.reasons)


def monitor_turn(subject: str) -> bool:
    return live_monitor._turn_text(fact(subject)) is not None


def goal_verdict(subject: str) -> bool:
    recorded = reading.recorded_from([fact(subject)], "claude", "s1")
    return bool(recorded.writes or recorded.checks or recorded.prs)


def history(subject: str) -> bool:
    return semantic_history._event_from_fact(fact(subject), {}) is not None


def unasked_ledger(subject: str) -> bool:
    return bool(reading.build_ledger([fact(subject)], "claude", "s1"))


CONSUMERS: dict[str, Callable[[str], bool]] = {
    "work_floor": work_floor,
    "check_supports": check_supports,
    "live_level": live_level,
    "analysis_level": analysis_level,
    "monitor_turn": monitor_turn,
    "goal_verdict": goal_verdict,
    "history": history,
    "unasked_ledger": unasked_ledger,
}


class EverySubjectThroughEveryConsumer(unittest.TestCase):
    def test_the_probes_cover_exactly_the_consumers_the_table_names(self) -> None:
        self.assertEqual(set(reading.CONSUMER_SUBJECTS), set(CONSUMERS))

    def test_each_consumer_reads_the_subjects_its_row_admits_and_no_other(self) -> None:
        for name, probe in CONSUMERS.items():
            for subject in ALL_SUBJECTS:
                with self.subTest(consumer=name, subject=subject):
                    self.assertEqual(
                        subject in reading.CONSUMER_SUBJECTS[name],
                        probe(subject),
                        f"{name} and {subject} disagree with CONSUMER_SUBJECTS",
                    )

    def test_a_row_names_only_subjects_the_probe_list_knows(self) -> None:
        for name, subjects in reading.CONSUMER_SUBJECTS.items():
            with self.subTest(consumer=name):
                self.assertLessEqual(subjects, set(ALL_SUBJECTS))

    def test_a_command_that_cannot_fail_reaches_no_consumer(self) -> None:
        cannot = {**fact("command"), "summary": "echo done", "cannot_fail": True}
        rows = reading.build_ledger([cannot], "claude", "s1", tool_output={})
        self.assertFalse(any(row["work"] for row in rows))
        self.assertIsNone(live_monitor._turn_text(cannot))
        self.assertFalse(
            any(reading.check_supports(r, reading.RESULT_CONSISTENT, 0.0) for r in rows)
        )


class NoCommandReachesARowOrTheHistory(ClaudeChecksTestCase):
    def test_a_session_row_and_the_history_store_carry_no_command_field(self) -> None:
        for field in runtime_history.OBSERVATION_FIELDS:
            with self.subTest(field=field):
                self.assertNotIn("command", field)

    def test_the_scan_a_row_carries_holds_only_counts_of_commands(self) -> None:
        self.session.bash("make deploy", "done", is_error=False)
        self.session.bash("gh pr checks 1", "ok", is_error=False)
        _entries, scan = self.read()
        found = {
            key: value
            for key, value in scan.items()
            if key == "commands" or key.startswith(("command_", "ci_"))
        }
        self.assertTrue(found)
        for key, value in found.items():
            with self.subTest(key=key):
                self.assertIs(int, type(value))

    def test_the_ledger_of_an_unasked_reading_lists_no_command_fact(self) -> None:
        self.session.bash("make deploy", "boom", is_error=True)
        self.session.bash("gh pr checks 1", "Exit code 1\nfailing", is_error=True)
        entries, _scan = self.read()
        facts = [
            project_context._semantic_fact_from_event(
                dict(row), str(row["kind"]), "tool_report", ""
            )
            for row in entries
        ]
        self.assertTrue(facts)
        self.assertEqual((), reading.build_ledger(facts, "claude", SHORT))
        for fact in facts:
            self.assertIsNone(semantic_history._event_from_fact(fact, {}))


class TheProducerEmitsOnlyNamedSubjects(ClaudeChecksTestCase):
    def test_every_kind_of_entry_a_transcript_can_hold_has_a_subject_the_test_covers(self) -> None:
        self.session.bash("pytest -q", "3 passed", is_error=False)
        self.session.bash("make deploy", "done", is_error=False)
        self.session.bash("gh pr checks 1", "ok", is_error=False)
        self.session.write(self.file("src/a.py"))
        call_id = self.session.call("Skill", {"skill": "widget-skill"})
        self.session.result(call_id, "Launching skill", tool_use_result={"success": True})
        call_id = self.session.call("Bash", {"command": "npm run dev", "run_in_background": True})
        self.session.result(call_id, "Command running in background with ID: b2.")
        entries, _scan = self.read()
        self.assertLessEqual({event["subject"] for event in entries}, set(ALL_SUBJECTS))
        self.assertGreaterEqual(
            {event["subject"] for event in entries},
            {"check", "command", "ci_command", "write", "skill", "launch"},
        )


if __name__ == "__main__":
    unittest.main()
