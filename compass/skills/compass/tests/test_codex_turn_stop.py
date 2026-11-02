"""Codex's recorded turn finish, read as a turn stop (owner, 2026-11-02).

The rollout shapes below are the ones measured over 1,087 real rollouts: `task_complete` closes a
turn, and Codex then appends a `thread_settings_applied` record or the stopped turn's own
`item_completed` command without any turn having started. Those two do not retire the stop.
Everything else after it is a new turn's work and does.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any

from compass_runtime import transcripts as runtime_transcripts
from compass_runtime.collectors import codex as codex_collector

from .support import RuntimeTestCase, make_runtime, runtime, store_patch
from .test_codex import _stamp

SID = "44444444-4444-4444-4444-444444444444"
STOP_AT = 1000.0  # seconds after the rollout's first record


def _record(when: float, kind: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {"timestamp": _stamp(when), "type": kind, "payload": payload}


def _started(when: float, turn: str = "t1") -> dict[str, Any]:
    return _record(when, "event_msg", {"type": "task_started", "turn_id": turn, "started_at": when})


def _complete(when: float, turn: str = "t1") -> dict[str, Any]:
    return _record(when, "event_msg", {"type": "task_complete", "turn_id": turn})


def _aborted(when: float, turn: str = "t1") -> dict[str, Any]:
    return _record(when, "event_msg", {"type": "turn_aborted", "turn_id": turn})


def _settings(when: float) -> dict[str, Any]:
    return _record(when, "event_msg", {"type": "thread_settings_applied", "thread_settings": {}})


def _command_done(when: float, turn: str) -> dict[str, Any]:
    return _record(
        when,
        "event_msg",
        {
            "type": "item_completed",
            "turn_id": turn,
            "completed_at_ms": int(when * 1000),
            "item": {"type": "CommandExecution", "id": "c1"},
        },
    )


def _model_output(when: float) -> dict[str, Any]:
    return _record(when, "response_item", {"type": "function_call", "name": "exec"})


class CodexTurnStopTest(RuntimeTestCase):
    """What a collection publishes as `turn_end_at` and `work_activity` for a Codex rollout."""

    def setUp(self) -> None:
        super().setUp()
        self.now = time.time()
        # The stop is far enough back that every later record is older than the press.
        self.stop = self.now - 300

    def _head(self) -> list[dict[str, Any]]:
        return [
            {"type": "session_meta", "payload": {"id": SID, "cwd": "/tmp/project"}},
            _started(self.stop - 60),
            _complete(self.stop),
        ]

    def _collect(self, entries: list[dict[str, Any]]) -> dict[str, Any]:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "2026" / "11" / "02" / "rollout-stop.jsonl"
            path.parent.mkdir(parents=True)
            path.write_text("".join(json.dumps(row) + "\n" for row in entries))
            # The file was written last just now, as a rollout Codex appended to is.
            os.utime(path, (self.now, self.now))
            with store_patch(CODEX_SESSIONS_DIR=tmp):
                config, state = runtime()
                (session,) = codex_collector.collect(config, state, self.now, 24, False)
        return session

    def test_a_reader_whose_codex_session_finished_a_turn_has_that_finish_as_its_stop(self) -> None:
        session = self._collect(self._head())
        self.assertAlmostEqual(self.stop, session["turn_end_at"], delta=1.0)
        self.assertEqual("idle", session["state"])

    def test_a_stop_survives_codex_recording_a_settings_change_after_it(self) -> None:
        entries = [*self._head(), _settings(self.stop + 200)]
        session = self._collect(entries)
        self.assertAlmostEqual(self.stop, session["turn_end_at"], delta=1.0)
        self.assertAlmostEqual(self.stop, session["work_activity"], delta=1.0)

    def test_a_stop_survives_a_command_the_stopped_turn_left_running_finishing_after_it(
        self,
    ) -> None:
        entries = [*self._head(), _command_done(self.stop + 200, "t1")]
        session = self._collect(entries)
        self.assertAlmostEqual(self.stop, session["turn_end_at"], delta=1.0)
        self.assertAlmostEqual(self.stop, session["work_activity"], delta=1.0)

    def test_a_stop_is_retired_when_codex_writes_another_turns_output_after_it(self) -> None:
        # The measured start-less continuation: a later turn's item before its `task_started`.
        entries = [*self._head(), _command_done(self.stop + 200, "t2")]
        session = self._collect(entries)
        self.assertIsNone(session["turn_end_at"])
        self.assertAlmostEqual(self.stop + 200, session["work_activity"], delta=1.0)

    def test_a_stop_is_retired_when_the_model_writes_output_after_it(self) -> None:
        session = self._collect([*self._head(), _model_output(self.stop + 200)])
        self.assertIsNone(session["turn_end_at"])

    def test_a_stop_is_retired_when_a_new_turn_starts_after_it(self) -> None:
        session = self._collect([*self._head(), _started(self.stop + 200, "t2")])
        self.assertIsNone(session["turn_end_at"])

    def test_a_turn_record_inside_the_activity_grace_still_retires_the_stop(self) -> None:
        # Work newer than the stop by less than the grace does not retire it, but a turn record does:
        # the abort and the new turn below are 5 s after the finish, inside the 10 s grace.
        for newer in (_started(self.stop + 5, "t2"), _aborted(self.stop + 5, "t2")):
            with self.subTest(record=newer["payload"]["type"]):
                self.assertIsNone(self._collect([*self._head(), newer])["turn_end_at"])

    def test_a_non_turn_record_inside_the_activity_grace_leaves_the_stop(self) -> None:
        session = self._collect([*self._head(), _settings(self.stop + 5)])
        self.assertAlmostEqual(self.stop, session["turn_end_at"], delta=1.0)

    def test_a_record_type_nobody_has_measured_retires_the_stop(self) -> None:
        # The closed list of two non-turn shapes is the safe direction: an unknown one retires.
        unknown = _record(self.stop + 200, "event_msg", {"type": "a_future_record"})
        self.assertIsNone(self._collect([*self._head(), unknown])["turn_end_at"])

    def test_an_aborted_turn_is_not_a_stop(self) -> None:
        entries = [
            {"type": "session_meta", "payload": {"id": SID, "cwd": "/tmp/project"}},
            _started(self.stop - 60),
            _aborted(self.stop),
        ]
        self.assertIsNone(self._collect(entries)["turn_end_at"])

    def test_an_abort_after_a_finished_turn_retires_that_stop(self) -> None:
        entries = [*self._head(), _started(self.stop + 20, "t2"), _aborted(self.stop + 40, "t2")]
        self.assertIsNone(self._collect(entries)["turn_end_at"])

    def test_the_newest_finish_is_the_stop_when_several_turns_ended(self) -> None:
        entries = [
            *self._head(),
            _started(self.stop + 20, "t2"),
            _complete(self.stop + 40, "t2"),
        ]
        self.assertAlmostEqual(self.stop + 40, self._collect(entries)["turn_end_at"], delta=1.0)

    def test_a_session_with_no_finished_turn_publishes_no_stop(self) -> None:
        entries = [
            {"type": "session_meta", "payload": {"id": SID, "cwd": "/tmp/project"}},
            _started(self.stop),
        ]
        self.assertIsNone(self._collect(entries)["turn_end_at"])


class CodexTranscriptNewestTurnRecordTest(RuntimeTestCase):
    """`analyze_codex_transcript`'s `last_turn_ts`: the newest record that is a turn's."""

    def _analyze(self, entries: list[dict[str, Any]]) -> dict[str, Any]:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rollout-a.jsonl"
            path.write_text("".join(json.dumps(row) + "\n" for row in entries))
            config, _ = make_runtime()
            return runtime_transcripts.analyze_codex_transcript(config, str(path))

    def test_a_settings_record_does_not_move_the_newest_turn_record(self) -> None:
        info = self._analyze([_started(100), _complete(200), _settings(900)])
        self.assertAlmostEqual(200, info["last_turn_ts"], delta=1.0)
        self.assertAlmostEqual(200, info["turn_stop_ts"], delta=1.0)

    def test_a_closed_turns_late_item_does_not_move_it_but_an_open_turns_does(self) -> None:
        closed = self._analyze([_started(100), _complete(200), _command_done(900, "t1")])
        self.assertAlmostEqual(200, closed["last_turn_ts"], delta=1.0)
        other = self._analyze([_started(100), _complete(200), _command_done(900, "t2")])
        self.assertAlmostEqual(900, other["last_turn_ts"], delta=1.0)

    def test_an_item_before_its_turns_close_is_the_turns_own_work(self) -> None:
        info = self._analyze([_started(100), _command_done(150, "t1"), _complete(200)])
        self.assertAlmostEqual(200, info["last_turn_ts"], delta=1.0)

    def test_an_abort_is_a_turn_record_and_not_a_stop(self) -> None:
        info = self._analyze(
            [_started(100), _complete(200), _started(300, "t2"), _aborted(400, "t2")]
        )
        self.assertAlmostEqual(400, info["last_turn_ts"], delta=1.0)
        self.assertAlmostEqual(200, info["turn_stop_ts"], delta=1.0)

    def test_a_rollout_with_no_record_reports_zero(self) -> None:
        info = self._analyze([])
        self.assertEqual((0, 0), (info["last_turn_ts"], info["turn_stop_ts"]))
