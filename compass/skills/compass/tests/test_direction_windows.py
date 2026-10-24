"""A listed direction is reachable without moving an unchanged goal's window."""

from __future__ import annotations

import contextlib
import copy
import dataclasses
import http.client
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest import mock

from compass_runtime import (
    aggregate,
    http_api,
    levels,
    project_context,
    reading,
    record_pages,
    records,
)
from compass_runtime import annotations as annotation_store

from . import test_correction as correction_tests
from .support import make_runtime, make_server, serve_until_closed
from .test_claude_checks import SHORT
from .test_direction_adoption import FIRST_AT, LONG, NOW, _ClaudeSession, _row

DEPARTS = reading.RESULT_DEPARTURE
CONSISTENT = reading.RESULT_CONSISTENT
_WHO = {"harness": "claude", "sid": "focus-1"}
_EVIDENCE = {"source": "Claude Bash call and paired result", "confidence": "exact"}


def _report(fact_id: str, at: float, subject: str, **extra: Any) -> dict[str, Any]:
    return {
        "fact_id": fact_id,
        "at": at,
        "type": "tool_report",
        "subject": subject,
        "source_session": _WHO,
        "evidence": _EVIDENCE,
        **extra,
    }


# A passing check and three writes in a window opening at 100, plus one write before it.
NO_FAILURE = (
    _report("c-pass", 104.5, "check", result="passed", summary="pytest tests/parser"),
    _report("w-lex", 104.6, "write", summary="src/parser/lex.py"),
    _report("w-gram", 104.7, "write", summary="src/parser/grammar.py"),
    _report("w-readme", 104.8, "write", summary="README.md"),
    _report("w-early", 99.5, "write", summary="old/notes.md"),
)


def scan_for(facts: tuple[dict[str, Any], ...]) -> dict[str, Any]:
    """Full and numbered-window counts, with omitted paths on both sides."""
    checks = [f for f in facts if f["subject"] == "check"]
    writes = [f for f in facts if f["subject"] == "write"]
    return {
        "harness": "claude",
        "sid": "focus-1",
        "failed": sum(1 for f in checks if f.get("result") == "failed"),
        "passed": sum(1 for f in checks if f.get("result") == "passed"),
        "not_recorded": 0,
        "background": 0,
        "written_paths": len(writes) + (2 if writes else 0),
        "window_written_paths": sum(f["at"] >= 100 for f in writes) + (1 if writes else 0),
        "window_start": 100,
        "outside_paths": 0,
        "more": 0,
        "last_changing_command_at": None,
        "check_runs": len(checks),
        "distinct_checks": len(checks),
    }


def criterion(result: str | None, *cites: str) -> dict[str, Any]:
    row: dict[str, Any] = {"cites": list(cites), "why": "", "detail": ""}
    if result is not None:
        row["result"] = result
    return row


def assessment(criteria: dict[str, Any], **over: Any) -> dict[str, Any]:
    value: dict[str, Any] = {
        "revision_read": 2,
        "window_start": 100,
        "read_at": 106.0,
        "evidence_through": 105.0,
        "criteria": criteria,
    }
    value.update(over)
    return value


def server_level(value: dict[str, Any], facts: tuple[dict[str, Any], ...]) -> str:
    """What the server's function answers for this reading over these facts."""
    lines = sum(1 for key in value["criteria"] if key.startswith("line_"))
    return levels.analysis_level(
        value, levels.Evidence(facts, scan_for(facts), 0), outcome_lines=lines
    ).level


class AnUnchangedGoalKeepsItsWindow(unittest.TestCase):
    def setUp(self) -> None:
        home = tempfile.TemporaryDirectory()
        self.addCleanup(home.cleanup)
        self.config, self.state = make_runtime(state_home=home.name, state_dir=Path(home.name))
        annotation_store.annotate(
            self.config,
            self.state,
            "claude",
            "s1",
            goal="Ship retry",
            lines=["Pass checks"],
            now=1000.0,
            window_start=100.0,
        )

    def saved(self) -> Any:
        entry = annotation_store.find(annotation_store.load(self.config), "claude", "s1")
        assert entry is not None
        return entry["revisions"][-1]

    def test_a_lines_only_save_keeps_the_window(self) -> None:
        annotation_store.annotate(
            self.config,
            self.state,
            "claude",
            "s1",
            lines=["Pass all checks"],
            now=2000.0,
            window_start=1900.0,
            expected_revision=1,
        )
        self.assertEqual(100.0, self.saved()["window_start"])

    def test_repeating_the_goal_with_new_lines_keeps_the_window(self) -> None:
        annotation_store.annotate(
            self.config,
            self.state,
            "claude",
            "s1",
            goal="Ship retry",
            lines=["Pass all checks"],
            now=2000.0,
            window_start=1900.0,
            expected_revision=1,
        )
        self.assertEqual(100.0, self.saved()["window_start"])

    def test_add_keeps_the_same_typed_goals_window(self) -> None:
        outcome = annotation_store.add_direction(
            self.config,
            self.state,
            {"harness": "claude", "sid": "s1"},
            source_id="fact:0123456789abcdef",
            text="Every retry is bounded",
            entry_at=1500.0,
            expected_revision=1,
            now=2000.0,
            window_start=1900.0,
        )
        self.assertEqual("stored", outcome)
        self.assertEqual(100.0, self.saved()["window_start"])

    def test_new_goal_words_keep_the_window_unless_read_from_now_is_asked(self) -> None:
        """The owner's ruling of 2026-10-21 replaced "new goal words move the window"."""
        annotation_store.annotate(
            self.config,
            self.state,
            "claude",
            "s1",
            goal="Ship parser",
            now=2000.0,
            window_start=1900.0,
            expected_revision=1,
        )
        self.assertEqual(100.0, self.saved()["window_start"])
        annotation_store.annotate(
            self.config,
            self.state,
            "claude",
            "s1",
            goal="Ship parser and lexer",
            now=2100.0,
            window_start=2050.0,
            read_from_now=True,
            expected_revision=2,
        )
        self.assertEqual(2050.0, self.saved()["window_start"])

    def test_clock_step_back_clamps_the_carried_window(self) -> None:
        annotation_store.annotate(
            self.config,
            self.state,
            "claude",
            "s1",
            lines=["Pass all checks"],
            now=90.0,
            window_start=80.0,
            expected_revision=1,
        )
        self.assertEqual(90.0, self.saved()["window_start"])


class AListedDirectionReachesItsSource(_ClaudeSession):
    def test_a_source_disappearing_or_becoming_unreadable_is_refused(self) -> None:
        fact_id = str(self.direction()["fact_id"])
        for failure in (FileNotFoundError, PermissionError):
            with (
                self.subTest(failure=failure.__name__),
                mock.patch("compass_runtime.record_pages.open", side_effect=failure, create=True),
            ):
                self.assertEqual(
                    "",
                    project_context.direction_text(
                        self.config, self.state, "claude", SHORT, fact_id
                    ).text,
                )

    def test_a_direction_outside_the_tail_can_be_opened_whole(self) -> None:
        fact_id = str(self.direction()["fact_id"])
        for _ in range(40):
            self.session.bash("pytest", "p" * 200)
        self.session.save(self.path)
        narrow = dataclasses.replace(self.config, tail_bytes=4096)
        self.assertEqual(
            LONG, project_context.direction_text(narrow, self.state, "claude", SHORT, fact_id).text
        )

    def test_the_goal_menu_resolves_a_history_message_without_words(self) -> None:
        fact = self.direction()
        fact.pop("reader_words", None)
        app = SimpleNamespace(config=self.config, state=self.state)
        context = {"semantic": {"facts": [fact]}}
        got = http_api._with_prompt_choices(
            app,
            context,
            [{"harness": "claude", "sid": SHORT, "project": "billing"}],
            ("claude", SHORT),
            "billing",
        )
        self.assertEqual(fact["fact_id"], got["prompt_choices"][0]["fact_id"])
        self.assertEqual(fact["at"], got["prompt_choices"][0]["at"])
        self.assertTrue(got["prompt_choices"][0]["text"].startswith("Use the placeholder lexer"))

    def test_a_child_identity_is_never_offered_as_the_parent_prompt(self) -> None:
        fact = self.direction()
        fact["fact_id"] = "fact:child"
        fact["source_session"] = {"harness": "claude", "sid": "other"}
        app = SimpleNamespace(config=self.config, state=self.state)
        got = http_api._with_prompt_choices(
            app,
            {"semantic": {"facts": [fact]}},
            [{"harness": "claude", "sid": SHORT, "project": "billing"}],
            ("claude", SHORT),
            "billing",
        )
        self.assertTrue(
            all(choice["fact_id"] != fact["fact_id"] for choice in got["prompt_choices"])
        )

    def test_a_direction_beyond_the_source_budget_is_refused(self) -> None:
        fact_id = str(self.direction()["fact_id"])
        with mock.patch.object(
            self, "config", dataclasses.replace(self.config, direction_scan_max_bytes=16)
        ):
            self.assertEqual(
                "",
                project_context.direction_text(
                    self.config, self.state, "claude", SHORT, fact_id
                ).text,
            )

    def test_a_file_changed_while_opening_a_direction_is_refused(self) -> None:
        fact_id = str(self.direction()["fact_id"])
        original = record_pages.scan_source

        def moving(*args: Any, **kwargs: Any) -> record_pages.SourceScan:
            value = original(*args, **kwargs)
            with self.path.open("a") as handle:
                handle.write("\n")
            return value

        with mock.patch.object(record_pages, "scan_source", moving):
            self.assertEqual(
                "",
                project_context.direction_text(
                    self.config, self.state, "claude", SHORT, fact_id
                ).text,
            )

    def test_ambiguous_raw_words_under_one_fact_id_are_refused(self) -> None:
        fact_id = str(self.direction()["fact_id"])
        altered = copy.deepcopy(self.session.rows[-1])
        altered["message"]["content"][0]["text"] = LONG + " Another ending."
        self.session.rows.append(altered)
        self.session.save(self.path)
        self.assertEqual(
            "",
            project_context.direction_text(self.config, self.state, "claude", SHORT, fact_id).text,
        )

    def test_a_menu_refuses_ambiguous_raw_words_before_they_are_folded(self) -> None:
        fact = self.direction()
        altered = copy.deepcopy(self.session.rows[-1])
        altered["message"]["content"][0]["text"] = LONG.replace("Use the", "Use   the", 1)
        self.session.rows.append(altered)
        self.session.save(self.path)
        app = SimpleNamespace(config=self.config, state=self.state)
        choices = http_api._prompt_facts(app, _row(), [fact])
        self.assertFalse(
            any(
                choice["fact_id"] == fact["fact_id"]
                for choice in annotation_store.prompt_choices(_row(), choices, 240)
            )
        )

    def test_goal_menu_masking_does_not_change_or_poison_analyze_words(self) -> None:
        self.session.prompt("Keep retry. AKIAIOSFODNN7\nEXAMPLE")
        self.session.save(self.path)
        before = project_context.transcript_user_facts(
            self.config, self.state, str(self.path), "claude", SHORT
        )
        menu = project_context.transcript_user_facts(
            self.config, self.state, str(self.path), "claude", SHORT, goal_choices=True
        )
        after = project_context.transcript_user_facts(
            self.config, self.state, str(self.path), "claude", SHORT
        )
        self.assertEqual(before, after)
        self.assertNotEqual(before[-1]["reader_words"], menu[-1]["reader_words"])
        self.assertNotIn(records.GOAL_SOURCE_CUT_FIELD, before[-1])
        self.assertNotIn(records.GOAL_SOURCE_CUT_FIELD, project_context.for_page(menu[-1]))

    def test_missing_raw_source_never_offers_folded_words_as_a_goal(self) -> None:
        self.session.prompt("Keep retry. AKIAIOSFODNN7\nEXAMPLE")
        self.session.save(self.path)
        fact = max(
            (item for item in self.facts() if item["type"] == "user_message"),
            key=lambda item: item["at"],
        )
        app = SimpleNamespace(config=self.config, state=self.state)
        with mock.patch(
            "compass_runtime.record_pages.open", side_effect=PermissionError, create=True
        ):
            restored = http_api._prompt_facts(app, _row(), [fact])
            self.assertEqual([], annotation_store.prompt_choices(_row(), restored, 240))

    def test_a_command_cut_before_folding_stays_an_excerpt_in_every_choice(self) -> None:
        self.session.prompt(
            "<command-message>review</command-message>\n<command-name>/review</command-name>\n"
            "<command-args>Keep retry." + " " * 2100 + "later omitted</command-args>"
        )
        self.session.save(self.path)
        fact = max(
            (item for item in self.facts() if item["type"] == "user_message"),
            key=lambda item: item["at"],
        )
        app = SimpleNamespace(config=self.config, state=self.state)
        choices = annotation_store.prompt_choices(
            _row(), http_api._prompt_facts(app, _row(), [fact]), 240
        )
        raw = project_context.direction_text(
            self.config, self.state, "claude", SHORT, str(fact["fact_id"])
        )
        self.assertTrue(raw.cut)
        explicit = annotation_store.prompt_choice(
            str(fact["fact_id"]), float(fact["at"]), raw.text, 240, cut=raw.cut
        )
        self.assertEqual(
            [explicit], [choice for choice in choices if choice["fact_id"] == fact["fact_id"]]
        )

    def test_an_ambiguity_after_the_fact_cap_still_refuses_an_earlier_choice(self) -> None:
        words = "Keep   retries bounded.\nUse the original boundary."
        self.session.prompt(words)
        self.session.save(self.path)
        fact = max(
            (item for item in self.facts() if item["type"] == "user_message"),
            key=lambda item: item["at"],
        )
        duplicate = copy.deepcopy(self.session.rows[-1])
        duplicate["message"]["content"][0]["text"] = words.replace("   ", " ").replace(
            "original boundary", "changed boundary"
        )
        for k in range(project_context.TRANSCRIPT_USER_FACTS_MAX):
            self.session.prompt(f"Use fixture {k} to check the boundary.")
        self.session.rows.append(duplicate)
        self.session.save(self.path)
        self.assertLess(self.path.stat().st_size, project_context.SEMANTIC_BACKFILL_MAX_BYTES)
        # The fact cap is what this test measures, so the wall-clock allowance must not end the read first:
        # under coverage tracing the default two seconds stopped it at 1,281 facts on CI.
        config = dataclasses.replace(self.config, direction_scan_max_seconds=600.0)
        source = project_context.transcript_user_facts(
            config, self.state, str(self.path), "claude", SHORT, goal_choices=True
        )
        self.assertEqual(project_context.TRANSCRIPT_USER_FACTS_MAX, len(source))
        app = SimpleNamespace(config=config, state=self.state)
        choices = annotation_store.prompt_choices(
            _row(), http_api._prompt_facts(app, _row(), [fact]), 240
        )
        self.assertFalse(any(choice["fact_id"] == fact["fact_id"] for choice in choices))


class AReadingKeepsTheBaselineItRead(unittest.TestCase):
    def test_a_message_after_the_read_does_not_erase_a_departure(self) -> None:
        row = correction_tests.session_row(
            annotation_assessment=correction_tests.reading(
                goal=correction_tests.row_of(correction_tests.DEPARTED, ("write",))
            )
        )
        row["annotation_assessment"]["read_at"] = 120.0
        facts = (
            correction_tests.fact("write", 110, "agent_message"),
            correction_tests.fact("later", 130, "user_message"),
        )
        got = correction_tests.compose(row, facts)
        self.assertTrue(got["ok"], got)

    def test_a_message_before_the_read_still_demotes_the_departure(self) -> None:
        row = correction_tests.session_row(
            annotation_assessment=correction_tests.reading(
                goal=correction_tests.row_of(correction_tests.DEPARTED, ("write",))
            )
        )
        row["annotation_assessment"]["read_at"] = 120.0
        facts = (
            correction_tests.fact("write", 110, "agent_message"),
            correction_tests.fact("later", 115, "user_message"),
        )
        self.assertFalse(correction_tests.compose(row, facts)["ok"])

    def test_the_http_level_uses_the_read_time_for_later_directions(self) -> None:
        person = correction_tests.fact("new-person", 107, "user_message")
        person["source_session"] = {"harness": "claude", "sid": "focus-1"}
        facts = [*NO_FAILURE, person]
        value = assessment(
            {
                "goal": criterion(DEPARTS, "task-a"),
                "line_1": criterion(CONSISTENT, "c-pass"),
            },
            read_at=103,
        )
        entry: Any = {
            "assessment": value,
            "revisions": [{"n": 2, "lines": [{"text": "Pass checks", "source": "typed"}]}],
        }
        row = {
            "harness": "claude",
            "sid": "focus-1",
            "annotation_goal": "Ship retry",
            "annotation_goal_saved_at": 103,
        }
        context = {
            "semantic": {"facts": facts},
            "sources": {"work": {"tool_reports": [scan_for(NO_FAILURE)]}},
        }
        app = SimpleNamespace(clock=lambda: 150)
        got = http_api._analysis_levels(app, context, row, entry, 103)[0]["level"]
        expected = server_level(value, NO_FAILURE)
        self.assertEqual(expected, got)


class TheServerVerifiesAnExplicitDirection(_ClaudeSession):
    def test_a_goal_choice_uses_the_same_safe_words_inside_and_outside_the_menu(self) -> None:
        samples = (
            "Keep   retry bounded.",
            "Keep retry. -pPLACEHOLDERpw9",
            "Keep retry. 'deploy:PLACEHOLDERpw9 two@db.example'",
            "Keep retry. AKIAIOSFODNN7\nEXAMPLE",
        )
        for words in samples:
            for newer in (0, 8):
                with self.subTest(words=words, newer=newer):
                    self.session.prompt(words)
                    self.session.save(self.path)
                    selected = max(
                        (fact for fact in self.facts() if fact["type"] == "user_message"),
                        key=lambda fact: fact["at"],
                    )
                    for k in range(newer):
                        self.session.prompt(f"Use fixture variant {k} after {selected['at']}.")
                    self.session.save(self.path)
                    entry = annotation_store.find(
                        annotation_store.load(self.config), "claude", SHORT
                    )
                    revision = entry["revisions"][-1]["n"] if entry else 0
                    with self.serving() as port:
                        opened = self.request(
                            port,
                            "/api/direction",
                            {"harness": "claude", "sid": SHORT, "fact_id": selected["fact_id"]},
                        )
                        choice = opened["goal_choice"]
                        expected = annotation_store.direction_review(
                            words, self.config.annotation_text_cap_chars
                        )[0]
                        self.assertEqual(expected, choice["text"])
                        menu = self.request(
                            port,
                            f"/api/project-context?project=billing&session=claude:{SHORT}&prompts=1",
                        )
                        for offered in menu["prompt_choices"]:
                            if offered["fact_id"] == selected["fact_id"]:
                                self.assertEqual(expected, offered["text"])
                        answer = self.request(
                            port,
                            "/api/annotate",
                            {
                                "harness": "claude",
                                "sid": SHORT,
                                "adopt": "chosen-prompt",
                                "prompt_fact": choice["fact_id"],
                                "expected_prompt": choice["text"],
                                "expected_prompt_at": choice["at"],
                                "expected_revision": revision,
                            },
                        )
                    self.assertEqual("stored", answer["outcome"])
                    saved = annotation_store.load(self.config)[0]["revisions"][-1]
                    self.assertEqual(expected, saved["goal"])

    @contextlib.contextmanager
    def serving(self) -> Any:
        spec = aggregate.HarnessSpec(
            key="claude",
            label="Claude",
            discover=lambda *_: True,
            collect=lambda *_a, **_k: [_row()],
        )
        app = aggregate.Application(
            self.config,
            self.state,
            (spec,),
            clock=lambda: NOW,
            diagnostic_sink=lambda _m: None,
            native_notifier=lambda _p: "",
            popup_notifier=lambda _t, _b: None,
        )
        server = make_server(application=app)
        thread = serve_until_closed(server)
        try:
            yield server.server_port
        finally:
            server.shutdown()
            thread.join(timeout=5)

    @staticmethod
    def request(port: int, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        try:
            connection.request(
                "POST" if body is not None else "GET",
                path,
                body=json.dumps(body).encode() if body is not None else None,
                headers={"Content-Type": "application/json"},
            )
            response = connection.getresponse()
            assert response.status == 200
            parsed = json.loads(response.read())
            assert isinstance(parsed, dict)
            return parsed
        finally:
            connection.close()

    def test_an_explicit_listed_direction_outside_the_five_can_be_adopted(self) -> None:
        old = self.direction()
        for k in range(8):
            self.session.prompt(f"Use retry limit {k} for fixture {k}.")
        self.session.save(self.path)
        annotation_store.annotate(
            self.config, self.state, "claude", SHORT, goal="Ship retry", now=FIRST_AT + 1
        )
        with self.serving() as port:
            menu = self.request(
                port, f"/api/project-context?project=billing&session=claude:{SHORT}&prompts=1"
            )
            self.assertNotIn(old["fact_id"], [r["fact_id"] for r in menu["prompt_choices"]])
            opened = self.request(
                port,
                "/api/direction",
                {"harness": "claude", "sid": SHORT, "fact_id": old["fact_id"]},
            )
            choice = opened["goal_choice"]
            answer = self.request(
                port,
                "/api/annotate",
                {
                    "harness": "claude",
                    "sid": SHORT,
                    "adopt": "chosen-prompt",
                    "prompt_fact": choice["fact_id"],
                    "expected_prompt": choice["text"],
                    "expected_prompt_at": choice["at"],
                    "expected_revision": 1,
                },
            )
        self.assertEqual("stored", answer["outcome"])
        saved = annotation_store.load(self.config)[0]["revisions"][-1]
        self.assertEqual(choice["text"], saved["goal"])
        # The ruling of 2026-10-21: using a direction as the goal keeps the window the saved words had.
        self.assertEqual(FIRST_AT + 1, saved["window_start"])

    def test_unknown_fact_and_changed_expectation_adopt_nothing(self) -> None:
        old = self.direction()
        annotation_store.annotate(
            self.config, self.state, "claude", SHORT, goal="Ship retry", now=FIRST_AT + 1
        )
        with self.serving() as port:
            for fact_id, words in (("fact:unknown", LONG), (old["fact_id"], "Changed expectation")):
                answer = self.request(
                    port,
                    "/api/annotate",
                    {
                        "harness": "claude",
                        "sid": SHORT,
                        "adopt": "chosen-prompt",
                        "prompt_fact": fact_id,
                        "expected_prompt": words,
                        "expected_prompt_at": old["at"],
                        "expected_revision": 1,
                    },
                )
                self.assertEqual("refused", answer["outcome"])
        self.assertEqual(1, len(annotation_store.load(self.config)[0]["revisions"]))

    def test_polled_context_has_no_prompt_choices_until_the_menu_opens(self) -> None:
        with self.serving() as port:
            poll = self.request(
                port, f"/api/project-context?project=billing&session=claude:{SHORT}"
            )
            menu = self.request(
                port, f"/api/project-context?project=billing&session=claude:{SHORT}&prompts=1"
            )
        self.assertNotIn("prompt_choices", poll)
        self.assertGreater(len(menu["prompt_choices"]), 0)
