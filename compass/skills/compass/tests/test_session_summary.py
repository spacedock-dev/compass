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

    def test_backstop_keeps_attribution_and_names_but_refuses_own_voice(self) -> None:
        cases = [
            ("Fixed the parser", True),
            ("the agent said the parser is fixed", False),
            ("Said the fix is done", False),
            ("the person reported it works", False),
            ("pytest reported passed, as the tool reported", False),
            ('Quoted "the parser is fixed"', False),
            ("Quoted 'done'", False),
            ("Reviewed a list of fixes", False),
            ("Inspected the `fix/foo` branch", False),
            ("Moved the issue to Done", False),
            ("Marked the state as complete", True),
            ("Asked the agent to fix the parser", False),
            ("Got the tests to pass", True),
            ("The agent reported the error and fixed the parser", True),
            ("Fixed the parser, pytest reported passed, as the tool reported", True),
            ("Inspected the parser and the agent said it is fixed", False),
            ("Working on the parser", False),
            ("The agent said it is fixed; shipped the parser", True),
            ("The agent said it is fixed, but the parser works", True),
            ("The agent said it is fixed\nShipped the parser", True),
            ("Ship the parser", True),
            ("The parser is resolved", True),
            ("Merged the change", True),
        ]
        for text, withheld in cases:
            with self.subTest(text=text):
                model = Replies({"phases": [phase([1], text=text)]})
                value = self.run_summary([entry(1)], model).as_dict()["blocks"][0]["phases"][0][
                    "bullets"
                ][0]["text"]
                if withheld:
                    self.assertEqual({"withheld": True, "reason": "completion_claim"}, value)
                else:
                    self.assertEqual(text, value)
        model = Replies(
            {"phases": [phase([1], title="Fixed the parser")]},
            {"lede": "Completed the parser", "cites": [1]},
        )
        data = self.run_summary([entry(1)], model).as_dict()
        self.assertEqual("completion_claim", data["lede"]["reason"])
        self.assertEqual("completion_claim", data["blocks"][0]["phases"][0]["title"]["reason"])
        self.assertEqual(1, len(data["blocks"][0]["phases"][0]["bullets"]))

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
                    "reason": "readings-off",
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

    def test_pass_check_does_not_license_a_delivery_claim(self) -> None:
        entries = [entry(1, "check", result="passed")]
        model = Replies(
            {
                "phases": [
                    {
                        "title": "Check report",
                        "bullets": [
                            phase([1], text="Tests passed", kind="did")["bullets"][0],
                            phase([1], text="Fixed the parser", kind="did")["bullets"][0],
                        ],
                    }
                ]
            }
        )
        bullets = self.run_summary(entries, model).as_dict()["blocks"][0]["phases"][0]["bullets"]
        self.assertEqual("Tests passed", bullets[0]["text"])
        self.assertFalse(bullets[0]["kind_overridden"])
        self.assertEqual({"withheld": True, "reason": "completion_claim"}, bullets[1]["text"])
