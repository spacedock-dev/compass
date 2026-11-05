"""Compass's own command, and the turn it opens, are not what a reader or an agent did.

A reader who types `/compass:compass sessions` inside a session asks Compass a question; the agent
runs Compass and repeats what it printed. Before this, Compass read that turn back as the reader's
latest direction and as the agent's work: a later direction that demoted every departure, the
goal drafted from it, the latest-prompt offer, `last_prompt`, an outline phase, and evidence a
reading, the Live monitor and a summary sent or cited.

The fixture writes Claude Code 2.1.318's records with the key sets the capture recorded
(`docs/captures/claude/skill-action-shapes-2.1.318-macos.jsonl`): a typed command is a `user`
record whose string content opens with `<command-message>` and names `/compass:compass` in
`<command-name>`, then the `isMeta` skill body, a `command_permissions` attachment, and
`last-prompt` records that repeat the command and name no prompt. The capture also measured that
`attributionSkill` stays on the agent's later work after the model starts the skill itself, so
nothing here keys on attribution. Every text is placeholder prose.
"""

from __future__ import annotations

import dataclasses
import json
import os
import re
import shutil
import tempfile
import unittest
from pathlib import Path
from typing import Any, cast
from unittest import mock

from compass_runtime import (
    aggregate,
    claude_data,
    compass_turns,
    correction,
    http_api,
    live_monitor,
    observer,
    project_context,
    reading,
    records,
    session_outline,
    session_source,
    transcripts,
    unasked,
)
from compass_runtime import sessions as runtime_sessions
from compass_runtime.config import build_runtime_config
from compass_runtime.state import build_runtime_state

from . import test_reading, test_reading_source_final
from .test_claude_checks import SHORT, START
from .test_slash_command_direction import CAVEAT, Session, local_command, prompt_command

REPO = Path(__file__).resolve().parents[4]
CAPTURE = REPO / "docs/captures/claude/skill-action-shapes-2.1.318-macos.jsonl"
STORY_FIXTURE = REPO / "frontend/test/fixtures/compass-skill-action.json"

FIRST = "Add retry with backoff to the webhook handler."
LATER = "Now cover the retry path with a test."
COMMAND = "/compass:compass"
NOW = START.timestamp() + 3600
# Stand-ins for what Compass printed and the agent repeated: a reading's own text once the
# in-session `drift` action exists, a board listing today.
PRINTED = "PRINTED-BY-COMPASS placeholder board line for another session"
ECHOED = "ECHOED-BY-AGENT placeholder board line for another session"
RUN = "python3 compass/skills/compass/server.py --sessions"


def _capture() -> list[dict[str, Any]]:
    return [json.loads(line) for line in CAPTURE.read_text(encoding="utf-8").splitlines()]


def _keys(arm: str, shape: str) -> list[str]:
    for row in _capture():
        if row["arm"] == arm and row["shape"] == shape:
            return list(row.get("entry_keys") or row["types"])
    raise AssertionError(f"no {arm}/{shape} in the capture")


# Placeholder values for the keys Claude Code writes and nothing here reads.
_FILLER: dict[str, Any] = {
    "promptId": "prompt-placeholder",
    "turnOrigin": "sdk",
    "turnPosition": {"promptIndex": 0, "turnIndex": 0},
    "entrypoint": "sdk-cli",
    "gitBranch": "main",
    "userType": "external",
    "version": "2.1.318",
    "turnCompanion": True,
    "advisorModel": None,
    "apiBlockIndex": 0,
    "effort": "medium",
    "perTurnEffort": "medium",
    "requestId": "req-placeholder",
    "requestRef": "ref-placeholder",
    "requestedModel": "claude-haiku-placeholder",
    "permissionDecision": "allow",
    "sandboxed": False,
}


class CompassSession(Session):
    """`Session` with the records Claude Code 2.1.318 writes around a Compass skill action."""

    def _shaped(
        self, kind: str, content: Any, arm: str, shape: str, **values: Any
    ) -> dict[str, Any]:
        row = self._entry(kind, content if isinstance(content, list) else [])
        if not isinstance(content, list):
            row["message"]["content"] = content
        for key in _keys(arm, shape):
            if key not in row:
                row[key] = values.pop(key) if key in values else _FILLER.get(key, "placeholder")
        row.update(values)
        return row

    def _last_prompt(self, typed: str | None) -> None:
        row: dict[str, Any] = {
            "type": "last-prompt",
            "leafUuid": self.rows[-1]["uuid"],
            "sessionId": self.rows[-1]["sessionId"],
        }
        if typed is not None:
            row["lastPrompt"] = typed
        self.rows.append(row)

    def asked(self, text: str) -> float:
        """A prompt the reader typed, and the `last-prompt` record Claude Code writes after it."""
        self.prompt(text)
        self._last_prompt(text)
        return START.timestamp() + self.seconds

    def said(self, text: str, **extra: Any) -> None:
        self._entry("assistant", [{"type": "text", "text": text}], **extra)

    def _attributed(self) -> dict[str, Any]:
        return {"attributionSkill": "compass:compass", "attributionPlugin": "compass"}

    def compass(self, action: str = "sessions", *, stop: bool = True) -> float:
        """The reader types Compass's command; the agent runs it and repeats what it printed."""
        arm = "typed-headless" if action else "typed-bare-headless"
        text = (
            prompt_command("compass:compass", action)
            if action
            else "<command-message>compass:compass</command-message>\n"
            f"<command-name>{COMMAND}</command-name>"
        )
        self._shaped("user", text, arm, "typed-command")
        at = START.timestamp() + self.seconds
        body = [
            {"type": "text", "text": "Base directory for this skill: /skills/compass\n\n# Compass"}
        ]
        self._shaped("user", body, arm, "skill-body", isMeta=True)
        self.rows.append(
            {
                "type": "attachment",
                "uuid": f"u{len(self.rows)}",
                "isSidechain": False,
                "sessionId": self.rows[-1]["sessionId"],
                "timestamp": self._stamp(),
                "attachment": {"type": "command_permissions", "allowedTools": []},
            }
        )
        typed = f"{COMMAND} {action}" if action else None
        self._last_prompt(typed)
        call = self.call("Bash", {"command": RUN, "description": "List sessions"})
        self.rows[-1].update(self._attributed())
        self.result(call, PRINTED, is_error=False)
        self.rows[-1]["toolUseResult"] = {
            "stdout": PRINTED,
            "stderr": "",
            "interrupted": False,
            "isImage": False,
            "noOutputExpected": False,
        }
        self._last_prompt(typed)
        self.said(ECHOED, **self._attributed())
        # The measured order: the reply, Claude Code's turn stop, then `last-prompt`.
        if stop:
            self.stopped()
        self._last_prompt(typed)
        return at

    def stopped(self) -> float:
        """Claude Code's turn stop after the agent's reply, as `claude_data.is_turn_stop_record`
        reads it."""
        self.rows.append(
            {
                "type": "system",
                "subtype": "stop_hook_summary",
                "isSidechain": False,
                "preventedContinuation": False,
                "sessionId": self.rows[-1]["sessionId"],
                "timestamp": self._stamp(),
                "uuid": f"u{len(self.rows)}",
            }
        )
        return START.timestamp() + self.seconds

    def queued(self, text: str) -> None:
        """A message the reader typed while the turn ran: Claude Code's `queued_command`
        attachment."""
        self.rows.append(
            {
                "type": "attachment",
                "uuid": f"u{len(self.rows)}",
                "isSidechain": False,
                "sessionId": self.rows[-1]["sessionId"],
                "timestamp": self._stamp(),
                "attachment": {
                    "type": "queued_command",
                    "commandMode": "prompt",
                    "origin": {"kind": "human"},
                    "prompt": text,
                    "timestamp": self._stamp(),
                },
            }
        )

    def model_started_compass(self, work: str) -> float:
        """The model starts the Compass skill itself, then keeps working: the agent's own turn."""
        call = self.call("Skill", {"skill": "compass:compass", "args": "sessions"})
        self.result(
            call,
            "Launching skill: compass:compass",
            tool_use_result={"success": True, "commandName": "compass:compass"},
        )
        body = [{"type": "text", "text": "Base directory for this skill: /skills/compass"}]
        self._entry("user", body, isMeta=True, sourceToolUseID=call)
        run = self.call("Bash", {"command": RUN})
        self.rows[-1].update(self._attributed())
        self.result(run, PRINTED)
        self.said(ECHOED, **self._attributed())
        self.write(work)
        self.rows[-2].update(self._attributed())
        at = START.timestamp() + self.seconds
        self.said("Wrote the retry notes.", **self._attributed())
        return at


def _row(**extra: Any) -> dict[str, Any]:
    row: dict[str, Any] = dict(runtime_sessions.base_session("claude", SHORT, "billing"))
    row.update(
        {
            "project": "billing",
            "state": "working",
            "active": True,
            "last_activity": NOW,
            "first_prompt": FIRST,
            "first_prompt_at": START.timestamp() + 5,
        }
    )
    row.update(extra)
    return row


class _Case(unittest.TestCase):
    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        cwd = self.root / "work" / "billing"
        cwd.mkdir(parents=True)
        self.path = self.root / "claude" / "projects" / "-work-billing" / f"{SHORT}-full.jsonl"
        self.config = build_runtime_config(
            environ={"HOME": str(self.root), "COMPASS_HOME": str(self.root / "state")},
            platform_name="linux",
            os_name="posix",
            launcher_path=self.root / "server.py",
            store_root_overrides={"claude.projects": str(self.root / "claude" / "projects")},
        )
        self.state = build_runtime_state(self.config, started=NOW)
        patcher = mock.patch.object(observer.CodexGoalModel, "__call__", return_value=None)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.session = CompassSession(cwd)
        self.work = str(cwd / "retry_notes.md")

    def save(self) -> str:
        self.session.save(self.path)
        return str(self.path)

    def application(self) -> aggregate.Application:
        def collect(*_: Any) -> list[dict[str, Any]]:
            return [_row()]

        spec = aggregate.HarnessSpec(
            key="claude", label="Claude", discover=lambda *_: True, collect=collect
        )
        return aggregate.Application(
            self.config,
            self.state,
            (spec,),
            native_notifier=lambda _p: "",
            popup_notifier=lambda _t, _b: None,
            diagnostic_sink=lambda _m: None,
            clock=lambda: NOW,
        )

    def published(self) -> list[dict[str, Any]]:
        """The facts the board publishes: what Full activity lists."""
        self.save()
        context = project_context.collect(
            self.config, self.state, [_row()], "billing", now=NOW, focus=("claude", SHORT)
        )
        return list(context["semantic"]["facts"])

    def read_facts(self) -> list[dict[str, Any]]:
        """The facts a reading and the Live monitor read, the way `/api/reading` gets them."""
        self.save()
        return http_api._facts_of(http_api._session_context(self.application(), _row()))

    def page(self) -> session_source.SourcePage:
        return session_source.read(self.config, self.save(), "claude", SHORT)

    def summaries(self, facts: list[dict[str, Any]]) -> list[str]:
        return [str(fact.get("summary") or "") for fact in facts]


class TheFixtureIsWhatTheCaptureRecordedTest(_Case):
    def test_every_record_the_fixture_writes_for_a_typed_command_has_the_captured_keys(
        self,
    ) -> None:
        self.session.compass()
        typed, body = self.session.rows[0], self.session.rows[1]
        self.assertEqual(sorted(_keys("typed-headless", "typed-command")), sorted(typed))
        self.assertEqual(sorted(_keys("typed-headless", "skill-body")), sorted(body))
        last = next(row for row in self.session.rows if row["type"] == "last-prompt")
        self.assertEqual(sorted(_keys("typed-headless", "last-prompt")), sorted(last))

    def test_the_capture_records_the_tags_and_name_the_recogniser_reads(self) -> None:
        typed = [row for row in _capture() if row["shape"] == "typed-command"]
        self.assertTrue(typed)
        for row in typed:
            self.assertEqual("command-message", row["opens_with"])
            self.assertEqual(["command-message", "command-name"], row["content_tags"][:2])
        self.assertEqual({COMMAND}, {row["command_name"] for row in typed})

    def test_the_capture_shows_attribution_cannot_mark_the_commands_turn(self) -> None:
        (verdict,) = [
            row for row in _capture() if row["shape"] == "attribution-after-model-started-skill"
        ]
        after = verdict["verdicts"]["after_skill_call"]
        self.assertIn({"record": "assistant tool_use", "tool": "Write", "attributed": True}, after)
        self.assertFalse(verdict["verdicts"]["typed_command_record_present"])


class TheRecogniserTest(unittest.TestCase):
    def test_a_typed_compass_command_with_or_without_an_action_is_compass_s_own(self) -> None:
        self.assertTrue(records.compass_command(prompt_command("compass:compass", "sessions")))
        self.assertTrue(records.compass_command(prompt_command("compass:compass")))
        bare = f"<command-message>compass:compass</command-message>\n<command-name>{COMMAND}</command-name>"
        self.assertTrue(records.compass_command(bare))

    def test_another_skill_a_project_skill_named_compass_a_control_and_prose_are_not(self) -> None:
        for text in (
            prompt_command("review"),
            prompt_command("other:compass", "sessions"),
            prompt_command("compass", "sessions"),
            prompt_command("compass:compass-extra", "sessions"),
            local_command("clear"),
            CAVEAT,
            f"Please run {COMMAND} sessions for me.",
            f"{COMMAND} sessions",
            "",
        ):
            with self.subTest(text=text[:40]):
                self.assertFalse(records.compass_command(text))


class TheTypedCommandIsNotTheReadersMessageTest(_Case):
    def setUp(self) -> None:
        super().setUp()
        self.first_at = self.session.asked(FIRST)
        self.session.bash("pytest", "5 passed")

    def test_the_observed_record_publishes_no_entry_for_the_command(self) -> None:
        self.session.compass()
        events = project_context.instruction_events(self.config, self.save(), "claude", SHORT)
        self.assertEqual([FIRST], [event["title"] for event in events])

    def test_it_is_not_a_later_direction_after_a_saved_goal(self) -> None:
        self.session.compass()
        row = {"harness": "claude", "sid": SHORT}
        facts = self.published()
        self.assertEqual(0, correction.unsettled_directions(row, facts, floor=self.first_at))

    def test_the_session_goal_is_never_the_command(self) -> None:
        self.session.compass()
        result = observer.analyze(self.config, self.state, self.save(), now=NOW, window_sec=86400)
        self.assertEqual(FIRST, result["goal"])

    def test_the_latest_prompt_offer_skips_the_command(self) -> None:
        self.session.compass()
        line = claude_data.session_instruction(self.config, self.state, self.save())
        assert line is not None
        self.assertEqual(("asked", FIRST), (line["label"], line["text"]))

    def test_last_prompt_keeps_the_readers_prompt_after_the_command(self) -> None:
        self.session.compass()
        info = claude_data.analyze_transcript(self.config, self.state, self.save())
        self.assertEqual(FIRST, info["last_prompt"])

    def test_the_readers_next_prompt_is_the_last_prompt_again(self) -> None:
        self.session.compass()
        self.session.asked(LATER)
        info = claude_data.analyze_transcript(self.config, self.state, self.save())
        self.assertEqual(LATER, info["last_prompt"])

    def test_a_bare_command_changes_neither_the_offer_nor_the_last_prompt(self) -> None:
        self.session.compass("")
        path = self.save()
        info = claude_data.analyze_transcript(self.config, self.state, path)
        self.assertEqual(FIRST, info["last_prompt"])
        events = project_context.instruction_events(self.config, path, "claude", SHORT)
        self.assertEqual([FIRST], [event["title"] for event in events])
        line = claude_data.session_instruction(self.config, self.state, path)
        assert line is not None
        self.assertEqual(("asked", FIRST), (line["label"], line["text"]))


class APromptSurfaceReadsTheLatestTypedPromptTest(_Case):
    """Interactive Claude Code keeps writing `last-prompt` after a turn stops, repeating the latest
    typed prompt, and the skill body after a typed command can push the command out of the tail
    the collector reads. Whether a `last-prompt` is the reader's is decided by the typed prompt
    before it in record order, wherever that prompt lies."""

    def turn_duration(self) -> None:
        self.session.rows.append(
            {
                "type": "system",
                "subtype": "turn_duration",
                "isSidechain": False,
                "isMeta": False,
                "sessionId": self.session.rows[-1]["sessionId"],
                "timestamp": self.session._stamp(),
                "uuid": f"u{len(self.session.rows)}",
            }
        )

    def command_only_after_the_tail_start(self) -> str:
        """The command, its turn, the turn stop, `turn_duration` and a trailing `last-prompt`,
        read with a tail that begins just after the command's skill body, as on a real session."""
        self.session.compass("sessions waiting")
        self.turn_duration()
        self.session._last_prompt(f"{COMMAND} sessions waiting")
        path = self.save()
        body = next(i for i, row in enumerate(self.session.rows) if row.get("isMeta"))
        lines = Path(path).read_bytes().split(b"\n")
        start = sum(len(line) + 1 for line in lines[: body + 1])
        self.config = dataclasses.replace(self.config, tail_bytes=os.path.getsize(path) - start)
        return path

    def test_a_trailing_last_prompt_after_a_command_only_session_publishes_nothing(self) -> None:
        path = self.command_only_after_the_tail_start()
        info = claude_data.analyze_transcript(self.config, self.state, path)
        self.assertIsNone(info["last_prompt"])
        self.assertIsNone(claude_data.session_instruction(self.config, self.state, path))
        self.assertIsNone(claude_data.session_title(self.config, self.state, path))

    def test_a_trailing_last_prompt_after_the_command_falls_back_to_the_readers_prompt(
        self,
    ) -> None:
        self.session.asked(FIRST)
        path = self.command_only_after_the_tail_start()
        info = claude_data.analyze_transcript(self.config, self.state, path)
        self.assertEqual(FIRST, info["last_prompt"])
        line = claude_data.session_instruction(self.config, self.state, path)
        assert line is not None
        self.assertEqual(("asked", FIRST), (line["label"], line["text"]))
        self.assertEqual(FIRST, claude_data.session_title(self.config, self.state, path))

    def test_a_trailing_last_prompt_read_whole_after_the_command_falls_back_too(self) -> None:
        self.session.asked(FIRST)
        self.session.compass()
        self.turn_duration()
        self.session._last_prompt(f"{COMMAND} sessions")
        info = claude_data.analyze_transcript(self.config, self.state, self.save())
        self.assertEqual(FIRST, info["last_prompt"])

    def test_a_prompt_typed_after_the_command_outranks_the_commands_last_prompt(self) -> None:
        # The command's trailing `last-prompt` is in the tail and the command is not; the reader's
        # next prompt is in the tail with no `last-prompt` after it yet.
        before = os.path.getsize(self.command_only_after_the_tail_start())
        self.session.prompt(LATER)
        path = self.save()
        grown = self.config.tail_bytes + os.path.getsize(path) - before
        self.config = dataclasses.replace(self.config, tail_bytes=grown)
        info = claude_data.analyze_transcript(self.config, self.state, path)
        self.assertEqual(LATER, info["last_prompt"])

    def test_a_second_collection_of_an_unchanged_long_turn_reads_nothing_back(self) -> None:
        # Every collection runs this; during a long turn the tail holds no typed prompt, so the
        # judgement comes from a cached forward read that an unchanged file does not repeat.
        self.session.asked(FIRST)
        for n in range(6):
            self.session.bash(f"pytest tests/test_{n}.py", "1 passed")
        self.session._last_prompt(FIRST)
        path = self.save()
        self.config = dataclasses.replace(self.config, tail_bytes=600)
        forward = mock.Mock(wraps=claude_data._advance_prompts)
        with mock.patch.object(claude_data, "_advance_prompts", forward):
            first = claude_data.analyze_transcript(self.config, self.state, path)
            second = claude_data.analyze_transcript(self.config, self.state, path)
        self.assertEqual((FIRST, FIRST), (first["last_prompt"], second["last_prompt"]))
        self.assertEqual(1, forward.call_count)

    def test_a_long_turn_the_tail_starts_inside_keeps_the_readers_last_prompt(self) -> None:
        self.session.asked(FIRST)
        for n in range(6):
            self.session.bash(f"pytest tests/test_{n}.py", "1 passed")
        self.session._last_prompt(FIRST)
        path = self.save()
        self.config = dataclasses.replace(self.config, tail_bytes=600)
        info = claude_data.analyze_transcript(self.config, self.state, path)
        self.assertEqual(FIRST, info["last_prompt"])


class AnOpeningCommandIsSkippedNotAControlTest(_Case):
    def test_goal_adoption_drafts_from_the_prompt_after_an_opening_command(self) -> None:
        self.session.compass()
        at = self.session.asked(FIRST)
        found = transcripts.first_prompt(self.config, self.state, self.save(), "claude")
        self.assertEqual((FIRST, at, False), tuple(found.values()))

    def test_a_clear_that_opens_the_session_still_stops_the_scan(self) -> None:
        self.session._text(CAVEAT, isMeta=True)
        self.session._text(local_command("clear"))
        self.session.asked(FIRST)
        found = transcripts.first_prompt(self.config, self.state, self.save(), "claude")
        self.assertEqual(("/clear", True), (found["first_prompt"], found["first_prompt_control"]))

    def test_the_session_title_is_the_prompt_after_an_opening_command(self) -> None:
        self.session.compass()
        self.session.asked(FIRST)
        self.assertEqual(FIRST, claude_data.session_title(self.config, self.state, self.save()))


class TheTurnItOpensIsNotEvidenceTest(_Case):
    """Full activity still lists what the agent ran and said; no reader of evidence takes it."""

    def setUp(self) -> None:
        super().setUp()
        self.first_at = self.session.asked(FIRST)
        self.session.bash("pytest tests/test_retry.py", "1 failed", is_error=True)
        self.session.said("The retry handler is in place.")

    def test_full_activity_still_lists_what_the_agent_ran_and_repeated(self) -> None:
        self.session.compass()
        published = self.summaries(self.published())
        self.assertIn(ECHOED, published)
        self.assertTrue(any(RUN in summary for summary in published), published)
        self.assertNotIn(f"{COMMAND} sessions", published)

    def test_a_readings_ledger_holds_nothing_from_the_turn(self) -> None:
        self.session.compass()
        ledger = reading.build_ledger(
            self.read_facts(), "claude", SHORT, tool_output={}, read_agent_words=True
        )
        summaries = [str(entry["summary"]) for entry in ledger]
        self.assertIn("The retry handler is in place.", summaries)
        self.assertFalse([s for s in summaries if ECHOED in s or RUN in s], summaries)

    def produce(self, facts: list[dict[str, Any]], answer: str = "{}") -> tuple[Any, str]:
        prompts: list[str] = []
        state_dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, state_dir, True)
        config = test_reading.WhatOnePressActuallyCostsAndProduces._Config()
        config.state_dir = state_dir  # type: ignore[attr-defined]

        def model(prompt: str, **_kw: Any) -> tuple[str, str]:
            prompts.append(prompt)
            return answer, "ok"

        tails = {
            # What the press would carry of each call's output: the board for Compass's own run.
            str(fact["branch"]["record_id"]): PRINTED if RUN in str(fact["summary"]) else "1 failed"
            for fact in facts
            if isinstance(fact.get("branch"), dict) and fact.get("type") == "tool_report"
        }
        assessment, _why, _spent = reading.produce(
            cast("Any", config),
            {"harness": "claude", "sid": SHORT, "state": "working", "ended_at": None},
            [{"n": 1, "at": self.first_at + 1, "goal": "add retry", "output": "tests pass"}],
            facts,
            now=NOW,
            stamp_text="read at 10:00",
            model=model,
            tool_output=reading.ToolOutput(destination="api", label="Claude", tails=tails),
            read_lines=True,
            read_agent_words=True,
        )
        return assessment, prompts[0] if prompts else ""

    def test_the_composed_prompt_holds_none_of_the_printed_or_repeated_text(self) -> None:
        self.session.compass()
        _assessment, prompt = self.produce(self.read_facts())
        self.assertIn("The retry handler is in place.", prompt)
        self.assertNotIn(ECHOED, prompt)
        self.assertNotIn(PRINTED, prompt)
        self.assertNotIn(RUN, prompt)

    def test_a_second_reading_after_the_command_has_the_first_readings_departures(self) -> None:
        before = self.read_facts()
        _first, prompt = self.produce(before)
        (number,) = re.findall(
            r"^\[(\d+)\] tool_report .*pytest tests/test_retry\.py", prompt, re.MULTILINE
        )
        answer = json.dumps(
            {"goal": {"result": "departure", "cites": [int(number)], "detail": "tests fail"}}
        )
        first, _ = self.produce(before, answer)
        self.session.compass()
        after = self.read_facts()
        row = {"harness": "claude", "sid": SHORT}
        self.assertEqual(0, correction.unsettled_directions(row, after, floor=self.first_at))
        second, _ = self.produce(after, answer)
        self.assertEqual(reading.RESULT_DEPARTURE, first["criteria"]["goal"]["result"])
        self.assertEqual(first["criteria"], second["criteria"])

    def test_the_unasked_lane_reads_nothing_from_the_turn(self) -> None:
        self.session.compass()
        self.save()
        lane = unasked.Lane(self.config, popup_notifier=lambda *_: None)
        facts = list(lane._facts(self.state, _row(), NOW))
        ledger = reading.build_ledger(facts, "claude", SHORT, tool_output={}, read_agent_words=True)
        summaries = " ".join(str(entry["summary"]) for entry in ledger)
        self.assertIn("The retry handler is in place.", summaries)
        self.assertNotIn(ECHOED, summaries)
        self.assertNotIn(RUN, summaries)

    def ledger(self) -> str:
        facts = self.read_facts()
        rows = reading.build_ledger(facts, "claude", SHORT, tool_output={}, read_agent_words=True)
        return " ".join(str(entry["summary"]) for entry in rows)

    def test_a_transcript_read_while_it_grows_keeps_the_turn(self) -> None:
        # The board reads while the command has only just been typed; the echo lands after.
        self.session.compass()
        rows = self.session.rows
        cut = next(i for i, row in enumerate(rows) if ECHOED in json.dumps(row))
        self.session.rows = rows[:cut]
        self.read_facts()
        self.session.rows = rows
        self.assertNotIn(ECHOED, self.ledger())
        self.session.asked(LATER)
        self.session.said("Real work after.")
        self.assertIn("Real work after.", self.ledger())
        ((_start, end),) = compass_turns.spans(self.save())
        self.assertIsNotNone(end)

    def test_the_live_monitor_sends_nothing_from_the_turn(self) -> None:
        self.session.compass()
        sent = live_monitor.new_entries(
            self.read_facts(),
            harness="claude",
            sid=SHORT,
            seen=(),
            cap_chars=20_000,
            tool_rows=True,
        )
        words = " ".join(" ".join(entry) for entry in sent)
        self.assertIn("The retry handler is in place.", words)
        self.assertNotIn(ECHOED, words)
        self.assertNotIn(RUN, words)

    def test_a_summary_may_cite_no_entry_from_the_turn(self) -> None:
        self.session.compass()
        self.session.asked(LATER)
        self.session.bash("pytest tests/test_retry.py", "2 passed")
        titles = [entry.title for entry in self.page().entries]
        self.assertIn(LATER, titles)
        self.assertFalse([t for t in titles if ECHOED in t or RUN in t or COMMAND in t], titles)

    def test_the_outline_has_no_phase_for_the_command_and_none_of_its_entries(self) -> None:
        self.session.compass()
        self.session.asked(LATER)
        self.session.bash("pytest tests/test_retry.py", "2 passed")
        outline = session_outline.build(self.page(), self.config)
        prompts = [block["prompt"]["title"] for block in outline["blocks"] if block["prompt"]]
        self.assertEqual([FIRST, LATER], prompts)
        self.assertNotIn(ECHOED, json.dumps(outline))
        # The reader's first message, its failing check and the agent's reply: nothing after.
        opening = outline["blocks"][0]
        self.assertEqual(1, opening["counts"]["agent_messages"], opening)
        self.assertEqual(3, opening["span"]["entries"], opening)


class AModelStartedSkillIsTheAgentsOwnWorkTest(_Case):
    """When the model starts the Compass skill itself, the reader typed nothing: no turn is
    Compass's, and the work after it is the agent's, attribution or none."""

    def setUp(self) -> None:
        super().setUp()
        self.session.asked(FIRST)
        self.session.model_started_compass(self.work)

    def test_the_work_after_a_model_started_compass_skill_stays_evidence(self) -> None:
        ledger = reading.build_ledger(
            self.read_facts(), "claude", SHORT, tool_output={}, read_agent_words=True
        )
        summaries = " ".join(str(entry["summary"]) for entry in ledger)
        self.assertIn("retry_notes.md", summaries)
        self.assertIn("Wrote the retry notes.", summaries)
        self.assertIn(ECHOED, summaries)

    def test_a_summary_and_the_outline_still_hold_that_work(self) -> None:
        titles = " ".join(entry.title for entry in self.page().entries)
        self.assertIn("retry_notes.md", titles)
        self.assertIn("Wrote the retry notes.", titles)


class TheStoryReadsWhatTheServerPublishesTest(_Case):
    """`DriftCompassSkillAction` is drawn from this file: the facts the board publishes for a
    session whose latest message is a Compass skill action, and the outline the server makes for
    it. A server that again publishes the command as the reader's message, or opens a phase for
    it, changes this file and the story asserts against the change. Regenerate with
    `COMPASS_WRITE_STORY_FIXTURE=1`."""

    def collected(self) -> dict[str, Any]:
        # A fixed working directory: a check's id is derived from where it ran, and a temporary
        # one would make the committed ids change on every run.
        self.session = CompassSession(Path("/work/billing"))
        self.session.asked(FIRST)
        self.session.bash("pytest tests/test_retry.py", "5 passed")
        self.session.said("The retry handler is in place.")
        self.session.compass()
        facts = [project_context.for_page(fact) for fact in self.published()]
        outline = session_outline.build(self.page(), self.config)
        return {"facts": facts, "outline": outline}

    def test_the_committed_scenario_is_what_the_server_publishes_now(self) -> None:
        collected = self.collected()
        if os.environ.get("COMPASS_WRITE_STORY_FIXTURE") == "1":
            STORY_FIXTURE.write_text(json.dumps(collected, indent=2) + "\n", encoding="utf-8")
        self.assertEqual(json.loads(STORY_FIXTURE.read_text(encoding="utf-8")), collected)


class ALongReadingTakesNothingFromTheTurnTest(unittest.TestCase):
    """The long reading reads the whole transcript itself; the same turn is not its evidence."""

    def setUp(self) -> None:
        self.source = test_reading_source_final.RetainedStrictFinalTest()
        self.source.setUp()
        self.addCleanup(self.source.doCleanups)

    def test_the_long_readings_evidence_and_final_words_hold_nothing_from_the_turn(self) -> None:
        self.source.parent.__class__ = CompassSession
        session = cast("CompassSession", self.source.parent)
        self.source.say("The retry handler is in place.")
        session.compass()
        echo = next(row for row in session.rows if ECHOED in json.dumps(row))
        echo["message"]["stop_reason"] = "end_turn"
        result = self.source.collect()
        assert result.evidence is not None
        ledger = reading.build_ledger(result.evidence.facts, "claude", SHORT, read_agent_words=True)
        summaries = [str(entry["summary"]) for entry in ledger]
        self.assertIn("The retry handler is in place.", summaries)
        self.assertNotIn(ECHOED, summaries)
        self.assertEqual("whole", (result.final or {}).get("outcome"), result.final)
        self.assertNotIn(ECHOED, json.dumps(result.final))


PLANTED = (
    f"<command-message>compass:compass</command-message>\n<command-name>{COMMAND}</command-name>"
)


class AToolResultIsNeverTheCommandTest(_Case):
    """Output the agent read that opens with the command's tags is not the reader typing it, so it
    hides none of the agent's later work."""

    def setUp(self) -> None:
        super().setUp()
        self.session.asked(FIRST)

    def then_work(self, planted: dict[str, Any]) -> None:
        self.session._last_prompt(FIRST)
        self.session.write(self.work)
        self.session.said("Dropped the ledger table.")
        path = self.save()
        self.assertFalse(records.compass_command_record(planted))
        self.assertEqual((), compass_turns.spans(path))
        ledger = reading.build_ledger(
            self.read_facts(), "claude", SHORT, tool_output={}, read_agent_words=True
        )
        self.assertIn("Dropped the ledger table.", [str(entry["summary"]) for entry in ledger])
        self.assertIn("Dropped the ledger table.", [entry.title for entry in self.page().entries])
        info = claude_data.analyze_transcript(self.config, self.state, path)
        self.assertEqual(FIRST, info["last_prompt"])

    def test_a_shell_result_opening_with_the_commands_tags_is_not_the_command(self) -> None:
        call = self.session.call("Bash", {"command": "cat notes.txt"})
        self.session.result(call, PLANTED, is_error=False)
        self.session.rows[-1]["toolUseResult"] = {"stdout": PLANTED, "stderr": ""}
        self.then_work(self.session.rows[-1])

    def test_a_tool_result_in_text_blocks_opening_with_the_tags_is_not_the_command(self) -> None:
        call = self.session.call("mcp__notes__read", {"name": "notes"})
        self.session.result(call, [{"type": "text", "text": PLANTED}])
        self.then_work(self.session.rows[-1])

    def test_a_string_record_carrying_a_tool_result_is_not_the_command(self) -> None:
        self.session._text(PLANTED)
        self.session.rows[-1]["toolUseResult"] = {}
        self.then_work(self.session.rows[-1])


class TheTurnEndsWhenTheAgentsTurnDoesTest(_Case):
    """Compass's turn ends at the agent's turn stop, at any other prompt record, or at a message
    the reader sent while it ran: the agent's work after any of them is evidence."""

    def setUp(self) -> None:
        super().setUp()
        self.session.asked(FIRST)
        self.session.said("The retry handler is in place.")

    def ledger(self) -> str:
        facts = self.read_facts()
        rows = reading.build_ledger(facts, "claude", SHORT, tool_output={}, read_agent_words=True)
        return " ".join(str(entry["summary"]) for entry in rows)

    def test_the_turn_ends_at_the_agents_turn_stop(self) -> None:
        at = self.session.compass()
        ((start, end),) = compass_turns.spans(self.save())
        self.assertEqual(at, start)
        self.assertIsNotNone(end)

    def test_work_after_a_finished_background_task_is_evidence(self) -> None:
        self.session.compass(stop=False)
        self.session._text(
            "<task-notification><task-id>b1</task-id><status>completed</status></task-notification>"
        )
        self.session.bash("pytest tests/test_after_notice.py", "3 failed", is_error=True)
        self.session.said("GENUINE-AFTER-NOTICE")
        ledger = self.ledger()
        self.assertIn("GENUINE-AFTER-NOTICE", ledger)
        self.assertIn("test_after_notice", ledger)
        self.assertNotIn(ECHOED, ledger)
        self.assertIn("GENUINE-AFTER-NOTICE", [entry.title for entry in self.page().entries])
        sent = live_monitor.new_entries(
            self.read_facts(),
            harness="claude",
            sid=SHORT,
            seen=(),
            cap_chars=20_000,
            tool_rows=True,
        )
        self.assertIn("GENUINE-AFTER-NOTICE", json.dumps(sent))

    def test_work_after_a_message_the_reader_sent_mid_turn_is_evidence(self) -> None:
        self.session.compass(stop=False)
        self.session.queued("MIDTURN also fix the parser")
        self.session.bash("pytest tests/test_parser.py", "1 failed", is_error=True)
        self.session.said("MIDTURN-WORK")
        ledger = self.ledger()
        self.assertIn("MIDTURN-WORK", ledger)
        self.assertIn("test_parser", ledger)
        self.assertNotIn(ECHOED, ledger)

    def test_a_stop_hook_that_blocks_the_stop_keeps_the_turn_open(self) -> None:
        self.session.compass(stop=False)
        self.session._text("Stop hook feedback: not done", isMeta=True)
        self.session.stopped()
        self.session.said("SECOND-ECHO", **self.session._attributed())
        self.session.stopped()
        self.assertNotIn("SECOND-ECHO", self.ledger())
