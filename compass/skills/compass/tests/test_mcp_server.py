"""The ask_operator MCP server: its frame contract, its call flow, its guards.

Driven in-process against a scripted stdin and a captured stdout. No child
process and no socket: AGENTS.md records subprocess and loopback-bind tests as
the ones that manufacture failures under a concurrent suite, and every property
worth asserting here is reachable without either.
"""

from __future__ import annotations

import dataclasses
import io
import json
import os
import pathlib
import queue
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Self
from unittest import mock

import mcp_server
import notify_hook
from compass_runtime import http_api
from compass_runtime.config import build_runtime_config

_LOGGED: list[str] = []
_LOG_PATCH = mock.patch.object(mcp_server, "log", _LOGGED.append)


def setUpModule() -> None:
    """Collect the server's stderr diagnostics instead of printing them.

    Several cases below drive a failure path that logs by design, and a suite
    that prints their tracebacks reads as a broken run.
    """
    _LOG_PATCH.start()


def tearDownModule() -> None:
    _LOG_PATCH.stop()


CLAUDE_PROTOCOL = "2025-11-25"
CODEX_PROTOCOL = "2025-06-18"
# One frame each, exactly as measured. Claude Code 2.1.239 sends no params key
# and codex-cli 0.146.1 sends one; see docs/captures/*/mcp-ask-gate-*.jsonl.
CLAUDE_TOOLS_LIST = {"id": 2, "jsonrpc": "2.0", "method": "tools/list"}
CODEX_TOOLS_LIST = {"id": 2, "jsonrpc": "2.0", "method": "tools/list", "params": {}}


class _Stdin:
    """A stdin a test can feed one frame at a time.

    Needed rather than a BytesIO because the cancellation case has to push a
    frame *while* a call is held: with everything queued up front the abort would
    be set before the worker had begun to poll, which is not the case under test.
    """

    def __init__(self) -> None:
        self._chunks: queue.Queue[bytes | None] = queue.Queue()
        self._buffer = b""
        self._eof = False

    def push(self, payload: dict[str, Any] | bytes) -> None:
        raw = payload if isinstance(payload, bytes) else json.dumps(payload).encode() + b"\n"
        self._chunks.put(raw)

    def close(self) -> None:
        self._chunks.put(None)

    def readline(self, limit: int = -1) -> bytes:
        while b"\n" not in self._buffer:
            if limit >= 0 and len(self._buffer) >= limit:
                break
            if self._eof:
                break
            chunk = self._chunks.get()
            if chunk is None:
                self._eof = True
                break
            self._buffer += chunk
        if not self._buffer:
            return b""
        end = self._buffer.find(b"\n")
        cut = end + 1 if end >= 0 else len(self._buffer)
        if limit >= 0:
            cut = min(cut, limit)
        out, self._buffer = self._buffer[:cut], self._buffer[cut:]
        return out


class _Stdout:
    """Captured frames, readable from the test thread while a worker writes."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._raw = b""

    def write(self, payload: bytes) -> int:
        with self._lock:
            self._raw += payload
        return len(payload)

    def flush(self) -> None:
        return None

    def lines(self) -> list[bytes]:
        with self._lock:
            return [line for line in self._raw.split(b"\n") if line.strip()]

    def frames(self) -> list[dict[str, Any]]:
        return [json.loads(line) for line in self.lines()]


class _Harness:
    """One server run, driven from the test thread."""

    def __init__(self, ports: tuple[int, ...] = (4553,)) -> None:
        self.stdin = _Stdin()
        self.stdout = _Stdout()
        self.server = mcp_server.AskServer(stdin=self.stdin, stdout=self.stdout, ports=ports)
        self._thread = threading.Thread(target=self.server.run, daemon=True)

    def __enter__(self) -> Self:
        self._thread.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.stdin.close()
        self._thread.join(timeout=10.0)

    def push(self, payload: dict[str, Any] | bytes) -> None:
        self.stdin.push(payload)

    def wait_for_frames(self, count: int, timeout: float = 10.0) -> list[dict[str, Any]]:
        deadline = threading.Event()
        waited = 0.0
        while waited < timeout:
            frames = self.stdout.frames()
            if len(frames) >= count:
                return frames
            deadline.wait(0.02)
            waited += 0.02
        return self.stdout.frames()


def _call(request_id: Any, question: str, options: list[Any]) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "tools/call",
        "params": {"name": "ask_operator", "arguments": {"question": question, "options": options}},
    }


def _body(request: urllib.request.Request) -> dict[str, Any]:
    """One posted JSON body, as the dashboard would parse it."""
    assert isinstance(request.data, bytes)
    parsed = json.loads(request.data)
    assert isinstance(parsed, dict)
    return parsed


def _text(frame: dict[str, Any]) -> str:
    content = frame["result"]["content"]
    return str(content[0]["text"])


def _config() -> Any:
    return build_runtime_config(
        environ={"HOME": "/nonexistent-compass-test"},
        platform_name="linux",
        os_name="posix",
        launcher_path=pathlib.Path(mcp_server.__file__),
    )


@dataclasses.dataclass(frozen=True)
class _Echo:
    """Register as the real route does: `http_api.ask_text` on the body, then
    the id with the card's question and options, or a 400 if it refuses.

    Calling the route's own normaliser rather than restating it is the point: a
    double that echoed what it was sent hid a card that differed from the answer.
    """

    ask_id: str = "ask-1"


_Register = tuple[int, dict[str, Any]] | _Echo | None
_ECHO = _Echo()


class _FakeDashboard:
    """A stand-in for the loopback dashboard, patched in at `mcp_server._open`.

    Patched below the loopback check on purpose, so the guard stays exercised on
    a real 127.0.0.1 URL while no socket is ever opened.
    """

    def __init__(
        self,
        *,
        register: _Register = _ECHO,
        register_by_port: dict[int, _Register] | None = None,
        poll: list[tuple[int, dict[str, Any] | None]] | None = None,
        withdraw: tuple[int, dict[str, Any]] | None = (200, {"ok": True, "withdrawn": True}),
    ) -> None:
        self.register = register
        # A port this maps to nothing refuses the connection, which is how a
        # walk-past-a-refusal case is told apart from a walk-past-a-response one.
        self.register_by_port = register_by_port
        self.poll = poll or []
        self.withdraw = withdraw
        self.requests: list[str] = []
        self.registrations: list[dict[str, Any]] = []
        # What each register was answered with, so a test reads the card's text
        # where the real route publishes it.
        self.replies: list[dict[str, Any]] = []
        self.withdrawals: list[dict[str, Any]] = []
        self.polls = threading.Semaphore(0)
        self._lock = threading.Lock()

    def __call__(self, request: urllib.request.Request, timeout: float) -> tuple[int, bytes] | None:
        del timeout
        url = request.full_url
        with self._lock:
            self.requests.append(url)
        # Checked before the poll fallthrough: the withdraw path also lives under
        # /api/ask/, so an order swap here would score it as a poll.
        if url.endswith("/api/ask/withdraw"):
            with self._lock:
                self.withdrawals.append(_body(request))
            if self.withdraw is None:
                return None
            status, body = self.withdraw
            return status, json.dumps(body).encode()
        if url.endswith("/api/ask"):
            return self._registered(request)
        self.polls.release()
        step: tuple[int, dict[str, Any] | None] | None
        with self._lock:
            # A one-entry script is served over and over, which is how a test
            # holds a call at 204 until something aborts it.
            step = (
                self.poll[0] if len(self.poll) == 1 else (self.poll.pop(0) if self.poll else None)
            )
        if step is None:
            return None
        poll_status, poll_body = step
        return poll_status, b"" if poll_body is None else json.dumps(poll_body).encode()

    def _registered(self, request: urllib.request.Request) -> tuple[int, bytes] | None:
        sent = _body(request)
        with self._lock:
            self.registrations.append(sent)
        answer = self.register
        if self.register_by_port is not None:
            answer = self.register_by_port.get(urllib.parse.urlsplit(request.full_url).port or 0)
        if answer is None:
            return None
        if isinstance(answer, _Echo):
            text = http_api.ask_text(sent, _config())
            if text is None:
                return 400, b""
            card = {"question": text.question, "options": list(text.options)}
            answer = (200, {"ok": True, "id": answer.ask_id, **card})
        status, body = answer
        with self._lock:
            self.replies.append(body)
        return status, json.dumps(body).encode()

    def poll_count(self) -> int:
        with self._lock:
            return sum(
                1
                for url in self.requests
                if "/api/ask/" in url and not url.endswith("/api/ask/withdraw")
            )

    def register_ports(self) -> list[int]:
        with self._lock:
            return [
                urllib.parse.urlsplit(url).port or 0
                for url in self.requests
                if url.endswith("/api/ask")
            ]


class FrameContractTest(unittest.TestCase):
    """One valid JSON-RPC object per request, and nothing else on stdout."""

    def test_malformed_json_gets_one_parse_error(self) -> None:
        with _Harness() as harness:
            harness.push(b"{not json at all\n")
            frames = harness.wait_for_frames(1)
        self.assertEqual(1, len(frames))
        self.assertIsNone(frames[0]["id"])
        self.assertEqual(mcp_server.PARSE_ERROR, frames[0]["error"]["code"])

    def test_oversized_frame_is_answered_and_the_next_frame_still_lands(self) -> None:
        huge = (
            b'{"jsonrpc":"2.0","id":1,"method":"ping","pad":"' + b"a" * mcp_server.MAX_FRAME_BYTES
        )
        with _Harness() as harness:
            harness.push(huge + b'"}\n')
            harness.push({"jsonrpc": "2.0", "id": 9, "method": "ping"})
            frames = harness.wait_for_frames(2)
        self.assertEqual(2, len(frames))
        self.assertEqual(mcp_server.PARSE_ERROR, frames[0]["error"]["code"])
        # The drain is what this proves: the tail of the oversized line was not
        # read back as a second frame.
        self.assertEqual(9, frames[1]["id"])

    def test_a_bare_newline_is_not_a_request_and_gets_no_reply(self) -> None:
        with _Harness() as harness:
            harness.push(b"\n")
            harness.push({"jsonrpc": "2.0", "id": 3, "method": "ping"})
            frames = harness.wait_for_frames(1)
        self.assertEqual([3], [frame["id"] for frame in frames])

    def test_a_non_object_frame_is_an_invalid_request(self) -> None:
        with _Harness() as harness:
            harness.push(b"[1,2,3]\n")
            frames = harness.wait_for_frames(1)
        self.assertEqual(mcp_server.INVALID_REQUEST, frames[0]["error"]["code"])

    def test_a_notification_gets_no_reply(self) -> None:
        with _Harness() as harness:
            harness.push({"jsonrpc": "2.0", "method": "notifications/initialized"})
            harness.push({"jsonrpc": "2.0", "id": 4, "method": "ping"})
            frames = harness.wait_for_frames(1)
        self.assertEqual([4], [frame["id"] for frame in frames])

    def test_initialize_echoes_each_measured_protocol_version(self) -> None:
        for announced in (CLAUDE_PROTOCOL, CODEX_PROTOCOL):
            with self.subTest(announced=announced), _Harness() as harness:
                harness.push(
                    {
                        "id": 1,
                        "jsonrpc": "2.0",
                        "method": "initialize",
                        "params": {"protocolVersion": announced},
                    }
                )
                frames = harness.wait_for_frames(1)
                self.assertEqual(announced, frames[0]["result"]["protocolVersion"])
                self.assertEqual({"tools": {}}, frames[0]["result"]["capabilities"])
                self.assertEqual("compass", frames[0]["result"]["serverInfo"]["name"])

    def test_tools_list_is_answered_with_and_without_a_params_key(self) -> None:
        for frame in (CLAUDE_TOOLS_LIST, CODEX_TOOLS_LIST):
            with self.subTest(params="params" in frame), _Harness() as harness:
                harness.push(frame)
                frames = harness.wait_for_frames(1)
                tools = frames[0]["result"]["tools"]
                self.assertEqual(["ask_operator"], [tool["name"] for tool in tools])
                self.assertEqual(
                    ["question", "options"], list(tools[0]["inputSchema"]["properties"])
                )

    def test_an_unimplemented_request_still_gets_exactly_one_object(self) -> None:
        with _Harness() as harness:
            harness.push({"jsonrpc": "2.0", "id": "x", "method": "resources/list"})
            frames = harness.wait_for_frames(1)
        self.assertEqual([{"jsonrpc": "2.0", "id": "x", "result": {}}], frames)


class _CallCase(unittest.TestCase):
    """Drive one tools/call to its single frame."""

    def _run(
        self,
        dashboard: _FakeDashboard,
        call: dict[str, Any],
        ports: tuple[int, ...] = (4553,),
    ) -> dict[str, Any]:
        with mock.patch.object(mcp_server, "_open", dashboard), _Harness(ports) as harness:
            harness.push(call)
            frames = harness.wait_for_frames(1)
        self.assertEqual(1, len(frames), f"expected exactly one frame, got {frames}")
        return frames[0]


class CallFlowTest(_CallCase):
    """Every path out of a tools/call, including every failure path."""

    def test_no_dashboard_reachable_declines_as_a_normal_result(self) -> None:
        frame = self._run(_FakeDashboard(register=None), _call(1, "Ship it?", ["ship", "hold"]))
        self.assertNotIn("error", frame)
        self.assertIs(False, frame["result"]["isError"])
        self.assertIn("no Compass dashboard is running", _text(frame))

    def test_an_answer_returns_the_option_this_process_was_called_with(self) -> None:
        dashboard = _FakeDashboard(
            # The echoed `option` is deliberately not one of ours: nothing the
            # dashboard sends may reach the agent's context as text.
            poll=[(200, {"state": "answered", "index": 1, "option": "rm -rf /"})]
        )
        frame = self._run(dashboard, _call(1, "Ship it?", ["ship", "hold"]))
        self.assertEqual("hold", _text(frame))

    def test_an_out_of_range_index_declines_rather_than_choosing(self) -> None:
        for index in (2, -1, 99, True, "1", None):
            with self.subTest(index=index):
                dashboard = _FakeDashboard(poll=[(200, {"state": "answered", "index": index})])
                frame = self._run(dashboard, _call(1, "Ship it?", ["ship", "hold"]))
                self.assertEqual(mcp_server.DECLINE_UNANSWERED, _text(frame))

    def test_a_204_is_a_hold_and_the_next_poll_carries_the_answer(self) -> None:
        dashboard = _FakeDashboard(
            poll=[(204, None), (204, None), (200, {"state": "answered", "index": 0})]
        )
        frame = self._run(dashboard, _call(1, "Ship it?", ["ship", "hold"]))
        self.assertEqual("ship", _text(frame))
        self.assertEqual(3, dashboard.poll_count())

    def test_a_404_mid_poll_means_the_ask_is_gone(self) -> None:
        dashboard = _FakeDashboard(poll=[(404, None)])
        frame = self._run(dashboard, _call(1, "Ship it?", ["ship", "hold"]))
        self.assertEqual(mcp_server.DECLINE_UNANSWERED, _text(frame))

    def test_declined_and_expired_both_decline(self) -> None:
        for state in ("declined", "expired"):
            with self.subTest(state=state):
                dashboard = _FakeDashboard(poll=[(200, {"state": state})])
                frame = self._run(dashboard, _call(1, "Ship it?", ["ship", "hold"]))
                self.assertEqual(mcp_server.DECLINE_UNANSWERED, _text(frame))

    def test_an_unusable_ask_id_is_not_interpolated_into_a_url(self) -> None:
        dashboard = _FakeDashboard(register=(200, {"ok": True, "id": "../../etc/passwd"}))
        frame = self._run(dashboard, _call(1, "Ship it?", ["ship", "hold"]), ports=(4553, 4554))
        self.assertEqual(mcp_server.DECLINE_INTERNAL, _text(frame))
        self.assertEqual(0, dashboard.poll_count())
        # A 200 means the question is on that dashboard's board, so it is taken
        # back by id in a body rather than left clickable, and no second port is
        # asked to register the same question.
        self.assertEqual([{"id": "../../etc/passwd"}], dashboard.withdrawals)
        self.assertEqual([4553], dashboard.register_ports())

    def test_bad_arguments_are_an_error_result_not_a_protocol_error(self) -> None:
        cases: list[list[Any]] = [["only one"], [], ["a", 7], ["a", ""], ["x"] * 9]
        for options in cases:
            with self.subTest(options=options):
                frame = self._run(_FakeDashboard(), _call(1, "Ship it?", options))
                self.assertNotIn("error", frame)
                self.assertIs(True, frame["result"]["isError"])

    def test_an_empty_question_is_an_error_result(self) -> None:
        frame = self._run(_FakeDashboard(), _call(1, "   ", ["ship", "hold"]))
        self.assertIs(True, frame["result"]["isError"])

    def test_an_unknown_tool_name_is_answered_once(self) -> None:
        call = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "something_else", "arguments": {}},
        }
        frame = self._run(_FakeDashboard(), call)
        self.assertIs(True, frame["result"]["isError"])

    def test_a_raising_worker_still_answers_the_caller(self) -> None:
        def explode(*_args: object, **_kwargs: object) -> None:
            raise RuntimeError("boom")

        with mock.patch.object(mcp_server, "_open", explode), _Harness() as harness:
            harness.push(_call(1, "Ship it?", ["ship", "hold"]))
            frames = harness.wait_for_frames(1)
        self.assertEqual(1, len(frames))
        self.assertEqual(mcp_server.DECLINE_INTERNAL, _text(frames[0]))

    def test_the_registered_body_carries_the_question_and_options_uncut(self) -> None:
        # The dashboard redacts the whole of each string before it cuts, and
        # measures the question from what it received, so nothing is cut here.
        dashboard = _FakeDashboard(poll=[(200, {"state": "answered", "index": 0})])
        self._run(dashboard, _call(1, "Q" * 2_500, ["A" * 400, "hold"]))
        body = dashboard.registrations[0]
        self.assertEqual("Q" * 2_500, body["question"])
        self.assertEqual(["A" * 400, "hold"], body["options"])
        self.assertNotIn("question_sent_chars", body)
        self.assertIn("harness", body)

    def test_a_question_over_the_cap_ends_in_an_ellipsis_on_the_card(self) -> None:
        dashboard = _FakeDashboard(poll=[(200, {"state": "answered", "index": 0})])
        self._run(dashboard, _call(1, "Q" * 2_500, ["ship", "hold"]))
        self.assertEqual("Q" * 1_999 + "\u2026", dashboard.replies[0]["question"])

    def test_a_question_at_the_cap_is_sent_whole_and_unflagged(self) -> None:
        dashboard = _FakeDashboard(poll=[(200, {"state": "answered", "index": 0})])
        self._run(dashboard, _call(1, "Q" * 2_000, ["ship", "hold"]))
        body = dashboard.registrations[0]
        self.assertEqual("Q" * 2_000, body["question"])
        self.assertEqual("Q" * 2_000, dashboard.replies[0]["question"])
        self.assertNotIn("question_sent_chars", body)

    def test_an_option_over_the_cap_ends_in_an_ellipsis_inside_it(self) -> None:
        dashboard = _FakeDashboard(poll=[(200, {"state": "answered", "index": 0})])
        frame = self._run(dashboard, _call(1, "Which?", ["o" * 241, "p" * 240]))
        self.assertEqual(["o" * 239 + "\u2026", "p" * 240], dashboard.replies[0]["options"])
        self.assertEqual("o" * 239 + "\u2026", _text(frame))


class RegisterRefusalTest(_CallCase):
    """A dashboard that answered is the dashboard, whatever it answered.

    Measured before the fix: with `--no-ask` on the preferred port the question
    walked to the next candidate and was registered and answered on a different
    dashboard, which is exactly what the rollback switch is supposed to prevent.
    """

    def _refused(self, first: _Register) -> tuple[dict[str, Any], _FakeDashboard]:
        dashboard = _FakeDashboard(
            register_by_port={4553: first, 4554: _Echo("ask-2")},
            poll=[(200, {"state": "answered", "index": 0})],
        )
        frame = self._run(dashboard, _call(1, "Ship it?", ["ship", "hold"]), ports=(4553, 4554))
        return frame, dashboard

    def test_a_disabled_lane_is_not_walked_past(self) -> None:
        frame, dashboard = self._refused((503, {"ok": False, "reason": "disabled"}))
        self.assertEqual([4553], dashboard.register_ports())
        self.assertEqual(0, dashboard.poll_count())
        self.assertEqual(mcp_server.DECLINE_DISABLED, _text(frame))
        self.assertIn("ask lane", _text(frame))

    def test_a_full_budget_is_not_walked_past(self) -> None:
        frame, dashboard = self._refused((503, {"ok": False, "reason": "busy"}))
        self.assertEqual([4553], dashboard.register_ports())
        self.assertEqual(mcp_server.DECLINE_BUSY, _text(frame))
        self.assertIn("already waiting", _text(frame))

    def test_no_refusal_claims_that_nothing_is_running(self) -> None:
        # The agent puts this sentence in its context and may repeat it to the
        # user, so the cause has to be true rather than convenient.
        for first in (
            (503, {}),
            (503, {"ok": False, "reason": "something-newer"}),
            (400, {}),
            (413, {}),
            (500, {}),
        ):
            with self.subTest(first=first):
                frame, dashboard = self._refused(first)
                self.assertEqual([4553], dashboard.register_ports())
                self.assertNotIn("no Compass dashboard is running", _text(frame))
                self.assertIs(False, frame["result"]["isError"])

    def test_a_refused_connection_still_walks_to_the_next_candidate(self) -> None:
        dashboard = _FakeDashboard(
            register_by_port={4554: _Echo("ask-2")},
            poll=[(200, {"state": "answered", "index": 1})],
        )
        frame = self._run(dashboard, _call(1, "Ship it?", ["ship", "hold"]), ports=(4553, 4554))
        self.assertEqual([4553, 4554], dashboard.register_ports())
        self.assertEqual("hold", _text(frame))


class WithdrawTest(_CallCase):
    """An abandoned question comes off the board on the way out."""

    def test_a_poll_that_gave_up_withdraws_the_question(self) -> None:
        dashboard = _FakeDashboard(poll=[(500, None)])
        frame = self._run(dashboard, _call(1, "Ship it?", ["ship", "hold"]))
        self.assertEqual(mcp_server.DECLINE_UNANSWERED, _text(frame))
        self.assertEqual([{"id": "ask-1"}], dashboard.withdrawals)

    def test_a_failed_withdrawal_does_not_change_what_the_agent_is_told(self) -> None:
        for withdraw in (None, (500, {}), (200, {"ok": True, "withdrawn": False})):
            with self.subTest(withdraw=withdraw):
                dashboard = _FakeDashboard(poll=[(500, None)], withdraw=withdraw)
                frame = self._run(dashboard, _call(1, "Ship it?", ["ship", "hold"]))
                self.assertEqual(mcp_server.DECLINE_UNANSWERED, _text(frame))
                self.assertEqual(1, len(dashboard.withdrawals))

    def test_a_resolved_question_is_left_alone(self) -> None:
        # Answered, declined and expired are all resolutions the dashboard has
        # already released. Withdrawing one would be a second write for nothing.
        for state, index in (("answered", 0), ("declined", None), ("expired", None)):
            with self.subTest(state=state):
                dashboard = _FakeDashboard(poll=[(200, {"state": state, "index": index})])
                self._run(dashboard, _call(1, "Ship it?", ["ship", "hold"]))
                self.assertEqual([], dashboard.withdrawals)

    def test_an_ask_the_dashboard_already_dropped_is_not_withdrawn(self) -> None:
        dashboard = _FakeDashboard(poll=[(404, None)])
        self._run(dashboard, _call(1, "Ship it?", ["ship", "hold"]))
        self.assertEqual([], dashboard.withdrawals)

    def test_a_cancelled_call_withdraws_the_question(self) -> None:
        dashboard = _FakeDashboard(poll=[(204, None)])
        with mock.patch.object(mcp_server, "_open", dashboard), _Harness() as harness:
            harness.push(_call("c1", "Ship it?", ["ship", "hold"]))
            self.assertTrue(dashboard.polls.acquire(timeout=10.0))
            harness.push(
                {
                    "jsonrpc": "2.0",
                    "method": "notifications/cancelled",
                    "params": {"requestId": "c1"},
                }
            )
            frames = harness.wait_for_frames(1)
        self.assertEqual(mcp_server.DECLINE_UNANSWERED, _text(frames[0]))
        self.assertEqual([{"id": "ask-1"}], dashboard.withdrawals)


class OperatorConsentTest(_CallCase):
    """The agent gets the string the operator saw, not a longer one."""

    def test_the_returned_option_is_the_one_that_was_registered(self) -> None:
        long_option = "y" * 40 + "z" * 300
        dashboard = _FakeDashboard(poll=[(200, {"state": "answered", "index": 1})])
        frame = self._run(dashboard, _call(1, "Ship it?", ["ship", long_option]))
        registered = dashboard.replies[0]["options"]
        # Consent has to be to the thing that happens: the card can only show the
        # truncated label, so that is the string the answer resolves to.
        self.assertEqual(mcp_server.OPTION_CAP_CHARS, len(registered[1]))
        self.assertEqual(registered[1], _text(frame))

    def test_two_options_differing_only_past_the_cap_are_refused_not_registered(self) -> None:
        head = "a" * mcp_server.OPTION_CAP_CHARS
        dashboard = _FakeDashboard()
        frame = self._run(dashboard, _call(1, "Which?", [head + "-one", head + "-two"]))
        self.assertIs(True, frame["result"]["isError"])
        self.assertEqual(
            "ask_operator needs options that differ within their first 240 characters.",
            _text(frame),
        )
        self.assertEqual([], dashboard.registrations)

    def test_cut_options_keep_every_index_on_the_option_shown(self) -> None:
        # The reader pressed a button showing a cut label, and the registered
        # string at that position is what comes back, with the uncut option after
        # them still answering as itself.
        options = ["b" * 300, "c" * 300, "hold"]
        for index in range(3):
            with self.subTest(index=index):
                dashboard = _FakeDashboard(poll=[(200, {"state": "answered", "index": index})])
                frame = self._run(dashboard, _call(1, "Which?", options))
                registered = dashboard.replies[0]["options"]
                self.assertEqual(3, len(registered))
                self.assertEqual("hold", registered[2])
                self.assertEqual(registered[index], _text(frame))


class CardMatchesAnswerTest(_CallCase):
    """The card is redacted before it is cut, and the answer is that card's text.

    Each side cut on its own before, and they disagreed: the card showed a
    redacted label while the session was answered with the unredacted string.
    """

    KEY = "sk-ant-" + "A" * 35

    def test_a_redacted_option_answers_as_the_card_shows_it(self) -> None:
        option = "x" * 130 + " " + self.KEY
        dashboard = _FakeDashboard(poll=[(200, {"state": "answered", "index": 0})])
        frame = self._run(dashboard, _call(1, "Ship it?", [option, "hold"]))
        shown = dashboard.replies[0]["options"][0]
        self.assertEqual(shown, _text(frame))
        self.assertEqual("x" * 130 + " sk-ant-\u2026REDACTED", shown)
        self.assertNotIn("A" * 12, _text(frame))

    def test_a_key_straddling_the_cap_is_redacted_before_anything_is_cut(self) -> None:
        # Cutting first sent the card `AKIAAAAAAAAAA…`, a head too short to match.
        option = "x" * 225 + " AKIA" + "A" * 16 + " tail" * 20
        dashboard = _FakeDashboard(poll=[(200, {"state": "answered", "index": 0})])
        frame = self._run(dashboard, _call(1, "Ship it?", [option, "hold"]))
        self.assertEqual("x" * 225 + " AKIA\u2026REDACTED\u2026", _text(frame))
        # Sent whole, so the dashboard saw all of the key and redacted it.
        self.assertEqual(option, dashboard.registrations[0]["options"][0])

    def test_a_marker_straddling_the_cap_is_cut_before_and_the_answer_fits(self) -> None:
        option = "x" * 233 + " " + self.KEY + " tail" * 20
        dashboard = _FakeDashboard(poll=[(200, {"state": "answered", "index": 0})])
        frame = self._run(dashboard, _call(1, "Ship it?", [option, "hold"]))
        self.assertEqual("x" * 233 + "\u2026", _text(frame))
        self.assertEqual(_text(frame), dashboard.replies[0]["options"][0])

    def test_a_reply_without_the_card_text_is_withdrawn_and_declined(self) -> None:
        dashboard = _FakeDashboard(
            register=(200, {"ok": True, "id": "ask-1"}),
            poll=[(200, {"state": "answered", "index": 0})],
        )
        frame = self._run(dashboard, _call(1, "Ship it?", ["ship", "hold"]))
        # What a dashboard from before the echo answers: it is told apart from a
        # card that differs, because the fix is a restart.
        self.assertEqual(mcp_server.DECLINE_OUTDATED, _text(frame))
        self.assertIn("restart", _text(frame))
        self.assertEqual([{"id": "ask-1"}], dashboard.withdrawals)
        self.assertEqual(0, dashboard.poll_count())

    def test_a_card_unlike_this_processs_copy_is_withdrawn_and_declined(self) -> None:
        # A dashboard of another version, or something else on the port, showing
        # different labels: the reader would click one string and the session
        # would get another.
        unlike = {"ok": True, "id": "ask-1", "question": "Ship it?", "options": ["ship", "rm"]}
        dashboard = _FakeDashboard(
            register=(200, unlike), poll=[(200, {"state": "answered", "index": 1})]
        )
        frame = self._run(dashboard, _call(1, "Ship it?", ["ship", "hold"]))
        self.assertEqual(mcp_server.DECLINE_INTERNAL, _text(frame))
        self.assertEqual([{"id": "ask-1"}], dashboard.withdrawals)
        self.assertEqual(0, dashboard.poll_count())


class PayloadSizeTest(_CallCase):
    """The local size gate must not refuse what the dashboard would accept."""

    def test_a_non_latin_question_is_registered_rather_than_refused(self) -> None:
        # Every documented cap is in characters, and this payload is inside all of
        # them. Escaping it to \uXXXX made it 8 800 bytes against an 8 192-byte
        # gate, so it was refused locally and reported as no dashboard running.
        question = "測" * mcp_server.QUESTION_CAP_CHARS
        options = [
            str(n) + "選" * mcp_server.OPTION_CAP_CHARS for n in range(mcp_server.MAX_OPTIONS)
        ]
        dashboard = _FakeDashboard(poll=[(200, {"state": "answered", "index": 0})])
        with mock.patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": "/tmp/x"}, clear=False):
            frame = self._run(dashboard, _call(1, question, options))
        self.assertEqual(1, len(dashboard.registrations))
        reply = dashboard.replies[0]
        self.assertEqual(mcp_server.QUESTION_CAP_CHARS, len(reply["question"]))
        self.assertEqual(reply["options"][0], _text(frame))

    def test_the_widest_legal_text_is_registered_rather_than_refused(self) -> None:
        # A control character is the widest a character gets on the wire: JSON
        # escapes it to six bytes even with ensure_ascii off. Every field just
        # past its cap, sent uncut, still has to fit the gate.
        # Each led by a visible character: control characters alone are made
        # safe as spaces and strip to nothing, which is refused.
        question = "q" + "\x01" * mcp_server.QUESTION_CAP_CHARS
        options = [
            str(n) + "\x01" * mcp_server.OPTION_CAP_CHARS for n in range(mcp_server.MAX_OPTIONS)
        ]
        project = "/" + "\x01" * 511
        dashboard = _FakeDashboard(poll=[(200, {"state": "answered", "index": 0})])
        with mock.patch.dict(
            os.environ,
            {"CLAUDE_PROJECT_DIR": project, "CLAUDE_CODE_SESSION_ID": "s" * 64},
            clear=False,
        ):
            frame = self._run(dashboard, _call(1, question, options))
        self.assertEqual(1, len(dashboard.registrations))
        self.assertEqual(dashboard.replies[0]["options"][0], _text(frame))

    def test_a_question_past_the_body_cap_is_refused_with_a_sentence_not_cut(self) -> None:
        # Cutting here would cut before the dashboard redacts, so the bound on
        # what is sent is a refusal that says how much a card shows.
        dashboard = _FakeDashboard()
        frame = self._run(dashboard, _call(1, "q" * mcp_server.BODY_CAP_BYTES, ["ship", "hold"]))
        self.assertEqual([], dashboard.requests)
        self.assertEqual(mcp_server.DECLINE_TOO_LARGE_QUESTION, _text(frame))
        self.assertIn("32,768-byte limit", _text(frame))
        self.assertIn("2,000 characters of a question", _text(frame))

    def test_long_options_beside_a_short_question_are_named_as_the_part_over(self) -> None:
        # It used to say a shorter question could be asked, of an 11-character one.
        options = [f"opt {n} " + "z" * 4100 for n in range(mcp_server.MAX_OPTIONS)]
        dashboard = _FakeDashboard()
        with mock.patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": "/tmp/x"}, clear=False):
            frame = self._run(dashboard, _call(1, "Which plan?", options))
        self.assertEqual([], dashboard.requests)
        self.assertEqual(mcp_server.DECLINE_TOO_LARGE_OPTIONS, _text(frame))
        self.assertIn("shorter options", _text(frame))
        self.assertNotIn("shorter question", _text(frame))

    def test_a_question_and_options_over_only_together_name_both(self) -> None:
        question = "q" * 17_000
        options = ["a" * 8_000, "b" * 8_000]
        dashboard = _FakeDashboard()
        frame = self._run(dashboard, _call(1, question, options))
        self.assertEqual([], dashboard.requests)
        self.assertEqual(mcp_server.DECLINE_TOO_LARGE, _text(frame))
        self.assertIn("shorter question or shorter options", _text(frame))

    def test_a_payload_over_the_byte_cap_says_so_instead_of_blaming_the_dashboard(self) -> None:
        # Reachable through the one field this process does not bound: the
        # attributed project directory is whatever the harness exported.
        dashboard = _FakeDashboard()
        with mock.patch.dict(
            os.environ, {"CLAUDE_PROJECT_DIR": "/" + "p" * mcp_server.BODY_CAP_BYTES}, clear=False
        ):
            frame = self._run(dashboard, _call(1, "Ship it?", ["ship", "hold"]))
        self.assertEqual([], dashboard.requests)
        self.assertEqual(mcp_server.DECLINE_TOO_LARGE_ATTRIBUTION, _text(frame))
        self.assertNotIn("no Compass dashboard is running", _text(frame))


class ExitPathTest(unittest.TestCase):
    """An abnormal exit must not become a fatal-error dump or an exit 120."""

    def test_leaving_skips_finalization_and_survives_a_dead_stdout(self) -> None:
        exits: list[int] = []

        class _Broken:
            def flush(self) -> None:
                raise BrokenPipeError(32, "Broken pipe")

        with (
            mock.patch.object(os, "_exit", exits.append),
            mock.patch.object(sys, "stdout", _Broken()),
        ):
            mcp_server._leave(0)
        self.assertEqual([0], exits)

    def test_the_entry_point_leaves_rather_than_finalizing(self) -> None:
        # The stdin reader is a daemon parked in readline on every abnormal exit,
        # so ordinary finalization aborts on its buffered-reader lock. Read off the
        # source because the wiring is what fails, and a child process is the one
        # thing these tests may not spawn.
        source = pathlib.Path(mcp_server.__file__).read_text(encoding="utf-8")
        self.assertIn("_leave(main(sys.argv))", source)
        self.assertNotIn("sys.exit(main", source)

    def test_a_loop_that_raises_still_reports_a_clean_exit(self) -> None:
        # A non-zero exit is outside the promise even here, and stdin and stdout
        # are stood in for so the assertion does not depend on what the test
        # runner left in sys.stdin.
        streams = mock.Mock(buffer=io.BytesIO())
        with (
            mock.patch.object(mcp_server.AskServer, "run", side_effect=RuntimeError("boom")),
            mock.patch.object(sys, "stdin", streams),
            mock.patch.object(sys, "stdout", streams),
        ):
            self.assertEqual(0, mcp_server.main(["mcp_server.py"]))


class CancellationTest(unittest.TestCase):
    def test_a_cancellation_stops_the_poll_and_answers_once(self) -> None:
        # A single-step poll list is served repeatedly, so this holds at 204
        # until something aborts it.
        dashboard = _FakeDashboard(poll=[(204, None)])
        with mock.patch.object(mcp_server, "_open", dashboard), _Harness() as harness:
            harness.push(_call("c1", "Ship it?", ["ship", "hold"]))
            self.assertTrue(dashboard.polls.acquire(timeout=10.0))
            self.assertTrue(dashboard.polls.acquire(timeout=10.0))
            harness.push(
                {
                    "jsonrpc": "2.0",
                    "method": "notifications/cancelled",
                    "params": {"requestId": "c1", "reason": "user"},
                }
            )
            frames = harness.wait_for_frames(1)
            settled = dashboard.poll_count()
        self.assertEqual(1, len(frames))
        self.assertEqual("c1", frames[0]["id"])
        self.assertEqual(mcp_server.DECLINE_UNANSWERED, _text(frames[0]))
        # The poll stopped: nothing more went out after the frame was written.
        self.assertEqual(settled, dashboard.poll_count())

    def test_a_ping_is_answered_while_a_call_is_held(self) -> None:
        dashboard = _FakeDashboard(poll=[(204, None)])
        with mock.patch.object(mcp_server, "_open", dashboard), _Harness() as harness:
            harness.push(_call("c1", "Ship it?", ["ship", "hold"]))
            self.assertTrue(dashboard.polls.acquire(timeout=10.0))
            harness.push({"jsonrpc": "2.0", "id": "p", "method": "ping"})
            frames = harness.wait_for_frames(1)
            self.assertEqual(["p"], [frame["id"] for frame in frames])
            harness.push({"jsonrpc": "2.0", "method": "notifications/cancelled"})
            harness.wait_for_frames(2)

    def test_stdin_closing_aborts_an_outstanding_call(self) -> None:
        dashboard = _FakeDashboard(poll=[(204, None)])
        with mock.patch.object(mcp_server, "_open", dashboard):
            harness = _Harness()
            with harness:
                harness.push(_call("c1", "Ship it?", ["ship", "hold"]))
                self.assertTrue(dashboard.polls.acquire(timeout=10.0))
            # Leaving the block closes stdin and joins; the worker must not still
            # be polling a dashboard whose client has gone.
            self.assertEqual(1, len(harness.stdout.frames()))


class TransportGuardTest(unittest.TestCase):
    """The three guards, and that two of them have one implementation."""

    def test_the_guards_have_one_implementation(self) -> None:
        # SECURITY.md asserts these are implemented once. Read off the source
        # rather than inferred from behaviour, because a second copy that happens
        # to behave the same today is exactly what that claim rules out.
        source = pathlib.Path(mcp_server.__file__).read_text(encoding="utf-8")
        self.assertIn("import notify_hook", source)
        self.assertIs(notify_hook.is_loopback_url, vars(mcp_server)["notify_hook"].is_loopback_url)
        self.assertNotIn("LOOPBACK_HOSTS", source)
        self.assertNotIn("class _NoRedirects", source)

    def test_the_shared_loopback_check_refuses_the_lookalikes(self) -> None:
        for hostile in (
            "http://localhost.evil.com/api/ask",
            "http://localhost@evil.com/api/ask",
            "https://127.0.0.1/api/ask",
            "http://10.0.0.1/api/ask",
        ):
            self.assertFalse(notify_hook.is_loopback_url(hostile), hostile)

    def test_a_non_loopback_url_is_refused_before_any_request(self) -> None:
        with mock.patch.object(mcp_server, "_open") as opened:
            self.assertIsNone(mcp_server._request("http://evil.com/x", data=b"{}", timeout=1.0))
        opened.assert_not_called()

    def test_the_opener_disables_proxies_and_refuses_redirects(self) -> None:
        built: list[tuple[Any, ...]] = []

        class _Response:
            status = 200

            def __enter__(self) -> Self:
                return self

            def __exit__(self, *_exc: object) -> None:
                return None

            def read(self, _cap: int) -> bytes:
                return b"{}"

        def build_opener(*handlers: Any) -> Any:
            built.append(handlers)
            return mock.Mock(open=mock.Mock(return_value=_Response()))

        with mock.patch.object(urllib.request, "build_opener", build_opener):
            self.assertEqual(
                (200, b"{}"),
                mcp_server._request("http://127.0.0.1:4553/api/ask", data=b"{}", timeout=1.0),
            )
        proxies = [h for h in built[0] if isinstance(h, urllib.request.ProxyHandler)]
        self.assertEqual([{}], [getattr(handler, "proxies", None) for handler in proxies])
        self.assertIn(notify_hook._NoRedirects, built[0])

    def test_an_http_error_status_is_returned_rather_than_raised(self) -> None:
        def build_opener(*_handlers: Any) -> Any:
            error = urllib.error.HTTPError(
                "http://127.0.0.1:4553/x",
                503,
                "no",
                {},  # type: ignore[arg-type]
                io.BytesIO(b'{"state":"declined"}'),
            )
            return mock.Mock(open=mock.Mock(side_effect=error))

        with mock.patch.object(urllib.request, "build_opener", build_opener):
            answer = mcp_server._request("http://127.0.0.1:4553/x", data=None, timeout=1.0)
        self.assertIsNotNone(answer)
        assert answer is not None
        self.assertEqual(503, answer[0])

    def test_a_transport_failure_is_none_not_an_exception(self) -> None:
        def build_opener(*_handlers: Any) -> Any:
            return mock.Mock(open=mock.Mock(side_effect=urllib.error.URLError("refused")))

        with mock.patch.object(urllib.request, "build_opener", build_opener):
            self.assertIsNone(
                mcp_server._request("http://127.0.0.1:4553/x", data=None, timeout=1.0)
            )


class DiscoveryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.home = tempfile.TemporaryDirectory()
        self.addCleanup(self.home.cleanup)
        patch = mock.patch.dict(os.environ, {"COMPASS_HOME": self.home.name})
        patch.start()
        self.addCleanup(patch.stop)

    def _write(self, port: int, started: float) -> None:
        path = os.path.join(self.home.name, f"compass-{port}.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump({"pid": 1, "port": port, "started": started}, handle)

    def test_published_ports_come_back_newest_first(self) -> None:
        self._write(5000, 100.0)
        self._write(6000, 300.0)
        self._write(7000, 200.0)
        self.assertEqual((6000, 7000, 5000, mcp_server.DEFAULT_PORT), mcp_server.candidate_ports())

    def test_an_argument_port_is_preferred_and_never_duplicated(self) -> None:
        self._write(6000, 300.0)
        self.assertEqual((6000, mcp_server.DEFAULT_PORT), mcp_server.candidate_ports(["6000"]))

    def test_the_default_is_tried_even_with_no_state_file(self) -> None:
        self.assertEqual((mcp_server.DEFAULT_PORT,), mcp_server.candidate_ports())

    def test_a_corrupt_or_nonsense_state_file_is_skipped(self) -> None:
        for name, body in (
            ("compass-1.json", "{not json"),
            ("compass-2.json", "[]"),
            ("compass-3.json", json.dumps({"port": "8080"})),
            ("compass-4.json", json.dumps({"port": 99999})),
            ("compass-5.json", json.dumps({"port": True})),
        ):
            with open(os.path.join(self.home.name, name), "w", encoding="utf-8") as handle:
                handle.write(body)
        self.assertEqual((mcp_server.DEFAULT_PORT,), mcp_server.candidate_ports())

    def test_the_candidate_list_is_bounded(self) -> None:
        for index in range(12):
            self._write(5000 + index, float(index))
        self.assertEqual(mcp_server.MAX_CANDIDATE_PORTS, len(mcp_server.candidate_ports()))


class AttributionTest(unittest.TestCase):
    def test_the_measured_claude_variables_are_used(self) -> None:
        env = {
            "AI_AGENT": "claude-code_2-1-239_agent",
            "CLAUDE_CODE_SESSION_ID": "8a61f44c-13ae-45a1-84b6-fff4c17d10fa",
            "CLAUDE_PROJECT_DIR": "/repos/compass",
        }
        with mock.patch.dict(os.environ, env, clear=False):
            self.assertEqual(
                {
                    "harness": "claude",
                    "session_id": "8a61f44c-13ae-45a1-84b6-fff4c17d10fa",
                    "project": "/repos/compass",
                },
                mcp_server.attribution(),
            )

    def test_an_unmeasured_harness_never_invents_a_session_id(self) -> None:
        env = dict.fromkeys(("AI_AGENT", "CLAUDE_CODE_SESSION_ID", "CLAUDE_PROJECT_DIR"), "")
        with mock.patch.dict(os.environ, env, clear=False):
            attribution = mcp_server.attribution()
        self.assertEqual(mcp_server.UNKNOWN_HARNESS, attribution["harness"])
        self.assertNotIn("session_id", attribution)


class ContractTest(unittest.TestCase):
    """The caps here and the caps the dashboard enforces must not drift apart."""

    def _knob(self, name: str) -> Any:
        """One `ask_*` value off a built config.

        Built rather than read off the dataclass, because config.py sets these in
        its builder block and not as field defaults. Looked up by name and typed
        Any because config.py belongs to another lane; its absence is the failure
        this reports.
        """
        config = _config()
        self.assertTrue(hasattr(config, name), f"RuntimeConfig.{name} is missing")
        return getattr(config, name)

    def test_the_poll_timeout_outlasts_the_dashboards_own_hold(self) -> None:
        # A socket timeout under the dashboard's hold would abort every poll and
        # read as a dead dashboard.
        self.assertGreater(mcp_server.POLL_TIMEOUT_SEC, self._knob("ask_poll_timeout_sec"))
        self.assertGreater(mcp_server.OVERALL_DEADLINE_SEC, self._knob("ask_deadline_sec"))

    def test_the_text_caps_match_the_ingress(self) -> None:
        self.assertEqual(mcp_server.MAX_OPTIONS, self._knob("ask_max_options"))
        self.assertEqual(mcp_server.QUESTION_CAP_CHARS, self._knob("ask_question_cap_chars"))
        self.assertEqual(mcp_server.OPTION_CAP_CHARS, self._knob("ask_option_cap_chars"))
        self.assertEqual(mcp_server.BODY_CAP_BYTES, self._knob("ask_body_cap_bytes"))

    def test_the_advertised_schema_states_the_same_limits(self) -> None:
        schema = mcp_server.TOOL["inputSchema"]["properties"]
        self.assertEqual(mcp_server.QUESTION_CAP_CHARS, schema["question"]["maxLength"])
        self.assertEqual(mcp_server.OPTION_CAP_CHARS, schema["options"]["items"]["maxLength"])
        self.assertEqual(mcp_server.MAX_OPTIONS, schema["options"]["maxItems"])
        self.assertEqual(mcp_server.MIN_OPTIONS, schema["options"]["minItems"])

    def test_the_script_is_executable_like_every_other_edge_script(self) -> None:
        self.assertTrue(
            os.access(mcp_server.__file__, os.X_OK), f"{mcp_server.__file__} must be mode 755"
        )


if __name__ == "__main__":
    unittest.main()
