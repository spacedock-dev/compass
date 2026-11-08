"""A drift press from inside a session spends only on the person's own typed command.

The transcripts are Claude Code 2.1.318's records as `test_compass_skill_action` writes them from
the capture: the typed `/compass:compass` record, the `isMeta` skill body, a `command_permissions`
attachment, `last-prompt` records, then the agent's Bash call. A model that starts the skill itself
writes a Skill tool call and its result, never a prompt record.
"""

from __future__ import annotations

import contextlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any
from unittest import mock

from compass_runtime import http_api, observer, reading_long_preview, typed_press
from compass_runtime import io as runtime_io
from compass_runtime.config import build_runtime_config
from compass_runtime.state import build_runtime_state

from .test_compass_skill_action import CompassSession
from .test_history import isolated_environment, no_instance, run_one_shot_cli

if TYPE_CHECKING:
    from collections.abc import Iterator


class TypedPressCase(unittest.TestCase):
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
        self.path = root / "claude" / "projects" / "-work" / "session.jsonl"
        self.session = CompassSession(root / "work")
        self.session.prompt("Teach the parser about tabs.")

    def admit(self, action: str) -> str:
        return self.admitted(action)[0]

    def admitted(self, action: str) -> tuple[str, str]:
        self.session.save(self.path)
        return typed_press.admit(self.config, str(self.path), action)

    def typed(self, action: str) -> None:
        """The person types the command; the agent's Bash call is running when the press lands."""
        self.session.compass(action, stop=False)

    def machinery(self, kind: str) -> None:
        """Reuse the committed corpus fixtures, with no invented origin or scheduling fields.

        `test_claude.ClaudeInstructionTest` records the measured compaction flag;
        `test_compass_skill_action` and `test_delegated_work` carry the non-meta notification
        as a string and text blocks respectively. `records` documents the corpus derivation.
        """
        if kind == "compaction":
            self.session._text("compaction summary", isCompactSummary=True)
        elif kind == "notification-attachment":
            # Closed values from mid-turn-and-answer-shapes-2.1.305-macos.jsonl.
            self.session.queued("Background task completed.")
            self.session.rows[-1]["attachment"].update(
                commandMode="task-notification",
                origin={"kind": "task-notification", "producer": "session-task"},
            )
        else:
            text = (
                "<task-notification><task-id>b1</task-id>"
                "<status>completed</status></task-notification>"
            )
            if kind == "notification-string":
                self.session._text(text)
            else:
                self.session._entry("user", [{"type": "text", "text": text}])


MACHINERY = ("compaction", "notification-string", "notification-blocks", "notification-attachment")
ACTIONS = ("drift", "drift again", "monitor on", "summary", "summary update", "summary again")


class TypedPressTest(TypedPressCase):
    def test_a_persons_words_after_a_long_quoted_notification_still_revoke_consent(self) -> None:
        opening, closing = "<task-notification>", "</task-notification>"
        envelope = opening + "x" * (2000 - len(opening + closing)) + closing
        for action in ACTIONS:
            for blocks in (False, True):
                with self.subTest(action=action, blocks=blocks):
                    self.typed(action)
                    text = envelope + " Stop the reading and work on the lexer instead."
                    if blocks:
                        self.session._entry("user", [{"type": "text", "text": text}])
                    else:
                        self.session.prompt(text)
                    self.assertEqual(typed_press.REQUIRED, self.admit(action))

    def test_a_persons_command_survives_a_complete_long_notification(self) -> None:
        for action in ACTIONS:
            with self.subTest(action=action):
                self.typed(action)
                self.session._text("<task-notification>" + "x" * 2100 + "</task-notification>")
                self.assertEqual("", self.admit(action))

    def test_a_persons_image_beside_a_quoted_notification_revokes_consent(self) -> None:
        for action in ACTIONS:
            with self.subTest(action=action):
                self.typed(action)
                # Image block shape from test_mid_turn_directions and its capture.
                self.session._entry(
                    "user",
                    [
                        {"type": "text", "text": "<task-notification>example</task-notification>"},
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": "PRIVATE_IMAGE_BYTES",
                            },
                        },
                    ],
                )
                self.assertEqual(typed_press.REQUIRED, self.admit(action))

    def test_a_persons_message_sent_mid_turn_revokes_every_pending_action(self) -> None:
        for action in ACTIONS:
            with self.subTest(action=action):
                self.typed(action)
                self.session.queued("Stop the reading and work on the lexer instead.")
                self.machinery("notification-attachment")
                self.assertEqual(typed_press.REQUIRED, self.admit(action))

    def test_a_persons_prompt_that_quotes_harness_text_still_revokes_their_command(self) -> None:
        for action in ACTIONS:
            for text in (
                "This session is being continued from a previous conversation, but stop the reading.",
                "<task-notification>example</task-notification>\nStop the reading.",
                (
                    "<task-notification>first</task-notification> Stop the reading. "
                    "<task-notification>second</task-notification>"
                ),
                "<task-notification>example</task-notification>",
            ):
                for blocks in (False, True):
                    with self.subTest(action=action, text=text, blocks=blocks):
                        self.typed(action)
                        if blocks:
                            self.session._entry(
                                "user",
                                [
                                    {"type": "text", "text": text},
                                    {"type": "text", "text": "Stop the reading."},
                                ],
                            )
                        elif text == "<task-notification>example</task-notification>":
                            # An otherwise identical notification alone has no author discriminator.
                            continue
                        else:
                            self.session.prompt(text)
                        self.assertEqual(typed_press.REQUIRED, self.admit(action))

    def test_a_persons_pending_command_survives_known_harness_machinery(self) -> None:
        for action in ACTIONS:
            for kind in MACHINERY:
                with self.subTest(action=action, kind=kind):
                    self.typed(action)
                    self.machinery(kind)
                    self.assertEqual("", self.admit(action))
                    self.assertEqual(typed_press.REQUIRED, self.admit(action))

    def test_a_persons_later_prompt_revokes_every_pending_action_despite_machinery(self) -> None:
        for action in ACTIONS:
            for kind in MACHINERY:
                with self.subTest(action=action, kind=kind):
                    self.typed(action)
                    self.machinery(kind)
                    self.session.prompt("Now fix the lexer, then explain <task-notification>.")
                    self.machinery(kind)
                    self.assertEqual(typed_press.REQUIRED, self.admit(action))

    def test_a_person_can_type_the_closed_action_names_in_any_letter_case(self) -> None:
        for action in ACTIONS:
            for spelling in (action.upper(), action.title(), "  " + action.title() + "  "):
                with self.subTest(action=action, spelling=spelling):
                    self.typed(spelling)
                    self.assertEqual("", self.admit(action))

    def test_a_persons_paraphrase_never_authorizes_a_closed_action(self) -> None:
        for action, paraphrase in zip(
            ACTIONS,
            (
                "check drift",
                "drift once more",
                "start monitor",
                "summarize",
                "update summary",
                "redo summary",
            ),
            strict=True,
        ):
            with self.subTest(action=action):
                self.typed(paraphrase)
                self.assertEqual(typed_press.REQUIRED, self.admit(action))

    def test_a_person_summary_command_authorizes_only_its_exact_action_once(self) -> None:
        actions = ("summary", "summary update", "summary again")
        for typed in actions:
            for requested in actions:
                with self.subTest(typed=typed, requested=requested):
                    self.typed(typed)
                    self.assertEqual(
                        "" if typed == requested else typed_press.REQUIRED, self.admit(requested)
                    )
                    if typed == requested:
                        self.assertEqual(typed_press.REQUIRED, self.admit(requested))

    def test_a_person_who_types_drift_gets_one_press(self) -> None:
        self.typed("drift")
        self.assertEqual("", self.admit("drift"))

    def test_a_person_who_types_drift_again_gets_one_press_of_either_kind(self) -> None:
        self.typed("drift again")
        self.assertEqual("", self.admit("drift again"))
        self.typed("drift again")
        self.assertEqual("", self.admit("drift"))

    def test_the_same_typed_command_never_pays_for_a_second_press(self) -> None:
        self.typed("drift again")
        self.assertEqual("", self.admit("drift again"))
        for action in ("drift again", "drift"):
            with self.subTest(action=action):
                self.assertEqual(typed_press.REQUIRED, self.admit(action))

    def test_the_once_holds_across_a_restart_of_the_dashboard(self) -> None:
        self.typed("drift")
        self.assertEqual("", self.admit("drift"))
        typed = [
            row["uuid"]
            for row in self.session.rows
            if str(row.get("message", {}).get("content", "")).startswith("<command-message>")
        ]
        self.assertIn(typed[-1], typed_press.store_path(self.config).read_text())
        self.assertEqual(typed_press.REQUIRED, self.admit("drift"))

    def test_a_model_that_starts_the_skill_itself_cannot_spend(self) -> None:
        self.session.model_started_compass("Keep going with the parser.")
        self.assertEqual(typed_press.REQUIRED, self.admit("drift"))
        self.assertEqual(typed_press.REQUIRED, self.admit("drift again"))

    def test_drift_again_is_refused_after_a_person_typed_plain_drift(self) -> None:
        # A stored reading makes plain `drift` free; only the person can ask to spend over it.
        self.typed("drift")
        self.assertEqual(typed_press.REQUIRED, self.admit("drift again"))

    def test_a_person_s_later_prompt_ends_what_their_typed_command_allowed(self) -> None:
        self.typed("drift again")
        self.session.prompt("Now fix the lexer.")
        self.assertEqual(typed_press.REQUIRED, self.admit("drift again"))

    def test_another_compass_action_or_another_skill_allows_no_press(self) -> None:
        self.typed("sessions")
        self.assertEqual(typed_press.REQUIRED, self.admit("drift"))
        self.session.skill("other:skill", "drift again")
        self.assertEqual(typed_press.REQUIRED, self.admit("drift again"))

    def test_the_command_typed_in_a_subagent_or_as_meta_allows_no_press(self) -> None:
        self.typed("drift again")
        for marks in ({"isSidechain": True}, {"isMeta": True}):
            with self.subTest(marks=marks):
                rows = [row for row in self.session.rows if "<command-message>" in str(row)]
                for row in rows:
                    row.update(marks)
                self.assertEqual(typed_press.REQUIRED, self.admit("drift again"))
                for row in rows:
                    for key in marks:
                        row.pop(key)

    def test_an_unreadable_transcript_is_refused_rather_than_guessed(self) -> None:
        self.typed("drift")
        self.assertEqual(
            typed_press.UNCONFIRMED, typed_press.admit(self.config, str(self.path), "drift")[0]
        )
        self.assertEqual(typed_press.UNCONFIRMED, typed_press.admit(self.config, None, "drift")[0])

    def test_a_store_that_cannot_be_read_refuses_rather_than_spend_twice(self) -> None:
        self.typed("drift")
        store = typed_press.store_path(self.config)
        store.parent.mkdir(parents=True, exist_ok=True)
        store.write_text("not json", encoding="utf-8")
        self.assertEqual(typed_press.UNCONFIRMED, self.admit("drift"))

    def test_a_person_whose_press_was_refused_downstream_can_press_again_on_that_command(
        self,
    ) -> None:
        self.typed("drift again")
        reason, uuid = self.admitted("drift again")
        self.assertEqual("", reason)
        typed_press.release(self.config, uuid)
        self.assertEqual("", self.admit("drift again"))
        self.assertEqual(typed_press.REQUIRED, self.admit("drift again"))

    def test_a_board_that_cannot_lock_the_store_refuses_rather_than_admit_twice(self) -> None:
        # Unlocked, two presses could both read the store before either wrote it; a reviewer
        # reproduced four of four admitted on one typed record with the lock unsupported.
        @contextlib.contextmanager
        def unsupported(*_args: object, **_kwargs: object) -> Iterator[str]:
            yield runtime_io.LOCK_UNSUPPORTED

        self.typed("drift")
        with mock.patch.object(runtime_io, "held_file_lock", unsupported):
            self.assertEqual(typed_press.UNCONFIRMED, self.admit("drift"))
        self.assertEqual("", self.admit("drift"))

    def test_forget_keeps_the_commands_a_person_already_paid_for(self) -> None:
        # The record guards the spend, as the spend timestamps do, and holds no words.
        root = self.path.parents[3]
        environ = isolated_environment(str(root / "state"), str(root))
        config = build_runtime_config(
            environ=environ, platform_name="linux", os_name="posix", launcher_path=root / "x.py"
        )
        self.typed("drift")
        self.session.save(self.path)
        self.assertEqual("", typed_press.admit(config, str(self.path), "drift")[0])
        with no_instance(), mock.patch.object(runtime_io, "diag"):
            run_one_shot_cli(["--forget"], environ)
        self.assertTrue(typed_press.store_path(config).exists())
        self.assertEqual(
            typed_press.REQUIRED, typed_press.admit(config, str(self.path), "drift")[0]
        )

    def test_a_tail_that_cuts_a_line_reads_only_whole_records(self) -> None:
        self.typed("drift")
        self.session.save(self.path)
        size = self.path.stat().st_size
        lines = typed_press.tail_lines(str(self.path), limit=size - 10)
        assert lines is not None
        for line in lines:
            json.loads(line)


class ReadingRouteTest(TypedPressCase):
    """The reading route asks the guard only for a press the client marked as from a session."""

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
            # What `_reading_press` does once a job has started, or leaves undone on a refusal.
            if starts:
                handler._press_started = True

        handler._reading_press = mock.Mock(side_effect=reading_press)
        return handler

    def press(self, *, starts: bool = True, **fields: Any) -> Any:
        self.session.save(self.path)
        handler = self.handler(starts=starts)
        body = {"harness": "claude", "sid": "abc", "press": True, "observer_model": 1, **fields}
        with mock.patch.object(observer, "resolve_transcript", return_value=str(self.path)):
            handler._reading_dispatch(body)
        return handler

    def refused_with(self, handler: Any) -> str:
        handler._reading_press.assert_not_called()
        payload, _kind, status = handler._send.call_args.args
        self.assertEqual(409, status)
        answer = json.loads(payload)
        self.assertEqual((False, False), (answer["ok"], answer["produced"]))
        return str(answer["reason"])

    def test_a_typed_press_reaches_the_page_s_press(self) -> None:
        self.typed("drift")
        self.press(typed_action="drift")._reading_press.assert_called_once()

    def test_a_persons_drift_press_survives_machinery_and_a_later_prompt_revokes_it(self) -> None:
        for action in ("drift", "drift again"):
            for kind in MACHINERY:
                with self.subTest(action=action, kind=kind):
                    self.typed(action.title())
                    self.machinery(kind)
                    self.press(typed_action=action)._reading_press.assert_called_once()
                    self.typed(action)
                    self.session.prompt("Work on the lexer instead.")
                    self.machinery(kind)
                    self.refused_with(self.press(typed_action=action))

    def test_a_person_cannot_pay_for_a_long_reading_through_a_typed_action(self) -> None:
        for action in ("drift", "drift again"):
            for typed in (False, True):
                with self.subTest(action=action, typed=typed):
                    if typed:
                        self.typed(action)
                    else:
                        self.session.prompt("Keep working on the lexer.")
                    fields: dict[str, Any] = {
                        "mode": "long",
                        "plan_binding": "a" * 64,
                        "expected_revision": 1,
                        "provider": "claude",
                        "destination": "local-cli",
                        "model": "sonnet",
                        "words_destination": "local-cli",
                        "typed_action": action,
                    }
                    self.assertTrue(
                        reading_long_preview.valid_ingress(
                            {
                                "harness": "claude",
                                "sid": "abc",
                                **fields,
                            }
                        )
                    )
                    with (
                        mock.patch.object(reading_long_preview, "describe", return_value={}),
                        mock.patch.object(reading_long_preview, "changed", return_value=False),
                        mock.patch.object(
                            reading_long_preview, "_published", return_value=(None, None)
                        ),
                        mock.patch.object(typed_press, "admit") as admission,
                    ):
                        handler = self.press(**fields)
                    handler._reading_press.assert_not_called()
                    handler._reject.assert_called_once_with(400)
                    admission.assert_not_called()

    def test_an_untyped_press_from_a_session_is_refused_before_anything_is_spent(self) -> None:
        self.session.model_started_compass("Keep going.")
        self.assertEqual(typed_press.REQUIRED, self.refused_with(self.press(typed_action="drift")))

    def test_the_second_press_on_one_typed_command_is_refused(self) -> None:
        self.typed("drift again")
        self.press(typed_action="drift again")._reading_press.assert_called_once()
        handler = self.press(typed_action="drift again")
        self.assertEqual(typed_press.REQUIRED, self.refused_with(handler))

    def test_a_press_refused_downstream_leaves_the_typed_command_for_a_retry(self) -> None:
        # The daily cap, a pause, consent, a changed revision or a reading already running.
        self.typed("drift again")
        self.press(typed_action="drift again", starts=False)._reading_press.assert_called_once()
        self.press(typed_action="drift again")._reading_press.assert_called_once()
        handler = self.press(typed_action="drift again")
        self.assertEqual(typed_press.REQUIRED, self.refused_with(handler))

    def test_a_press_that_fails_on_the_way_leaves_the_typed_command_for_a_retry(self) -> None:
        self.typed("drift")
        self.session.save(self.path)
        handler = self.handler(starts=False)
        handler._reading_press.side_effect = RuntimeError("no thread")
        body = {"harness": "claude", "sid": "abc", "press": True, "typed_action": "drift"}
        with (
            mock.patch.object(observer, "resolve_transcript", return_value=str(self.path)),
            self.assertRaises(RuntimeError),
        ):
            handler._reading_dispatch(body)
        self.press(typed_action="drift")._reading_press.assert_called_once()

    def test_a_press_from_a_shell_or_the_page_is_unaffected(self) -> None:
        self.session.model_started_compass("Keep going.")
        self.press()._reading_press.assert_called_once()

    def test_a_person_asking_for_a_summary_cannot_pay_for_a_drift_reading_instead(self) -> None:
        for command in ("summary", "summary update", "summary again"):
            self.typed(command)
            handler = self.press(typed_action=command)
            handler._reject.assert_called_once_with(400)
            handler._reading_press.assert_not_called()

    def test_an_action_the_skill_does_not_have_is_refused_as_malformed(self) -> None:
        self.typed("drift")
        handler = self.press(typed_action="sessions")
        handler._reject.assert_called_once_with(400)
        handler._reading_press.assert_not_called()


class MonitorRouteTest(TypedPressCase):
    def test_a_persons_monitor_command_survives_machinery_and_a_later_prompt_revokes_it(
        self,
    ) -> None:
        for kind in MACHINERY:
            with self.subTest(kind=kind):
                self.typed("Monitor On")
                self.machinery(kind)
                self.press().admission.assert_called_once()
                self.typed("monitor on")
                self.session.prompt("Work on the lexer instead.")
                self.machinery(kind)
                self.press().admission.assert_not_called()

    def press(
        self, *, accepted: bool = True, failure: Exception | None = None, **fields: Any
    ) -> Any:
        self.session.save(self.path)
        handler: Any = object.__new__(http_api._RequestHandler)
        handler.server = SimpleNamespace(
            application=SimpleNamespace(
                config=self.config, state=build_runtime_state(self.config, started=0)
            )
        )
        handler._send = mock.Mock()
        handler._reject = mock.Mock()
        handler._is_document_navigation = mock.Mock(return_value=False)
        handler._loopback_resource_ok = mock.Mock(return_value=True)
        body = json.dumps(
            {
                "harness": "claude",
                "sid": "one",
                "tab_id": "terminal-one",
                "action": "start",
                "holder_kind": "terminal",
                "observer_model": 1,
                "typed_action": "monitor on",
                **fields,
            }
        ).encode()
        handler.headers = {"Content-Length": str(len(body))}
        handler._read_body = mock.Mock(return_value=body)
        with (
            mock.patch.object(observer, "resolve_transcript", return_value=str(self.path)),
            mock.patch.object(http_api, "_live_leases"),
            mock.patch.object(
                http_api, "_lease_answer", return_value={"ok": accepted}, side_effect=failure
            ) as start,
        ):
            handler._live_monitor()
        handler.admission = start
        return handler

    def test_a_person_who_types_monitor_on_admits_exactly_one_run(self) -> None:
        self.typed("monitor on")
        self.press().admission.assert_called_once()
        self.press().admission.assert_not_called()

    def test_a_model_started_monitor_never_admits_a_lease(self) -> None:
        self.session.model_started_compass("Keep going.")
        self.press().admission.assert_not_called()

    def test_a_person_s_refused_monitor_can_retry_the_same_typed_command(self) -> None:
        self.typed("monitor on")
        self.press(accepted=False).admission.assert_called_once()
        self.press().admission.assert_called_once()
        self.press().admission.assert_not_called()

    def test_a_person_s_beat_and_stop_consume_no_command(self) -> None:
        self.typed("monitor on")
        self.press(action="beat").admission.assert_called_once()
        self.press(action="stop").admission.assert_called_once()
        self.press().admission.assert_called_once()

    def test_a_person_s_failed_admission_releases_the_typed_command(self) -> None:
        self.typed("monitor on")
        with self.assertRaises(RuntimeError):
            self.press(failure=RuntimeError("cannot start ticker"))
        self.press().admission.assert_called_once()
        self.press().admission.assert_not_called()


class SummaryRouteTest(TypedPressCase):
    def test_a_persons_summary_command_survives_machinery_and_a_later_prompt_revokes_it(
        self,
    ) -> None:
        for action, command in (
            ("start", "summary"),
            ("update", "summary update"),
            ("rerun", "summary again"),
        ):
            for kind in MACHINERY:
                with self.subTest(action=action, kind=kind):
                    self.typed(command.title())
                    self.machinery(kind)
                    self.press(action)._summary_start.assert_called_once()
                    self.typed(command)
                    self.session.prompt("Work on the lexer instead.")
                    self.machinery(kind)
                    self.press(action)._summary_start.assert_not_called()

    def press(self, action: str, *, starts: bool = True, typed: str | None = None) -> Any:
        self.session.save(self.path)
        handler: Any = object.__new__(http_api._RequestHandler)
        handler.server = SimpleNamespace(
            application=SimpleNamespace(
                config=self.config, state=build_runtime_state(self.config, started=0)
            )
        )
        handler._reject, handler._send = mock.Mock(), mock.Mock()
        body = {
            "harness": "claude",
            "sid": "abc",
            "action": action,
            "origin": "press",
            "typed_action": typed
            or {"start": "summary", "update": "summary update", "rerun": "summary again"}[action],
        }
        handler._summary_payload = mock.Mock(return_value=body)

        def start(_body: Any) -> None:
            handler._summary_started = starts

        handler._summary_start = mock.Mock(side_effect=start)
        with mock.patch.object(observer, "resolve_transcript", return_value=str(self.path)):
            handler._summary()
        return handler

    def test_a_person_gets_one_matching_summary_spend_and_a_refusal_keeps_the_command(self) -> None:
        for action, command in (
            ("start", "summary"),
            ("update", "summary update"),
            ("rerun", "summary again"),
        ):
            self.typed(command)
            self.press(action, starts=False)._summary_start.assert_called_once()
            self.press(action)._summary_start.assert_called_once()
            self.press(action)._summary_start.assert_not_called()

    def test_a_person_without_a_typed_command_spends_nothing_and_plain_summary_cannot_rerun(
        self,
    ) -> None:
        self.session.model_started_compass("Keep working.")
        self.press("start")._summary_start.assert_not_called()
        self.typed("summary")
        self.press("rerun")._summary_start.assert_not_called()
        handler = self.press("rerun", typed="summary")
        handler._reject.assert_called_once_with(400)
        handler._summary_start.assert_not_called()
