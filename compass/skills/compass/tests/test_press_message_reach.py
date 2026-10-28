"""A press reads the focused session's messages back to the window's start.

The tail reads cover 400,000 bytes. A long session outgrows that before its first turn, so what
the agent said it had done sat outside the reading (measured on a 1.82 MB transcript whose tail
began four minutes after the Goal). Only a reader's Analyze press reads back; ordinary
collection keeps the tail, which these tests pin as well.
"""

from __future__ import annotations

import json
import math
from dataclasses import replace
from types import SimpleNamespace
from typing import Any
from unittest import mock

from compass_runtime import http_api, observer, project_context, reading
from compass_runtime.state import build_runtime_state

from . import test_claude_checks as checks
from . import test_reading as producer

NOW = checks.START.timestamp() + 3600
EARLY = "The connection to the remote works."


class PressReachTestCase(checks.ClaudeChecksTestCase):
    def setUp(self) -> None:
        super().setUp()
        patcher = mock.patch.object(observer.CodexGoalModel, "__call__", return_value=None)
        patcher.start()
        self.addCleanup(patcher.stop)
        # The goal prompt is the first record, five seconds into the file.
        self.window = checks.START.timestamp() + 5

    def say(self, text: str) -> None:
        self.session._entry("assistant", [{"type": "text", "text": text}])

    def long_session(self, turns: int = 40, *, pad: int = 3000) -> None:
        """The first turn answers the goal, then enough padding to leave it outside a small tail."""
        self.say(EARLY)
        for index in range(turns):
            self.session.prompt(f"Continue {index}. " + "x" * pad)

    def stamp(self) -> tuple[int, int, int, int] | None:
        self.session.save(self.path)
        return project_context.transcript_stamp(str(self.path))

    def collect(
        self,
        *,
        reach: project_context.PressWindow | None = None,
        config: Any = None,
    ) -> dict[str, Any]:
        # A press stamps the file before it reads, so a reach saved here must not touch it again.
        if reach is None:
            self.session.save(self.path)
        used = config or replace(self.config, tail_bytes=600)
        rows = [
            {
                "project": "billing",
                "harness": "claude",
                "sid": checks.SHORT,
                "last_activity": NOW,
                "active": True,
            }
        ]
        return project_context.collect(
            used,
            build_runtime_state(used, started=NOW),
            rows,
            "billing",
            now=NOW,
            focus=("claude", checks.SHORT),
            message_reach=reach,
        )

    def window_at(self, start: float | None = None) -> project_context.PressWindow:
        return project_context.PressWindow(self.window if start is None else start, self.stamp())

    @staticmethod
    def facts(context: dict[str, Any], kind: str) -> list[dict[str, Any]]:
        return [fact for fact in context["semantic"]["facts"] if fact.get("type") == kind]

    def said(self, context: dict[str, Any]) -> list[str]:
        return [fact["summary"] for fact in self.facts(context, "agent_message")]


class ThePressReadsBackToTheWindow(PressReachTestCase):
    def test_the_first_turns_agent_message_is_read_when_the_tail_has_lost_it(self) -> None:
        self.long_session()
        context = self.collect(reach=self.window_at())
        self.assertIn(EARLY, self.said(context))
        reach = context["sources"]["message_reach"]
        self.assertIs(reach["tail_truncated"], False)
        self.assertLessEqual(reach["tail_start"], self.window)

    def test_the_same_session_without_a_press_loses_it_and_publishes_no_reach(self) -> None:
        self.long_session()
        context = self.collect()
        self.assertNotIn(EARLY, self.said(context))
        self.assertNotIn("message_reach", context["sources"])

    def test_the_press_stops_after_a_run_of_records_older_than_the_window(self) -> None:
        self.long_session(turns=3)
        later = checks.START.timestamp() + 600
        for _ in range(project_context.PRESS_OLDER_RUN + 2):
            self.session.prompt("Before the window.")
        for row in self.session.rows[-(project_context.PRESS_OLDER_RUN + 2) :]:
            row["timestamp"] = "2026-09-24T02:00:00Z"
        self.say("After the run.")
        self.session.rows[-1]["timestamp"] = checks.START.isoformat().replace("+00:00", "Z")
        context = self.collect(reach=self.window_at(start=later - 900))
        reach = context["sources"]["message_reach"]
        self.assertIs(reach["tail_truncated"], False)
        self.assertLess(reach["tail_start"], self.window)

    def test_a_short_replayed_block_of_older_records_does_not_end_the_read_early(self) -> None:
        self.long_session(turns=3)
        replay = [json.loads(json.dumps(row)) for row in self.session.rows[:5]]
        for index, row in enumerate(replay):
            row["uuid"] = f"replay{index}"
            row["timestamp"] = "2026-09-24T02:00:00Z"
        self.session.rows.extend(replay)
        context = self.collect(reach=self.window_at())
        self.assertIn(EARLY, self.said(context))


class TheReadIsBounded(PressReachTestCase):
    def test_the_byte_bound_marks_the_window_unread_and_names_where_the_read_began(self) -> None:
        for index in range(60):
            self.session.prompt(f"Continue {index}. " + "x" * 300)
        config = replace(self.config, tail_bytes=600, direction_scan_max_bytes=4000)
        context = self.collect(reach=self.window_at(), config=config)
        reach = context["sources"]["message_reach"]
        self.assertIs(reach["tail_truncated"], True)
        self.assertGreater(reach["tail_start"], self.window)

    def test_the_clock_marks_the_window_unread(self) -> None:
        self.long_session(turns=10)
        config = replace(self.config, tail_bytes=600, direction_scan_max_seconds=-1.0)
        context = self.collect(reach=self.window_at(), config=config)
        self.assertIs(context["sources"]["message_reach"]["tail_truncated"], True)

    def test_a_file_that_moved_since_the_press_stamped_it_keeps_the_tail_reads(self) -> None:
        self.long_session(turns=5)
        window = self.window_at()
        with self.path.open("a") as handle:
            handle.write("\n")
        self.assertIsNone(
            project_context.press_message_events(
                self.config, str(self.path), "claude", checks.SHORT, window
            )
        )
        context = self.collect(reach=window)
        self.assertNotIn("message_reach", context["sources"])

    def test_more_messages_than_the_project_keeps_leave_the_window_unread(self) -> None:
        for index in range(project_context.MAX_PROJECT_EVENTS + 20):
            self.say(f"Step {index}.")
        context = self.collect(reach=self.window_at())
        reach = context["sources"]["message_reach"]
        self.assertIs(reach["tail_truncated"], True)
        self.assertGreater(reach["tail_start"], self.window)


class CoverageReadsWhatTheCapKept(PressReachTestCase):
    def test_a_read_that_reached_the_start_still_says_the_cap_dropped_the_oldest(self) -> None:
        for index in range(95):
            self.say(f"Step {index}.")
        # Twelve checks and writes are kept first, and so is the reader's own prompt, so it is the
        # agent's oldest messages that go.
        for index in range(12):
            self.session.write(self.file(f"src/f{index}.py"))
        context = self.collect(reach=self.window_at())
        reach = context["sources"]["message_reach"]
        agent = sorted(fact["at"] for fact in self.facts(context, "agent_message"))
        self.assertLess(len(agent), 95)
        self.assertIs(reach["tail_truncated"], True)
        # The record is whole only after the newest message lost, never "from the Goal's own prompt".
        self.assertGreater(reach["tail_start"], self.window)
        self.assertEqual(agent[0], reach["tail_start"])

    def test_the_page_and_the_cutoff_both_see_that_part_of_the_window_was_not_read(self) -> None:
        for index in range(95):
            self.say(f"Step {index}.")
        for index in range(12):
            self.session.write(self.file(f"src/f{index}.py"))
        reach = self.collect(reach=self.window_at())["sources"]["message_reach"]
        text = reading.cutoff_text([], 0, NOW, window_start=self.window, coverage=reach)
        self.assertIn("The message tail starts", text)

    def test_a_window_of_exactly_the_cap_read_to_its_start_is_complete(self) -> None:
        for index in range(project_context.MAX_PROJECT_EVENTS - 1):
            self.say(f"Step {index}.")
        reach = self.collect(reach=self.window_at())["sources"]["message_reach"]
        self.assertIs(reach["tail_truncated"], False)


class AnUnreadRegionInTheWindowIsNotHidden(PressReachTestCase):
    def test_a_message_too_long_to_redact_marks_the_window_unread_from_where_it_sat(self) -> None:
        self.say(EARLY)
        self.say("x" * (project_context.PRESS_TEXT_MAX_CHARS + 1000))
        self.say("Later one.")
        self.say("Later two.")
        context = self.collect(reach=self.window_at())
        reach = context["sources"]["message_reach"]
        later = [
            fact["at"]
            for fact in self.facts(context, "agent_message")
            if "Later" in fact["summary"]
        ]
        self.assertIs(reach["tail_truncated"], True)
        self.assertEqual(min(later), reach["tail_start"])
        self.assertNotIn("x" * 50, " ".join(self.said(context)))

    def test_a_pasted_image_around_a_short_message_is_read_and_is_not_an_unread_region(
        self,
    ) -> None:
        self.say(EARLY)
        self.session.prompt("Why can it not tell?")
        block = {"type": "image", "source": {"type": "base64", "data": "A" * (3 * 1024 * 1024)}}
        self.session.rows[-1]["message"]["content"].append(block)
        context = self.collect(reach=self.window_at())
        reach = context["sources"]["message_reach"]
        self.assertIs(reach["tail_truncated"], False)
        asked = [fact["summary"] for fact in self.facts(context, "user_message")]
        self.assertIn("Why can it not tell?", asked)

    def test_a_line_the_scan_skips_whole_marks_the_window_unread_the_same_way(self) -> None:
        self.say(EARLY)
        self.say("y" * (17 * 1024 * 1024))
        self.say("Later one.")
        context = self.collect(reach=self.window_at())
        reach = context["sources"]["message_reach"]
        later = [
            fact["at"]
            for fact in self.facts(context, "agent_message")
            if "Later" in fact["summary"]
        ]
        self.assertIs(reach["tail_truncated"], True)
        self.assertEqual(min(later), reach["tail_start"])

    def test_a_large_record_further_back_than_a_record_before_the_window_is_not_unread(
        self,
    ) -> None:
        small = json.loads(json.dumps(self.session.rows[0]))
        big = json.loads(json.dumps(self.session.rows[0]))
        small["uuid"], small["timestamp"] = "old-small", "2026-09-24T02:00:00Z"
        big["uuid"], big["timestamp"] = "old-big", "2026-09-24T01:00:00Z"
        big["message"]["content"][0]["text"] = "z" * (project_context.PRESS_TEXT_MAX_CHARS + 1000)
        self.session.rows[:0] = [big, small]
        self.say(EARLY)
        reach = self.collect(reach=self.window_at())["sources"]["message_reach"]
        self.assertIs(reach["tail_truncated"], False)

    def test_a_stray_older_record_does_not_pull_a_partial_read_back_to_it(self) -> None:
        for index in range(60):
            self.session.prompt(f"Continue {index}. " + "x" * 300)
        self.session.prompt("A replayed record.")
        self.session.rows[-1]["timestamp"] = "2026-09-24T02:00:00Z"
        config = replace(self.config, tail_bytes=600, direction_scan_max_bytes=4000)
        reach = self.collect(reach=self.window_at(), config=config)["sources"]["message_reach"]
        self.assertIs(reach["tail_truncated"], True)
        self.assertGreater(reach["tail_start"], self.window)

    def test_a_read_that_stopped_with_nothing_read_says_its_start_was_not_recorded(self) -> None:
        self.long_session(turns=3)
        config = replace(self.config, tail_bytes=600, direction_scan_max_seconds=-1.0)
        reach = self.collect(reach=self.window_at(), config=config)["sources"]["message_reach"]
        self.assertIs(reach["tail_truncated"], True)
        self.assertIsNone(reach["tail_start"])
        text = reading.cutoff_text([], 0, NOW, window_start=self.window, coverage=reach)
        self.assertIn("its start time was not recorded", text)


class OnlyAUsableWindowReadsBack(PressReachTestCase):
    def test_a_window_that_is_zero_nan_or_in_the_future_reads_the_tail(self) -> None:
        self.long_session(turns=5)
        for start in (0.0, math.nan, NOW + 1000.0, math.inf):
            with self.subTest(start=start):
                context = self.collect(reach=self.window_at(start=start))
                self.assertNotIn("message_reach", context["sources"])
                self.assertNotIn(EARLY, self.said(context))

    def test_a_harness_without_agent_messages_is_not_read_back(self) -> None:
        self.long_session(turns=2)
        self.assertIsNone(
            project_context.press_message_events(
                self.config, str(self.path), "codex", checks.SHORT, self.window_at()
            )
        )


class TheReadMatchesTheTailsParsing(PressReachTestCase):
    def test_invalid_utf8_inside_a_message_is_read_as_the_tail_reads_it(self) -> None:
        self.say("placeholder")
        self.session.save(self.path)
        rows = self.path.read_bytes().rstrip(b"\n").split(b"\n")
        rows[-1] = rows[-1].replace(b"placeholder", b"caf\xe9 works")
        self.path.write_bytes(b"\n".join(rows) + b"\n")
        stamp = project_context.transcript_stamp(str(self.path))
        pressed = project_context.press_message_events(
            self.config,
            str(self.path),
            "claude",
            checks.SHORT,
            project_context.PressWindow(self.window, stamp),
        )
        tail = project_context.agent_message_events(
            self.config, str(self.path), "claude", checks.SHORT
        )
        assert pressed is not None
        said = [event["title"] for event in pressed.events if event["kind"] == "agent_say"]
        self.assertEqual([event["title"] for event in tail], said)
        self.assertEqual(1, len(said))

    def test_nothing_the_press_reads_gains_a_field_a_page_could_publish(self) -> None:
        self.long_session(turns=3)
        context = self.collect(reach=self.window_at())
        published = project_context.for_page(context)
        self.assertNotIn(project_context.AGENT_WORDS_FIELD, json.dumps(published))


class TheHttpPressAsksForItsOwnWindow(PressReachTestCase):
    @staticmethod
    def context() -> dict[str, Any]:
        fact = producer.fact(at=110.0, source_session={"harness": "claude", "sid": checks.SHORT})
        return {"semantic": {"facts": [fact]}}

    def press(self, context: dict[str, Any]) -> tuple[dict[str, Any], list[Any]]:
        self.long_session(turns=2)
        self.session.save(self.path)
        asked: list[Any] = []
        handler = SimpleNamespace(
            server=SimpleNamespace(
                application=SimpleNamespace(
                    config=self.config, state=SimpleNamespace(), clock=lambda: NOW
                )
            ),
            _reading_arguments=lambda *_args, **_kw: {
                "model": lambda *_a, **_kw: ("{}", "ok"),
                "stamp_text": "read",
                "now": NOW,
            },
        )

        def collected(_application: Any, _row: Any, reach: Any = None) -> dict[str, Any]:
            asked.append(reach)
            return context

        with (
            mock.patch.object(http_api, "_session_context", side_effect=collected),
            mock.patch.object(observer, "resolve_transcript", return_value=str(self.path)),
            # The window is what is under test; the press-time CI read has its own suite and
            # needs an application this stand-in does not carry.
            mock.patch.object(http_api, "_read_ci", return_value=None),
        ):
            compose: Any = http_api._RequestHandler._compose_reading
            got, _why, _spent = compose(
                handler,
                {"harness": "claude", "sid": checks.SHORT, "state": "working"},
                {"revisions": [{"n": 1, "at": 50.0, "goal": "Keep retry", "output": "Done"}]},
                {},
                SimpleNamespace(phase=None),
            )
        return got, asked

    def test_the_window_is_the_revision_being_read_and_carries_the_stamp(self) -> None:
        _got, asked = self.press(self.context())
        self.assertEqual(1, len(asked))
        self.assertEqual(50.0, asked[0].start)
        self.assertEqual(project_context.transcript_stamp(str(self.path)), asked[0].stamp)

    def test_coverage_is_what_the_context_says_was_kept_when_it_read_back(self) -> None:
        context = {
            **self.context(),
            "sources": {"message_reach": {"tail_truncated": False, "tail_start": 12.5}},
        }
        got, _asked = self.press(context)
        self.assertIs(got["coverage"]["tail_truncated"], False)
        self.assertEqual(12.5, got["coverage"]["tail_start"])
