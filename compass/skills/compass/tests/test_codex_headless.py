"""Exec origin and a reversible finished-run reading, through the real rollout collector."""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any

from compass_runtime import transcripts
from compass_runtime.collectors import codex

from .support import RuntimeTestCase, make_runtime, runtime, store_patch
from .test_codex_turn_stop import (
    SID,
    _aborted,
    _command_done,
    _complete,
    _model_output,
    _settings,
    _started,
)


class CodexHeadlessTest(RuntimeTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "2026" / "11" / "15" / f"rollout-{SID}.jsonl"
        self.path.parent.mkdir(parents=True)
        self.now = time.time()
        self.stop = self.now - 300
        self.config, self.state = make_runtime()

    def _write(self, path: Path, entries: list[dict[str, Any]], *, stale: bool = False) -> None:
        path.write_text("".join(json.dumps(row) + "\n" for row in entries))
        at = self.now - 48 * 3600 if stale else self.now
        os.utime(path, (at, at))

    def _head(self, source: Any = "exec") -> dict[str, Any]:
        return {"type": "session_meta", "payload": {"id": SID, "source": source}}

    def _collect(self) -> dict[str, Any]:
        with store_patch(CODEX_SESSIONS_DIR=self.tmp.name):
            config, _ = runtime()
            (row,) = codex.collect(config, self.state, self.now, 24, True)
        return row

    def test_a_reader_can_filter_exec_and_interactive_origins_without_guessing_other_sources(
        self,
    ) -> None:
        cases: list[tuple[Any, bool | None]] = [
            ("exec", True),
            ("cli", False),
            (None, None),
            ("vscode", None),
            ("future_exec", None),
            ({"subagent": {}}, None),
            ([], None),
            (True, None),
        ]
        for source, expected in cases:
            with self.subTest(source=source):
                _, self.state = make_runtime()
                self._write(self.path, [self._head(source)])
                self.assertIs(self._collect()["headless"], expected)

    def test_a_missing_source_does_not_infer_headless_from_originator(self) -> None:
        self._write(
            self.path,
            [{"type": "session_meta", "payload": {"id": SID, "originator": "codex_exec"}}],
        )
        self.assertIsNone(self._collect()["headless"])

    def test_a_stale_row_keeps_origin_without_claiming_an_unread_turn_finished(self) -> None:
        self._write(
            self.path, [self._head(), _started(self.stop - 60), _complete(self.stop)], stale=True
        )
        row = self._collect()
        self.assertIs(row["headless"], True)
        self.assertIsNone(row["turn_end_at"])
        self.assertNotEqual("run finished", row["state_detail"])

    def test_a_partial_head_retries_and_then_keeps_the_immutable_origin_in_cache(self) -> None:
        self.path.write_text('{"type":"session_meta",')
        self.assertEqual({}, transcripts.codex_meta(self.config, self.state, str(self.path)))
        self._write(self.path, [self._head()])
        self.assertIs(
            transcripts.codex_meta(self.config, self.state, str(self.path))["headless"], True
        )
        self.assertIs(self._collect()["headless"], True)

    def test_a_finished_exec_run_is_finished_without_declaring_the_session_ended(self) -> None:
        self._write(self.path, [self._head(), _started(self.stop - 60), _complete(self.stop)])
        row = self._collect()
        self.assertEqual(("idle", "run finished"), (row["state"], row["state_detail"]))
        self.assertAlmostEqual(self.stop, row["turn_end_at"], delta=1)
        self.assertIsNone(row["ended_at"])

    def test_a_working_row_keeps_its_detail_even_when_a_rollout_stop_still_stands(self) -> None:
        fields = codex.turn_stop_fields(
            self.config,
            self.now,
            {"last_turn_ts": self.stop, "turn_stop_ts": self.stop},
            (self.stop,),
            blocked=False,
            headless=True,
            session_state="working",
            state_detail="generating…",
        )
        self.assertEqual(self.stop, fields["turn_end_at"])
        self.assertEqual("generating…", fields["state_detail"])

    def test_interactive_and_unknown_origins_keep_their_waiting_detail(self) -> None:
        sources: tuple[Any, ...] = ("cli", None, {"subagent": {}})
        for source in sources:
            with self.subTest(source=source):
                _, self.state = make_runtime()
                self._write(
                    self.path, [self._head(source), _started(self.stop - 60), _complete(self.stop)]
                )
                self.assertEqual("awaiting your message", self._collect()["state_detail"])

    def test_a_late_settings_or_closed_command_record_keeps_the_finished_reading(self) -> None:
        for later in (_settings(self.stop + 200), _command_done(self.stop + 200, "t1")):
            with self.subTest(later=later):
                self._write(
                    self.path, [self._head(), _started(self.stop - 60), _complete(self.stop), later]
                )
                self.assertEqual("run finished", self._collect()["state_detail"])

    def test_a_resume_or_abort_reverses_the_finished_reading_on_the_next_collection(self) -> None:
        entries = [self._head(), _started(self.stop - 60), _complete(self.stop)]
        self._write(self.path, entries)
        self.assertEqual("run finished", self._collect()["state_detail"])
        for later in (
            _started(self.stop + 200, "t2"),
            _aborted(self.stop + 200),
            _model_output(self.stop + 200),
        ):
            with self.subTest(later=later):
                self._write(self.path, [*entries, later])
                row = self._collect()
                self.assertNotEqual("run finished", row["state_detail"])
                self.assertIsNone(row["turn_end_at"])
                self.assertIsNone(row["ended_at"])

    def test_an_exec_run_without_a_completed_turn_is_not_finished(self) -> None:
        for tail in ([], [_started(self.stop)], [_started(self.stop - 60), _aborted(self.stop)]):
            with self.subTest(tail=tail):
                self._write(self.path, [self._head(), *tail])
                self.assertNotEqual("run finished", self._collect()["state_detail"])

    def test_a_running_child_retires_its_parents_finished_reading(self) -> None:
        self._write(self.path, [self._head(), _started(self.stop - 60), _complete(self.stop)])
        child = {
            "type": "session_meta",
            "payload": {
                "id": "child",
                "session_id": SID,
                "thread_source": "subagent",
                "source": {"subagent": {"thread_spawn": {"parent_thread_id": SID}}},
            },
        }
        self._write(self.path.with_name("rollout-child.jsonl"), [child, _started(self.now - 5)])
        row = self._collect()
        self.assertTrue(row["subagents"])
        self.assertIsNone(row["turn_end_at"])
        self.assertNotEqual("run finished", row["state_detail"])
