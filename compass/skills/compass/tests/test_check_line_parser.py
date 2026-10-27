"""DRC-4703: one quote-aware parser for a Claude Code check line.

DEC-23 (docs/design-reading-a-session.md) and its 2026-09-25 amendment are the
ruling. The check line is the published fact's `summary` and the prompt row
`reading.build_ledger` sends to a model, so every leak test below reads both.
Every secret here is a placeholder: `EXAMPLEaa EXAMPLEbb`, `EXAMPLEpw` and the
documented `AKIAIOSFODNN7EXAMPLE`.
"""

from __future__ import annotations

import itertools
import json
import ntpath
import os
import re
import shlex
from typing import TYPE_CHECKING, Any
from unittest import mock

from compass_runtime import project_context, reading, records

from .test_claude_checks import SHORT, ClaudeChecksTestCase, Transcript

if TYPE_CHECKING:
    from collections.abc import Callable

HALF_A, HALF_B = "EXAMPLEaa", "EXAMPLEbb"
SECRET = f"{HALF_A} {HALF_B}"
SENTINEL = "zzsentinel7"


def _quotings(value: str) -> dict[str, str]:
    """One value in every quoting a shell accepts, and the two it rejects."""
    ansi = value.replace("\\", "\\\\").replace("'", "\\'")
    return {
        "single": f"'{value}'",
        "double": f'"{value}"',
        "ansi": f"$'{ansi}'",
        "locale": f'$"{value}"',
        "escaped": value.replace(" ", "\\ "),
        "concat": f"'{value[:4]}'\"{value[4:]}\"",
        "continued": "'" + value.replace(" ", " '\\\n'") + "'",
        "newline": "$'" + ansi.replace(" ", "\\n") + "'",
        "literal-newline": "'" + value.replace(" ", "\n") + "'",
        "open-single": f"'{value}",
        "open-double": f'"{value}',
        "open-ansi": f"$'{ansi}",
    }


UNBALANCED = frozenset({"open-single", "open-double", "open-ansi"})
# Wrappers whose unbalanced line is the call's own: every other one hides it
# inside a command string, which leaves only that wrapper segment unread.
TOP_LEVEL_WRAPPERS = frozenset({"none", "env"})

# Each named form of DEC-23 item 5, built from one quoting function. The
# leading assignment quotes its value, since a quoted `NAME=` is a command
# name in every shell and not an assignment.
FORMS: dict[str, Callable[[Callable[[str], str]], str]] = {
    "flag-next": lambda q: f"--password {q(SECRET)}",
    "flag-eq": lambda q: f"--password={q(SECRET)}",
    "flag-eq-whole": lambda q: q(f"--password={SECRET}"),
    "p-joined-whole": lambda q: q(f"-p{SECRET}"),
    "assign-arg": lambda q: f"--env {q('TOKEN=' + SECRET)}",
    "header": lambda q: f"-H {q('Authorization: Bearer ' + SECRET)}",
    "userinfo": lambda q: f"--dsn {q('postgres://app:' + SECRET + '@db/x')}",
    "userinfo-noscheme": lambda q: f"--dsn {q('app:' + SECRET + '@db')}",
}
POSITIONS: dict[str, Callable[[str], str]] = {
    "first": lambda form: f"pytest {form}",
    "middle": lambda form: f"pytest -x {form} -q",
    "last": lambda form: f"pytest -q -x {form}",
}


def _double_quoted(text: str) -> str:
    return '"' + re.sub(r'(["\\$`])', r"\\\1", text) + '"'


WRAPPERS: dict[str, Callable[[str], str]] = {
    "none": lambda line: line,
    "bash -c": lambda line: f"bash -c {shlex.quote(line)}",
    "bash -c (double)": lambda line: f"bash -c {_double_quoted(line)}",
    "sh -c": lambda line: f"sh -c {shlex.quote(line)}",
    "zsh -c": lambda line: f"zsh -c {shlex.quote(line)}",
    "bash -lc": lambda line: f"bash -lc {shlex.quote(line)}",
    "env": lambda line: f"env CI=1 {line}",
    "env bash -c": lambda line: f"env CI=1 bash -c {shlex.quote(line)}",
    "nested": lambda line: "bash -c " + shlex.quote("sh -c " + shlex.quote(line)),
}


class CheckLineTestCase(ClaudeChecksTestCase):
    def fresh(self) -> None:
        """A new transcript on the same fixture, cheaper than `setUp` per case."""
        self.session = Transcript(self.cwd)
        self.session.prompt("Add retry with backoff to the webhook handler.")

    def published(self) -> tuple[str, list[dict[str, Any]], dict[str, Any]]:
        """The published facts and the prompt rows a granted reading would send."""
        events, scan = self.read()
        facts = [
            project_context._semantic_fact_from_event(event, event["kind"], "tool_report", "")
            for event in events
        ]
        press = project_context.claude_check_press(self.config, str(self.path))
        ledger = reading.build_ledger(
            facts,
            "claude",
            SHORT,
            tool_output=press.tails,
            changed_after=press.changed_after,
        )
        self.ledger = list(ledger)
        text = json.dumps(events) + json.dumps(facts) + json.dumps(self.ledger)
        return text, [e for e in events if e["subject"] == "check"], scan

    def assert_the_prompt_row_holds_neither_half(self, checks: list[dict[str, Any]]) -> None:
        """The prompt row on its own: exactly one row per listed check, built from
        its masked line, and neither half of the value anywhere in the rows."""
        # A check's redirect target is a written-path row beside it (DRC-4709).
        rows = [
            row
            for row in self.ledger
            if row["type"] == reading.TOOL_REPORT_TYPE and row.get("subject") == "check"
        ]
        self.assertEqual(len(checks), len(rows), rows)
        for check, row in zip(checks, rows, strict=True):
            self.assertTrue(row["summary"].startswith(check["title"]), row["summary"])
        prompt = json.dumps(self.ledger)
        self.assertNotIn(HALF_A, prompt)
        self.assertNotIn(HALF_B, prompt)


class NoPartOfAMaskedValueSurvivesAnyQuoting(CheckLineTestCase):
    """Form x quoting x position x wrapper: neither half of the value reaches
    the fact or the prompt row, and every balanced case is still a check, so
    the matrix cannot pass by publishing nothing."""

    def test_a_reader_sees_no_part_of_a_masked_value_however_it_was_quoted_or_wrapped(
        self,
    ) -> None:
        cases = 0
        for (form_name, form), quoting, (where, place), (wrapper_name, wrap) in itertools.product(
            FORMS.items(), _quotings("x"), POSITIONS.items(), WRAPPERS.items()
        ):

            def quote(value: str, quoting: str = quoting) -> str:
                return _quotings(value)[quoting]

            command = wrap(place(form(quote)))
            cases += 1
            with self.subTest(form=form_name, quoting=quoting, at=where, wrapper=wrapper_name):
                self.fresh()
                self.session.bash(command, "", is_error=False)
                text, checks, scan = self.published()
                self.assertNotIn(HALF_A, text)
                self.assertNotIn(HALF_B, text)
                self.assert_the_prompt_row_holds_neither_half(checks)
                if quoting in UNBALANCED:
                    self.assertEqual([], checks)
                    top_level = wrapper_name in TOP_LEVEL_WRAPPERS
                    self.assertEqual(1 if top_level else 0, scan["not_run"])
                    self.assertIsNotNone(scan["last_changing_command_at"])
                else:
                    self.assertEqual(1, len(checks), command)
                    self.assertTrue(checks[0]["title"].startswith("pytest"), checks[0]["title"])
        expected = len(FORMS) * len(_quotings("x")) * len(POSITIONS) * len(WRAPPERS)
        self.assertEqual(expected, cases)
        self.assertGreaterEqual(cases, 8 * 12 * 3 * 9)

    def test_a_leading_password_assignment_never_reaches_the_reader_in_any_quoting(self) -> None:
        for quoting, (wrapper_name, wrap) in itertools.product(_quotings("x"), WRAPPERS.items()):
            value = _quotings(SECRET)[quoting]
            with self.subTest(quoting=quoting, wrapper=wrapper_name):
                self.fresh()
                self.session.bash(wrap(f"PGPASSWORD={value} pytest -q"), "", is_error=False)
                text, checks, _scan = self.published()
                self.assertNotIn(HALF_A, text)
                self.assertNotIn(HALF_B, text)
                self.assertEqual(0 if quoting in UNBALANCED else 1, len(checks))
                self.assert_the_prompt_row_holds_neither_half(checks)

    def test_a_redirection_between_a_flag_and_its_value_hides_nothing(self) -> None:
        # The shell strips redirections before argv is built, so the program
        # receives the flag and the value side by side, and so must masking.
        for flag, redirect, (wrapper_name, wrap) in itertools.product(
            ("--password", "--token", "-p", "-P"),
            (" 2>/dev/null ", " 2>&1 ", " > out ", " 2> err.log ", " >out ", " <in ",
             " 3>x ", " &>/dev/null ", " <<<x ", ">/dev/null ", "<in ", " >>log "),
            (("none", WRAPPERS["none"]), ("bash -c", WRAPPERS["bash -c"])),
        ):  # fmt: skip
            command = wrap(f"pytest {flag}{redirect}{HALF_A} -q")
            with self.subTest(flag=flag, redirect=redirect.strip(), wrapper=wrapper_name):
                self.fresh()
                self.session.bash(command, "", is_error=False)
                text, checks, _scan = self.published()
                self.assertEqual(1, len(checks), command)
                self.assertNotIn(HALF_A, text)
                self.assert_the_prompt_row_holds_neither_half(checks)

    def test_a_heredoc_between_a_flag_and_its_value_hides_nothing(self) -> None:
        self.session.bash(f"pytest --password <<EOF {HALF_A} -q\nbody\nEOF", "", is_error=False)
        text, checks, _scan = self.published()
        self.assertEqual(1, len(checks))
        self.assertNotIn(HALF_A, text)

    def test_a_value_the_check_line_masked_is_scrubbed_from_the_output_tail_too(self) -> None:
        # An echoed command (`set -x`, a runner printing its argv) repeats the
        # value in the tool output the prompt row carries.
        for command, echoed in (
            (f"pytest --password '{SECRET}'", f"+ pytest --password '{SECRET}'"),
            (f"pytest --dsn 'app:{SECRET}@db'", f"connecting app:{SECRET}@db"),
            (f"pytest -p{HALF_A}", f"argv: -p{HALF_A}"),
        ):
            with self.subTest(command=command[:14]):
                self.fresh()
                self.session.bash(command, f"{echoed}\n1 passed in 0.1s", is_error=False)
                text, checks, _scan = self.published()
                self.assertEqual(1, len(checks))
                self.assertTrue(
                    any(row.get("tail") for row in self.ledger), "the tail must reach the row"
                )
                self.assertNotIn(HALF_A, text)
                self.assertNotIn(HALF_B, text)


class NoTextFromAnotherSegmentReachesACheckLine(CheckLineTestCase):
    def test_a_sentinel_beside_the_check_is_never_published(self) -> None:
        for command in (
            f"pytest -q && echo {SENTINEL}",
            f"pytest -q; curl -u app:{SENTINEL} https://h/",
            f"pytest -q | grep {SENTINEL}",
            f"pytest -q\nls {SENTINEL}",
            f"pytest -q & echo {SENTINEL}",
            f"bash -c 'pytest -q && echo {SENTINEL}'",
            f"bash -c 'echo {SENTINEL}; pytest -q'",
            f"pytest -q <<< {SENTINEL}",
            f"pytest -q <<<'{SENTINEL} two'",
            f"pytest -q <<EOF\n{SENTINEL}\nEOF",
            f"pytest -k 'x && curl -u app:{SENTINEL} https://h/ && echo",
            f'pytest -k "x ; mysql -u root -p{SENTINEL} && echo done',
        ):
            with self.subTest(command=command.replace(SENTINEL, "S")):
                self.fresh()
                self.session.bash(command, "", is_error=False)
                text, _checks, _scan = self.published()
                self.assertNotIn(SENTINEL, text)


class AnUnterminatedQuoteStaysInItsOwnSegment(CheckLineTestCase):  # D3
    def test_a_quoted_joiner_is_part_of_the_check_and_the_next_command_is_not(self) -> None:
        self.session.bash(
            f"pytest -k 'x && y' && curl -u app:{SENTINEL} https://h/", "", is_error=False
        )
        text, checks, _scan = self.published()
        self.assertEqual(["pytest -k 'x && y'"], [c["title"] for c in checks])
        self.assertNotIn(SENTINEL, text)

    def test_an_unterminated_quote_publishes_nothing_of_the_line(self) -> None:
        self.session.bash(
            f"pytest -k 'x && curl -u app:{SENTINEL} https://h/ && echo", "", is_error=False
        )
        text, checks, _scan = self.published()
        self.assertEqual([], checks)
        self.assertNotIn(SENTINEL, text)
        self.assertNotIn("curl", text)


class UnbalancedQuotingIsACallThatDidNotRun(CheckLineTestCase):  # D4
    def test_it_is_not_listed_and_is_counted_as_not_run(self) -> None:
        self.session.bash(
            "pytest -k 'x",
            "Exit code 2\nbash: unexpected EOF while looking for matching `''",
            is_error=True,
        )
        _text, checks, scan = self.published()
        self.assertEqual([], checks)
        self.assertEqual(1, scan["not_run"])
        self.assertEqual(0, scan["check_runs"])
        self.assertEqual(0, scan["shell_calls"])
        self.assertIsNotNone(scan["last_changing_command_at"])

    def test_the_balanced_line_beside_it_is_a_run(self) -> None:
        # The boring outcome: the count must differ from the one above.
        self.session.bash("pytest -k 'x'", "Exit code 2\nerror", is_error=True)
        _text, checks, scan = self.published()
        self.assertEqual(["failed"], [c["result"] for c in checks])
        self.assertEqual(0, scan["not_run"])
        self.assertEqual(1, scan["check_runs"])

    def test_it_still_ages_an_earlier_pass(self) -> None:
        self.session.bash("pytest", "5 passed", is_error=False)
        self.session.bash("rm -rf build; pytest -k 'x", "Exit code 2\nsyntax error", is_error=True)
        check = self.only_check()
        self.assertEqual("passed", check["result"])
        self.assertIs(True, check["changed_after"])

    def test_an_unbalanced_wrapper_line_leaves_only_that_segment_unread(self) -> None:
        self.session.bash('bash -c "pytest -k \'x"', "Exit code 2\nsyntax error", is_error=True)
        _text, checks, scan = self.published()
        self.assertEqual([], checks)
        self.assertEqual(0, scan["not_run"])
        self.assertIsNotNone(scan["last_changing_command_at"])
        self.fresh()
        self.session.bash("bash -c 'echo \"unterminated'; pytest", "5 passed", is_error=False)
        _text, checks, scan = self.published()
        self.assertEqual(["passed"], [c["result"] for c in checks])
        self.assertEqual(0, scan["not_run"])

    def test_a_trailing_backslash_is_not_unbalanced(self) -> None:
        # Measured: `bash -c 'echo a\'` prints `a` and exits 0.
        self.session.bash("pytest -q \\", "5 passed", is_error=False)
        self.assertEqual("passed", self.only_check()["result"])


class AnAnsiCStringIsReadAsTheProgramReadsIt(CheckLineTestCase):  # D5
    def test_an_escaped_key_is_decoded_and_then_redacted(self) -> None:
        for word in (
            "$'\\x41KIAIOSFODNN7EXAMPLE'",
            "$'\\u0041KIAIOSFODNN7EXAMPLE'",
            "$'\\U00000041KIAIOSFODNN7EXAMPLE'",
            "$'\\101KIAIOSFODNN7EXAMPLE'",
            "A\\KIAIOSFODNN7EXAMPLE",
        ):
            with self.subTest(word=word[:8]):
                self.fresh()
                self.session.bash(f"pytest --key {word}", "", is_error=False)
                text, checks, _scan = self.published()
                self.assertEqual(1, len(checks))
                self.assertNotIn("KIAIOSFODNN7EXAMPLE", text)
                self.assertIn("AKIA…REDACTED", checks[0]["title"])

    def test_a_nul_ends_an_ansi_string_as_it_ends_the_argument(self) -> None:
        # argv is a C string: bash passes `$'--password\0'` as `--password`.
        for command in (
            f"pytest $'--password\\0' {HALF_A}",
            f"pytest $'--password\\x00' {HALF_A}",
            f"pytest $'--password\\u0000' {HALF_A}",
            f"pytest $'--password\\c@' {HALF_A}",
            f"pytest $'-p\\0junk' {HALF_A}",
            f"pytest --env $'TOKEN\\0'={HALF_A}",
            f"bash -c \"pytest \\$'--password\\\\0' {HALF_A}\"",
        ):
            with self.subTest(command=command[:22]):
                self.fresh()
                self.session.bash(command, "", is_error=False)
                text, checks, _scan = self.published()
                self.assertEqual(1, len(checks), command)
                self.assertNotIn(HALF_A, text)

    def test_a_raw_nul_in_the_command_is_a_call_that_did_not_run(self) -> None:
        self.session.bash(f"pytest --password\x00 {HALF_A}", "", is_error=False)
        text, checks, scan = self.published()
        self.assertEqual([], checks)
        self.assertEqual(1, scan["not_run"])
        self.assertNotIn(HALF_A, text)

    def test_a_decoded_word_is_published_as_the_program_received_it(self) -> None:
        for command, title in (
            ('pytest -k "a\\`b" -q', "pytest -k a`b -q"),
            ('pytest -k "a\\\nb" -q', "pytest -k ab -q"),
            ("pytest -k $'a\\\\b' -q", "pytest -k a\\b -q"),
            ("pytest -k $'a\\tb' -q", "pytest -k 'a b' -q"),
            ("pytest -k a\\\nb -q", "pytest -k ab -q"),
            ("pytest -q &>/dev/null", "pytest -q"),
            ("pytest -q 2>&1", "pytest -q"),
            ("pytest -q <<<x", "pytest -q"),
            ("pytest -q \\", "pytest -q"),
            ("pytest \\", "pytest"),
        ):
            with self.subTest(command=command):
                self.fresh()
                self.session.bash(command, "", is_error=False)
                self.assertEqual(title, self.only_check()["title"])

    def test_a_named_form_inside_an_ansi_string_is_masked(self) -> None:
        for command in (
            f"pytest $'--password={SECRET}'",
            f"pytest --env $'TOKEN={SECRET}' -q",
            f"pytest -H $'Authorization: Bearer {SECRET}' -q",
            f"pytest --password $'{HALF_A}\\x20{HALF_B}'",
        ):
            with self.subTest(command=command[:18]):
                self.fresh()
                self.session.bash(command, "", is_error=False)
                text, checks, _scan = self.published()
                self.assertEqual(1, len(checks))
                self.assertNotIn(HALF_A, text)
                self.assertNotIn(HALF_B, text)

    def test_an_escaped_quote_inside_it_is_balanced(self) -> None:
        self.session.bash("pytest -k $'it\\'s' -q", "5 passed", is_error=False)
        check = self.only_check()
        self.assertEqual("passed", check["result"])
        self.assertEqual("pytest -k it's -q", check["title"])


class ALineContinuationIsOneSegment(CheckLineTestCase):  # D6
    def test_a_continued_check_has_no_false_change_and_keeps_its_pass(self) -> None:
        self.session.bash("pytest tests/ \\\n  -q", "", is_error=False)
        events, scan = self.read()
        check = self.only_check()
        self.assertEqual("pytest tests/ -q", check["title"])
        self.assertEqual("passed", check["result"])
        self.assertIs(False, check["changed_after"])
        self.assertIsNone(scan["last_changing_command_at"])
        self.assertEqual(1, len(events))

    def test_a_password_continued_across_lines_is_masked_whole(self) -> None:
        self.session.bash(f"pytest --dsn app:{HALF_A}\\\n{HALF_B}@db -q", "", is_error=False)
        text, checks, _scan = self.published()
        self.assertEqual(1, len(checks))
        self.assertNotIn(HALF_A, text)
        self.assertNotIn(HALF_B, text)

    def test_an_escaped_joiner_is_part_of_the_word(self) -> None:
        self.session.bash("pytest -k a\\;b", "5 passed", is_error=False)
        _events, scan = self.read()
        self.assertEqual("passed", self.only_check()["result"])
        self.assertIsNone(scan["last_changing_command_at"])


class AHeredocIsDataOnlyWhereTheShellSaysSo(CheckLineTestCase):  # D7
    def test_a_quoted_heredoc_marker_hides_no_later_change(self) -> None:
        self.session.bash('pytest -q\necho "<<END"\nrm -rf build\nEND', "1 passed")
        check = self.only_check()
        self.assertIs(True, check["changed_after"])

    def test_any_delimiter_word_keeps_its_body_out_of_the_checks(self) -> None:
        for command in (
            f"cat <<'MY-EOF'\npytest --dsn \"app:{SENTINEL} two@db\"\nMY-EOF",
            f'cat <<"a.b"\npytest {SENTINEL}\na.b',
            f"cat <<-END\n\tpytest {SENTINEL}\n\tEND",
            f"cat <<A <<B\npytest {SENTINEL}\nA\nmypy {SENTINEL}\nB",
            f"cat <<END\npytest {SENTINEL}",
            f"git commit -m \"$(cat <<'EOF'\nit's done; pytest {SENTINEL}\nEOF\n)\"",
        ):
            with self.subTest(command=command.split("\n", 1)[0]):
                self.fresh()
                self.session.bash(command, "", is_error=False)
                text, checks, scan = self.published()
                self.assertEqual([], checks)
                self.assertNotIn(SENTINEL, text)
                self.assertEqual(0, scan["not_run"])

    def test_the_command_after_a_heredoc_is_read(self) -> None:
        self.session.bash("cat > run.sh <<'EOF'\nrm -rf /\nEOF\npytest -q", "", is_error=False)
        self.assertEqual("pytest -q", self.only_check()["title"])

    def test_an_unrecognised_delimiter_is_never_a_check(self) -> None:
        self.session.bash(f"cat <<'x y'\npytest {SENTINEL}\nx y", "", is_error=False)
        self.assertEqual([], self.checks())


class AShellWrapperStandsForItsInnerSegments(CheckLineTestCase):  # D8
    def run_one(self, command: str, output: str = "", *, is_error: bool = False) -> None:
        self.fresh()
        self.session.bash(command, output, is_error=is_error)

    def test_each_wrapper_publishes_only_the_inner_segment(self) -> None:
        for command in (
            "bash -c 'pytest -q'",
            "sh -c 'pytest -q'",
            "zsh -c 'pytest -q'",
            "bash -lc 'pytest -q'",
            "bash -euc 'pytest -q'",
            "bash -e -o pipefail -c 'pytest -q'",
            "bash --noprofile --norc -c 'pytest -q'",
            "/bin/bash -c 'pytest -q'",
            "env CI=1 pytest -q",
            "env -i A=1 bash -c 'pytest -q'",
            "env -u HOME -- pytest -q",
            "bash -c 'pytest -q' extra0 arg1",
            "timeout 60 bash -c 'pytest -q'",
            "/usr/bin/env CI=1 pytest -q",
            "env --unset=HOME pytest -q",
            "env -uHOME pytest -q",
            "env --ignore-environment pytest -q",
            "env - pytest -q",
        ):
            with self.subTest(command=command):
                self.run_one(command, "", is_error=False)
                check = self.only_check()
                self.assertEqual("pytest -q", check["title"])
                self.assertEqual("passed", check["result"])

    def test_a_wrapper_and_a_bare_run_are_one_check(self) -> None:
        self.session.bash("bash -c 'pytest'", "1 failed", is_error=True)
        self.session.bash("pytest", "5 passed", is_error=False)
        check = self.only_check()
        self.assertEqual("passed", check["result"])
        self.assertIs(True, check["earlier_failed"])

    def test_a_cd_inside_the_wrapper_does_not_carry_past_it(self) -> None:
        self.session.bash("bash -c 'cd sub && pytest'", "1 failed", is_error=True)
        self.session.bash("pytest", "5 passed", is_error=False)
        results = sorted(c["result"] for c in self.checks())
        self.assertEqual(["failed", "passed"], results)
        self.fresh()
        self.session.bash("bash -c 'cd sub && pytest' && pytest", "", is_error=False)
        self.assertEqual(2, len(self.checks()))

    def test_attribution_through_the_splice_only_withholds(self) -> None:
        for command, output, flag, expected in (
            ("bash -c 'mypy .; pytest' && echo ok", "", False, {"mypy .": "not-recorded",
                                                              "pytest": "not-recorded"}),
            ("bash -c 'ruff check . && pytest'", "", False, {"ruff check .": "passed",
                                                           "pytest": "passed"}),
            # Any `||` before a segment withholds it, the wrapper's own included.
            ("bash -c 'make x || pytest' && ruff check .", "", False, {"pytest": "not-recorded",
                                                                     "ruff check .": "not-recorded"}),
            ("rm -rf x && bash -c 'pytest || true'", "", False, {"pytest": "not-recorded"}),
            ("bash -c 'pytest' | tail -2", "5 passed", False, {"pytest": "passed"}),
            ("bash -c 'cd api && pytest'", "", True, {"pytest": "failed"}),
            ("bash -c 'pytest; echo x'", "", True, {"pytest": "not-recorded"}),
            # rtk outside the wrapper still reads the flag alone.
            ("rtk bash -c 'pytest -q'", "2 failed", False, {"pytest -q": "not-recorded"}),
        ):  # fmt: skip
            with self.subTest(command=command):
                self.run_one(command, output, is_error=flag)
                found = {c["title"]: c["result"] for c in self.checks()}
                self.assertEqual(expected, found)

    def test_a_backgrounded_wrapper_backgrounds_every_inner_segment(self) -> None:
        for command in ("bash -c 'pytest; echo started' &", "pytest && bash -c 'a; b' &"):
            with self.subTest(command=command):
                self.run_one(command, "5 passed", is_error=False)
                _events, scan = self.read()
                self.assertEqual([], self.checks())
                self.assertEqual(1, scan["background"])
        # The control: the same line without the `&` is one foreground check.
        self.run_one("bash -c 'pytest; echo started'", "5 passed", is_error=False)
        _events, scan = self.read()
        self.assertEqual(1, len(self.checks()))
        self.assertEqual(0, scan["background"])

    def test_a_background_launch_inside_the_wrapper_is_counted(self) -> None:
        self.run_one("bash -c 'pytest &'", "", is_error=False)
        _events, scan = self.read()
        self.assertEqual([], self.checks())
        self.assertEqual(1, scan["background"])

    def test_nesting_stops_at_two_levels(self) -> None:
        self.run_one("bash -c \"sh -c 'pytest -q'\"")
        self.assertEqual("pytest -q", self.only_check()["title"])
        three = "bash -c " + shlex.quote("sh -c " + shlex.quote("zsh -c 'pytest -q'"))
        self.run_one(three)
        _events, scan = self.read()
        self.assertEqual([], self.checks())
        self.assertIsNotNone(scan["last_changing_command_at"])

    def test_options_outside_the_closed_set_leave_the_segment_unread(self) -> None:
        for command in (
            "bash --rcfile x -c 'pytest'",
            "bash --rcfile=x -c 'pytest'",
            "bash --posix -c 'pytest'",
            "bash -xc 'pytest'",
            "bash -x -c 'pytest'",
            "bash -i -c 'pytest'",
            "bash +e -c 'pytest'",
            "bash -o posix -c 'pytest'",
            "bash script.sh -c 'pytest'",
            "bash -c",
            "fish -c 'pytest'",
            "env -S 'pytest -q'",
            "env -C sub pytest -q",
            "env --split-string='pytest -q'",
            "env --chdir=sub pytest -q",
        ):
            with self.subTest(command=command):
                self.run_one(command)
                _events, scan = self.read()
                self.assertEqual([], self.checks())
                self.assertIsNotNone(scan["last_changing_command_at"])


class EveryUnterminatedConstructIsACallThatDidNotRun(CheckLineTestCase):
    def test_each_publishes_nothing_is_counted_as_not_run_and_still_ages_a_pass(self) -> None:
        for command in (
            f"pytest -q $'--password={SECRET}",
            f"pytest -q $(echo {SENTINEL}",
            f"pytest -q `echo {SENTINEL}",
            f"pytest -q ${{HOME {SENTINEL}",
            f"pytest -q <<\nrm -rf {SENTINEL}",
            f"pytest -q << ; echo {SENTINEL}",
            f"pytest -q > ; echo {SENTINEL}",
        ):
            with self.subTest(command=command[:16]):
                self.fresh()
                self.session.bash("pytest", "5 passed", is_error=False)
                self.session.bash(command, "Exit code 2\nsyntax error", is_error=True)
                text, checks, scan = self.published()
                self.assertEqual(["pytest"], [c["title"] for c in checks])
                self.assertIs(True, checks[0]["changed_after"])
                self.assertEqual(1, scan["not_run"])
                self.assertNotIn(SENTINEL, text)
                self.assertNotIn(HALF_A, text)

    def test_nesting_past_the_cap_is_not_run_and_raises_nothing(self) -> None:
        deep = "pytest " + '"$(' * 400 + HALF_A + ')"' * 400
        self.session.bash("pytest", "5 passed", is_error=False)
        self.session.bash(deep, "", is_error=False)
        text, checks, scan = self.published()
        self.assertEqual(1, scan["not_run"])
        self.assertIs(True, checks[0]["changed_after"])
        self.assertNotIn(HALF_A, text)

    def test_nesting_is_refused_past_its_cap_and_read_below_it(self) -> None:
        # Both depths sit far inside Python's recursion limit, so the refusal is
        # the cap's own and not the catch-all at the call.
        for levels, runs in ((30, 1), (33, 0)):
            with self.subTest(levels=levels):
                self.fresh()
                self.session.bash("pytest -q " + '"$(' * levels + "x" + ')"' * levels, "")
                _text, checks, scan = self.published()
                self.assertEqual(runs, len(checks))
                self.assertEqual(1 - runs, scan["not_run"])

    def test_a_parser_fault_fails_closed_at_the_call(self) -> None:
        self.session.bash("pytest", "5 passed", is_error=False)
        self.session.bash("pytest -q", "", is_error=False)
        with mock.patch.object(
            project_context._ShellLexer, "segments", side_effect=ValueError("boom")
        ):
            _text, checks, scan = self.published()
        self.assertEqual([], checks)
        self.assertEqual(2, scan["not_run"])
        self.assertIsNotNone(scan["last_changing_command_at"])


class ASubstitutionIsReadAsTheShellReadsIt(CheckLineTestCase):
    def test_a_closing_mark_inside_a_parameter_or_case_pattern_does_not_end_it(self) -> None:
        for command in (
            f'pytest "$(echo ${{UNSET:-)}} {HALF_A})"',
            f"pytest $(echo ${{x:-)}} {HALF_A})",
            f'pytest --x "$(echo ${{x/)/}} {HALF_A})"',
            f"pytest $(case a in a) echo {HALF_A};; esac)",
            f'pytest --x "$(case a in a) echo {HALF_A};; esac)"',
            f'pytest "$(case $f in *.py) echo {HALF_A};; esac)" -q',
        ):
            with self.subTest(command=command[:24]):
                self.fresh()
                self.session.bash(command, "", is_error=False)
                text, checks, _scan = self.published()
                self.assertEqual(1, len(checks), command)
                self.assertNotIn(HALF_A, text)

    def test_a_quoted_brace_inside_a_parameter_is_balanced(self) -> None:
        for command in ('pytest -k ${UNSET:-"}"}', "pytest -k ${UNSET:-'}'}"):
            with self.subTest(command=command):
                self.fresh()
                self.session.bash(command, "5 passed", is_error=False)
                _text, checks, scan = self.published()
                self.assertEqual(["passed"], [c["result"] for c in checks])
                self.assertEqual(0, scan["not_run"])

    def test_a_brace_expansion_is_withheld_because_its_words_are_unknown(self) -> None:
        for command in (
            f"pytest {{--password=,x}}{HALF_A}",
            "pytest AKIA{IOSFODNN7EXAMPLE,}",
            f"pytest -k {{a..z}}{HALF_A}",
        ):
            with self.subTest(command=command[:18]):
                self.fresh()
                self.session.bash(command, "", is_error=False)
                text, checks, _scan = self.published()
                self.assertEqual(1, len(checks))
                self.assertNotIn(HALF_A, text)
                self.assertNotIn("IOSFODNN7EXAMPLE", text)
                self.assertIn("…", checks[0]["title"])

    def test_a_quoted_or_single_brace_is_not_an_expansion(self) -> None:
        for command, title in (
            ("pytest -k '{a,b}'", "pytest -k {a,b}"),
            ("pytest -k {a}", "pytest -k {a}"),
            ("pytest -k ${x}", "pytest -k ${x}"),
        ):
            with self.subTest(command=command):
                self.fresh()
                self.session.bash(command, "", is_error=False)
                self.assertEqual(title, self.only_check()["title"])

    def test_a_process_substitution_is_a_redirection_target(self) -> None:
        # Measured on local transcripts: `done < <(find …)` and `> >(tee log)`.
        for command in ("pytest -q < <(ls tests)", "pytest -q > >(tee log)"):
            with self.subTest(command=command):
                self.fresh()
                self.session.bash(command, "", is_error=False)
                _text, checks, scan = self.published()
                self.assertEqual(["pytest -q"], [c["title"] for c in checks])
                self.assertEqual(0, scan["not_run"])

    def test_an_arithmetic_shift_is_not_a_heredoc(self) -> None:
        self.session.bash("(( n <<= 1 ))\npytest -q", "", is_error=False)
        self.assertEqual("pytest -q", self.only_check()["title"])


class AChangeASubstitutionOrRedirectionMakesIsNeverHidden(CheckLineTestCase):
    """C-1 and C-2, and DRC-4724's second acceptance criterion."""

    def test_each_later_change_ages_the_pass(self) -> None:
        for later in (
            "bash -c 'ls' > build/output",
            "X=$(rm -rf build)",
            "X=<(rm x)",
            'echo "$(rm -rf build)"',
            "echo `rm -rf build`",
            "pytest -k x $(rm x)",
            "bash -c 'echo hi' \"$(rm -rf build)\"",
            "ls > $(rm x)",
            'cat <<< "$(rm x)"',
        ):
            with self.subTest(later=later):
                self.fresh()
                self.session.bash("pytest", "5 passed", is_error=False)
                self.session.bash(later, "", is_error=False)
                check = next(c for c in self.checks() if c["title"] == "pytest")
                self.assertIs(True, check["changed_after"])

    def test_a_substitution_later_in_the_same_call_ages_the_pass(self) -> None:
        self.session.bash("pytest && X=$(rm -rf build)", "5 passed", is_error=False)
        self.assertIs(True, self.only_check()["changed_after"])

    def test_a_read_only_substitution_ages_nothing(self) -> None:
        for later in (
            'echo "$(cat notes.txt)"',
            "X=$(git status)",
            "echo $((1 + 2))",
            "ls $(pwd)",
            "cat <(ls a) <(ls b)",
        ):
            with self.subTest(later=later):
                self.fresh()
                self.session.bash("pytest", "5 passed", is_error=False)
                self.session.bash(later, "", is_error=False)
                self.assertIs(False, self.only_check()["changed_after"])


class TheVerifiersThreeFindings(CheckLineTestCase):
    """N1 to N3, from the fresh verifier's report of 2026-09-27."""

    def test_a_segment_that_is_only_a_redirect_into_a_file_ages_the_pass(self) -> None:  # N1
        for later in ("> build/output", ">> build/log", "bash -c '> build/output'", "&> build/x"):
            with self.subTest(later=later):
                self.fresh()
                self.session.bash("pytest -q", "5 passed", is_error=False)
                self.session.bash(later, "", is_error=False)
                self.assertIs(True, self.only_check()["changed_after"])
        self.fresh()
        self.session.bash("pytest -q && > build/x", "5 passed", is_error=False)
        self.assertIs(True, self.only_check()["changed_after"])

    def test_a_redirect_to_nothing_or_a_descriptor_alone_ages_nothing(self) -> None:  # N1
        for later in ("> /dev/null", "2>&1"):
            with self.subTest(later=later):
                self.fresh()
                self.session.bash("pytest -q", "5 passed", is_error=False)
                self.session.bash(later, "", is_error=False)
                self.assertIs(False, self.only_check()["changed_after"])

    def test_a_named_descriptor_redirect_is_a_redirection(self) -> None:  # N2
        # bash 4.1 and later, and zsh, read `{fd}>` as a redirection, so the
        # program receives the flag and the value side by side.
        for redirect in ("{fd}>/dev/null", "{fd}<in", "{out}>>log", "{fd}>&-"):
            with self.subTest(redirect=redirect):
                self.fresh()
                self.session.bash(f"pytest --password {redirect} {HALF_A} -q", "", is_error=False)
                text, checks, _scan = self.published()
                self.assertEqual(1, len(checks))
                self.assertNotIn(HALF_A, text)
                self.assert_the_prompt_row_holds_neither_half(checks)

    def test_a_withheld_brace_word_withholds_the_word_after_it(self) -> None:  # N3
        for command in (f"pytest --{{x,password}} {HALF_A}", f"pytest --password{{,}} {HALF_A}"):
            with self.subTest(command=command[:20]):
                self.fresh()
                self.session.bash(command, "", is_error=False)
                text, checks, _scan = self.published()
                self.assertEqual(1, len(checks))
                self.assertNotIn(HALF_A, text)


class ACdInsideASubshellDoesNotCarryPastIt(CheckLineTestCase):
    """DRC-4724's first criterion: a `(` at command position opens a subshell,
    and its `)` restores the directory current at the `(`, as a `bash -c`
    wrapper already does."""

    @staticmethod
    def check_directories(command: str) -> list[str]:
        """Each check's directory, normalised on both sides of the comparison.

        The directory is the check's identity key, joined with `os.path` as it
        was before DRC-4724, so on Windows a directory a `cd` reached carries
        backslashes while the starting one keeps what the record said. It is
        never published; a written path is, and it is always `/`-separated
        (`test_a_published_path_is_slash_separated_whatever_the_os`).
        """
        call = project_context._ShellCall(0.0, "/w", {"command": command})
        return [os.path.normpath(call.directories[index]) for index in call.checks]

    def assert_directories(self, expected: list[str], command: str) -> None:
        self.assertEqual([os.path.normpath(path) for path in expected],
                         self.check_directories(command))  # fmt: skip

    def test_each_check_runs_in_the_directory_its_subshell_left(self) -> None:
        for command, expected in (
            ("(cd sub && pytest); pytest", ["/w/sub", "/w"]),
            ("(cd sub) && pytest", ["/w"]),
            ("(cd a; (cd b; pytest); pytest); pytest", ["/w/a/b", "/w/a", "/w"]),
            ("cd a && (cd b && pytest) && pytest", ["/w/a/b", "/w/a"]),
            ("(cd sub && pytest ; ); pytest", ["/w/sub", "/w"]),
            ("(bash -c 'cd x && pytest'); pytest", ["/w/x", "/w"]),
            ("( bash -c 'cd x' && cd y && pytest ); pytest", ["/w/y", "/w"]),
            ("bash -c '(cd x && pytest); pytest'; pytest", ["/w/x", "/w", "/w"]),
        ):
            with self.subTest(command=command):
                self.assert_directories(expected, command)

    def test_a_parenthesis_that_opens_no_subshell_changes_nothing(self) -> None:
        for command, expected in (
            ("cd sub; case x in a) true;; esac; pytest", ["/w/sub"]),
            ("case x in a) true;; esac; pytest", ["/w"]),
            ("cd sub && f() { true; }; pytest", ["/w/sub"]),
            ("cd sub && ((n = 1)) && pytest", ["/w/sub"]),
            ("cd sub; echo $(cd other); pytest", ["/w/sub"]),
        ):
            with self.subTest(command=command):
                self.assert_directories(expected, command)

    def test_a_failure_in_the_subshell_is_not_superseded_by_a_pass_outside_it(self) -> None:
        self.session.bash("cd sub && pytest", "1 failed", is_error=True)
        self.session.bash("(cd sub && true); pytest", "", is_error=False)
        results = sorted(c["result"] for c in self.checks())
        self.assertEqual(["failed", "passed"], results)
        self.assertEqual([False, False], [c["earlier_failed"] for c in self.checks()])

    def test_the_published_line_is_unchanged_by_the_subshell(self) -> None:
        self.session.bash(f"(cd api && pytest --password {HALF_A} -q); pytest", "", is_error=False)
        text, checks, _scan = self.published()
        self.assertEqual(
            ["pytest", f"pytest --password {records.SECRET_MARKER} -q"],
            sorted(c["title"] for c in checks),
        )
        self.assertNotIn(HALF_A, text)


class APublishedPathIsTheSameOnEveryOs(CheckLineTestCase):
    """PR #414's Windows run: a written path a reader sees never carries the
    host's separator, whichever path module joined it."""

    def test_a_published_path_is_slash_separated_whatever_the_os(self) -> None:
        with (
            mock.patch.object(os, "path", ntpath),
            mock.patch.object(os, "sep", "\\"),
        ):
            call = project_context._ShellCall(
                0.0, "C:\\work\\billing", {"command": "cd sub && pytest > logs/out.txt"}
            )
            index, target, start = call.redirect_writes[0]
            self.assertEqual(index, start)
            published = call.written_path(target, start, "C:\\work\\billing")
            write = project_context._written_path(
                "C:\\work\\billing\\src\\a.py", "C:\\work\\billing"
            )
        self.assertEqual("sub/logs/out.txt", published)
        self.assertEqual("src/a.py", write)

    def test_a_host_absolute_path_places_the_directory_and_the_target(self) -> None:
        # PR #414's second Windows run: a drive or UNC path is a literal absolute path, for the
        # `cd` that places the directory again and for a redirect target, and it still counts
        # outside unless it resolves inside the working directory.
        cwd = "C:\\work\\billing"
        cases = (
            ("cd $HOME && cd 'C:\\work\\billing\\src' && pytest > t4", "src/t4"),
            ("cd $HOME && pytest > 'C:\\work\\billing\\abs.txt'", "abs.txt"),
            ("cd $HOME && pytest > C:/work/billing/fwd.txt", "fwd.txt"),
            ("cd $HOME && pytest > 'C:\\other\\x.txt'", None),
            ("cd $HOME && pytest > '\\\\server\\share\\x.txt'", None),
            # Unquoted, the shell reads the backslashes as escapes: `C:workbillingsrc` is
            # relative to the drive's current directory, so the directory stays unknown.
            ("cd $HOME && cd C:\\work\\billing\\src && pytest > t5", None),
        )
        with mock.patch.object(os, "path", ntpath), mock.patch.object(os, "sep", "\\"):
            found = {}
            for command, _expected in cases:
                call = project_context._ShellCall(0.0, cwd, {"command": command})
                ((_index, target, start),) = call.redirect_writes
                found[command] = call.written_path(target, start, cwd)
        for command, expected in cases:
            with self.subTest(command=command):
                self.assertEqual(expected, found[command])


class ALoopOrANegationAroundACheckIsStillThatCheck(CheckLineTestCase):
    """A check inside `for`, `while`, `until` or after `!` is found, and a negated one is never a pass."""

    def test_a_check_inside_a_loop_is_listed(self) -> None:
        for command in (
            "for i in 1 2 3; do pytest -q; done",
            "for i in 1 2\ndo\n  pytest -q\ndone",
            "while true; do pytest -q; done",
            "until pytest -q; do sleep 1; done",
            "i=0; while [ $i -lt 2 ]; do pytest -q; i=$((i + 1)); done",
        ):
            with self.subTest(command=command):
                self.fresh()
                self.session.bash(command, "5 passed", is_error=False)
                titles = [c["title"] for c in self.checks()]
                self.assertTrue(titles and all(t == "pytest -q" for t in titles), titles)

    def test_a_negated_check_is_listed_and_never_a_pass(self) -> None:
        for command in ("! pytest -q", "if ! pytest -q; then echo broke; fi", "ls && ! pytest -q"):
            for output, is_error in (("5 passed", False), ("", False), ("1 failed", True)):
                with self.subTest(command=command, output=output):
                    self.fresh()
                    self.session.bash(command, output, is_error=is_error)
                    check = self.only_check()
                    self.assertEqual("pytest -q", check["title"])
                    self.assertEqual("not-recorded", check["result"])

    def test_a_bang_inside_a_test_expression_negates_nothing(self) -> None:
        self.session.bash("[ ! -f x ] && pytest -q", "5 passed", is_error=False)
        self.assertEqual("passed", self.only_check()["result"])


class ACiPollingLoopIsReadOnly(CheckLineTestCase):
    """DEC-23 item 3, amended 2026-10-27: waiting on CI changes no file."""

    POLL = (
        "for i in $(seq 1 28); do out=$(gh pr checks 7 --repo acme/widgets 2>&1); "
        'if echo "$out" | grep -q x && ! echo "$out" | grep -qiE "pending|queued"; '
        'then break; fi; sleep 20; done; echo "$out"'
    )

    def changed_after(self, *later: str, keep_commit: bool = True) -> bool:
        self.fresh()
        self.session.bash("pytest -q", "5 passed", is_error=False)
        if keep_commit:
            self.session.bash(
                "git commit -m 'fix widget guard'", "[fix/widget-guard 1]", is_error=False
            )
            self.session.bash("git push origin fix/widget-guard", "", is_error=False)
        for command in later:
            self.session.bash(command, "all passing", is_error=False)
        return bool(self.only_check()["changed_after"])

    def test_the_loop_alone_does_not_age_a_pass(self) -> None:
        self.assertIs(False, self.changed_after(self.POLL, keep_commit=False))

    def test_the_commit_and_push_still_do_and_the_loop_adds_nothing_to_them(self) -> None:
        self.assertIs(True, self.changed_after(self.POLL))
        self.assertIs(True, self.changed_after())

    def test_each_polling_command_is_read_only(self) -> None:
        for command in (
            "sleep 20",
            "gh pr checks 7 --repo acme/widgets",
            "gh pr view 7 --json state --jq .state",
            "gh run view 123 --log-failed",
            "gh run list --limit 3",
            "gh run watch 123 --exit-status",
            "glab ci status",
            "for i in 1 2; do sleep 1; done",
            "out=$(gh pr checks 7 --repo acme/widgets)",
            "while ! gh pr checks 7; do sleep 5; done",
        ):
            with self.subTest(command=command):
                self.assertIs(False, self.changed_after(command, keep_commit=False))

    def test_a_write_hidden_in_the_same_shapes_still_ages_the_pass(self) -> None:
        for command in (
            "gh run view 123 --log > out.txt",
            "gh run download 123",
            "gh pr checkout 7",
            "gh pr merge 7",
            "for f in *; do rm $f; done",
            "for i in 1 2; do sleep 1; touch x; done",
            "out=$(gh run download 123)",
            "while true; do gh pr checks 7 > checks.txt; done",
        ):
            with self.subTest(command=command):
                self.assertIs(True, self.changed_after(command, keep_commit=False))


class ALoopDoesNotPlaceADirectoryItMovesEachTurn(CheckLineTestCase):
    """A relative `cd` in a loop body runs again on the next turn, from where it ended."""

    def placed(self, command: str) -> list[bool]:
        call = project_context._ShellCall(0.0, "/work/billing", {"command": command})
        return [call.placed[i] for i in call.checks]

    def test_a_check_in_a_plain_loop_stays_placed(self) -> None:
        self.assertEqual([True], self.placed("for i in 1 2; do pytest -q; done"))

    def test_a_relative_cd_in_the_body_leaves_the_check_unplaced(self) -> None:
        self.assertEqual([False], self.placed("for i in 1 2; do cd sub; pytest -q; done"))

    def test_an_absolute_cd_in_the_body_places_it_every_turn(self) -> None:
        self.assertEqual([True], self.placed("for i in 1 2; do cd /work/other; pytest -q; done"))

    def test_a_directory_changed_inside_the_loop_is_unknown_after_it(self) -> None:
        self.assertEqual([False], self.placed("for i in 1 2; do cd sub; done; pytest -q"))
