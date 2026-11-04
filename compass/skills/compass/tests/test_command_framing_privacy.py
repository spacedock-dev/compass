"""Premasked command callers retain ordinary arguments without exposing credentials."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest import mock

from compass_runtime import annotations as annotation_store
from compass_runtime import (
    copied_corrections,
    http_api,
    observer,
    project_context,
    reading,
    records,
    semantic_history,
    transcripts,
)

from . import test_copied_corrections as copied_cases
from . import test_window_words as window_cases
from .test_claude_checks import SHORT, START, Transcript
from .test_slash_command_direction import NOW, _SlashSession, local_command, prompt_command

ORDINARY = ("token: ordinary", "secret: disabled", "password: placeholder")
EXAMPLE = "AKIAIOSFODNN7EXAMPLE"


class TheObserverRetainsOriginalCommandFraming(_SlashSession):
    def observe(self, raw: str, *, model: Any = None) -> dict[str, Any]:
        self.session._text(raw)
        self.session.save(self.board.path)
        return observer.analyze(
            self.config, self.state, str(self.board.path), now=NOW, window_sec=86400, model=model
        )

    def test_complete_ordinary_cue_arguments_reach_the_observer_goal_without_a_false_cut(
        self,
    ) -> None:
        for value in ORDINARY:
            with self.subTest(value=value):
                result = self.observe(prompt_command("review", value))
                self.assertEqual(f"/review {value}", result["goal"])
                self.assertNotIn("…", result["goal"])

    def test_complete_ordinary_cue_arguments_reach_the_actual_instruction_event(self) -> None:
        for value in ORDINARY:
            with self.subTest(value=value):
                self.session.skill("review", value)
                self.assertEqual(f"/review {value}", self.titles()[-1])
                fact = max(
                    (f for f in self.facts() if f.get("type") == "user_message"),
                    key=lambda f: f["at"],
                )
                ledger = reading.build_ledger([fact], "claude", SHORT)
                self.assertEqual(f"/review {value}", ledger[0]["words"])

    def test_ordinary_cue_arguments_reach_history_without_wrappers_or_false_cuts(self) -> None:
        self.session.skill("review", ORDINARY[0])
        self.facts()
        stored = semantic_history.read(self.config, self.state, "billing")
        user = [
            event for event in stored["events"] if event.get("event_type") == "operator_direction"
        ]
        self.assertTrue(user, stored)
        self.assertIn(f"/review {ORDINARY[0]}", [event["summary"] for event in user])
        self.assertNotIn("command-args", json.dumps(stored))

    def test_the_optional_observer_model_packet_keeps_the_safe_command_arguments(self) -> None:
        packets: list[str] = []

        def model(recent: str, _stage: str) -> None:
            packets.append(recent)

        result = self.observe(prompt_command("review", ORDINARY[0]), model=model)
        self.assertEqual(f"/review {ORDINARY[0]}", result["deterministic_goal"])
        self.assertEqual(1, len(packets))
        self.assertIn(f"/review {ORDINARY[0]}", packets[0])
        self.assertNotIn("command-args", packets[0])

    def test_documented_credentials_stay_masked_in_events_history_and_optional_packets(
        self,
    ) -> None:
        value = "token: AKIA<em>IOSFODNN7EXAMPLE</em>"
        packets: list[str] = []
        result = self.observe(
            prompt_command("review", value), model=lambda recent, _stage: packets.append(recent)
        )
        self.assertNotIn(EXAMPLE, json.dumps(result) + " ".join(packets))
        self.assertIn("REDACTED", result["goal"])
        parsed = observer.parse_message_record(
            {"type": "user", "message": {"content": prompt_command("review", value)}}
        )
        assert parsed is not None
        self.assertFalse(transcripts.command_cut(parsed["text"]))
        facts = self.facts()
        published = project_context.for_page({"semantic": {"facts": facts}})
        history = semantic_history.read(self.config, self.state, "billing")
        for artifact in (facts, published, history):
            self.assertNotIn(EXAMPLE, json.dumps(artifact))
            self.assertNotIn("IOSFODNN7EXAMPLE", json.dumps(artifact))

    def test_local_and_shared_controls_still_fall_back_to_the_real_objective(self) -> None:
        for raw in (local_command("compact", ORDINARY[0]), prompt_command("insights", ORDINARY[0])):
            with self.subTest(raw=raw):
                self.assertEqual(
                    "Add retry with backoff to the webhook handler.", self.observe(raw)["goal"]
                )

    def test_genuinely_missing_command_args_closing_tag_remains_a_cut(self) -> None:
        raw = prompt_command("review", ORDINARY[0]).removesuffix("</command-args>")
        parsed = observer.parse_message_record({"type": "user", "message": {"content": raw}})
        assert parsed is not None
        self.assertTrue(transcripts.command_cut(parsed["text"]))
        self.assertEqual(
            f"/review {ORDINARY[0]}…", transcripts.command_direction(self.config, parsed["text"])
        )
        self.assertEqual(f"/review {ORDINARY[0]}…", self.observe(raw)["goal"])

    def test_preextraction_redaction_remains_safe_at_each_source_cap(self) -> None:
        for cap in (2000, 8192):
            raw = prompt_command("review", "word " * ((cap - 120) // 5) + EXAMPLE)
            for content in (raw, [{"type": "text", "text": raw}], {"content": raw}):
                with self.subTest(cap=cap, shape=type(content).__name__):
                    parsed = observer._message_from("user", content, "claude", cap)
                    assert parsed is not None
                    self.assertLessEqual(len(parsed["text"]), cap)
                    self.assertNotIn("IOSFODNN7EXAMPLE", parsed["text"])
                    self.assertIn("REDACTED", parsed["text"])

    def test_the_child_observer_packet_uses_the_same_safe_command_projection(self) -> None:
        self.session._text(prompt_command("review", ORDINARY[0]))
        self.session._entry("assistant", [{"type": "text", "text": "Synthetic response."}])
        self.session.save(self.board.path)
        packets: list[str] = []

        def model(recent: str, _stage: str) -> None:
            packets.append(recent)

        observer.derive_child_assignment(self.config, str(self.board.path), model)
        self.assertEqual(1, len(packets))
        self.assertIn(f"/review {ORDINARY[0]}", packets[0])
        self.assertNotIn("command-args", packets[0])

    def test_a_command_at_the_source_cap_keeps_ordinary_framing_without_expansion(self) -> None:
        for cap in (2000, 8192):
            padding = cap - len(prompt_command("review", ORDINARY[0]))
            raw = prompt_command("review", "x" * (padding - 1) + " " + ORDINARY[0])
            self.assertEqual(cap, len(raw))
            parsed = observer._message_from("user", raw, "claude", cap)
            assert parsed is not None
            self.assertFalse(transcripts.command_cut(parsed["text"]))
            self.assertEqual(raw, parsed["text"])

    def test_malformed_overlapping_framing_keeps_credential_scrubbing(self) -> None:
        raw = (
            "<command-message><command-name>/review</command-name> token: "
            + EXAMPLE
            + "</command-message>"
        )
        parsed = observer.parse_message_record({"type": "user", "message": {"content": raw}})
        assert parsed is not None
        self.assertNotIn("IOSFODNN7EXAMPLE", parsed["text"])
        self.assertIn("REDACTED", parsed["text"])
        self.assertEqual(2, parsed["text"].count("command-name"))

    def test_a_long_goal_remains_bounded_and_redacted_after_command_rendering(self) -> None:
        raw = prompt_command("review", "Use " + EXAMPLE + " then " + "word " * 80)
        result = self.observe(raw)
        self.assertLessEqual(len(result["goal"]), self.config.observer_goal_cap_chars + 1)
        self.assertTrue(result["goal"].endswith("…"))
        self.assertIn("REDACTED", result["goal"])
        self.assertNotIn("IOSFODNN7EXAMPLE", result["goal"])

    def test_the_optional_packet_keeps_its_original_bound_after_rendering(self) -> None:
        self.session._text(
            prompt_command("review", "token: " + EXAMPLE + " then " + "word " * 3000)
        )
        self.session._entry("assistant", [{"type": "text", "text": "Observed response. " * 200}])
        self.session.save(self.board.path)
        packets: list[str] = []

        def model(recent: str, _stage: str) -> None:
            packets.append(recent)

        observer.analyze(
            self.config, self.state, str(self.board.path), now=NOW, window_sec=86400, model=model
        )
        self.assertEqual(1, len(packets))
        self.assertLessEqual(len(packets[0]), self.config.observer_model_context_chars)
        self.assertIn("REDACTED", packets[0])
        self.assertNotIn("IOSFODNN7EXAMPLE", packets[0])

    def test_a_malformed_long_command_stays_bounded_before_extraction(self) -> None:
        code = r"""
from compass.skills.compass.tests.test_claude_checks import SHORT
from compass_runtime import observer
import time
raw = '<command-message>token: AKIAIOSFODNN7EXAMPLE ' + ' ' * 300000
started = time.monotonic()
parsed = observer.parse_message_record({'type': 'user', 'message': {'content': raw}})
assert time.monotonic() - started < 10, 'Malformed framing exceeded its parse allowance'
assert parsed is None or len(parsed['text']) <= 2000
assert parsed is None or 'IOSFODNN7EXAMPLE' not in parsed['text']
"""
        try:
            result = subprocess.run(
                [sys.executable, "-c", code],
                cwd=Path(__file__).resolve().parents[4],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        except subprocess.TimeoutExpired:
            self.fail("A malformed full command stalled before the source cap")
        self.assertEqual(0, result.returncode, result.stderr)


class CopiedCommandProvenanceKeepsTheCorrectFirstPrompt(copied_cases._App):
    def test_a_same_time_typed_command_is_not_withheld_as_a_copied_correction(self) -> None:
        # A copied and a typed message share a timestamp. Only the raw digest
        # match is derived; the first-prompt projection must join the typed one.
        self.session = Transcript(self.root / "work" / "billing")
        self.path.write_bytes(b"")
        self.register(now=START.timestamp())
        typed = prompt_command("review", ORDINARY[0])
        typed_at = copied_cases._paste(self.session, typed)
        self.session.seconds -= 5
        pasted_at = copied_cases._paste(self.session, copied_cases.STORED)
        self.assertEqual(typed_at, pasted_at)
        self.session.save(self.path)
        first_fields = transcripts.first_prompt(self.config, self.state, str(self.path), "claude")
        first, at = first_fields["first_prompt"], first_fields["first_prompt_at"]
        self.assertEqual(f"/review {ORDINARY[0]}", first)
        row = self.app(first_prompt=first, first_prompt_at=at).collect(show_all=True)["sessions"][0]
        self.assertEqual([], row["copied_prompts"][0]["quoted_as"])
        self.assertEqual((first, at), annotation_store.prompt_candidate(row, "first-prompt"))

    def test_the_copied_scan_renders_ordinary_and_secret_command_fields_safely(self) -> None:
        for args in (*ORDINARY, "token: " + EXAMPLE):
            with self.subTest(args=args):
                self.session = Transcript(self.root / "work" / "billing")
                copied_cases._paste(self.session, prompt_command("review", args))
                self.session.save(self.path)
                messages, _ = copied_corrections._scan(
                    self.config, str(self.path), SHORT, 0, self.path.stat().st_size
                )
                self.assertEqual(1, len(messages))
                if EXAMPLE not in args:
                    self.assertEqual(f"/review {args}", messages[0].first)
                else:
                    self.assertTrue(messages[0].first.startswith("/review token:"))
                    self.assertIn("REDACTED", messages[0].first)
                self.assertNotIn("IOSFODNN7EXAMPLE", messages[0].first)


class RestoredCommandsKeepTheirOriginalFraming(window_cases.ThePressRecoversOnlyListedWindowWords):
    def command_source(self, raw: str) -> None:
        self.source["message"]["content"] = raw
        self.write([self.source])
        self.facts = project_context.transcript_user_facts(
            self.config, self.state, str(self.path), "claude", "s1"
        )
        self.listed = reading.build_ledger(self.facts, "claude", "s1")

    def test_complete_ordinary_arguments_survive_actual_source_restoration(self) -> None:
        for value in ORDINARY:
            with self.subTest(value=value):
                self.command_source(prompt_command("review", value))
                (source,) = self.lookup()
                self.assertEqual(f"/review {value}", source["reader_words"])
                self.assertEqual(self.listed[0]["id"], source["fact_id"])
                self.assertEqual(self.listed[0]["at"], source["at"])

    def test_restored_missing_close_is_cut_and_controls_supply_no_words(self) -> None:
        self.command_source(prompt_command("review", ORDINARY[0]).removesuffix("</command-args>"))
        (source,) = self.lookup()
        self.assertEqual(f"/review {ORDINARY[0]}…", source["reader_words"])
        for raw in (local_command("compact", ORDINARY[0]), prompt_command("insights", ORDINARY[0])):
            with self.subTest(raw=raw):
                self.command_source(raw)
                self.assertEqual([], self.lookup())

    def test_restored_commands_keep_cli_credentials_paths_and_raw_line_masks(self) -> None:
        private = "/Users/synthetic/private/repository/synthetic-private-file.txt"
        for args, forbidden in (
            ("--token fake-cli-value inspect " + private, ("fake-cli-value", private)),
            (
                "Authorization: Bearer fake-header-value inspect " + private,
                ("fake-header-value", private),
            ),
            (
                "Inspect " + EXAMPLE[:9] + "\n" + EXAMPLE[9:] + " then preserve fixtures",
                (EXAMPLE[:9], EXAMPLE[9:]),
            ),
        ):
            with self.subTest(args=args):
                self.command_source(prompt_command("review", args))
                (source,) = self.lookup()
                for word in forbidden:
                    self.assertNotIn(word, source["reader_words"])
                self.assertIn("REDACTED", source["reader_words"])
                self.assertNotIn("command-args", source["reader_words"])
                self.assertFalse(source["reader_words"].endswith("…"))

    def test_restored_command_is_redacted_before_the_existing_word_bound(self) -> None:
        self.command_source(prompt_command("review", "--token " + "x" * 500 + " " + "word " * 4000))
        (source,) = self.lookup()
        self.assertLessEqual(len(source["reader_words"]), project_context.READER_WORDS_CAP_CHARS)
        self.assertNotIn("x" * 50, source["reader_words"])
        self.assertIn("REDACTED", source["reader_words"])

    def test_actual_source_restoration_reaches_direct_and_http_composition_prompts(self) -> None:
        for raw, expected in (
            (prompt_command("review", ORDINARY[0]), f"/review {ORDINARY[0]}"),
            (
                prompt_command("review", ORDINARY[0]).removesuffix("</command-args>"),
                f"/review {ORDINARY[0]}…",
            ),
            (
                prompt_command("review", "--token fake-cli-value inspect fixtures"),
                f"/review --token {records.SECRET_MARKER} inspect fixtures",
            ),
        ):
            with self.subTest(raw=raw):
                self.command_source(raw)
                facts = [
                    {key: value for key, value in fact.items() if key != "reader_words"}
                    for fact in self.facts
                ]
                prompts: list[str] = []

                def model(
                    prompt: str, prompt_sink: list[str] = prompts, **_kwargs: Any
                ) -> tuple[str, str]:
                    prompt_sink.append(prompt)
                    return "{}", "ok"

                now = float(facts[0]["at"]) + 200
                revisions = [{"n": 1, "at": now - 300, "goal": "Check the queue"}]
                row = {"harness": "claude", "sid": "s1", "state": "working"}
                arguments: dict[str, Any] = {"model": model, "stamp_text": "synthetic", "now": now}
                handler = SimpleNamespace(
                    server=SimpleNamespace(
                        application=SimpleNamespace(
                            config=self.config, state=self.state, clock=lambda current=now: current
                        )
                    ),
                    _reading_arguments=lambda *_args, current_args=arguments: current_args,
                )
                with (
                    mock.patch.object(
                        http_api, "_session_context", return_value={"semantic": {"facts": facts}}
                    ),
                    mock.patch.object(observer, "resolve_transcript", return_value=str(self.path)),
                ):
                    compose: Any = http_api._RequestHandler._compose_reading
                    compose(
                        handler,
                        row,
                        {"revisions": revisions},
                        {},
                        SimpleNamespace(phase=None, capture=lambda _value: None),
                    )
                reading.produce(
                    self.config,
                    row,
                    revisions,
                    facts,
                    **arguments,
                    read_lines=True,
                    read_agent_words=True,
                    admit_turn_stop=True,
                    person_source_lookup=self.lookup,
                )
                self.assertEqual(2, len(prompts))
                self.assertEqual(prompts[0], prompts[1])
                self.assertIn(expected, prompts[0])
                if not expected.endswith("…"):
                    self.assertNotIn(expected + "…", prompts[0])
                self.assertNotIn("fake-cli-value", prompts[0])
                self.assertNotIn("command-args", prompts[0])
