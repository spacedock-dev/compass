"""A drift press from inside a Codex session spends only on the person's own typed command.

The rollout rows are the committed exec capture's two user-message shapes (`captured_messages`,
`docs/captures/codex/skill-action-shapes-0.167.0-macos.jsonl`), with ids and text filled in. The
capture holds shape only, so a message id and a turn id are placeholders here and the guard is
held to what the shapes establish: a whole typed `$compass <action>`, provenance `user`, a
timestamp, and nothing typed after it.
"""

from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest import mock

from compass_runtime import http_api, observer, typed_press
from compass_runtime.config import build_runtime_config
from compass_runtime.state import build_runtime_state

from .test_codex_compass_action import CAPTURE, NOW, captured_image_messages, captured_messages

START = "2026-11-08T12:00:00Z"


def injected() -> dict[str, Any]:
    """The capture's harness-injected project instructions: a user-role message, not the person's."""
    for line in CAPTURE.read_text(encoding="utf-8").splitlines():
        record = copy.deepcopy(json.loads(line)["record"])
        meta = record["payload"].get("internal_chat_message_metadata_passthrough") or {}
        kinds = [m["provenance"]["type"] for m in meta.get("content_item_metadata", [])]
        if record["type"] == "response_item" and kinds == ["agents_md"]:
            record["payload"]["content"][0]["text"] = "Project instructions."
            record["timestamp"] = START
            return dict(record)
    raise AssertionError("capture must hold the injected project instructions")


def said(text: str, *, turn: str, message: str, second: int = 10) -> dict[str, Any]:
    """The person's user message, as the capture's `response_item` shape, ids filled."""
    record = captured_messages(text, command=text.startswith("$compass "), second=second)[0]
    assert record["type"] == "response_item"
    record["payload"]["id"] = message
    record["payload"]["internal_chat_message_metadata_passthrough"]["turn_id"] = turn
    return record


class CodexTypedPressCase(unittest.TestCase):
    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        self.config = build_runtime_config(
            environ={"HOME": str(root), "COMPASS_HOME": str(root / "state")},
            platform_name="linux",
            os_name="posix",
            launcher_path=root / "server.py",
        )
        self.path = root / "rollout.jsonl"
        self.enterContext(
            mock.patch.object(typed_press, "time", return_value=NOW + 30, create=True)
        )
        self.rows: list[dict[str, Any]] = [injected()]
        self.say("Teach the parser about tabs.", turn="t0", message="m0", second=1)

    def say(self, text: str, *, turn: str = "t1", message: str = "m1", second: int = 10) -> None:
        self.rows.append(said(text, turn=turn, message=message, second=second))

    def save(self) -> str:
        self.path.write_text("\n".join(json.dumps(r) for r in self.rows) + "\n", encoding="utf-8")
        return str(self.path)

    def admitted(self, action: str) -> tuple[str, str]:
        return typed_press.admit(self.config, self.save(), action, "codex")

    def admit(self, action: str) -> str:
        return self.admitted(action)[0]

    def agent_works(self) -> None:
        """What the agent writes after the typed command: its own call and output."""
        for kind in ("function_call", "function_call_output"):
            self.rows.append(
                {
                    "timestamp": "2026-11-08T12:00:11Z",
                    "type": "response_item",
                    "payload": {"type": kind, "call_id": "c1"},
                }
            )


class APersonsTypedCodexCommandTest(CodexTypedPressCase):
    def test_a_person_who_types_drift_gets_one_press(self) -> None:
        self.say("$compass drift")
        self.agent_works()
        self.assertEqual("", self.admit("drift"))
        self.assertEqual(typed_press.REQUIRED, self.admit("drift"))

    def test_a_person_who_types_drift_again_gets_one_press_of_either_kind(self) -> None:
        for action in ("drift again", "drift"):
            with self.subTest(action=action):
                self.rows = [injected()]
                self.say(
                    "$compass  Drift   AGAIN",
                    turn=f"t-{action.replace(' ', '-')}",
                    message="m-again",
                )
                self.assertEqual("", self.admit(action))

    def test_a_person_who_typed_plain_drift_cannot_pay_for_drift_again(self) -> None:
        self.say("$compass drift")
        self.assertEqual(typed_press.REQUIRED, self.admit("drift again"))

    def test_the_press_a_refused_start_gave_back_can_be_asked_again(self) -> None:
        self.say("$compass drift")
        reason, uuid = self.admitted("drift")
        self.assertEqual("", reason)
        typed_press.release(self.config, uuid)
        self.assertEqual("", self.admit("drift"))

    def test_an_agent_that_runs_the_skill_on_its_own_cannot_spend(self) -> None:
        self.agent_works()
        self.assertEqual(typed_press.REQUIRED, self.admit("drift"))
        self.assertEqual(typed_press.REQUIRED, self.admit("drift again"))

    def test_a_persons_prose_naming_the_command_cannot_spend(self) -> None:
        self.say("Please finish, then use $compass drift to check it.")
        self.assertEqual(typed_press.REQUIRED, self.admit("drift"))

    def test_a_persons_other_compass_action_cannot_pay_for_a_reading(self) -> None:
        self.say("$compass sessions waiting")
        self.assertEqual(typed_press.REQUIRED, self.admit("drift"))

    def test_a_persons_later_message_ends_what_their_typed_command_allowed(self) -> None:
        self.say("$compass drift")
        self.say("Now also handle tabs in strings.", turn="t2", message="m2", second=20)
        self.assertEqual(typed_press.REQUIRED, self.admit("drift"))

    def test_a_persons_typed_command_survives_the_harness_s_own_injected_message(self) -> None:
        self.say("$compass drift")
        late = injected()
        late["timestamp"] = "2026-11-08T12:00:12Z"
        self.rows.append(late)
        self.assertEqual("", self.admit("drift"))

    def test_the_harness_s_added_context_after_the_command_does_not_end_it(self) -> None:
        # The image capture's first message carries project instructions and harness context.
        self.say("$compass drift")
        late = injected()
        late["payload"]["internal_chat_message_metadata_passthrough"]["content_item_metadata"] = [
            {"provenance": {"type": "agents_md"}},
            {"provenance": {"type": "harness", "hook": False}},
        ]
        self.rows.append(late)
        self.assertEqual("", self.admit("drift"))

    def test_a_message_that_mixes_the_persons_words_with_harness_context_ends_it(self) -> None:
        self.say("$compass drift")
        mixed = said("Also handle tabs.", turn="t2", message="m2", second=20)
        mixed["payload"]["internal_chat_message_metadata_passthrough"]["content_item_metadata"] = [
            {"provenance": {"type": "harness", "hook": False}},
            {"provenance": {"type": "user"}},
        ]
        self.rows.append(mixed)
        self.assertEqual(typed_press.REQUIRED, self.admit("drift"))

    def test_a_message_of_unknown_provenance_after_the_command_ends_it(self) -> None:
        self.say("$compass drift")
        stranger = said("Do something else.", turn="t2", message="m2", second=20)
        meta = stranger["payload"]["internal_chat_message_metadata_passthrough"]
        meta["content_item_metadata"] = [{"provenance": {"type": "something_new"}}]
        self.rows.append(stranger)
        self.assertEqual(typed_press.REQUIRED, self.admit("drift"))

    def test_a_typed_command_without_a_user_provenance_cannot_spend(self) -> None:
        self.say("$compass drift")
        meta = self.rows[-1]["payload"]["internal_chat_message_metadata_passthrough"]
        meta["content_item_metadata"] = []
        self.assertEqual(typed_press.REQUIRED, self.admit("drift"))

    def test_a_typed_command_with_no_message_or_turn_id_cannot_spend(self) -> None:
        for field in ("id", "turn_id"):
            with self.subTest(field=field):
                self.rows = [injected()]
                self.say("$compass drift")
                payload = self.rows[-1]["payload"]
                if field == "id":
                    payload["id"] = ""
                else:
                    payload["internal_chat_message_metadata_passthrough"]["turn_id"] = ""
                self.assertEqual(typed_press.REQUIRED, self.admit("drift"))

    def test_a_typed_command_older_than_a_day_or_with_no_time_cannot_spend(self) -> None:
        self.say("$compass drift")
        self.rows[-1]["timestamp"] = "2026-11-06T12:00:00Z"
        self.assertEqual(typed_press.REQUIRED, self.admit("drift"))
        self.rows[-1]["timestamp"] = "yesterday"
        self.assertEqual(typed_press.REQUIRED, self.admit("drift"))

    def test_a_typed_command_beside_an_image_is_still_the_persons_command(self) -> None:
        for row in captured_image_messages("$compass drift"):
            if row["type"] == "response_item":
                row["payload"]["id"] = "m-img"
                row["payload"]["internal_chat_message_metadata_passthrough"]["turn_id"] = "t-img"
                self.rows.append(row)
        self.assertEqual("", self.admit("drift"))

    def test_a_claude_transcript_shape_never_backs_a_codex_press(self) -> None:
        self.rows = [
            {
                "type": "user",
                "uuid": "u1",
                "timestamp": START,
                "message": {
                    "role": "user",
                    "content": (
                        "<command-message>compass</command-message>"
                        "<command-name>/compass:compass</command-name>"
                        "<command-args>drift</command-args>"
                    ),
                },
            }
        ]
        self.assertEqual(typed_press.REQUIRED, self.admit("drift"))

    def test_an_unreadable_rollout_is_refused_rather_than_guessed(self) -> None:
        self.assertEqual(
            (typed_press.UNCONFIRMED, ""),
            typed_press.admit(self.config, str(self.path.parent / "gone.jsonl"), "drift", "codex"),
        )

    def test_a_codex_command_and_a_claude_command_never_share_a_spent_id(self) -> None:
        self.say("$compass drift")
        _reason, uuid = self.admitted("drift")
        self.assertTrue(uuid.startswith("codex:"))


class ACodexPressRouteTest(CodexTypedPressCase):
    """The reading route asks the guard for a Codex press the client marked as from a session."""

    def handler(self, *, starts: bool) -> Any:
        handler: Any = object.__new__(http_api._RequestHandler)
        state = build_runtime_state(self.config, started=0.0)
        handler.server = SimpleNamespace(
            application=SimpleNamespace(config=self.config, state=state), server_port=12345
        )
        handler._send = mock.Mock()
        handler._reject = mock.Mock()
        handler._reading_refusal = mock.Mock(return_value=None)

        def reading_press(*_args: object) -> None:
            if starts:
                handler._press_started = True

        handler._reading_press = mock.Mock(side_effect=reading_press)
        return handler

    def press(self, *, starts: bool = True, **fields: Any) -> Any:
        self.save()
        handler = self.handler(starts=starts)
        body = {"harness": "codex", "sid": "abc", "press": True, "observer_model": 1, **fields}
        with mock.patch.object(
            observer, "resolve_transcript", return_value=str(self.path)
        ) as found:
            handler._reading_dispatch(body)
        found.assert_called_once()
        self.assertEqual(("codex", "abc"), found.call_args.args[2:])
        return handler

    def reason(self, handler: Any) -> str:
        handler._reading_press.assert_not_called()
        payload, _kind, status = handler._send.call_args.args
        self.assertEqual(409, status)
        return str(json.loads(payload)["reason"])

    def test_a_person_s_typed_codex_command_reaches_the_press_once(self) -> None:
        self.say("$compass drift")
        self.press(typed_action="drift")._reading_press.assert_called_once()
        self.assertEqual(typed_press.REQUIRED, self.reason(self.press(typed_action="drift")))

    def test_an_agent_s_own_codex_press_is_refused_before_anything_is_spent(self) -> None:
        self.agent_works()
        self.assertEqual(typed_press.REQUIRED, self.reason(self.press(typed_action="drift again")))

    def test_a_codex_press_refused_downstream_leaves_the_command_for_a_retry(self) -> None:
        self.say("$compass drift")
        self.press(typed_action="drift", starts=False)
        self.press(typed_action="drift")._reading_press.assert_called_once()

    def test_a_person_cannot_pay_for_a_long_codex_reading_through_a_typed_action(self) -> None:
        self.say("$compass drift")
        self.save()
        handler = self.handler(starts=True)
        body = {
            "harness": "codex",
            "sid": "abc",
            "press": True,
            "observer_model": 1,
            "typed_action": "drift",
            "mode": "long",
        }
        handler._reading_dispatch(body)
        handler._reading_press.assert_not_called()

    def test_a_press_for_another_harness_is_unconfirmed_and_spends_nothing(self) -> None:
        self.say("$compass drift")
        self.save()
        handler = self.handler(starts=True)
        handler._reading_dispatch(
            {
                "harness": "pi",
                "sid": "abc",
                "press": True,
                "observer_model": 1,
                "typed_action": "drift",
            }
        )
        handler._reading_press.assert_not_called()
        self.assertEqual(typed_press.UNCONFIRMED, self.reason(handler))
