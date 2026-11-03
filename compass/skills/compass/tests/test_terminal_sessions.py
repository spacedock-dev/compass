"""`--sessions`: the terminal listing against the board's Sessions screen and Attention queue.

The recorded payload and the expected file are the ones `frontend/src/sessions/terminalParity.test.ts`
checks the board against, so a pass here and a pass there mean the terminal and the board give one
answer for the same payload.

`session-groups.json` is the BOARD's output, committed by hand. It must never be regenerated from
this module's port: a file the port wrote would agree with the port by construction and prove nothing.
"""

from __future__ import annotations

import copy
import json
import re
import unittest
from typing import Any

from compass_runtime import events, terminal_sessions

from .support import SERVER_PATH

ROOT = SERVER_PATH.parents[3]
FIXTURES = ROOT / "frontend" / "test" / "fixtures"
PAYLOAD: dict[str, Any] = json.loads(
    (FIXTURES / "client-contract" / "data-session-states.json").read_text(encoding="utf-8")
)["response"]["body"]
EXPECTED: dict[str, Any] = json.loads(
    (FIXTURES / "session-groups.json").read_text(encoding="utf-8")
)["board"]
VOCABULARY: dict[str, Any] = json.loads((FIXTURES / "vocabulary.json").read_text(encoding="utf-8"))
NOTHING = "Nothing is reported as waiting on you."
LEVEL_WORDS = ("None or low", "Low", "Medium", "High", "Not enough recorded yet")
ESC = "\x1b"
NASTY = f"plain {ESC}]52;c;QUJD\x07{ESC}[31mred{ESC}[0m \u202eevil\u2066 tail\x00\x08\x9b\n\tsecond line"


def board() -> terminal_sessions.Board:
    return terminal_sessions.board(PAYLOAD)


def keys(entries: list[Any]) -> list[list[str]]:
    return [[entry.harness, entry.sid] for entry in entries]


def with_rows(**changes: Any) -> dict[str, Any]:
    """The recorded payload with fields changed on the row named by `sid` in each change."""
    payload = copy.deepcopy(PAYLOAD)
    for sid, fields in changes.items():
        for row in payload["sessions"]:
            if row["sid"] == sid:
                row.update(fields)
    return payload


class BoardParityTest(unittest.TestCase):
    def test_the_groups_hold_the_sessions_the_board_holds_in_the_board_order(self) -> None:
        got = board()

        self.assertEqual([row["key"] for row in EXPECTED["active"]], keys(got.active))
        self.assertEqual([row["key"] for row in EXPECTED["history"]], keys(got.history))

    def test_every_row_says_what_the_board_says_about_state_outcome_git_and_the_command(
        self,
    ) -> None:
        got = board()

        for group in ("active", "history"):
            for expected, entry in zip(EXPECTED[group], getattr(got, group), strict=True):
                with self.subTest(group=group, key=expected["key"]):
                    self.assertEqual(
                        {
                            "state": expected["state"],
                            "outcome": expected["outcome"],
                            "git": expected["git"],
                            "command": expected["command"],
                            "ended": expected["ended"],
                            "drift": expected["drift"],
                        },
                        {
                            "state": entry.state,
                            "outcome": entry.outcome,
                            "git": entry.git,
                            "command": entry.command,
                            "ended": entry.ended,
                            "drift": entry.drift,
                        },
                    )

    def test_the_waiting_list_holds_the_sessions_the_attention_queue_holds_in_its_order(
        self,
    ) -> None:
        got = [
            [waiter.entry.harness, waiter.entry.sid]
            if waiter.entry
            else ["ask", waiter.asks[0]["id"]]
            for waiter in board().waiting
        ]

        self.assertEqual(EXPECTED["waiting"], got)

    def test_an_idle_row_with_a_recorded_departure_is_promoted_into_the_active_group(self) -> None:
        self.assertIn(["claude", "f6a7b8c9"], keys(board().active))

    def test_a_departure_promotes_nothing_while_annotations_are_off(self) -> None:
        payload = {**PAYLOAD, "annotate": False}

        got = terminal_sessions.board(payload)

        self.assertNotIn(["claude", "f6a7b8c9"], keys(got.active))
        self.assertIn(["claude", "f6a7b8c9"], keys(got.history))
        self.assertTrue(all(entry.drift is None for entry in got.history))

    def test_an_ask_names_its_owner_only_where_exactly_one_row_matches(self) -> None:
        payload = copy.deepcopy(PAYLOAD)
        twin = copy.deepcopy(next(r for r in payload["sessions"] if r["sid"] == "b2c3d4e5"))
        twin["project"] = "elsewhere"
        payload["sessions"].append(twin)

        waiting = terminal_sessions.board(payload).waiting

        self.assertTrue(all(waiter.entry is None for waiter in waiting if waiter.asks))

    def test_the_two_vocabularies_ported_from_the_page_equal_the_recorded_ones(self) -> None:
        self.assertEqual(
            VOCABULARY["assessmentKeys"], list(terminal_sessions.READING_ASSESSMENT_KEYS)
        )
        self.assertEqual("claims", terminal_sessions.READING_CLAIMS)


class WaitingCallerTest(unittest.TestCase):
    CALLER = "b2c3d4e5-11111111-2222-4333-8444-555500000002"

    def sids(self, exclude: str | None) -> list[str]:
        return [
            waiter.entry.sid
            for waiter in terminal_sessions.board(PAYLOAD, exclude=exclude).waiting
            if waiter.entry
        ]

    def test_the_caller_is_left_out_by_the_resume_id_of_its_row(self) -> None:
        self.assertNotIn("b2c3d4e5", self.sids(self.CALLER))
        self.assertIn("b2c3d4e5", self.sids(None))

    def test_the_caller_is_left_out_by_the_eight_character_prefix_when_a_row_has_no_resume_id(
        self,
    ) -> None:
        payload = with_rows(b2c3d4e5={"resume_id": None})

        got = terminal_sessions.board(payload, exclude=self.CALLER).waiting

        self.assertNotIn("b2c3d4e5", [w.entry.sid for w in got if w.entry])

    def test_only_a_claude_row_can_be_the_caller(self) -> None:
        payload = with_rows(**{"019c0000-1111-7222-8333-444455556666": {"harness": "gemini"}})

        got = terminal_sessions.board(payload, exclude="019c0000-1111-7222-8333-444455556666")

        self.assertIn(
            "019c0000-1111-7222-8333-444455556666",
            [w.entry.sid for w in got.waiting if w.entry],
        )

    def test_a_caller_id_that_is_not_uuid_shaped_leaves_nobody_out(self) -> None:
        for bad in ("not a uuid at all", "zzzzzzzz-zzzz", "b2c3"):
            with self.subTest(bad=bad):
                self.assertEqual(self.sids(None), self.sids(bad))

    def test_the_prefix_rule_is_the_one_the_event_ingress_keys_claude_rows_by(self) -> None:
        for raw in (self.CALLER, "ABCDEF12-0000", "short", "ghijklmn-xx"):
            with self.subTest(raw=raw):
                self.assertEqual(
                    events.normalize_session_id("claude", raw),
                    terminal_sessions.claude_sid(raw),
                )


class SessionsRenderTest(unittest.TestCase):
    def render(self, payload: dict[str, Any] | None = None) -> list[str]:
        return terminal_sessions.render_sessions(payload or PAYLOAD)

    def test_active_sessions_come_first_and_recent_ones_follow_under_their_own_heading(
        self,
    ) -> None:
        lines = self.render()

        active, history = lines.index("Active now"), lines.index("Recent history")
        self.assertLess(active, history)
        self.assertLess(lines.index(next(x for x in lines if "Wire the parser" in x)), history)
        self.assertGreater(lines.index(next(x for x in lines if "Idle and recent" in x)), history)

    def test_a_row_names_its_harness_project_state_and_the_first_line_of_its_goal(self) -> None:
        payload = with_rows(
            a1b2c3d4={
                "annotation_goal": "Ship the parser\nsecond line is not shown",
                "annotation_goal_source": "typed",
            }
        )

        text = "\n".join(self.render(payload))

        self.assertRegex(text, r"Working +Claude Code +alpha-app")
        self.assertIn("Ship the parser", text)
        self.assertNotIn("second line is not shown", text)

    def test_a_long_goal_is_cut_at_one_hundred_and_twenty_characters(self) -> None:
        payload = with_rows(a1b2c3d4={"annotation_goal": "g" * 400})

        line = next(x for x in self.render(payload) if "ggg" in x)

        self.assertIn("g" * 119 + "…", line)
        self.assertNotIn("g" * 121, line)

    def test_the_stop_and_end_sentences_print_on_exactly_the_rows_the_board_draws_them_on(
        self,
    ) -> None:
        text = "\n".join(self.render())
        expected = [
            row["outcome"]
            for group in ("active", "history")
            for row in EXPECTED[group]
            if row["outcome"]
        ]

        found = re.findall(r"(Session ended[^\n]*|Stop observed[^\n]*|Turn stop in [^\n]*)", text)

        self.assertEqual(len(expected), len(found))
        for sentence in expected:
            self.assertIn(sentence, text)

    def test_the_changed_entry_count_prints_where_the_probe_published_one(self) -> None:
        text = "\n".join(self.render())

        self.assertIn("3 changed entries", text)
        self.assertIn("2 changed entries", text)

    def test_no_row_prints_a_drift_level_even_where_a_stored_reading_departs(self) -> None:
        departing = {
            "criteria": {
                "goal": {"result": "departure", "cites": ["the third step"]},
            },
            "revision_read": 1,
            "read_at": 1_899_999_000.0,
        }
        payload = with_rows(f6a7b8c9={"annotation_assessment": departing})

        text = "\n".join(self.render(payload))

        self.assertIn("Drift · ", text)
        for word in LEVEL_WORDS:
            self.assertNotIn(word, text)
        self.assertNotIn("Medium or higher", text)

    def test_a_departure_prints_its_age_against_the_payload_clock(self) -> None:
        text = "\n".join(self.render())

        self.assertIn("Drift · 10m ago", text)

    def test_a_departure_with_no_time_prints_that_its_age_is_unknown(self) -> None:
        payload = with_rows(f6a7b8c9={"departures": [{"revision": 1}]})

        self.assertIn("Drift · age unknown", "\n".join(self.render(payload)))

    def test_a_command_prints_only_for_a_claude_or_codex_row_with_a_valid_published_id(
        self,
    ) -> None:
        text = "\n".join(self.render())
        wanted = {row["command"] for group in ("active", "history") for row in EXPECTED[group]} - {
            ""
        }

        printed = set(re.findall(r"((?:claude --resume|codex resume) \S+)", text))

        self.assertEqual(wanted, printed)
        self.assertNotIn("-dangerous-token", text)
        self.assertEqual(0, text.count("--resume gem"))

    def test_a_row_without_a_published_id_prints_no_command(self) -> None:
        payload = with_rows(a1b2c3d4={"resume_id": None})

        self.assertNotIn("a1b2c3d4-", "\n".join(self.render(payload)))

    def test_a_quiet_row_says_how_long_ago_it_was_last_active_by_the_payload_clock(self) -> None:
        text = "\n".join(self.render())

        self.assertIn("last active 1m ago", text)

    def test_an_ended_row_says_how_long_ago_it_ended_and_a_working_row_states_no_duration(
        self,
    ) -> None:
        lines = self.render()

        self.assertTrue(any("ended 30m ago" in line for line in lines))
        working = lines.index(next(x for x in lines if "Wire the parser" in x))
        self.assertNotRegex("\n".join(lines[working : working + 4]), r"\b\d+[smhd]\b")

    def test_a_board_with_no_active_or_recent_rows_says_so_in_the_boards_own_sentences(
        self,
    ) -> None:
        payload = {**PAYLOAD, "sessions": [], "asks": []}

        text = "\n".join(self.render(payload))

        self.assertIn("No exact session has active evidence right now.", text)
        self.assertIn("No recent-history rows in this payload.", text)

    def test_annotations_off_prints_the_boards_sentence_where_a_goal_would_be(self) -> None:
        payload = {**PAYLOAD, "annotate": False}

        self.assertIn("Annotations off", "\n".join(self.render(payload)))

    def test_the_listing_never_says_unread_and_names_stop_observed_instead(self) -> None:
        text = "\n".join(self.render())

        self.assertNotIn("unread", text.lower())
        self.assertIn("Stop observed", text)

    def test_a_board_missing_every_optional_field_still_prints_each_row(self) -> None:
        payload = {"sessions": [{"harness": "claude", "sid": "x"}, {"harness": 3}, "junk"]}

        text = "\n".join(terminal_sessions.render_sessions(payload))

        self.assertIn("Title not published", text)


class SessionsPrintableTest(unittest.TestCase):
    def test_escape_sequences_and_bidi_controls_are_gone_from_every_printed_value(self) -> None:
        for field in ("title", "annotation_goal", "project", "state_detail"):
            payload = with_rows(a1b2c3d4={field: NASTY})
            with self.subTest(field=field):
                text = "\n".join(terminal_sessions.render_sessions(payload))

                self.assertNotIn(ESC, text)
                self.assertNotIn("\x07", text)
                self.assertNotIn("\x00", text)
                self.assertNotIn("\x9b", text)
                self.assertNotRegex(text, "[\u202a-\u202e\u2066-\u2069]")
                self.assertNotIn("52;c;QUJD", text)

    def test_a_question_and_a_wait_reason_pass_through_the_same_filter(self) -> None:
        payload = copy.deepcopy(PAYLOAD)
        payload["asks"][0]["question"] = NASTY
        payload["asks"][0]["options"] = [NASTY]
        payload["asks"][1]["question"] = NASTY
        for row in payload["sessions"]:
            row["state_detail"] = NASTY

        text = "\n".join(
            terminal_sessions.render_waiting(payload, port=4553, exclude=None, nothing=NOTHING)
        )

        self.assertNotIn(ESC, text)
        self.assertNotRegex(text, "[\u202a-\u202e\u2066-\u2069\x00\x07\x08\x9b]")
        self.assertIn("plain", text)

    def test_printable_drops_whole_sequences_and_keeps_readable_text(self) -> None:
        got = terminal_sessions.printable(NASTY)

        self.assertEqual("plain red evil tail second line", got)

    def test_printable_collapses_line_breaks_and_tabs_to_single_spaces(self) -> None:
        self.assertEqual("a b c", terminal_sessions.printable("a\r\nb\t\tc"))

    def test_printable_accepts_anything_a_payload_may_carry(self) -> None:
        self.assertEqual("", terminal_sessions.printable(None))
        self.assertEqual("3", terminal_sessions.printable(3))
        self.assertEqual("héllo ✓", terminal_sessions.printable("héllo ✓"))


class WaitingRenderTest(unittest.TestCase):
    def render(
        self, payload: dict[str, Any] | None = None, *, exclude: str | None = None
    ) -> list[str]:
        return terminal_sessions.render_waiting(
            payload or PAYLOAD, port=4553, exclude=exclude, nothing=NOTHING
        )

    def block(self, lines: list[str], needle: str) -> str:
        start = next(i for i, line in enumerate(lines) if needle in line)
        end = next(
            (i for i in range(start + 1, len(lines)) if lines[i] and not lines[i].startswith(" ")),
            len(lines),
        )
        return "\n".join(lines[start:end])

    def test_a_held_question_shows_the_question_the_options_the_age_and_the_board_url(self) -> None:
        block = self.block(self.render(), "Choose the retry plan")

        self.assertIn("Approve the retry plan?", block)
        self.assertIn("2 published options", block)
        self.assertIn("4m", block)
        self.assertIn(
            "http://127.0.0.1:4553/#n=session:alpha-app:claude:b2c3d4e5&from=attention", block
        )
        self.assertIn("claude --resume b2c3d4e5-", block)

    def test_a_wait_with_no_question_says_what_the_harness_published_and_how_long(self) -> None:
        block = self.block(self.render(), "Review the schema")

        self.assertIn("waiting on a permission prompt", block)
        self.assertIn("1h 1m", block)
        self.assertNotIn("#n=session", block)

    def test_an_unconfirmed_wait_carries_the_boards_caution(self) -> None:
        block = self.block(self.render(), "Review the schema")

        self.assertIn(
            "Unconfirmed: no positive observation in 5m; prompt may still be standing", block
        )

    def test_a_wait_with_no_published_words_says_the_state_was_reported(self) -> None:
        payload = with_rows(c3d4e5f6={"state_detail": ""})

        block = self.block(self.render(payload), "Review the schema")

        self.assertIn("Needs-input state reported", block)

    def test_a_question_nobody_owns_points_at_the_attention_screen_alone(self) -> None:
        block = self.block(self.render(), "Which environment should this deploy to?")

        self.assertIn("http://127.0.0.1:4553/#n=attention", block)
        self.assertNotIn("#n=session", block)

    def test_the_board_url_percent_encodes_every_part_as_the_page_does(self) -> None:
        payload = with_rows(b2c3d4e5={"project": "a b/c:é"})
        payload["asks"][0]["project"] = "a b/c:é"

        text = "\n".join(self.render(payload))

        self.assertIn("#n=session:a%20b%2Fc%3A%C3%A9:claude:b2c3d4e5&from=attention", text)

    def test_the_list_is_in_the_order_the_attention_queue_draws_it(self) -> None:
        lines = self.render()
        titles = [
            "Choose the retry plan",
            "Which environment should this deploy to?",
            "Ended while it still asked for input",
            "Review the schema",
            "Document the endpoint",
        ]

        positions = [next(i for i, x in enumerate(lines) if title in x) for title in titles]

        self.assertEqual(sorted(positions), positions)

    def test_the_oldest_question_comes_first_and_a_wait_with_a_stamp_before_one_without(
        self,
    ) -> None:
        payload = copy.deepcopy(PAYLOAD)
        payload["asks"][1]["age_sec"] = 900
        for row in payload["sessions"]:
            if row["sid"] == "c3d4e5f6":
                row["blocked_since"] = None

        lines = self.render(payload)

        def at(text: str) -> int:
            return next(i for i, line in enumerate(lines) if text in line)

        self.assertLess(at("Which environment"), at("Choose the retry plan"))
        self.assertLess(at("Document the endpoint"), at("Review the schema"))
        self.assertIn("Wait duration not published", self.block(lines, "Review the schema"))

    def test_an_ended_session_the_board_hides_behind_a_risk_row_is_not_listed(self) -> None:
        self.assertNotIn("Ended dirty while it asked for input", "\n".join(self.render()))

    def test_an_ended_session_with_a_stuck_signal_or_a_quiet_launch_is_hidden_too(self) -> None:
        loop = {"errors": 3, "failures": 5}
        launch = {
            "delegated_launches": 2,
            "delegated_unpaired": 1,
            "delegated_quiet_since": 1_899_999_000.0 - 4000,
        }
        for name, fields in (("stuck", {"loop": loop}), ("quiet launch", launch)):
            payload = with_rows(a7b8c9d0=fields)
            with self.subTest(name):
                self.assertNotIn(
                    "Ended while it still asked for input", "\n".join(self.render(payload))
                )

    def test_the_caller_is_not_listed_when_the_command_runs_inside_a_session(self) -> None:
        text = "\n".join(self.render(exclude="b2c3d4e5-11111111-2222-4333-8444-555500000002"))

        self.assertNotIn("Choose the retry plan", text)
        self.assertIn("Review the schema", text)

    def test_nothing_waiting_says_so_and_states_the_coverage_gap_and_never_all_clear(self) -> None:
        payload = {**PAYLOAD, "sessions": [], "asks": []}

        lines = self.render(payload)
        text = "\n".join(lines)

        self.assertEqual(NOTHING, lines[0])
        self.assertIn("0 of 0 sessions report block state · 0 unknown · ends unobservable", text)
        self.assertIn("Gemini CLI: Harness does not report blocks", text)
        for word in ("all clear", "All clear", "nothing to do", *LEVEL_WORDS):
            self.assertNotIn(word, text)

    def test_the_coverage_line_is_derived_from_the_rows_and_never_authored(self) -> None:
        text = "\n".join(self.render())

        self.assertIn(EXPECTED["coverage"], text)
        for line in EXPECTED["unreported"]:
            self.assertIn(line, text)

    def test_a_harness_whose_source_could_not_be_read_is_named_with_that_reason(self) -> None:
        payload = copy.deepcopy(PAYLOAD)
        payload["harnesses"][2]["error"] = "store unreadable"
        payload["sessions"] = [r for r in payload["sessions"] if r["harness"] != "gemini"]
        payload["asks"] = []

        text = "\n".join(self.render(payload))

        self.assertIn("Gemini CLI: Harness source could not be read", text)

    def test_ends_unobservable_replaces_the_end_count_when_the_payload_says_so(self) -> None:
        payload = {**PAYLOAD, "ends_observable": True}

        self.assertIn("ends observed on 3 sessions", "\n".join(self.render(payload)))

    def test_the_coverage_line_prints_whenever_something_is_waiting_too(self) -> None:
        self.assertIn("report block state", "\n".join(self.render()))


HOSTILE = "\x1b]52;c;QUJD\x07\x1b[31m\u202e\u2066x\x00"


def assert_clean(test: unittest.TestCase, text: str) -> None:
    test.assertNotIn(ESC, text)
    test.assertNotRegex(text, "[\u202a-\u202e\u2066-\u2069\x00\x07\x08\x9b]")
    test.assertNotIn("52;c;QUJD", text)


class CoverageTextTest(unittest.TestCase):
    def hostile_payload(self) -> dict[str, Any]:
        payload = copy.deepcopy(PAYLOAD)
        payload["harnesses"][2]["label"] = HOSTILE
        payload["harnesses"].append(
            {"key": HOSTILE, "label": "", "reports_needs_input": False, "discovered": True}
        )
        payload["harnesses"].append(
            {"key": "x", "label": HOSTILE, "error": HOSTILE, "reports_needs_input": True}
        )
        return payload

    def test_a_hostile_harness_label_or_key_survives_neither_listing(self) -> None:
        payload = self.hostile_payload()

        sessions = "\n".join(terminal_sessions.render_sessions(payload))
        waiting = "\n".join(
            terminal_sessions.render_waiting(payload, port=4553, exclude=None, nothing=NOTHING)
        )

        assert_clean(self, sessions)
        assert_clean(self, waiting)
        self.assertIn("Harness does not report blocks", waiting)

    def test_a_label_that_is_nothing_but_controls_falls_back_to_a_plain_name(self) -> None:
        payload = copy.deepcopy(PAYLOAD)
        payload["harnesses"][2]["label"] = "\x1b[31m\x00"
        payload["harnesses"][2]["key"] = "\x00"

        waiting = "\n".join(
            terminal_sessions.render_waiting(payload, port=4553, exclude=None, nothing=NOTHING)
        )

        self.assertIn("Harness not published: Harness does not report blocks", waiting)


class AbsurdNumbersTest(unittest.TestCase):
    HUGE = 10**400

    def renders(self, payload: dict[str, Any]) -> tuple[list[str], list[str]]:
        return (
            terminal_sessions.render_sessions(payload),
            terminal_sessions.render_waiting(payload, port=4553, exclude=None, nothing=NOTHING),
        )

    def test_an_integer_too_big_for_a_float_is_no_number_at_all(self) -> None:
        self.assertIsNone(terminal_sessions._num(self.HUGE))
        self.assertIsNone(terminal_sessions._num(-self.HUGE))
        self.assertEqual(3.0, terminal_sessions._num(3))

    def test_a_huge_generated_stamp_is_absent_and_both_listings_still_print(self) -> None:
        payload = {**PAYLOAD, "generated": self.HUGE}

        sessions, waiting = self.renders(payload)

        self.assertIn("Active now", sessions)
        self.assertIn("Waiting on you", waiting)

    def test_a_huge_departure_time_is_an_unknown_age_not_a_crash(self) -> None:
        payload = with_rows(f6a7b8c9={"departures": [{"at": self.HUGE, "revision": 1}]})

        sessions, _ = self.renders(payload)

        self.assertIn("  Drift · age unknown", sessions)

    def test_a_huge_loop_error_count_prints_both_listings(self) -> None:
        payload = with_rows(a7b8c9d0={"loop": {"errors": self.HUGE, "failures": self.HUGE}})

        sessions, waiting = self.renders(payload)

        self.assertIn("Active now", sessions)
        self.assertNotIn("Ended while it still asked for input", "\n".join(waiting))


class SortOrderTest(unittest.TestCase):
    # Pinned to what the board's `localeCompare(..., 'en')` gives, taken from node
    # (`names.sort((a, b) => a.localeCompare(b, 'en'))`) and not from this module.
    NAMES = ("Zeta", "alpha", "Beta", "_tmp", "app-2", "Alpha")
    BOARD_ORDER = ("_tmp", "alpha", "Alpha", "app-2", "Beta", "Zeta")

    def test_waiting_sessions_sort_by_project_the_way_the_board_compares_text(self) -> None:
        sessions = [
            {
                "harness": "claude",
                "sid": f"s{i}",
                "project": name,
                "title": f"t{i}",
                "state": "needs_input",
            }
            for i, name in enumerate(self.NAMES)
        ]
        payload = {"generated": 1000.0, "harnesses": [{"key": "claude"}], "sessions": sessions}

        lines = terminal_sessions.render_waiting(payload, port=4553, exclude=None, nothing=NOTHING)

        got = [m.group(1) for line in lines if (m := re.match(r"claude  (\S+)  t\d", line))]
        self.assertEqual(list(self.BOARD_ORDER), got)


if __name__ == "__main__":
    unittest.main()
