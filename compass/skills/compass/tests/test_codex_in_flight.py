"""Quiet shell-capable calls remain working only while their bounded evidence stands."""

from __future__ import annotations

import json
import os
import tempfile
import time
from dataclasses import replace
from pathlib import Path
from typing import Any
from unittest import mock

from compass_runtime import aggregate, ends, transcripts
from compass_runtime.collectors import codex

from .support import RuntimeTestCase, runtime, store_patch
from .test_codex_turn_stop import SID, _aborted, _command_done, _complete, _record, _started


class CodexInFlightTest(RuntimeTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "2026" / "11" / "15" / f"rollout-{SID}.jsonl"
        self.path.parent.mkdir(parents=True)
        self.now = time.time()
        self.call_at = self.now - 300

    def _call(
        self,
        call_id: Any = "shell-1",
        *,
        name: str = "exec",
        at: float | None = None,
    ) -> dict[str, Any]:
        custom = name == "exec"
        return _record(
            self.call_at if at is None else at,
            "response_item",
            {
                "type": "custom_tool_call" if custom else "function_call",
                "call_id": call_id,
                "name": name,
                "input" if custom else "arguments": "await tools.exec_command(...)"
                if custom
                else json.dumps(
                    {"session_id": 123}
                    if name == "write_stdin"
                    else {"command" if name == "shell_command" else "cmd": "sleep 300"}
                ),
            },
        )

    def _output(self, call_id: Any = "shell-1", *, custom: bool = True) -> dict[str, Any]:
        return _record(
            self.call_at + 1,
            "response_item",
            {
                "type": "custom_tool_call_output" if custom else "function_call_output",
                "call_id": call_id,
                "output": [] if custom else "Process exited with code 0",
            },
        )

    def _collect(
        self,
        tail: list[dict[str, Any]],
        *,
        started: bool = True,
        fresh_mtime: bool = False,
        cap: float | None = None,
    ) -> dict[str, Any]:
        rows = [
            {"type": "session_meta", "payload": {"id": SID, "source": "exec"}},
            *([_started(self.call_at - 1)] if started else []),
            *tail,
        ]
        self.path.write_text("".join(json.dumps(row) + "\n" for row in rows))
        at = self.now if fresh_mtime else self.call_at
        os.utime(self.path, (at, at))
        with store_patch(CODEX_SESSIONS_DIR=self.tmp.name):
            config, state = runtime()
            if cap is not None:
                config = replace(config, codex_tool_in_flight_max_sec=cap)
            (row,) = codex.collect(config, state, self.now, 24, False)
        return row

    def test_measured_shell_capable_calls_outlive_the_activity_window(self) -> None:
        for name in ("exec", "exec_command", "shell_command", "write_stdin"):
            with self.subTest(name=name):
                row = self._collect([self._call(name=name)])
                self.assertEqual("working", row["state"])
                self.assertEqual(f"running {name}", row["state_detail"])

    def test_a_returned_call_reads_as_generating_or_its_plan_instead_of_running_the_tool(
        self,
    ) -> None:
        for name in ("exec", "exec_command"):
            for plan in ([], [self._plan()]):
                with self.subTest(name=name, plan=bool(plan)):
                    row = self._collect(
                        [*plan, self._call(name=name), self._output(custom=name == "exec")],
                        fresh_mtime=True,
                    )
                    self.assertEqual("working", row["state"])
                    self.assertEqual(
                        "Build project…" if plan else "generating…", row["state_detail"]
                    )

    def test_an_expired_call_with_fresh_activity_does_not_claim_the_tool_is_running(self) -> None:
        row = self._collect([self._call()], fresh_mtime=True, cap=200)
        self.assertEqual(("working", "generating…"), (row["state"], row["state_detail"]))

    def test_missing_or_invalid_bodies_cannot_extend_work(self) -> None:
        for name in ("exec", "exec_command", "shell_command", "write_stdin"):
            invalid: list[Any] = [None, {}, "", "  "]
            if name != "exec":
                invalid += ["{oops", "[]", "null", "{}"]
                field = {
                    "exec_command": "cmd",
                    "shell_command": "command",
                    "write_stdin": "session_id",
                }[name]
                values = [None, "", " ", 42] if name != "write_stdin" else [None, True, "123", 1.5]
                invalid += [json.dumps({field: value}) for value in values]
            for body in invalid:
                with self.subTest(name=name, body=body):
                    call = self._call(name=name)
                    key = "input" if name == "exec" else "arguments"
                    if body is None:
                        call["payload"].pop(key)
                    else:
                        call["payload"][key] = body
                    self.assertEqual("idle", self._collect([call])["state"])

    def test_custom_exec_is_javascript_and_stdin_chars_are_optional(self) -> None:
        for body in ("doSomething()", "{}", "[]"):
            call = self._call()
            call["payload"]["input"] = body
            self.assertEqual("working", self._collect([call])["state"])
        for arguments in ({"session_id": 123}, {"session_id": 123, "chars": ""}):
            call = self._call(name="write_stdin")
            call["payload"]["arguments"] = json.dumps(arguments)
            self.assertEqual("working", self._collect([call])["state"])

    def test_only_the_matching_output_retires_the_call(self) -> None:
        for name in ("exec", "exec_command"):
            with self.subTest(name=name):
                custom = name == "exec"
                call = self._call(name=name)
                row = self._collect([call, self._output("other", custom=custom)])
                self.assertEqual("working", row["state"])
                row = self._collect([call, self._output(custom=custom)])
                self.assertEqual("idle", row["state"])

    def test_an_output_from_a_different_tool_protocol_does_not_retire_the_call(self) -> None:
        row = self._collect([self._call(), self._output(custom=False)])
        self.assertEqual("working", row["state"])

    def test_parallel_calls_retire_independently(self) -> None:
        row = self._collect([self._call(), self._call("shell-2"), self._output()])
        self.assertEqual("working", row["state"])
        row = self._collect(
            [self._call(), self._call("shell-2"), self._output(), self._output("shell-2")]
        )
        self.assertEqual("idle", row["state"])

    def _plan(self) -> dict[str, Any]:
        return _record(
            self.call_at - 1,
            "response_item",
            {
                "type": "function_call",
                "name": "update_plan",
                "arguments": json.dumps(
                    {"plan": [{"step": "Build project", "status": "in_progress"}]}
                ),
            },
        )

    def test_call_ceiling_is_900_seconds_and_unrelated_events_do_not_renew_it(self) -> None:
        self.call_at = self.now - 901
        call, plan = self._call(), self._plan()
        tokens = []
        for delta in (0, 100, 900):
            self.now += delta
            tokens.append(_record(self.now, "event_msg", {"type": "thread_settings_applied"}))
            row = self._collect([plan, call, *tokens], cap=900)
            self.assertEqual(("working", "Build project…"), (row["state"], row["state_detail"]))
        self.assertEqual("idle", self._collect([call], cap=900)["state"])

    def test_parallel_distinct_tools_select_newest_and_retire_independently(self) -> None:
        first = self._call(name="exec_command", at=self.call_at - 10)
        last = self._call("shell-2", name="write_stdin")
        row = self._collect([first, last])
        self.assertEqual("running write_stdin", row["state_detail"])
        row = self._collect([first, last, self._output("shell-2", custom=False)])
        self.assertEqual("running exec_command", row["state_detail"])
        row = self._collect(
            [first, last, self._output("shell-2", custom=False), self._output(custom=False)]
        )
        self.assertEqual("idle", row["state"])

    def test_assistant_commentary_preserves_pending(self) -> None:
        row = self._collect([self._call(), self._message("Still waiting", role="assistant")])
        self.assertEqual("working", row["state"])

    def test_invalid_protocol_and_envelope_pairings_cannot_extend_work(self) -> None:
        for kind, name, envelope in (
            ("function_call", "exec", "response_item"),
            ("custom_tool_call", "exec_command", "response_item"),
            ("custom_tool_call", "exec", "event_msg"),
        ):
            with self.subTest(kind=kind, name=name, envelope=envelope):
                call = self._call(name=name)
                call["type"] = envelope
                call["payload"].update(
                    type=kind, input="doSomething()", arguments=json.dumps({"cmd": "sleep 1"})
                )
                self.assertEqual("idle", self._collect([call])["state"])

    def test_zero_cap_at_now_uses_plan_fallback(self) -> None:
        row = self._collect([self._plan(), self._call(at=self.now)], cap=0)
        self.assertEqual("Build project…", row["state_detail"])

    def test_parser_clears_pending_on_completion_and_abort(self) -> None:
        for end in (_complete, _aborted):
            with self.subTest(end=end.__name__):
                self._collect([self._call(), end(self.call_at + 1)])
                config, _ = runtime()
                info = transcripts.analyze_codex_transcript(config, str(self.path))
                self.assertEqual([], info["pending_shell_calls"])

    def test_ceiling_can_be_shortened_or_disabled(self) -> None:
        for cap in (200, 0):
            with self.subTest(cap=cap):
                self.assertEqual("idle", self._collect([self._call()], cap=cap)["state"])

    def test_default_ceiling_does_not_follow_file_mtime(self) -> None:
        self.call_at = self.now - 901
        self.assertEqual("idle", self._collect([self._call()])["state"])

    def test_a_call_just_inside_the_default_ceiling_still_qualifies(self) -> None:
        self.call_at = self.now - 899
        self.assertEqual("working", self._collect([self._call()])["state"])

    def test_an_untimed_or_unkeyed_output_does_not_renew_or_wrongly_retire_a_call(self) -> None:
        output = self._output([])
        output.pop("timestamp")
        self.assertEqual("working", self._collect([self._call(), output])["state"])
        output = self._output()
        output.pop("timestamp")
        self.assertEqual("idle", self._collect([self._call(), output])["state"])

    def test_pending_shell_detail_takes_precedence_over_an_old_plan(self) -> None:
        plan = _record(
            self.call_at - 1,
            "response_item",
            {
                "type": "function_call",
                "name": "update_plan",
                "arguments": json.dumps(
                    {"plan": [{"step": "Prepare the build", "status": "in_progress"}]}
                ),
            },
        )
        row = self._collect([plan, self._call()])
        self.assertEqual("working", row["state"])
        self.assertEqual("running exec", row["state_detail"])

    def test_future_call_does_not_claim_work(self) -> None:
        self.assertEqual("idle", self._collect([self._call(at=self.now + 3600)])["state"])

    def test_calls_without_a_usable_id_or_timestamp_do_not_claim_work(self) -> None:
        keys: list[Any] = [None, "", [], {}, True]
        for key in keys:
            with self.subTest(key=key):
                self.assertEqual("idle", self._collect([self._call(key)])["state"])
        call = self._call()
        call.pop("timestamp")
        self.assertEqual("idle", self._collect([call])["state"])

    def test_non_shell_tools_do_not_extend_the_activity_window(self) -> None:
        for name in ("sleep", "request_user_input_async", "update_plan", "future_shell"):
            with self.subTest(name=name):
                self.assertEqual("idle", self._collect([self._call(name=name)])["state"])

    def test_a_call_without_an_open_turn_does_not_claim_work(self) -> None:
        self.assertEqual("idle", self._collect([self._call()], started=False)["state"])

    def test_finish_or_abort_retires_pending_work_even_with_a_fresh_file(self) -> None:
        for end in (_complete, _aborted):
            with self.subTest(end=end.__name__):
                row = self._collect([self._call(), end(self.call_at + 1)], fresh_mtime=True)
                self.assertEqual("idle", row["state"])
                self.assertEqual(
                    "run finished" if end is _complete else "awaiting your message",
                    row["state_detail"],
                )

    def test_a_new_turn_cannot_inherit_an_old_unanswered_call(self) -> None:
        row = self._collect([self._call(), _started(self.call_at + 1, "t2")])
        self.assertEqual("idle", row["state"])

    def test_a_new_user_message_retires_pending_work(self) -> None:
        prompt = _record(
            self.call_at + 1, "response_item", {"type": "message", "role": "user", "content": []}
        )
        self.assertEqual("idle", self._collect([self._call(), prompt])["state"])

    def test_injected_user_records_preserve_pending(self) -> None:
        for body in (
            '<codex_internal_context source="user_goal">context</codex_internal_context>',
            "<subagent_notification>done</subagent_notification>",
        ):
            with self.subTest(body=body):
                message = self._message(body)
                self.assertEqual("working", self._collect([self._call(), message])["state"])

    def _message(self, body: str, role: str = "user") -> dict[str, Any]:
        return _record(
            self.call_at + 1,
            "response_item",
            {"type": "message", "role": role, "content": [{"type": "input_text", "text": body}]},
        )

    def test_genuine_prompts_and_explicit_interruptions_retire_pending(self) -> None:
        for body in ("Please do this next", "<turn_aborted>", "[Request interrupted by user]"):
            with self.subTest(body=body):
                self.assertEqual(
                    "idle", self._collect([self._call(), self._message(body)])["state"]
                )

    def _aggregate(
        self, *, stop: float = 0, end: float = 0, restored: bool = False
    ) -> dict[str, Any]:
        config, state = runtime()
        source = mock.Mock()
        source.overlays_for.return_value = []
        source.finished_at.return_value = stop
        source.ended_at.return_value = 0 if restored else end
        source.git_for.return_value = None
        source.focusable.return_value = False
        source.command_reports.return_value = []
        source.parent_declarations.return_value = {}
        if restored:
            self.assertTrue(
                ends.record(
                    config, harness="codex", sid=SID, at=end, diagnostic_sink=lambda _: None
                )
            )
        app = aggregate.Application(
            config,
            state,
            (aggregate.HarnessSpec("codex", "Codex", codex.discover, codex.collect),),
            overlays=source,
            clock=lambda: self.now,
            native_notifier=lambda _: "",
            popup_notifier=lambda _title, _body: None,
            diagnostic_sink=lambda _: None,
        )
        return app.collect(show_all=False)

    def test_observed_end_and_remembered_stop_settle_pending(self) -> None:
        for kind in ("stop", "end", "restored"):
            for age in (30, 300):
                with self.subTest(kind=kind, age=age):
                    self.call_at = self.now - age
                    self.assertEqual("working", self._collect([self._call()])["state"])
                    at = self.call_at + 10
                    with store_patch(CODEX_SESSIONS_DIR=self.tmp.name):
                        payload = self._aggregate(
                            stop=at if kind == "stop" else 0,
                            end=at if kind != "stop" else 0,
                            restored=kind == "restored",
                        )
                    (row,) = payload["sessions"]
                    self.assertEqual("idle", row["state"])
                    self.assertIs(row["active"], False)
                    self.assertEqual(0, payload["summary"]["working"])

    def test_settlement_keeps_an_already_idle_run_finished_detail(self) -> None:
        self._collect([self._call(), _complete(self.call_at + 1)])
        for kind in ("stop", "end"):
            with self.subTest(kind=kind), store_patch(CODEX_SESSIONS_DIR=self.tmp.name):
                payload = self._aggregate(
                    stop=self.call_at + 10 if kind == "stop" else 0,
                    end=self.call_at + 10 if kind == "end" else 0,
                )
                (row,) = payload["sessions"]
                self.assertEqual(("idle", "run finished"), (row["state"], row["state_detail"]))
                self.assertIs(row["active"], False)
                self.assertEqual(0, payload["summary"]["working"])

    def test_a_command_item_finish_does_not_finish_the_outer_exec_call(self) -> None:
        row = self._collect([self._call(), _command_done(self.call_at + 1, "t1")])
        self.assertEqual("working", row["state"])

    def test_a_resumed_turn_can_wait_on_a_new_call(self) -> None:
        row = self._collect(
            [_complete(self.call_at - 2), _started(self.call_at - 1, "t2"), self._call()]
        )
        self.assertEqual("working", row["state"])
        self.assertIsNone(row["turn_end_at"])

    def test_an_expired_parallel_call_does_not_hide_a_newer_pending_call(self) -> None:
        row = self._collect([self._call("old", at=self.now - 901), self._call()])
        self.assertEqual("working", row["state"])
