"""Synthetic source facts and recorded replies exercise the summary boundary."""

from __future__ import annotations

import dataclasses
import hashlib
import importlib
import json
import re
import unittest
from pathlib import Path
from typing import TYPE_CHECKING, Any

from compass_runtime import session_source
from compass_runtime.config import build_runtime_config
from compass_runtime.reading_policy import RefusedError

if TYPE_CHECKING:
    from collections.abc import Sequence


def entry(
    number: int, kind: str = "person", words: str | None = None, **kw: Any
) -> session_source.SourceEntry:
    text = words if words is not None else f"Synthetic instruction {number}."
    return session_source.SourceEntry(
        f"fact-{number}",
        hashlib.sha256(text.encode()).hexdigest()[:32],
        kind,
        "parent",
        "parent",
        float(number),
        f"Synthetic title {number}",
        words=text,
        **kw,
    )


def phase(
    cites: Sequence[object],
    text: str = "Inspected the parser",
    title: str = "Inspection",
    kind: str = "did",
) -> dict[str, Any]:
    return {"title": title, "bullets": [{"text": text, "kind": kind, "cites": list(cites)}]}


class Replies:
    def __init__(self, *replies: object) -> None:
        self.replies = list(replies)
        self.prompts: list[str] = []
        self.caps: list[int] = []

    def __call__(self, prompt: str, *, output_cap_bytes: int) -> tuple[str, str]:
        self.prompts.append(prompt)
        self.caps.append(output_cap_bytes)
        answer = self.replies.pop(0) if self.replies else None
        if isinstance(answer, Exception):
            raise answer
        if isinstance(answer, tuple):
            return str(answer[0]), str(answer[1])
        if isinstance(answer, str):
            return answer, "ok"
        if isinstance(answer, dict):
            return json.dumps(answer), "ok"
        if "Reply with one JSON object" in prompt:
            match = re.search(r"entries (\d+) to (\d+)", prompt)
            assert match is not None
            return json.dumps({"phases": [phase([int(match[1])])]}), "ok"
        numbers = re.findall(r"^\[(\d+)\]", prompt, re.MULTILINE)
        return json.dumps(
            {"lede": "The person requested a parser review.", "cites": [int(numbers[0])]}
        ), "ok"


class SessionSummaryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.summary = importlib.import_module("compass_runtime.session_summary")
        self.config = build_runtime_config(
            environ={"HOME": "/synthetic"},
            platform_name="linux",
            os_name="posix",
            launcher_path=Path("/synthetic/server.py"),
        )
        self.coverage = session_source.SourceCoverage(True, None, 0, 100, (), "read", "read")

    def run_summary(
        self,
        entries: Sequence[session_source.SourceEntry],
        replies: Replies | None = None,
        **bounds: Any,
    ) -> Any:
        return self.summary.summarize(
            entries,
            self.coverage,
            "claude",
            config=dataclasses.replace(self.config, **bounds),
            model=replies or Replies(),
            clock=lambda: 0.0,
        )

    def test_windows_resolve_only_their_own_fact_ids_and_freeze_blocks(self) -> None:
        entries = [
            entry(n, words=f"Unique synthetic request {n}: " + "x" * 65) for n in range(1, 7)
        ]
        model = Replies()
        result = self.run_summary(entries, model, session_summary_window_bytes=150)
        data = result.as_dict()
        self.assertEqual("ok", result.state)
        self.assertEqual(6, len(data["blocks"]))
        for n, block in enumerate(data["blocks"], 1):
            self.assertEqual(
                (f"fact-{n}", f"fact-{n}", 1), (block["first"], block["last"], block["entries"])
            )
            self.assertRegex(block["fingerprint"], r"^[0-9a-f]{32}$")
            self.assertEqual([f"fact-{n}"], block["phases"][0]["bullets"][0]["cites"])
        self.assertEqual(7, result.spend.calls)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            result.blocks[0].first = "changed"
        data["blocks"][0]["phases"].clear()
        self.assertEqual(1, len(result.blocks[0].phases))
        self.assertNotIn("words", json.dumps(result.as_dict()))

    def test_fenced_and_cut_replies_keep_complete_phases(self) -> None:
        complete = json.dumps(phase([1]))
        for reply in (
            "```json\n" + json.dumps({"phases": [phase([1])]}) + "\n```",
            '{"phases":[' + complete + ',{"title":"cut',
            '{"unused":1,"phases":[' + complete + ',{"title":"cut',
        ):
            with self.subTest(reply=reply):
                data = self.run_summary([entry(1)], Replies(reply)).as_dict()
                self.assertEqual(1, len(data["blocks"][0]["phases"]))
        for reply in (
            "Prose " + json.dumps({"phases": [phase([1])]}),
            "[]",
            "garbage",
            '{"phases":[]}',
        ):
            with self.subTest(reply=reply):
                block = self.run_summary([entry(1)], Replies(reply)).as_dict()["blocks"][0]
                self.assertEqual("no_valid_reply", block["reason"])

    def test_faults_withheld_in_place_and_other_windows_survive(self) -> None:
        entries = [entry(n, words="x" * 70) for n in range(1, 4)]
        mixed = phase([1, True, 200])
        mixed["bullets"].append(phase([2])["bullets"][0])
        model = Replies(
            {"phases": [phase([1], title="")]},
            {"phases": [mixed]},
            {"phases": [phase([1, 3, 3, False])]},
        )
        blocks = self.run_summary(entries, model, session_summary_window_bytes=100).as_dict()[
            "blocks"
        ]
        self.assertEqual("no_valid_reply", blocks[0]["reason"])
        self.assertEqual(
            {"withheld": True, "reason": "no_citation"},
            blocks[1]["phases"][0]["bullets"][0]["text"],
        )
        self.assertEqual(["fact-3"], blocks[2]["phases"][0]["bullets"][0]["cites"])

    def test_phase_with_no_cited_bullet_is_not_a_valid_phase(self) -> None:
        result = self.run_summary([entry(1)], Replies({"phases": [phase([True, 100])]}))
        self.assertEqual("no_valid_reply", result.blocks[0].reason)

    def test_kind_priority_and_relayed_authorship(self) -> None:
        entries = [
            entry(1),
            entry(2, "agent"),
            entry(3, "check", result="failed"),
            entry(4, "check", result="passed"),
            entry(5, "file", path="src/parser.py"),
            entry(6, words="Another Claude session sent a message: inspect parser"),
        ]
        cases = [
            ([3, 4], "failed"),
            ([1, 4], "did"),
            ([5], "did"),
            ([1], "asked"),
            ([1, 2], "asked"),
            ([2], "said"),
            ([6], "said"),
            ([1, 6], "asked"),
        ]
        model = Replies(
            {
                "phases": [
                    {
                        "title": "Inspection",
                        "bullets": [phase(c, kind="invented")["bullets"][0] for c, _ in cases],
                    }
                ]
            }
        )
        data = self.run_summary(entries, model, session_summary_max_bullets=10).as_dict()
        bullets = data["blocks"][0]["phases"][0]["bullets"]
        self.assertEqual([kind for _, kind in cases], [b["kind"] for b in bullets])
        self.assertTrue(all(b["kind_overridden"] for b in bullets))
        self.assertIn("[6] relayed:", model.prompts[0])
        self.assertIn("NOT written by the person", model.prompts[0])
        self.assertIn("result as the tool reported: failed", model.prompts[0])
        self.assertIn('only as "the error read: <its words>"', model.prompts[0])

    def assert_completion_verdict(self, text: str, verdict: str, kind: str) -> None:
        sources = {
            "asked": entry(1),
            "said": entry(1, "agent"),
            "did": entry(1, "check", result="passed"),
            "failed": entry(1, "check", result="failed"),
        }
        model = Replies({"phases": [phase([1], text=text, kind="invented")]})
        bullet = self.run_summary([sources[kind]], model).as_dict()["blocks"][0]["phases"][0][
            "bullets"
        ][0]
        self.assertEqual(kind, bullet["kind"])
        self.assertTrue(bullet["kind_overridden"])
        expected = (
            {"withheld": True, "reason": "completion_claim"} if verdict == "withheld" else text
        )
        self.assertEqual(expected, bullet["text"])

    def test_backstop_distinguishes_own_voice_from_reports_and_names(self) -> None:
        cases = [
            ("Fixed the parser", "withheld", "did"),
            ("The parser is done", "withheld", "said"),
            ("Completed the parser", "withheld", "asked"),
            ("The parser is working on every input now.", "withheld", "said"),
            ("The feature is verified", "withheld", "did"),
            ("The build went green.", "withheld", "did"),
            ("Solved the login bug", "withheld", "failed"),
            ("Implemented the change and delivered it", "withheld", "asked"),
            ("Merged the change", "withheld", "did"),
            ("Ship the parser", "withheld", "said"),
            ("Reviewed a list of fixes", "withheld", "did"),
            ("The agent said the parser is fixed", "kept", "did"),
            ("The person reported it works", "kept", "asked"),
            ("According to the user who wrote the request, it is fixed", "withheld", "asked"),
            ("The agent clearly said the parser is fixed", "kept", "did"),
            ("The tool output showed the tests passed", "withheld", "did"),
            ("Created branch fix/parser", "kept", "did"),
            ("The subagent confirmed the feature is implemented", "kept", "said"),
            ("The teammate explained it was repaired", "kept", "said"),
            ("The reviewer noted the change was merged", "kept", "did"),
            ("The check reports the tests passed", "withheld", "did"),
            ("The error read: unable to fix the parser", "kept", "failed"),
            ("The tool reported: verification failed", "withheld", "failed"),
            ("The tool error said unable to fix the import", "kept", "failed"),
            ("The error message says the merge was refused", "kept", "failed"),
            ('The agent said "the parser is fixed, and all tests pass."', "kept", "did"),
            ("“The parser is fixed,” the agent said", "kept", "did"),
            ('"The parser is fixed," the person reported', "kept", "asked"),
            ("`The parser is fixed` the reviewer stated", "kept", "did"),
            ("Said the parser is fixed", "kept", "said"),
            ("Asked the agent to fix the parser", "kept", "asked"),
            ("Reported the tests pass", "kept", "said"),
            ("Said the parser is fixed", "withheld", "did"),
            ("Asked the agent to fix the parser", "withheld", "failed"),
            ("Moved the issue to Done", "kept", "did"),
            ("Marked the ticket as `Done`", "kept", "asked"),
            ("Set the status to Verified", "kept", "did"),
            ("Changed the task to Complete", "kept", "did"),
            ("Switched the card to Done", "kept", "did"),
            ("Moved the item to done", "withheld", "did"),
            ("Created branch fix/parser-crash", "kept", "did"),
            ("Inspected hotfix_parser.py", "kept", "did"),
            ("Created feature/done-list", "kept", "said"),
            ("Read fixed.py", "kept", "did"),
            ("Created branch fix-parser", "kept", "did"),
            ("Created `fix-parser`", "withheld", "did"),
            ("Created fix-parser", "withheld", "did"),
            ("pytest reported passed, as the tool reported", "kept", "did"),
            ('"fixed" the agent reported passed, as the tool reported', "withheld", "did"),
            ("pytest reported failed, as the tool reported", "kept", "failed"),
            ("pytest passed, as the tool reported", "withheld", "did"),
            ("pytest failed, as the tool reported", "kept", "failed"),
            ("pytest not-recorded, as the tool reported", "kept", "did"),
            ("Tests passed", "withheld", "did"),
            ("Fixed parser; pytest passed, as the tool reported", "withheld", "did"),
            ("The build is green; pytest passed, as the tool reported", "withheld", "did"),
            ("fixed passed, as the tool reported", "withheld", "did"),
            ("pytest passed, as the tool reported; the parser works", "withheld", "did"),
            ("pytest passed, as the tool reported fixed the parser", "withheld", "did"),
            ("The agent said it got the tests to pass", "kept", "did"),
            ("The agent said it managed to fix the parser", "kept", "said"),
            ("Inspected the parser and read the failing test", "kept", "did"),
            ("The agent said file.py is fixed", "kept", "did"),
            ('The agent said file."py" is fixed', "withheld", "did"),
            ("The agent said `parser.py` is fixed", "kept", "did"),
            ("The person asked the agent to fix the parser", "kept", "asked"),
            ("The agent asked the user to fix the parser.", "kept", "said"),
            ("The agent told the user the parser is fixed.", "kept", "said"),
            ("The agent then said the parser is fixed", "kept", "said"),
            ("The agent also reported the build is green", "kept", "said"),
            ("The agent said the error is fixed", "kept", "said"),
            ("The person said the agent fixed it", "kept", "said"),
            ("The agent said that the person fixed it", "kept", "said"),
            ("Moved the ticket from Todo to Done", "kept", "did"),
            ("Moved DRC-1 to Done", "kept", "did"),
            ("Moved the issue to Ready for Merge", "kept", "did"),
            ("Read got.py beside branch fix/parser-crash.", "kept", "did"),
            ("Said: the parser is fixed", "kept", "said"),
        ]
        for text, verdict, kind in cases:
            with self.subTest(text=text, verdict=verdict, kind=kind):
                self.assert_completion_verdict(text, verdict, kind)

    def test_check_mark_glyphs_are_withheld_in_every_voice(self) -> None:
        cases = [
            ("Added the retry handler \u2713", "did"),
            ("Added the retry handler \u2714\ufe0f", "did"),
            ("\u2705 Retry handler", "did"),
            ("\u2611 the retry handler", "failed"),
            ("Added the retry handler \U0001f5f8", "did"),
            ("Retry handler \u221a", "did"),
            ("Said the retry handler is in \u2713", "said"),
            ("The agent said \u201cthe handler is in \u2713\u201d", "said"),
            ("Asked for the retry handler \u2713", "asked"),
            # An invisible format character elsewhere in the line does not hide the glyph.
            ("Added the retry\u200b handler \u2713", "did"),
        ]
        for text, kind in cases:
            with self.subTest(text=text, kind=kind):
                self.assert_completion_verdict(text, "withheld", kind)
        self.assert_completion_verdict("Added the retry handler", "kept", "did")

    def test_every_tick_glyph_is_withheld_in_recorded_replies_and_ballot_x_is_kept(self) -> None:
        for glyph in "✓✔✅☑√🗸🗹\U00010102\U0001fbb1☒":
            for text in (f"Inspected the parser {glyph}", f'The agent said "{glyph}"'):
                with self.subTest(text=text):
                    model = Replies(
                        {"phases": [phase([1], title=text, text=text)]},
                        {"lede": text, "cites": [1]},
                    )
                    data = self.run_summary([entry(1, "agent")], model).as_dict()
                    values = [
                        data["blocks"][0]["phases"][0]["title"],
                        data["blocks"][0]["phases"][0]["bullets"][0]["text"],
                        data["lede"],
                    ]
                    for value in values:
                        if glyph == "☒":
                            self.assertEqual(
                                text, value["text"] if isinstance(value, dict) else value
                            )
                        else:
                            self.assertEqual("completion_claim", value["reason"])

    def test_titles_and_lede_have_no_implicit_subject_licence(self) -> None:
        for text, verdict in [
            ("Said the parser is fixed", "withheld"),
            ("Asked the agent to fix the parser", "withheld"),
            ("Reported the tests pass", "withheld"),
            ("The agent said the parser is fixed", "kept"),
            ('"Fixed the parser," the agent said', "kept"),
        ]:
            with self.subTest(text=text, verdict=verdict):
                model = Replies(
                    {"phases": [phase([1], title=text)]},
                    {"lede": text, "cites": [1]},
                )
                data = self.run_summary([entry(1, "agent")], model).as_dict()
                self.assertIn("only as 'the error read: <its words>'", model.prompts[-1])
                title = data["blocks"][0]["phases"][0]["title"]
                if verdict == "withheld":
                    self.assertEqual({"withheld": True, "reason": "completion_claim"}, title)
                    self.assertEqual("completion_claim", data["lede"]["reason"])
                else:
                    self.assertEqual(text, title)
                    self.assertEqual(text, data["lede"]["text"])

    def test_completion_backstop_preserves_the_five_refusal_conditions(self) -> None:
        cases = [
            ("unattributed quotation", 'Quoted "the parser is fixed"', "said"),
            ("bare quotation", '"Fixed the parser."', "said"),
            ("bare backtick word", "The parser bug is `fixed`.", "said"),
            ("bare backtick phrase", "`all fixed`", "said"),
            ("speaker only inside quotation", '"The agent said the parser is fixed"', "said"),
            ("comma second clause", "The agent said it ran, the bug is fixed", "said"),
            ("so second clause", "The agent reported the root cause, so the bug is fixed.", "said"),
            ("passed then so", "The agent reported the tests passed, so it works", "said"),
            ("which second clause", "The agent said it ran, which fixed the bug", "said"),
            ("sentence end", 'The agent said "I will inspect it." The parser is fixed.', "said"),
            ("semicolon", "The agent said it ran; fixed the parser", "said"),
            ("and joiner", "The agent said it ran and fixed the parser", "said"),
            ("but joiner", "The agent said it ran but fixed the parser", "said"),
            ("then joiner", "The agent said it ran then fixed the parser", "said"),
            ("because joiner", "The agent said it ran because the parser works", "said"),
            ("while joiner", "The agent said it ran while the parser works", "said"),
            ("exclamation end", "The agent said it ran! The parser works", "said"),
            ("question end", "The agent asked did it run? The parser works", "asked"),
            ("implicit only first clause", "Read the parser; Said it is fixed", "said"),
            ("implicit comma", "Said it is fixed, it works", "said"),
            ("implicit must begin string", '"Inspection" Said it is fixed', "said"),
            ("postposed must be immediate", '"fixed" "inspection" the agent said', "said"),
            ("postposed covers only quote", '"fixed" the agent said the build is green', "said"),
            ("branch must be immediate", 'branch "inspection" fix-parser', "did"),
            ("unclosed quote", 'Quoted "the agent said it is fixed', "said"),
            ("postposed attribution only quote", 'fixed it "all fixed" the agent said', "said"),
            ("speaker in passing", "The agent read the log before fixing the parser", "said"),
            ("wrote is not speech", "The agent wrote a working parser", "said"),
            ("verb not adjacent", "The agent in its reply said the parser is fixed", "said"),
            ("only a tool shows", "The agent showed the tests passed", "said"),
            ("later speaker", "The person asked about the bug the agent fixed", "asked"),
            ("slash prose", "Fixed/verified the parser", "did"),
            ("bare slashed token", "Pushed fix/parser", "did"),
            ("completion-only identifier", "Fixed.Verified", "did"),
            ("completion-only compound", "Created branch fixed-done", "did"),
            ("result named state", "Got everything to Verified.", "did"),
            ("result infinitive", "Got the tests to pass", "asked"),
            ("managed infinitive", "The agent managed to fix the parser bug.", "said"),
            ("brought result", "Brought the build to green", "did"),
            ("made result", "Made the tests pass", "did"),
            ("gotten result", "Gotten the tests to pass", "did"),
            ("result defeats implicit", "Said it got the tests to pass", "said"),
            ("result defeats tracker", "Got it marked the ticket as Done", "did"),
            ("result defeats name", "Got branch fix-parser", "did"),
            ("unreported pass", "Tests passed", "did"),
            ("unreported green", "The build went green.", "did"),
            (
                "tool suffix not adjacent",
                "Parser passed with warnings, as the tool reported",
                "did",
            ),
            (
                "tool suffix licenses only result",
                "Parser fixed passed, as the tool reported",
                "did",
            ),
            ("mixed script", "Parser fix\u0435d", "said"),
            ("mixed script attributed", "The agent said it is fix\u0435d", "said"),
            ("NFKC", "\uff26\uff49\uff58\uff45\uff44 the parser", "said"),
            ("dash", "The agent said it ran \u2014 the bug is fixed", "said"),
            ("spaced hyphen", "The agent said it ran - the bug is fixed", "said"),
            ("colon not after the verb", "The agent said it ran: the parser is fixed", "said"),
            ("parenthesis", "The agent said it ran (the parser is fixed)", "said"),
            ("sentence end without space", "The agent said it ran.The parser is fixed", "said"),
            ("ideographic full stop", "The agent said nothing\u3002The parser is fixed", "said"),
            ("line end", "The agent said it ran\nFixed the parser", "said"),
            ("after joiner", "The agent said nothing after the parser was fixed", "said"),
            ("although joiner", "The agent said nothing although the parser is fixed", "said"),
            ("as joiner", "The agent said it ran as the parser works", "said"),
            ("or joiner", "The agent said it ran or the parser works", "said"),
            ("text after a quote", 'The agent said "it ran" fixed the parser', "said"),
            ("comma in a quote", 'The agent said "it ran," the bug is fixed', "said"),
            ("semicolon in a quote", 'The agent said "it ran;" fixed the parser', "did"),
            ("implicit then dash", "Said it ran \u2014 fixed the parser", "said"),
            ("implicit colon not after verb", "Asked whether it ran: the parser is fixed", "asked"),
            (
                "joiner hidden by ZWJ",
                "The agent said it ran and\u200d the parser is fixed.",
                "said",
            ),
            ("soft hyphen in word", "The bug is fi\u00adxed", "said"),
            (
                "single-quoted sentence end",
                "The agent said 'I will inspect it.' The parser is fixed.",
                "said",
            ),
            ("check paraphrased", "The check showed the feature works", "did"),
            ("tool output paraphrased", "The tool output showed everything is done", "did"),
            ("error log shows", "The error log shows the deploy succeeded", "did"),
            (
                "report without comma",
                "The check reported passed as the tool reported leaving the parser fixed",
                "did",
            ),
            (
                "report inside speech without comma",
                "The agent said pytest reported passed as the tool reported the bug is fixed",
                "said",
            ),
            (
                "words before a report",
                "The check reported the bug is fixed passed, as the tool reported",
                "did",
            ),
            (
                "words after a report",
                "pytest reported passed, as the tool reported the bug is fixed",
                "did",
            ),
            ("postfix report", "Everything passed, as the tool reported", "did"),
            ("postfix report on the work", "The parser passed, as the tool reported", "did"),
            ("compound with and", "The parser is `fixed-and-verified`.", "did"),
            ("compound with all", "The parser is `all-fixed`.", "did"),
            ("compound with is", "Edited `parser-is-fixed`", "did"),
            ("branch of filler", "Pushed branch fully-fixed", "did"),
            ("dotted words", "it.is.fixed", "did"),
            ("dotted without extension", "Parser.fixed", "did"),
            ("capitalized after dot", "The parser works.Now", "did"),
            ("backticked sentence state", "Set the status to `the parser is fixed`", "did"),
            ("backticked phrase state", "Marked the ticket as `fixed and verified`", "did"),
            ("multi-word state not at end", "Moved the ticket to Done Fixed the parser", "did"),
            ("bare work", "Made the parser work", "did"),
            ("bare work present", "The parser now work", "did"),
            ("check failed colon", "pytest failed: ImportError cannot merge module", "failed"),
            ("claim after cap", "Inspected " + "x" * 250 + "; fixed the parser", "did"),
        ]
        for condition, text, kind in cases:
            with self.subTest(condition=condition):
                self.assert_completion_verdict(text, "withheld", kind)

    def test_attributed_speech_previously_matched_the_literal_backstop(self) -> None:
        texts = [
            "The agent said the parser is fixed",
            "The person reported it works",
            "The user asked to fix the parser",
            "The error said unable to verify the cache",
            "The error read unable to repair the cache",
            "The subagent replied it had implemented the change",
            "The teammate replied the release was shipped",
            "The reviewer suggested fixing the parser",
            "“The build is green,” the agent said",
        ]
        for text in texts:
            with self.subTest(text=text):
                self.assertIsNotNone(self.summary._COMPLETION.search(text))
                self.assert_completion_verdict(text, "kept", "did")

    def test_clipping_rechecks_attribution_and_names_in_the_surviving_prefix(self) -> None:
        for condition, text, cap in [
            ("postposed attribution", '"The parser is fixed," the agent said', 22),
            ("tool report", "pytest reported passed, as the tool reported", 23),
            ("identifier", "Read fixed.py", 11),
        ]:
            with self.subTest(condition=condition):
                model = Replies({"phases": [phase([1], text=text)]})
                bullet = self.run_summary(
                    [entry(1, "check", result="passed")],
                    model,
                    session_summary_bullet_chars=cap,
                ).as_dict()["blocks"][0]["phases"][0]["bullets"][0]
                self.assertEqual({"withheld": True, "reason": "too_long_cut"}, bullet["text"])

    def test_backstop_runs_before_cut_and_checks_surviving_prefix(self) -> None:
        model = Replies(
            {"phases": [phase([1], text="Inspected " + "x" * 250 + "; fixed the parser")]}
        )
        data = self.run_summary([entry(1)], model).as_dict()
        self.assertEqual(
            "completion_claim", data["blocks"][0]["phases"][0]["bullets"][0]["text"]["reason"]
        )

    def test_redaction_precedes_clips_and_every_prompt(self) -> None:
        secrets = [
            "AK" + "IA" + "A1" * 8,
            "gh" + "p_" + "a" * 36,
            "sk" + "-ant-" + "a" * 100,
            "-----BEGIN " + "PRIVATE KEY-----",
        ]
        entries = [entry(i, words="z" * 1189 + " " + value) for i, value in enumerate(secrets, 1)]
        entries += [
            entry(5, "agent", words=" ".join(secrets)),
            entry(6, "check", words="ignored", result="passed"),
            entry(7, "file", path=" ".join(secrets)),
        ]
        model = Replies({"phases": [phase(list(range(1, 8)))]})
        self.run_summary(entries, model)
        for prompt in model.prompts:
            for secret in secrets:
                self.assertNotIn(secret, prompt)
        self.assertIn("…redacted", model.prompts[0].lower())

    def test_bounds_cut_and_mark_without_splitting_blocks(self) -> None:
        entries = [entry(n) for n in range(1, 11)]
        p = phase(list(range(1, 11)), text="Inspected " + "x" * 250, title="Inspection " + "x" * 80)
        p["bullets"] *= 8
        data = self.run_summary(
            entries, Replies({"phases": [p] * 7}, {"lede": "Requested " + "x" * 500, "cites": [1]})
        ).as_dict()
        block = data["blocks"][0]
        self.assertEqual(4, len(block["phases"]))
        self.assertEqual(3, block["cut"]["phases"])
        self.assertEqual(6, len(block["phases"][0]["bullets"]))
        bullet = block["phases"][0]["bullets"][0]
        self.assertEqual(8, len(bullet["cites"]))
        self.assertTrue(bullet["cut"])
        self.assertEqual(200, len(bullet["text"]))
        self.assertTrue(bullet["text"].endswith("…"))
        self.assertEqual(60, len(block["phases"][0]["title"]))
        self.assertEqual(400, len(data["lede"]["text"]))
        large = [entry(n, words="x" * 70) for n in range(1, 7)]
        result = self.run_summary(
            large, session_summary_window_bytes=100, session_summary_max_bytes=1700
        )
        self.assertLessEqual(
            len(json.dumps(result.as_dict(), ensure_ascii=False, separators=(",", ":")).encode()),
            1700,
        )
        self.assertEqual("bytes", result.as_dict()["blocks"][-1]["reason"])

    def test_preflight_spends_nothing_when_the_plan_exceeds_calls_or_bytes(self) -> None:
        for bounds in ({"session_summary_max_calls": 1}, {"session_summary_max_bytes_sent": 10}):
            model = Replies()
            result = self.run_summary([entry(1)], model, **bounds)
            self.assertEqual("refused", result.state)
            self.assertEqual([], model.prompts)
            self.assertEqual(0, result.spend.calls)

    def test_empty_retry_spends_and_mid_job_call_ceiling_keeps_gaps(self) -> None:
        entries = [entry(n, words="x" * 70) for n in range(1, 4)]
        model = Replies(("", "unstopped"), ("", "failed"))
        result = self.run_summary(
            entries, model, session_summary_window_bytes=100, session_summary_max_calls=4
        )
        self.assertEqual(4, result.spend.calls)
        self.assertEqual(1, result.spend.retries)
        self.assertEqual("no_output", result.as_dict()["blocks"][0]["reason"])
        self.assertIsNone(result.lede)
        self.assertEqual("ceiling", result.lede_reason)

    def test_seconds_ceiling_stops_remaining_windows(self) -> None:
        elapsed = [0.0]
        recorded = Replies()

        def model(prompt: str, *, output_cap_bytes: int) -> tuple[str, str]:
            elapsed[0] = 601.0
            return recorded(prompt, output_cap_bytes=output_cap_bytes)

        result = self.summary.summarize(
            [entry(n, words="x" * 70) for n in range(1, 4)],
            self.coverage,
            "claude",
            config=dataclasses.replace(self.config, session_summary_window_bytes=100),
            model=model,
            clock=lambda: elapsed[0],
        )
        self.assertEqual(1, result.spend.calls)
        self.assertEqual(
            ["ceiling", "ceiling"], [b["reason"] for b in result.as_dict()["blocks"][1:]]
        )

    def test_terminal_statuses_stop_without_retry(self) -> None:
        for status in ("unavailable", "closed", "cancelled"):
            model = Replies(("", status))
            result = self.run_summary(
                [entry(n, words="x" * 70) for n in range(1, 4)],
                model,
                session_summary_window_bytes=100,
            )
            self.assertEqual(1, len(model.prompts))
            self.assertEqual(0, result.spend.retries)
            self.assertTrue(all(b["gap"] for b in result.as_dict()["blocks"]))
        model = Replies(
            RefusedError(
                {
                    "consent": False,
                    "off": True,
                    "notices": {},
                    "used": 0,
                    "limit": 100,
                    "retry_at": None,
                    "reason": "model-calls-paused",
                    "providers": {},
                    "rebind": {},
                    "tool_output": {},
                    "words": {},
                }
            )
        )
        result = self.run_summary([entry(1)], model)
        self.assertEqual("refused", result.state)
        self.assertEqual("refused", result.as_dict()["blocks"][0]["reason"])

    def test_newest_32_windows_leave_an_explicit_prefix_gap(self) -> None:
        entries = [entry(n, words=f"Unique request {n} " + "x" * 70) for n in range(1, 36)]
        model = Replies()
        result = self.run_summary(entries, model, session_summary_window_bytes=100)
        self.assertEqual("fact-4", result.starts_at)
        gap = result.as_dict()["blocks"][0]
        self.assertEqual(
            ("before_window", "fact-1", "fact-3", 3, "outline"),
            (gap["reason"], gap["first"], gap["last"], gap["entries"], gap["see"]),
        )
        self.assertEqual(33, result.spend.calls)
        self.assertNotIn("Unique request 1 ", "\n".join(model.prompts))

    def test_update_only_sends_new_entries_and_preserves_finished_blocks(self) -> None:
        old = [entry(1, words="EARLIER PRIVATE SYNTHETIC TEXT")]
        prior = self.run_summary(old)
        model = Replies(
            {"phases": [phase([1, 2]), phase([1])]},
            {"lede": "The person extended the review.", "cites": [2]},
        )
        result = self.summary.update(
            prior,
            [*old, entry(2, words="NEW SYNTHETIC REQUEST")],
            self.coverage,
            session_source.SourceChange("appended", appended=("fact-2",)),
            config=self.config,
            model=model,
            clock=lambda: 0.0,
        )
        self.assertIs(prior.blocks[0], result.blocks[0])
        self.assertNotIn("EARLIER PRIVATE SYNTHETIC TEXT", "\n".join(model.prompts))
        self.assertEqual(
            ["fact-2"], result.as_dict()["blocks"][1]["phases"][0]["bullets"][0]["cites"]
        )
        self.assertEqual(2, result.spend.calls)
        for kind in ("changed_earlier", "truncated", "replaced"):
            untouched = Replies()
            changed = self.summary.update(
                prior,
                old,
                self.coverage,
                session_source.SourceChange(kind),
                config=self.config,
                model=untouched,
                clock=lambda: 0.0,
            )
            self.assertEqual("source_changed", changed.state)
            self.assertEqual([], untouched.prompts)
        changed = self.summary.update(
            prior,
            [entry(1, words="Altered earlier words")],
            self.coverage,
            session_source.SourceChange("appended"),
            config=self.config,
            model=Replies(),
            clock=lambda: 0.0,
        )
        self.assertEqual("source_changed", changed.state)
        self.assertEqual((0,), changed.affected_blocks)
        unchanged = self.summary.update(
            prior,
            old,
            self.coverage,
            session_source.SourceChange("unchanged"),
            config=self.config,
            model=Replies(),
            clock=lambda: 0.0,
        )
        self.assertIs(prior, unchanged)

    def test_unsupported_harness_spends_nothing(self) -> None:
        for harness in ("codex", "pi", "droid"):
            model = Replies()
            result = self.summary.summarize(
                [entry(1)],
                self.coverage,
                harness,
                config=self.config,
                model=model,
                clock=lambda: 0.0,
            )
            self.assertEqual(
                ("unsupported", "harness_not_supported"), (result.state, result.reason)
            )
            self.assertEqual([], model.prompts)

    def test_asked_cut_keeps_the_instruction_with_following_work(self) -> None:
        entries = [entry(n, "person" if n in {1, 3} else "agent", "x" * 20) for n in range(1, 6)]
        result = self.run_summary(entries, session_summary_window_bytes=120)
        self.assertEqual(
            [("fact-1", "fact-2"), ("fact-3", "fact-5")], [(b.first, b.last) for b in result.blocks]
        )

    def test_context_and_lede_do_not_repeat_earlier_entries_or_model_bullets(self) -> None:
        entries = [
            entry(1, words="FIRST SYNTHETIC ENTRY " + "x" * 1200),
            entry(2, words="SECOND SYNTHETIC ENTRY " + "y" * 1200),
        ]
        model = Replies(
            {"phases": [phase([1], text="Inspected SYNTHETIC BULLET", title="Inspection context")]},
            {"phases": [phase([1, 2])]},
            {"lede": "The person requested inspection.", "cites": [1, 2]},
        )
        result = self.run_summary(entries, model, session_summary_window_bytes=2048)
        self.assertIn("Inspection context", model.prompts[1])
        self.assertNotIn("FIRST SYNTHETIC ENTRY", model.prompts[1])
        self.assertNotIn("SYNTHETIC BULLET", model.prompts[1])
        self.assertNotIn("SYNTHETIC BULLET", model.prompts[-1])
        self.assertNotIn("Inspection context", model.prompts[-1])
        self.assertLessEqual(len(model.prompts[-1].split("Record:\n")[1].encode()), 2048)
        self.assertEqual(
            ["fact-2"], result.as_dict()["blocks"][1]["phases"][0]["bullets"][0]["cites"]
        )

    def test_byte_bound_lede_reads_only_retained_blocks(self) -> None:
        entries = [
            entry(n, "agent" if n < 6 else "person", words=f"ENTRY{n} " + "x" * 80)
            for n in range(1, 7)
        ]
        model = Replies()
        result = self.run_summary(
            entries,
            model,
            session_summary_window_bytes=120,
            session_summary_max_bytes=1800,
            session_summary_lede_chars=80,
        )
        retained = {b.first for b in result.blocks if b.phases}
        self.assertIn("bytes", [b.reason for b in result.blocks])
        lede_prompts = [p for p in model.prompts if p.startswith("Write at most")]
        self.assertEqual(1, len(lede_prompts))
        for n in range(1, 7):
            if f"fact-{n}" not in retained:
                self.assertNotIn(f"ENTRY{n} ", lede_prompts[0])

    def test_call_and_response_bytes_are_accounted_and_output_cap_is_forwarded(self) -> None:
        model = Replies(
            {"phases": [phase([1])]},
            ("", "unstopped"),
            {"lede": "Requested inspection.", "cites": [1]},
        )
        result = self.run_summary([entry(1)], model)
        self.assertEqual(3, result.spend.calls)
        self.assertEqual(1, result.spend.retries)
        self.assertEqual(sum(len(p.encode()) for p in model.prompts), result.spend.bytes_sent)
        self.assertEqual([65536] * 3, model.caps)

    def test_untitled_phase_does_not_hide_a_sibling_and_failed_lede_keeps_it(self) -> None:
        model = Replies({"phases": [phase([1], title=""), phase([1])]}, "not JSON")
        data = self.run_summary([entry(1)], model).as_dict()
        self.assertEqual(1, len(data["blocks"][0]["phases"]))
        self.assertEqual({"shape_fault": 1}, data["blocks"][0]["withheld_phases"])
        self.assertIsNone(data["lede"])
        self.assertEqual("no_valid_reply", data["lede_reason"])

    def test_call_and_byte_ceilings_after_retries_leave_later_window_gaps(self) -> None:
        entries = [entry(n, words="x" * 70) for n in range(1, 4)]
        for bound in ({"session_summary_max_calls": 4}, {"session_summary_max_bytes_sent": 7000}):
            model = Replies(("", "unstopped"), ("", "failed"), ("", "oversized"), ("", "failed"))
            result = self.run_summary(entries, model, session_summary_window_bytes=100, **bound)
            self.assertEqual("partial", result.state)
            self.assertEqual("ceiling", result.blocks[-1].reason)
            self.assertEqual(4, result.spend.calls)
            self.assertLessEqual(result.spend.bytes_sent, 7000)

    def test_a_later_refusal_keeps_finished_blocks_and_does_not_retry(self) -> None:
        entries = [entry(n, words="x" * 70) for n in range(1, 4)]
        model = Replies({"phases": [phase([1])]}, ("", "unavailable"))
        result = self.run_summary(entries, model, session_summary_window_bytes=100)
        self.assertEqual("partial", result.state)
        self.assertTrue(result.blocks[0].phases)
        self.assertEqual(["stopped", "stopped"], [b.reason for b in result.blocks[1:]])
        self.assertEqual(1, result.spend.calls)
        self.assertEqual(0, result.spend.retries)
        self.assertIsNone(result.lede)

    def test_clipping_cannot_remove_the_tool_attribution_and_leave_a_claim(self) -> None:
        model = Replies(
            {"phases": [phase([1], text="Parser passed " + "x" * 210 + ", as the tool reported")]}
        )
        data = self.run_summary([entry(1)], model).as_dict()
        self.assertEqual(
            {"withheld": True, "reason": "completion_claim"},
            data["blocks"][0]["phases"][0]["bullets"][0]["text"],
        )

    def test_utf8_windows_bound_single_lines_without_splitting_characters(self) -> None:
        model = Replies()
        entries = [entry(n, words="界" * 700) for n in range(1, 4)]
        result = self.run_summary(entries, model, session_summary_window_bytes=120)
        self.assertEqual(3, len(result.blocks))
        for prompt in model.prompts:
            record = prompt.split("Record:\n")[1]
            self.assertLessEqual(len(record.encode()), 120)
            self.assertNotIn("\ufffd", record)

    def test_resumed_and_teammate_text_in_person_turns_is_relayed(self) -> None:
        entries = [
            entry(
                1,
                words='<teammate-message teammate_id="synthetic">inspect parser</teammate-message>',
            ),
            entry(
                2,
                words="This session is being continued from a previous conversation: synthetic context",
            ),
        ]
        model = Replies({"phases": [phase([1, 2])]})
        result = self.run_summary(entries, model)
        self.assertIn("[1] relayed:", model.prompts[0])
        self.assertIn("[2] relayed:", model.prompts[0])
        self.assertEqual("said", result.blocks[0].phases[0].bullets[0].kind)

    def test_empty_source_and_invalid_unicode_reply_are_stated_without_guessing(self) -> None:
        model = Replies()
        result = self.run_summary([], model)
        self.assertEqual("no_entries", result.reason)
        self.assertEqual([], model.prompts)
        result = self.run_summary([entry(1)], Replies("invalid \ud800 reply"))
        self.assertEqual("no_valid_reply", result.blocks[0].reason)

    def test_pass_check_does_not_license_pass_words_outside_the_tool_report(self) -> None:
        entries = [entry(1, "check", result="passed")]
        texts = [
            "pytest reported passed, as the tool reported",
            "Tests passed",
            "The build went green.",
            "Fixed the parser",
        ]
        model = Replies(
            {
                "phases": [
                    {
                        "title": "Check report",
                        "bullets": [phase([1], text=t)["bullets"][0] for t in texts],
                    }
                ]
            }
        )
        bullets = self.run_summary(entries, model).as_dict()["blocks"][0]["phases"][0]["bullets"]
        self.assertEqual(texts[0], bullets[0]["text"])
        withheld = {"withheld": True, "reason": "completion_claim"}
        self.assertEqual([withheld] * 3, [b["text"] for b in bullets[1:]])

    def test_prose_after_a_complete_reply_is_unreadable(self) -> None:
        reply = json.dumps({"phases": [phase([1])]}) + " I also confirm delivery."
        block = self.run_summary([entry(1)], Replies(reply)).as_dict()["blocks"][0]
        self.assertEqual("no_valid_reply", block["reason"])
        self.assertNotIn("cut", block)

    def test_lede_reports_how_many_citations_were_cut(self) -> None:
        entries = [entry(n) for n in range(1, 4)]
        p = phase([1, 2])
        p["bullets"].append(phase([3])["bullets"][0])
        model = Replies(
            {"phases": [p]}, {"lede": "The person requested a review.", "cites": [1, 2, 3]}
        )
        lede = self.run_summary(entries, model, session_summary_max_cites=2).as_dict()["lede"]
        self.assertEqual(
            (["fact-1", "fact-2"], True, 1), (lede["cites"], lede["cut"], lede["cites_cut"])
        )

    def test_malformed_bullet_rows_are_withheld_in_place(self) -> None:
        rows = [{"text": ""}, {"text": "Read it", "cites": [1]}, 5]
        model = Replies({"phases": [{"title": "Inspection", "bullets": rows}]})
        bullets = self.run_summary([entry(1)], model).as_dict()["blocks"][0]["phases"][0]["bullets"]
        fault = {"withheld": True, "reason": "shape_fault"}
        self.assertEqual([fault, "Read it", fault], [b["text"] for b in bullets])

    def test_a_refused_retry_is_not_counted_as_sent(self) -> None:
        result = self.run_summary([entry(1)], Replies(("", "failed"), refusal()))
        self.assertEqual((1, 0), (result.spend.calls, result.spend.retries))

    def test_a_seam_exception_stops_the_job_and_keeps_finished_blocks(self) -> None:
        entries = [entry(n, words="x" * 70) for n in range(1, 4)]
        model = Replies({"phases": [phase([1])]}, TimeoutError("synthetic"))
        result = self.run_summary(entries, model, session_summary_window_bytes=100)
        self.assertEqual(("partial", "stopped"), (result.state, result.reason))
        self.assertTrue(result.blocks[0].phases)
        self.assertEqual(["stopped", "stopped"], [b.reason for b in result.blocks[1:]])
        self.assertEqual(2, result.spend.calls)

    def test_blocks_dropped_for_bytes_name_bytes_as_the_reason(self) -> None:
        large = [entry(n, words="x" * 70) for n in range(1, 7)]
        result = self.run_summary(
            large, session_summary_window_bytes=100, session_summary_max_bytes=1700
        )
        self.assertEqual(
            ("partial", "bytes", "bytes"), (result.state, result.reason, result.lede_reason)
        )
        self.assertEqual(
            [("fact-1", "fact-6", "bytes")], [(b.first, b.last, b.reason) for b in result.blocks]
        )

    def update(
        self,
        prior: Any,
        entries: Sequence[session_source.SourceEntry],
        change: session_source.SourceChange,
        model: Replies,
        **bounds: Any,
    ) -> Any:
        return self.summary.update(
            prior,
            entries,
            self.coverage,
            change,
            config=dataclasses.replace(self.config, **bounds),
            model=model,
            clock=lambda: 0.0,
        )

    def test_late_evidence_between_prior_blocks_is_a_source_change(self) -> None:
        old = [entry(n, words="x" * 70) for n in range(1, 5)]
        prior = self.run_summary(old, session_summary_window_bytes=100)
        late = dataclasses.replace(entry(9, "check", result="passed"), fact_id="fact-X", at=2.5)
        model = Replies()
        result = self.update(
            prior,
            [*old[:2], late, *old[2:], entry(5, words="x" * 70)],
            session_source.SourceChange("appended", appended=("fact-X", "fact-5")),
            model,
            session_summary_window_bytes=100,
        )
        self.assertEqual(("source_changed", "late_evidence"), (result.state, result.reason))
        self.assertEqual((2,), result.affected_blocks)
        self.assertEqual([], model.prompts)

    def test_a_pending_check_resolved_in_the_tail_block_is_summarized_again(self) -> None:
        pending = entry(2, "check", result="not-recorded")
        old = [entry(1, words="EARLIER " + "x" * 70), pending]
        prior = self.run_summary(old, session_summary_window_bytes=100)
        resolved = dataclasses.replace(pending, fingerprint="f" * 32, result="passed")
        model = Replies()
        result = self.update(
            prior,
            [old[0], resolved, entry(3, words="NEW " + "x" * 70)],
            session_source.SourceChange(
                "changed_earlier", changed=(("fact-2", "check_result"),), appended=("fact-3",)
            ),
            model,
            session_summary_window_bytes=100,
        )
        self.assertEqual("ok", result.state)
        self.assertIs(prior.blocks[0], result.blocks[0])
        self.assertEqual(["fact-1", "fact-2", "fact-3"], [b.first for b in result.blocks])
        self.assertIn("result as the tool reported: passed", "\n".join(model.prompts))
        self.assertNotIn("EARLIER", "\n".join(model.prompts))
        earlier = self.update(
            prior,
            [dataclasses.replace(old[0], fingerprint="e" * 32), pending],
            session_source.SourceChange("changed_earlier", changed=(("fact-1", "check_result"),)),
            Replies(),
            session_summary_window_bytes=100,
        )
        self.assertEqual("source_changed", earlier.state)

    def test_an_update_with_no_room_left_refuses_before_any_call(self) -> None:
        prior = self.run_summary([entry(1)])
        size = len(json.dumps(prior.as_dict(), ensure_ascii=False, separators=(",", ":")).encode())
        for room in (30, 700):
            model = Replies()
            result = self.update(
                prior,
                [entry(1), entry(2)],
                session_source.SourceChange("appended", appended=("fact-2",)),
                model,
                session_summary_max_bytes=size + room,
            )
            self.assertEqual(("refused", "output_bound_full"), (result.state, result.reason))
            self.assertEqual(([], 0), (model.prompts, result.spend.calls))
            self.assertIs(prior.lede, result.lede)

    def test_a_failed_update_lede_keeps_the_prior_lede(self) -> None:
        prior = self.run_summary([entry(1)])
        result = self.update(
            prior,
            [entry(1), entry(2)],
            session_source.SourceChange("appended", appended=("fact-2",)),
            Replies({"phases": [phase([])]}),
        )
        self.assertIsNotNone(prior.lede)
        self.assertIs(prior.lede, result.lede)
        self.assertIsNone(result.lede_reason)


def refusal() -> RefusedError:
    return RefusedError(
        {
            "consent": False,
            "off": True,
            "notices": {},
            "used": 0,
            "limit": 100,
            "retry_at": None,
            "reason": "model-calls-paused",
            "providers": {},
            "rebind": {},
            "tool_output": {},
            "words": {},
        }
    )
