"""A partial session reading names what it could and could not read."""

from __future__ import annotations

import os
import unittest
from dataclasses import replace
from types import SimpleNamespace
from typing import Any, ClassVar, cast
from unittest import mock

from compass_runtime import annotations as annotation_store
from compass_runtime import http_api, observer, project_context, reading
from compass_runtime import io as runtime_io

from . import test_claude_checks as checks
from . import test_reading as producer


class ThePressMeasuresTheMessageTail(checks.ClaudeChecksTestCase):
    def test_a_file_changed_after_fact_collection_has_unknown_coverage(self) -> None:
        self.session.save(self.path)
        before = self.path.stat()
        expected = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
        with self.path.open("a") as handle:
            handle.write("\n")
        got = project_context.transcript_tail_coverage(
            self.config, str(self.path), expected_stamp=expected
        )
        self.assertIsNone(got["tail_truncated"])
        self.assertIsNone(got["tail_start"])

    def test_the_http_reading_measures_the_resolved_file_at_the_press(self) -> None:
        self.session.prompt("Padding " + "x" * 4000)
        self.session.prompt("Keep the retry in scope.")
        self.session.save(self.path)
        config = replace(self.config, tail_bytes=600)
        handler = SimpleNamespace(
            server=SimpleNamespace(
                application=SimpleNamespace(
                    config=config, state=SimpleNamespace(), clock=lambda: producer.NOW
                )
            ),
            _reading_arguments=lambda *_args: {
                "model": lambda *_a, **_kw: ("{}", "ok"),
                "stamp_text": "read",
                "now": producer.NOW,
            },
        )
        context = {
            "semantic": {
                "facts": [
                    producer.fact(at=110.0, source_session={"harness": "claude", "sid": "s1"})
                ]
            }
        }
        for changed in (False, True):

            def collected(*_args: Any, changes_file: bool = changed) -> dict[str, Any]:
                if changes_file:
                    with self.path.open("a") as handle:
                        handle.write("\n")
                return context

            with (
                self.subTest(changed=changed),
                mock.patch.object(http_api, "_session_context", side_effect=collected),
                mock.patch.object(observer, "resolve_transcript", return_value=str(self.path)),
            ):
                compose: Any = http_api._RequestHandler._compose_reading
                got, why, spent = compose(
                    handler,
                    {"harness": "claude", "sid": "s1", "state": "working"},
                    {
                        "revisions": [
                            {"n": 1, "at": 50.0, "goal": "Keep retry", "output": "Tests pass"}
                        ]
                    },
                    {},
                    SimpleNamespace(phase=None),
                )
                self.assertEqual("", why)
                self.assertTrue(spent)
                self.assertIs(got["coverage"]["tail_truncated"], None if changed else True)
                self.assertEqual(
                    None if changed else checks.START.timestamp() + 15,
                    got["coverage"]["tail_start"],
                )

    def test_a_short_file_is_measured_complete_even_after_a_long_silence(self) -> None:
        self.session.seconds = 90_000
        self.session.prompt("Continue the same task.")
        self.session.save(self.path)
        got = project_context.transcript_tail_coverage(self.config, str(self.path))
        self.assertIs(got["tail_truncated"], False)
        self.assertEqual(checks.START.timestamp() + 5, got["tail_start"])

    def test_a_large_file_reports_the_first_complete_tail_record(self) -> None:
        self.session.prompt("Padding " + "x" * 4000)
        self.session.prompt("Keep the retry in scope.")
        self.session.save(self.path)
        config = replace(self.config, tail_bytes=600)
        got = project_context.transcript_tail_coverage(config, str(self.path))
        self.assertIs(got["tail_truncated"], True)
        self.assertEqual(checks.START.timestamp() + 15, got["tail_start"])

    def test_a_missing_file_is_unknown_rather_than_a_complete_empty_read(self) -> None:
        got = project_context.transcript_tail_coverage(self.config, str(self.path))
        self.assertIsNone(got["tail_truncated"])
        self.assertIsNone(got["tail_start"])

    def test_a_file_that_changes_during_the_read_has_no_stable_coverage(self) -> None:
        self.session.save(self.path)
        original = runtime_io.read_tail

        def changed(*args: Any, **kwargs: Any) -> list[str]:
            lines = original(*args, **kwargs)
            with self.path.open("a") as handle:
                handle.write("\n")
            return lines

        with mock.patch.object(runtime_io, "read_tail", side_effect=changed):
            got = project_context.transcript_tail_coverage(self.config, str(self.path))
        self.assertIsNone(got["tail_truncated"])

    def test_a_replacement_with_the_same_size_and_time_is_not_the_file_that_was_read(self) -> None:
        self.session.save(self.path)
        before = self.path.stat()
        original = runtime_io.read_tail

        def replaced(*args: Any, **kwargs: Any) -> list[str]:
            lines = original(*args, **kwargs)
            replacement = self.path.with_suffix(".replacement")
            replacement.write_bytes(self.path.read_bytes())
            os.utime(replacement, ns=(before.st_atime_ns, before.st_mtime_ns))
            replacement.replace(self.path)
            return lines

        with mock.patch.object(runtime_io, "read_tail", side_effect=replaced):
            got = project_context.transcript_tail_coverage(self.config, str(self.path))
        self.assertIsNone(got["tail_truncated"])


class TheCutoffNamesKindsAndOmissions(unittest.TestCase):
    def test_a_starved_prompt_still_names_tail_loss_and_omitted_checks(self) -> None:
        text = reading.cutoff_text(
            (),
            2,
            producer.NOW,
            window_start=producer.NOW - 4800,
            coverage={
                "tail_truncated": True,
                "tail_start": producer.NOW - 120,
                "unlisted": 3,
                "unread_checks": 2,
            },
        )
        self.assertIn("None of the 2 entries", text)
        self.assertIn("message tail", text)
        self.assertIn("3 passes or writes in the window", text)
        self.assertIn("2 checks had no room", text)

    def test_checks_and_writes_are_not_counted_as_agent_messages(self) -> None:
        rows = (
            *tuple(
                producer.entry(id=str(n), type="tool_report", subject=subject, result=result)
                for n, (subject, result) in enumerate(
                    (
                        ("check", "passed"),
                        ("check", "failed"),
                        ("check", "not-recorded"),
                        ("write", ""),
                        ("launch", ""),
                    )
                )
            ),
            producer.entry(id="said", type="agent_message"),
            producer.person_entry(),
        )
        text = reading.cutoff_text(rows, len(rows), producer.NOW)
        self.assertIn("1 message from the agent", text)
        for words in (
            "1 passed check",
            "1 failed check",
            "1 check with no recorded result",
            "1 file write",
            "1 launch",
        ):
            self.assertIn(words, text)
        self.assertNotIn("6 messages from the agent", text)

    def test_a_partial_tail_names_the_missing_interval_instead_of_a_false_total(self) -> None:
        rows = (producer.entry(type="agent_message", at=producer.NOW - 60),)
        text = reading.cutoff_text(
            rows,
            1,
            producer.NOW,
            coverage={"tail_truncated": True, "tail_start": producer.NOW - 120},
            window_start=producer.NOW - 4800,
        )
        self.assertIn("78 min", text)
        self.assertIn("message tail", text)
        self.assertNotIn("of the 1 entry after your intent", text)

    def test_listing_omissions_are_the_window_count_not_the_session_wide_more(self) -> None:
        text = reading.cutoff_text(
            (producer.entry(),), 1, producer.NOW, coverage={"unlisted": 3, "unread_checks": 2}
        )
        self.assertIn("3 passes or writes in the window", text)
        self.assertIn("2 check", text)
        self.assertNotIn("Nothing outside that was read", text)

    def test_large_counts_keep_every_loss_clause_and_source_fallback_inside_the_store_cap(
        self,
    ) -> None:
        rows = tuple(
            producer.entry(
                id=str(n), type="tool_report", subject=subject, result=result, at=producer.NOW - 60
            )
            for n, (subject, result) in enumerate(
                (
                    ("check", "passed"),
                    ("check", "failed"),
                    ("check", "not-recorded"),
                    ("write", ""),
                    ("launch", ""),
                )
            )
        )
        rows = (
            *rows,
            producer.person_entry(at=producer.NOW - 60),
            producer.entry(id="said", type="agent_message", at=producer.NOW - 60),
            producer.derived_entry(at=producer.NOW - 60),
        )
        text = reading.cutoff_text(
            rows,
            5000,
            producer.NOW,
            earlier=1000000,
            untimed=1000000,
            after_stop=1000000,
            window_start=producer.NOW - 4800,
            coverage={
                "tail_truncated": True,
                "tail_start": producer.NOW - 120,
                "unlisted": 1000000,
                "unread_checks": 1000000,
                "other_commands": 2**53 - 1,
                "read_only_commands": 2**53 - 2,
            },
        )
        text += reading._goal_note(adopted=True, source=None, goal="Saved excerpt", whole=False)
        # The longest note `produce` appends after it, for a final reply that stayed an excerpt.
        text += max(reading._FINAL_NOTES.values(), key=len)
        self.assertLessEqual(len(text), reading.CUTOFF_CAP_CHARS)
        for words in (
            "message tail",
            "earlier",
            "untimed",
            "stop",
            "passed",
            "failed",
            "no recorded result",
            "file write",
            "launch",
            "unlisted",
            "no room",
            reading.GOAL_SOURCE_GONE.strip(),
        ):
            self.assertIn(words, text)


class TheReadingCarriesMeasuredCoverage(producer.AClaudeCodeReadingProducer):
    def test_a_found_source_already_equal_to_the_goal_is_whole(self) -> None:
        text = "Keep the retry in scope."
        source = producer.fact(
            fact_id="source",
            type="user_message",
            at=40.0,
            reader_words=text,
            source_session={"harness": "claude", "sid": "s1"},
        )
        got, _, _ = reading.produce(
            cast("Any", self.config),
            {"harness": "claude", "sid": "s1", "state": "working"},
            [
                {
                    "n": 1,
                    "at": 50.0,
                    "goal": text,
                    "output": "Tests pass",
                    "goal_source": "first-prompt",
                    "goal_source_at": 40.0,
                }
            ],
            [source, producer.fact(at=110.0, source_session={"harness": "claude", "sid": "s1"})],
            now=200.0,
            stamp_text="read",
            model=self._model(),
            read_lines=True,
            goal_source_lookup=lambda: [source],
        )
        assert got is not None
        assert got["coverage"] is not None
        self.assertEqual("whole", got["coverage"]["goal_source"])

    def _session_goal_coverage(self, goal: str) -> str:
        got, _, _ = reading.produce(
            cast("Any", self.config),
            {"harness": "claude", "sid": "s1", "state": "working"},
            [
                {
                    "n": 1,
                    "at": 50.0,
                    "goal": goal,
                    "output": "Tests pass",
                    "goal_source": reading.SESSION_GOAL,
                    "goal_source_at": 40.0,
                }
            ],
            [producer.fact(at=110.0, source_session={"harness": "claude", "sid": "s1"})],
            now=200.0,
            stamp_text="read",
            model=self._model(),
            read_lines=True,
            goal_source_lookup=list,
        )
        assert got is not None
        assert got["coverage"] is not None
        return cast("str", got["coverage"]["goal_source"])

    def test_a_slash_goal_that_was_not_cut_is_whole(self) -> None:
        # A /goal has no prompt behind it to find, so "no source found" is not a cut.
        self.assertEqual(
            "whole", self._session_goal_coverage("docs/e2e/notes.md exists and contains ready")
        )

    def test_a_slash_goal_cut_to_the_excerpt_is_still_an_excerpt(self) -> None:
        self.assertEqual("excerpt", self._session_goal_coverage("A long condition cut here\u2026"))

    def test_unlisted_work_after_the_stop_is_not_counted_inside_the_read_window(self) -> None:
        output = reading.ToolOutput(
            destination="local",
            label="Local reader",
            passes_and_writes=(("inside", "inside.py", 90.0), ("later", "later.py", 110.0)),
        )
        got, _, _ = reading.produce(
            cast("Any", self.config),
            {"harness": "claude", "sid": "s1", "state": "idle", "finished_at": 100.0},
            [{"n": 1, "at": 50.0, "goal": "Keep retry", "output": "Tests pass"}],
            [producer.fact(at=60.0, source_session={"harness": "claude", "sid": "s1"})],
            now=200.0,
            stamp_text="read",
            model=self._model(),
            read_lines=True,
            admit_turn_stop=True,
            tool_output=output,
        )
        assert got is not None
        assert got["coverage"] is not None
        self.assertEqual("last-turn", got["scope"])
        self.assertEqual(1, got["coverage"]["unlisted"])

    def test_coverage_changes_no_model_prompt_before_the_frozen_pilot(self) -> None:
        for measurement in (None, lambda: {"tail_truncated": True, "tail_start": 100.0}):
            reading.produce(
                cast("Any", self.config),
                {"harness": "claude", "sid": "s1", "state": "working"},
                [{"n": 1, "at": 50.0, "goal": "Keep retry", "output": "Tests pass"}],
                [producer.fact(at=110.0, source_session={"harness": "claude", "sid": "s1"})],
                now=200.0,
                stamp_text="read",
                model=self._model(),
                read_lines=True,
                record_coverage_lookup=measurement,
            )
        self.assertEqual(2, len(self.prompts))
        self.assertEqual(self.prompts[0], self.prompts[1])

    def test_unlisted_counts_only_passes_and_writes_inside_the_read_window(self) -> None:
        output = reading.ToolOutput(
            destination="local",
            label="Local reader",
            passes_and_writes=(("old", "old.py", 40.0), ("new", "new.py", 110.0)),
        )
        got, _, _ = self._produce(
            [producer.fact(at=110.0, source_session={"harness": "claude", "sid": "s1"})],
            tool_output=output,
        )
        self.assertEqual(1, got["coverage"]["unlisted"])
        self.assertIn("1 pass or write in the window", got["cutoff"])

    def test_coverage_is_measured_before_the_model_and_kept_without_words(self) -> None:
        order: list[str] = []

        def coverage() -> dict[str, Any]:
            order.append("coverage")
            return {"tail_truncated": True, "tail_start": 100.0}

        def model(_prompt: str, **_kwargs: Any) -> tuple[str, str]:
            order.append("model")
            return "{}", "ok"

        got, why, spent = reading.produce(
            cast("Any", self.config),
            {"harness": "claude", "sid": "s1", "state": "working"},
            [{"n": 1, "at": 50.0, "goal": "Add retry", "output": "Tests pass"}],
            [producer.fact(at=110.0, source_session={"harness": "claude", "sid": "s1"})],
            now=200.0,
            stamp_text="read",
            model=model,
            read_lines=True,
            record_coverage_lookup=coverage,
        )
        self.assertEqual(["coverage", "model"], order)
        self.assertEqual("", why)
        self.assertTrue(spent)
        self.assertIsNotNone(got)
        assert got is not None
        self.assertEqual(
            {
                "tail_truncated": True,
                "tail_start": 100.0,
                "unlisted": 0,
                "unread_checks": 0,
                "goal_source": "typed",
            },
            got["coverage"],
        )

    def test_the_complete_cutoff_keeps_tail_source_and_grant_loss_inside_the_store_bound(
        self,
    ) -> None:
        facts = [
            producer.fact(
                type="user_message",
                by="person",
                at=110.0,
                source_session={"harness": "claude", "sid": "s1"},
            ),
            producer.fact(
                fact_id="check",
                type="tool_report",
                subject="check",
                result="passed",
                at=120.0,
                source_session={"harness": "claude", "sid": "s1"},
            ),
            producer.fact(
                fact_id="said",
                type="agent_message",
                by="agent",
                agent_words="Finished the synthetic task.",
                at=150.0,
                source_session={"harness": "claude", "sid": "s1"},
            ),
        ]
        got, _, _ = reading.produce(
            cast("Any", self.config),
            {"harness": "claude", "sid": "s1", "state": "working"},
            [
                {
                    "n": 1,
                    "at": 50.0,
                    "goal": "Adopted excerpt",
                    "output": "Tests pass",
                    "goal_source": "first-prompt",
                    "goal_source_at": 50.0,
                }
            ],
            facts,
            now=200.0,
            stamp_text="read",
            model=self._model(),
            read_lines=True,
            read_agent_words=True,
            final_source_lookup=lambda _wanted: {"outcome": "source-moved"},
            record_coverage_lookup=lambda: {"tail_truncated": True, "tail_start": 100.0},
            goal_source_lookup=list,
            tool_output=reading.ToolOutput(
                destination="", label="Named reading model", allowed=False
            ),
        )
        assert got is not None
        self.assertLessEqual(len(got["cutoff"]), reading.CUTOFF_CAP_CHARS)
        self.assertIn("message tail", got["cutoff"])
        self.assertIn(reading.GOAL_SOURCE_GONE.strip(), got["cutoff"])
        self.assertIn("tool output was not allowed", got["cutoff"])
        self.assertIn(reading._FINAL_NOTES["unavailable"].strip(), got["cutoff"])


class CoverageSurvivesTheStoreWithoutNewWords(producer.AClaudeCodeReadingProducer):
    def stored(self) -> dict[str, Any]:
        got, _, _ = self._produce(
            [producer.fact(at=110.0, source_session={"harness": "claude", "sid": "s1"})]
        )
        return cast("dict[str, Any]", got)

    def test_a_measured_zero_is_kept_but_legacy_coverage_is_unknown(self) -> None:
        value = self.stored()
        kept = annotation_store._assessment(value, 240)
        assert kept is not None
        assert kept["coverage"] is not None
        self.assertEqual(0, kept["coverage"]["unlisted"])
        value.pop("coverage")
        legacy = annotation_store._assessment(value, 240)
        assert legacy is not None
        self.assertIsNone(legacy.get("coverage"))

    def test_malformed_coverage_refuses_the_reading_instead_of_repairing_the_count(self) -> None:
        value = self.stored()
        for patch in (
            {"unlisted": True},
            {"unread_checks": -1},
            {"tail_start": float("nan")},
            {"tail_start": 10**400},
            {"tail_start": 253402300800},
            {"unlisted": 2**53},
            {"tail_truncated": "false"},
            {"goal_source": "guessed"},
            {"words": "private extra field"},
        ):
            with self.subTest(patch=patch):
                forged = {**value, "coverage": {**value["coverage"], **patch}}
                self.assertIsNone(annotation_store._assessment(forged, 240))


class TheCutoffCountsTheCommandsItNeverSaw(producer.AClaudeCodeReadingProducer):
    def _read(self, counts: Any) -> dict[str, Any]:
        got, _, _ = reading.produce(
            cast("Any", self.config),
            {"harness": "claude", "sid": "s1", "state": "working"},
            [{"n": 1, "at": 50.0, "goal": "Keep retry", "output": "Tests pass"}],
            [producer.fact(at=110.0, source_session={"harness": "claude", "sid": "s1"})],
            now=200.0,
            stamp_text="read",
            model=self._model(),
            read_lines=True,
            command_counts_lookup=counts,
        )
        return cast("dict[str, Any]", got)

    def test_seven_other_commands_are_named_and_split_by_whether_they_were_read_only(self) -> None:
        got = self._read(lambda: {"other_commands": 7, "read_only_commands": 4})
        self.assertEqual(7, got["coverage"]["other_commands"])
        self.assertEqual(4, got["coverage"]["read_only_commands"])
        self.assertIn(
            "The session ran 7 other commands, 4 of them read-only; Compass did not read what they did.",
            got["cutoff"],
        )

    def test_one_command_and_none_are_worded_apart(self) -> None:
        one = self._read(lambda: {"other_commands": 1, "read_only_commands": 0})
        self.assertIn("The session ran 1 other command, none of them read-only;", one["cutoff"])
        none = self._read(lambda: {"other_commands": 0, "read_only_commands": 0})
        self.assertEqual(0, none["coverage"]["other_commands"])
        self.assertNotIn("other command", none["cutoff"])

    def test_counts_beyond_the_entries_read_are_the_sessions_not_the_windows(self) -> None:
        got = self._read(lambda: {"other_commands": 412, "read_only_commands": 300})
        self.assertIn("The session ran 412 other commands, 300 of them read-only;", got["cutoff"])
        self.assertNotIn("Compass read only when", got["cutoff"])

    def test_a_scan_cut_from_the_tail_records_neither_count(self) -> None:
        scan = {"harness": "claude", "sid": "s1", "other_commands": 3, "read_only_commands": 3}
        whole = {"sources": {"work": {"tool_reports": [scan]}}}
        cut = {"sources": {"work": {"tool_reports": [{**scan, "reads_from": 1.0}]}}}
        self.assertEqual(
            {"other_commands": 3, "read_only_commands": 3},
            http_api._command_counts_of(whole, "claude", "s1"),
        )
        self.assertEqual({}, http_api._command_counts_of(cut, "claude", "s1"))

    def test_a_count_nobody_measured_is_left_out_not_written_as_zero(self) -> None:
        for lookup in (None, dict, lambda: {"other_commands": True, "read_only_commands": 0}):
            with self.subTest(lookup=lookup):
                got = self._read(lookup)
                self.assertNotIn("other_commands", got["coverage"])
                self.assertNotIn("other command", got["cutoff"])

    def test_the_http_reading_takes_the_counts_from_this_sessions_scan(self) -> None:
        scans = [
            {"harness": "claude", "sid": "other", "other_commands": 9, "read_only_commands": 9},
            {"harness": "claude", "sid": "s1", "other_commands": 7, "read_only_commands": 4},
        ]
        got = http_api._command_counts_of(
            {"sources": {"work": {"tool_reports": scans}}}, "claude", "s1"
        )
        self.assertEqual({"other_commands": 7, "read_only_commands": 4}, got)
        self.assertEqual({}, http_api._command_counts_of({}, "claude", "s1"))


class CoverageAcceptsBothShapesAndRefusesAMalformedCount(unittest.TestCase):
    OLD: ClassVar[dict[str, Any]] = {
        "tail_truncated": False,
        "tail_start": 100.0,
        "unlisted": 0,
        "unread_checks": 0,
        "goal_source": "typed",
    }

    def test_an_older_reading_still_validates_and_gains_no_counts(self) -> None:
        self.assertEqual(self.OLD, reading.validate_coverage(dict(self.OLD)))

    def test_a_newer_reading_validates_with_both_counts(self) -> None:
        new = {**self.OLD, "other_commands": 7, "read_only_commands": 4}
        self.assertEqual(new, reading.validate_coverage(dict(new)))

    def test_a_malformed_or_lone_count_is_refused_not_read_as_zero(self) -> None:
        for patch in (
            {"other_commands": 7},
            {"read_only_commands": 4},
            {"other_commands": True, "read_only_commands": 0},
            {"other_commands": -1, "read_only_commands": 0},
            {"other_commands": 2**53, "read_only_commands": 0},
            {"other_commands": "7", "read_only_commands": 4},
            {"other_commands": None, "read_only_commands": None},
            {"other_commands": 3, "read_only_commands": 4},
        ):
            with self.subTest(patch=patch):
                self.assertIsNone(reading.validate_coverage({**self.OLD, **patch}))
