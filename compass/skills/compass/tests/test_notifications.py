from __future__ import annotations

import dataclasses
import http.client
import http.server
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar
from unittest import mock

from compass_runtime import (
    aggregate,
    claude_data,
    departures,
    dismissals,
    notifications,
    records,
    unasked,
)
from compass_runtime import events as runtime_events
from compass_runtime import sessions as runtime_sessions

from .support import (
    HOOK_PATH,
    REFUSED_NOTIFICATIONS,
    REGISTRY,
    RuntimeTestCase,
    collect,
    collect_claude,
    config_patch,
    dashboard_hook,
    forbid_native_notifications,
    is_native_notification,
    make_config,
    make_runtime,
    make_server,
    notifier_binaries,
    notify_handler,
    poll_fast,
    runtime,
    serve_until_closed,
    short_circuit_native_notifications,
    state_of,
    store_patch,
)

if TYPE_CHECKING:
    import email.message


def _claude_application(
    config: Any,
    state: Any,
    *,
    now: float,
    popups: list[Any],
) -> aggregate.Application:
    """An application over the registry's own Claude row, recording its popups.

    Collections go through this rather than the collector alone, because since
    DRC-4192 the collector raises no popup: the decision is taken once per
    collection, over rows whose overlays have already been applied.
    """
    spec = next(s for s in REGISTRY if s.key == "claude")
    return aggregate.Application(
        config,
        state,
        (spec,),
        native_notifier=lambda _platform: "osascript",
        popup_notifier=lambda title, message: popups.append((title, message)),
        diagnostic_sink=lambda _line: None,
        clock=lambda: now,
    )


class CompassServerTest(RuntimeTestCase):
    def test_popup_caches_are_bounded_and_globally_rate_limited(self) -> None:
        with (
            config_patch(max_cache_entries=2),
            # session2 lands inside the 15s global floor and is dropped;
            # session3 lands after it and fires.
            mock.patch.object(time, "time", side_effect=[100.0, 101.0, 120.0]),
        ):
            config, state = runtime()
            fired: list[tuple[str, str]] = []

            def notifier(title: str, message: str) -> None:
                fired.append((title, message))

            for sid, detail in (("session1", "one"), ("session2", "two"), ("session3", "three")):
                notifications.maybe_popup(
                    config,
                    state,
                    notifications.PopupSubject(
                        harness="claude", label="Claude", prefix=sid, activity=0.0
                    ),
                    "needs_input",
                    detail,
                    popup_notifier=notifier,
                )

        self.assertEqual(2, len(fired))
        self.assertLessEqual(len(state_of().last_session_state), 2)
        self.assertLessEqual(len(state_of().last_popup), 2)

    def test_hook_popups_respect_both_cooldown_floors(self) -> None:
        # Every existing cooldown test expires the floors first to isolate some
        # other rule, so the two floors themselves went unpinned. Distinct
        # messages here keep the repeat-suppression window out of the result.
        config, state = runtime()
        fired: list[str] = []

        def payload(sid: str, message: str, now: float) -> dict[str, Any]:
            return notifications.handle_payload(
                config,
                state,
                {"session_id": sid, "message": message},
                now=now,
                popup_notifier=lambda _title, body: fired.append(body),
            )

        # Same session inside the 60s per-session cooldown, but past the 15s
        # global floor, so only the per-session rule can stop the second one.
        # A 1s gap here would prove nothing: the global floor would mask it.
        payload("aaaaaaaa", "permission one", 1000.0)
        payload("aaaaaaaa", "permission two", 1000.0 + config.global_popup_cooldown_sec + 1)
        self.assertEqual(["permission one"], fired)
        payload("aaaaaaaa", "permission three", 1000.0 + config.popup_cooldown_sec)
        self.assertEqual(["permission one", "permission three"], fired)

        # A different session has its own cooldown key, so only the 15s global
        # floor can stop it.
        fired.clear()
        base = 5000.0
        payload("bbbbbbbb", "b one", base)
        payload("cccccccc", "c one", base + 1)
        self.assertEqual(["b one"], fired)
        payload("dddddddd", "d one", base + config.global_popup_cooldown_sec)
        self.assertEqual(["b one", "d one"], fired)

    def test_hook_popup_runs_with_the_hook_lock_released(self) -> None:
        # hook_lock is a plain Lock. Notifying inside the critical section would
        # hold it for the notifier's whole duration -- up to osascript's 5s
        # timeout -- stalling every other hook POST and every collection.
        config, state = runtime()
        held: list[bool] = []

        def notifier(_title: str, _message: str) -> None:
            acquired = state.hook_lock.acquire(blocking=False)
            held.append(acquired)
            if acquired:
                state.hook_lock.release()

        notifications.handle_payload(
            config,
            state,
            {"session_id": "eeeeeeee", "message": "permission needed"},
            now=9000.0,
            popup_notifier=notifier,
        )
        self.assertEqual([True], held, "popup fired while still holding hook_lock")

    def _post_notify(self, port: int, body: dict[str, Any]) -> bytes:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
        conn.request(
            "POST",
            "/api/notify",
            body=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
        )
        response = conn.getresponse()
        self.assertEqual(200, response.status)
        data = response.read()
        conn.close()
        return data

    def test_notify_from_subagent_session_is_suppressed(self) -> None:
        # Subagent sessions emit Notification-hook events too (permission
        # prompts inside agents); they must not raise popups or hook state.
        now = time.time()
        child_id = "cccc3333-0000-0000-0000-000000000000"
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp) / "projects" / "-Users-test-repo"
            proj.mkdir(parents=True)
            (proj / f"{child_id}.jsonl").write_text(
                json.dumps(
                    {
                        "type": "user",
                        "agentName": "helper",
                        "teamName": "session-aaaa1111",
                        "timestamp": datetime.fromtimestamp(now, UTC).isoformat(),
                        "message": {"role": "user", "content": "x"},
                    }
                )
                + "\n"
            )
            # The store patch has to be in place BEFORE the server is built: the
            # application captures its config once, at construction, so a patch
            # applied afterwards would not reach the running instance.
            with store_patch(PROJECTS_DIR=str(Path(tmp) / "projects")):
                httpd = make_server()
            thread = threading.Thread(target=poll_fast(httpd), daemon=True)
            thread.start()
            try:
                with mock.patch.object(notifications, "notify_mac") as notify:
                    data = self._post_notify(
                        httpd.server_port,
                        {"session_id": child_id, "message": "permission"},
                    )
                self.assertIn(b"suppressed", data)
                notify.assert_not_called()
                with state_of().hook_lock:
                    self.assertNotIn(child_id[:8], state_of().hook_notifications)
            finally:
                httpd.shutdown()
                httpd.server_close()
                thread.join(timeout=2)

    def test_notify_repeated_identical_message_popups_once(self) -> None:
        # Claude re-emits the same notification while a session stays blocked;
        # only the first within the suppression window may popup. A different
        # message from the same session still pops.
        httpd = make_server()
        thread = threading.Thread(target=poll_fast(httpd), daemon=True)
        thread.start()

        def expire_cooldowns() -> None:
            with state_of().hook_lock:
                state_of().last_popup["fedcba98"] = time.time() - 120
                state_of().last_popup["_global"] = time.time() - 120

        try:
            with mock.patch.object(notifications, "notify_mac") as notify:
                self._post_notify(
                    httpd.server_port,
                    {"session_id": "fedcba98", "message": "permission needed"},
                )
                self.assertEqual(1, notify.call_count)
                expire_cooldowns()
                self._post_notify(
                    httpd.server_port,
                    {"session_id": "fedcba98", "message": "permission needed"},
                )
                self.assertEqual(1, notify.call_count)  # identical: suppressed
                expire_cooldowns()
                self._post_notify(
                    httpd.server_port,
                    {"session_id": "fedcba98", "message": "open question"},
                )
                self.assertEqual(2, notify.call_count)  # new message: pops
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=2)

    def test_hook_without_marker_clears_on_newer_parsed_event(self) -> None:
        # Payloads without transcript_path (the documented curl simulation,
        # older Claude Code versions) get no user-event marker; they must
        # fall back to the parsed-timestamp rule instead of sticking forever.
        _config, state = runtime()
        with state_of().hook_lock:
            state_of().hook_notifications["cafe1234"] = {"ts": 1000.0, "message": "hi"}
        self.assertIsNotNone(notifications.current_hook(state, "cafe1234", None, 999.0))
        self.assertIsNone(notifications.current_hook(state, "cafe1234", None, 1001.0))
        with state_of().hook_lock:
            self.assertNotIn("cafe1234", state_of().hook_notifications)

    def test_hook_does_not_mark_actively_working_session_blocked(self) -> None:
        # Claude Code emits "waiting for your input" notifications for
        # sessions that keep running via background tasks (live case
        # 936f2c2b). While the transcript still receives events, the session
        # reads Working; the hook only surfaces once the session goes quiet.
        now = time.time()
        session_id = "dddd4444-0000-0000-0000-000000000000"

        def transcript(last_offset: float) -> str:
            iso_new = datetime.fromtimestamp(now - last_offset, UTC).isoformat()
            return (
                json.dumps(
                    {
                        "type": "user",
                        "sessionId": session_id,
                        "uuid": "u-1",
                        "timestamp": datetime.fromtimestamp(now - 900, UTC).isoformat(),
                        "message": {"role": "user", "content": "kick off reviews"},
                    }
                )
                + "\n"
                + json.dumps(
                    {
                        "type": "system",
                        "sessionId": session_id,
                        "timestamp": iso_new,
                        "content": "background shell event",
                    }
                )
                + "\n"
            )

        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp) / "projects" / "-Users-test-repo"
            proj.mkdir(parents=True)
            fp = proj / f"{session_id}.jsonl"

            def collect_with(last_offset: float) -> dict[str, Any]:
                fp.write_text(transcript(last_offset))
                with state_of().hook_lock:
                    state_of().hook_notifications[session_id[:8]] = {
                        "ts": now - 60,
                        "message": "Claude is waiting for your input",
                        "user_event": "u-1",  # marker unchanged: hook uncleared
                    }
                with (
                    store_patch(PROJECTS_DIR=str(Path(tmp) / "projects")),
                    store_patch(TASKS_DIR=str(Path(tmp) / "no-tasks")),
                ):
                    sessions = collect_claude(now, 24, False)
                return next(s for s in sessions if s["session"] == session_id[:8])

            fresh = collect_with(5)  # events still flowing -> working
            self.assertEqual("working", fresh["state"])
            # mtime too: staleness reads it, not only the record timestamps
            fp.write_text(transcript(600))
            old = now - 600
            os.utime(fp, (old, old))
            with state_of().hook_lock:
                state_of().hook_notifications[session_id[:8]] = {
                    "ts": now - 60,
                    "message": "Claude is waiting for your input",
                    "user_event": "u-1",
                }
            with (
                store_patch(PROJECTS_DIR=str(Path(tmp) / "projects")),
                store_patch(TASKS_DIR=str(Path(tmp) / "no-tasks")),
            ):
                sessions = collect_claude(now, 24, False)
            quiet = next(s for s in sessions if s["session"] == session_id[:8])
            self.assertEqual("needs_input", quiet["state"])

    def test_idle_nudge_pops_but_never_marks_session_blocked(self) -> None:
        # Claude Code emits "Claude is waiting for your input" after EVERY
        # completed turn. That is the dashboard's own definition of idle —
        # it may popup once as a nudge but must never flip a session to
        # needs_input. Permission prompts (different message) still do.
        now = time.time()
        session_id = "ffff6666-0000-0000-0000-000000000000"
        old_iso = datetime.fromtimestamp(now - 600, UTC).isoformat()
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp) / "projects" / "-Users-test-repo"
            proj.mkdir(parents=True)
            fp = proj / f"{session_id}.jsonl"
            fp.write_text(
                json.dumps(
                    {
                        "type": "user",
                        "sessionId": session_id,
                        "uuid": "u-1",
                        "timestamp": old_iso,
                        "message": {"role": "user", "content": "do the thing"},
                    }
                )
                + "\n"
            )
            old = now - 600
            os.utime(fp, (old, old))
            httpd = make_server()
            thread = threading.Thread(target=poll_fast(httpd), daemon=True)
            thread.start()
            try:
                with (
                    store_patch(PROJECTS_DIR=str(Path(tmp) / "projects")),
                    store_patch(TASKS_DIR=str(Path(tmp) / "no-tasks")),
                    mock.patch.object(notifications, "notify_mac") as notify,
                ):
                    # Idle nudge: pops once, no blocked state, no stored hook.
                    self._post_notify(
                        httpd.server_port,
                        {
                            "session_id": session_id,
                            "message": "Claude is waiting for your input",
                            "transcript_path": str(fp),
                        },
                    )
                    self.assertEqual(1, notify.call_count)
                    with state_of().hook_lock:
                        self.assertNotIn(session_id[:8], state_of().hook_notifications)
                    sessions = collect_claude(now, 24, False)
                    target = next(s for s in sessions if s["session"] == session_id[:8])
                    self.assertEqual("idle", target["state"])

                    # A permission prompt still blocks when the session is quiet.
                    self._post_notify(
                        httpd.server_port,
                        {
                            "session_id": session_id,
                            "message": "Claude needs your permission to use Bash",
                            "transcript_path": str(fp),
                        },
                    )
                    sessions = collect_claude(now, 24, False)
                    target = next(s for s in sessions if s["session"] == session_id[:8])
                    self.assertEqual("needs_input", target["state"])
            finally:
                httpd.shutdown()
                httpd.server_close()
                thread.join(timeout=2)

    def test_structured_notification_type_overrides_message_text(self) -> None:
        httpd = make_server()
        thread = threading.Thread(target=poll_fast(httpd), daemon=True)
        thread.start()
        try:
            with mock.patch.object(notifications, "notify_mac") as notify:
                # Informational notifications neither block nor claim that
                # Claude is waiting on the human.
                self._post_notify(
                    httpd.server_port,
                    {
                        "session_id": "aaaa1111",
                        "hook_event_name": "Notification",
                        "notification_type": "auth_success",
                        "message": "Authentication successful",
                    },
                )
                self.assertEqual(0, notify.call_count)
                self.assertNotIn("aaaa1111", state_of().hook_notifications)

                # Structured idle type wins even when the message is a
                # version/localization variant that lacks the old prefix, and
                # clears any older standing prompt for this session.
                with state_of().hook_lock:
                    state_of().hook_notifications["bbbb2222"] = {
                        "ts": time.time() - 60,
                        "message": "older permission prompt",
                    }
                    state_of().last_session_state["bbbb2222"] = "needs_input"
                self._post_notify(
                    httpd.server_port,
                    {
                        "session_id": "bbbb2222",
                        "hook_event_name": "Notification",
                        "notification_type": "idle_prompt",
                        "message": "Your agent has finished its turn",
                    },
                )
                self.assertEqual(1, notify.call_count)
                self.assertNotIn("bbbb2222", state_of().hook_notifications)
                self.assertNotIn("bbbb2222", state_of().last_session_state)

                with state_of().hook_lock:
                    state_of().last_popup["_global"] = time.time() - 120

                # Structured permission type also wins over misleading text.
                self._post_notify(
                    httpd.server_port,
                    {
                        "session_id": "cccc3333",
                        "hook_event_name": "Notification",
                        "notification_type": "permission_prompt",
                        "message": "Claude is waiting for your input to approve Bash",
                    },
                )
                self.assertEqual(2, notify.call_count)
                self.assertIn("cccc3333", state_of().hook_notifications)
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=2)

    def test_notification_disposition_covers_documented_and_observed_types(self) -> None:
        # Three groups. Eight are Claude Code's advertised matcher values. Four
        # are observed on 2.1.226 and absent from that list; they are here
        # because the unknown-type default would otherwise decide them, and it
        # decides `computer_use_enter` wrongly (DRC-4121). And `idle_timeout` is
        # in neither group: it is a deliberately retained compatibility alias for
        # `idle_prompt`, kept for hooks predating the rename, so it has to be
        # asserted here or nothing would catch its removal.
        expected = {
            "idle_prompt": (False, True),
            "idle_timeout": (False, True),
            "permission_prompt": (True, True),
            "auth_success": (False, False),
            "elicitation_dialog": (True, True),
            "elicitation_complete": (False, False),
            "elicitation_response": (False, False),
            "agent_needs_input": (True, True),
            "agent_completed": (False, False),
            "worker_permission_prompt": (True, True),
            "computer_use_enter": (False, False),
            "computer_use_exit": (False, False),
            "push_notification": (False, False),
        }
        for notification_type, disposition in expected.items():
            with self.subTest(notification_type=notification_type):
                self.assertEqual(
                    disposition,
                    notifications.notification_disposition(notification_type, "variant text"),
                )

    def test_elicitation_completion_clears_dialog_hook(self) -> None:
        with state_of().hook_lock:
            state_of().hook_notifications["feed1234"] = {
                "ts": time.time() - 30,
                "message": "MCP input requested",
            }
        httpd = make_server()
        thread = threading.Thread(target=poll_fast(httpd), daemon=True)
        thread.start()
        try:
            self._post_notify(
                httpd.server_port,
                {
                    "session_id": "feed1234",
                    "hook_event_name": "Notification",
                    "notification_type": "elicitation_complete",
                    "message": "MCP elicitation completed",
                },
            )
            with state_of().hook_lock:
                self.assertNotIn("feed1234", state_of().hook_notifications)
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=2)

    def test_informational_status_notification_leaves_a_standing_prompt(self) -> None:
        # Informational is not the same as clearing. A computer-use status line
        # arriving while a permission prompt stands must not retire the prompt —
        # the human still has a question waiting. Pins the deliberate asymmetry
        # between INFORMATIONAL_NOTIFICATION_TYPES and CLEARING_NOTIFICATION_TYPES.
        with state_of().hook_lock:
            state_of().hook_notifications["beef5678"] = {
                "ts": time.time() - 30,
                "message": "Claude needs your permission to use Bash",
            }
        httpd = make_server()
        thread = threading.Thread(target=poll_fast(httpd), daemon=True)
        thread.start()
        try:
            self._post_notify(
                httpd.server_port,
                {
                    "session_id": "beef5678",
                    "hook_event_name": "Notification",
                    "notification_type": "computer_use_enter",
                    "message": "Claude is using your computer \xb7 press Esc to stop",
                },
            )
            with state_of().hook_lock:
                standing = state_of().hook_notifications.get("beef5678")
            self.assertIsNotNone(standing)
            assert standing is not None
            self.assertIn("permission", standing["message"])
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=2)

    def test_session_end_hook_clears_standing_permission_state(self) -> None:
        with state_of().hook_lock:
            state_of().hook_notifications["deadbeef"] = {
                "ts": time.time() - 60,
                "message": "permission needed",
            }
            state_of().last_session_state["deadbeef"] = "needs_input"
        httpd = make_server()
        thread = threading.Thread(target=poll_fast(httpd), daemon=True)
        thread.start()
        try:
            data = self._post_notify(
                httpd.server_port,
                {
                    "session_id": "deadbeef-0000-0000-0000-000000000000",
                    "hook_event_name": "SessionEnd",
                    "reason": "prompt_input_exit",
                },
            )
            self.assertIn(b'"cleared":"session_end"', data)
            with state_of().hook_lock:
                self.assertNotIn("deadbeef", state_of().hook_notifications)
                self.assertNotIn("deadbeef", state_of().last_session_state)
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=2)

    def test_hook_block_uses_hook_time_and_inactive_sessions_are_idle(self) -> None:
        now = time.time()
        session_id = "abcd1234-0000-0000-0000-000000000000"
        event_time = datetime.fromtimestamp(now - 600, UTC).isoformat()
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "projects" / "sample"
            project.mkdir(parents=True)
            transcript = project / f"{session_id}.jsonl"
            transcript.write_text(
                json.dumps(
                    {
                        "type": "user",
                        "uuid": "user-before-hook",
                        "timestamp": event_time,
                        "message": {"role": "user", "content": "run it"},
                    }
                )
                + "\n"
            )
            old = now - 600
            os.utime(transcript, (old, old))
            hook_time = now - 45
            with state_of().hook_lock:
                state_of().hook_notifications[session_id[:8]] = {
                    "ts": hook_time,
                    "message": "permission needed",
                    "user_event": "user-before-hook",
                }
            with (
                store_patch(PROJECTS_DIR=str(Path(tmp) / "projects")),
                store_patch(TASKS_DIR=str(Path(tmp) / "no-tasks")),
            ):
                active = collect_claude(now, 24, False)[0]
                inactive = collect_claude(now, 0.1, True)[0]

        self.assertEqual("needs_input", active["state"])
        self.assertEqual(hook_time, active["blocked_since"])
        self.assertEqual("idle", inactive["state"])

    def test_transcript_open_question_outranks_fresh_activity(self) -> None:
        now = time.time()
        session_id = "face9999-0000-0000-0000-000000000000"
        question_time = datetime.fromtimestamp(now - 5, UTC).isoformat()
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "projects" / "sample"
            project.mkdir(parents=True)
            transcript = project / f"{session_id}.jsonl"
            transcript.write_text(
                json.dumps(
                    {
                        "type": "assistant",
                        "timestamp": question_time,
                        "message": {
                            "role": "assistant",
                            "content": [
                                {
                                    "type": "tool_use",
                                    "id": "question-1",
                                    "name": "AskUserQuestion",
                                    "input": {},
                                }
                            ],
                        },
                    }
                )
                + "\n"
            )
            with (
                store_patch(PROJECTS_DIR=str(Path(tmp) / "projects")),
                store_patch(TASKS_DIR=str(Path(tmp) / "no-tasks")),
            ):
                session = collect_claude(now, 24, False)[0]

        self.assertEqual("needs_input", session["state"])
        self.assertEqual(records.parse_ts(question_time), session["blocked_since"])

    def test_background_task_flap_lifecycle_end_to_end(self) -> None:
        # Full lifecycle of the live 936f2c2b case, through the real notify
        # endpoint: a turn ends into background work, Claude re-emits
        # "waiting for your input" hooks, background events keep the
        # transcript active. The session must read Working steadily (no
        # needs_input flapping), clear the hook when the session self-resumes
        # with a new user record, and only surface needs_input once the
        # session is genuinely quiet with a standing hook.
        now = time.time()
        session_id = "eeee5555-0000-0000-0000-000000000000"

        def iso(age: float) -> str:
            return str(datetime.fromtimestamp(now - age, UTC).isoformat())

        def user_rec(uuid: str, age: float, text: str) -> str:
            return (
                json.dumps(
                    {
                        "type": "user",
                        "sessionId": session_id,
                        "uuid": uuid,
                        "timestamp": iso(age),
                        "message": {"role": "user", "content": text},
                    }
                )
                + "\n"
            )

        def system_rec(age: float) -> str:
            return (
                json.dumps(
                    {
                        "type": "system",
                        "sessionId": session_id,
                        "timestamp": iso(age),
                        "content": "background shell event",
                    }
                )
                + "\n"
            )

        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp) / "projects" / "-Users-test-repo"
            proj.mkdir(parents=True)
            fp = proj / f"{session_id}.jsonl"
            patches = (
                store_patch(PROJECTS_DIR=str(Path(tmp) / "projects")),
                store_patch(TASKS_DIR=str(Path(tmp) / "no-tasks")),
            )
            # Built inside the store patches: config is captured at construction,
            # so the POSTs must reach a server that knows the temporary store.
            with patches[0], patches[1]:
                httpd = make_server()
            thread = threading.Thread(target=poll_fast(httpd), daemon=True)
            thread.start()
            try:
                with patches[0], patches[1]:

                    def post_hook() -> None:
                        # Permission-kind message: idle nudges never block at
                        # all (see test_idle_nudge_pops_but_never_marks_...).
                        self._post_notify(
                            httpd.server_port,
                            {
                                "session_id": session_id,
                                "message": "Claude needs your permission to use Bash",
                                "transcript_path": str(fp),
                            },
                        )

                    def state() -> str:
                        result = collect_claude(now, 24, False)
                        return str(
                            next(s for s in result if s["session"] == session_id[:8])["state"]
                        )

                    # Turn ended; hook fires; background events keep flowing.
                    fp.write_text(user_rec("u-1", 300, "review the PRs") + system_rec(50))
                    post_hook()
                    self.assertEqual("working", state())

                    # More background events + a RE-POSTED identical hook:
                    # still working, poll after poll — no flapping.
                    fp.write_text(
                        user_rec("u-1", 300, "review the PRs") + system_rec(50) + system_rec(20)
                    )
                    post_hook()
                    self.assertEqual("working", state())
                    self.assertEqual("working", state())

                    # Background work completes; the session self-resumes with
                    # a NEW user record (task notification): hook must CLEAR.
                    fp.write_text(
                        user_rec("u-1", 300, "review the PRs")
                        + system_rec(50)
                        + user_rec("u-2", 10, "task-notification: reviews done")
                    )
                    self.assertEqual("working", state())
                    with state_of().hook_lock:
                        self.assertNotIn(session_id[:8], state_of().hook_notifications)

                    # Final turn ends for real: standing hook + genuinely
                    # quiet transcript (old record timestamps AND old mtime)
                    # -> blocked on the human.
                    fp.write_text(
                        user_rec("u-1", 900, "review the PRs")
                        + system_rec(700)
                        + user_rec("u-2", 600, "task-notification: reviews done")
                    )
                    old = now - 600
                    os.utime(fp, (old, old))
                    post_hook()
                    self.assertEqual("needs_input", state())
            finally:
                httpd.shutdown()
                httpd.server_close()
                thread.join(timeout=2)

    def _subagent_fanout(self, tmp: str, now: float) -> tuple[Path, str]:
        """A parent parked for 10 minutes with one fresh subagent under it.

        This shape reads Working on the strength of the subagent alone, which is
        the state DRC-4121 is about: the parent's own transcript is long quiet, so
        the freshness half of the working test has lapsed and only the subagent
        clause is holding the row.
        """
        parent_id = "f00d9999-0000-0000-0000-000000000000"
        child_id = "f00daaaa-0000-0000-0000-000000000000"
        proj = Path(tmp) / "projects" / "-Users-test-repo"
        proj.mkdir(parents=True)
        parent_fp = proj / f"{parent_id}.jsonl"
        parent_fp.write_text(
            json.dumps(
                {
                    "type": "user",
                    "sessionId": parent_id,
                    "uuid": "u-1",
                    "timestamp": datetime.fromtimestamp(now - 600, UTC).isoformat(),
                    "message": {"role": "user", "content": "run the fan-out"},
                }
            )
            + "\n"
        )
        (proj / f"{child_id}.jsonl").write_text(
            json.dumps(
                {
                    "type": "user",
                    "sessionId": child_id,
                    "agentName": "fanout-worker",
                    "teamName": f"session-{parent_id[:8]}",
                    "timestamp": datetime.fromtimestamp(now - 5, UTC).isoformat(),
                    "message": {"role": "user", "content": "do the work"},
                }
            )
            + "\n"
        )
        old = now - 600
        os.utime(parent_fp, (old, old))
        return parent_fp, parent_id

    def _state_with_fanout_hook(self, notification_type: str, message: str) -> str:
        """Collect the parent's state after one real notify POST reaches it."""
        now = time.time()
        with tempfile.TemporaryDirectory() as tmp:
            patches = (
                store_patch(PROJECTS_DIR=str(Path(tmp) / "projects")),
                store_patch(TASKS_DIR=str(Path(tmp) / "no-tasks")),
            )
            with patches[0], patches[1]:
                parent_fp, parent_id = self._subagent_fanout(tmp, now)
                # Built inside the patches: config is captured at construction.
                httpd = make_server()
            thread = threading.Thread(target=poll_fast(httpd), daemon=True)
            thread.start()
            try:
                with patches[0], patches[1], mock.patch.object(notifications, "notify_mac"):
                    self._post_notify(
                        httpd.server_port,
                        {
                            "session_id": parent_id,
                            "hook_event_name": "Notification",
                            "notification_type": notification_type,
                            "message": message,
                            "transcript_path": str(parent_fp),
                        },
                    )
                    sessions = collect_claude(now, 24, False)
            finally:
                httpd.shutdown()
                httpd.server_close()
                thread.join(timeout=2)
        row = next(s for s in sessions if s["session"] == parent_id[:8])
        self.assertEqual(1, len(row["subagents"]), "fixture must have a live subagent")
        return str(row["state"])

    def test_recognised_prompt_outranks_a_live_subagent(self) -> None:
        # An MCP elicitation has no PermissionRequest behind it, so this POST is
        # the only signal that exists for it. Before DRC-4121 the live subagent
        # pinned the row to Working for as long as the fan-out ran, and the
        # question was never shown.
        self.assertEqual(
            "needs_input",
            self._state_with_fanout_hook("elicitation_dialog", "Claude Code needs your input"),
        )

    def test_an_unrecognised_notification_type_still_waits_for_quiet(self) -> None:
        # The other half of the same decision. An unknown structured type is
        # stored and popped -- fail-visible at the ingress is deliberate -- but it
        # does not get to outrank a busy session, because unknown is a claim and
        # not a measurement. It surfaces once the session goes quiet, as before.
        self.assertEqual(
            "working",
            self._state_with_fanout_hook("some_future_type", "something happened"),
        )


class NotifyHookTest(unittest.TestCase):
    """The forwarder replaces a curl one-liner that only worked in POSIX shells."""

    HOOK = str(HOOK_PATH)

    def run_hook(self, payload: bytes, url: str | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, self.HOOK, *([url] if url else [])],
            input=payload.decode(),
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )

    def test_payload_reaches_a_running_server(self) -> None:
        httpd = make_server()
        thread = threading.Thread(target=poll_fast(httpd), daemon=True)
        thread.start()
        url = f"http://127.0.0.1:{httpd.server_port}/api/notify"
        try:
            with mock.patch.object(notifications, "notify_mac"):
                result = self.run_hook(
                    json.dumps(
                        {
                            "session_id": "abcd1234-0000-0000-0000-000000000000",
                            "message": "Claude needs permission",
                            "notification_type": "permission_prompt",
                        }
                    ).encode(),
                    url,
                )
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=2)

        self.assertEqual(0, result.returncode, result.stderr)
        # The server recorded the hook, which is the whole point of the script.
        self.assertIn("abcd1234", state_of().hook_notifications)

    def test_never_fails_the_agent_that_invoked_it(self) -> None:
        # A hook that exits non-zero disturbs the session it reports on, and
        # "no dashboard running" is an ordinary state.
        cases = {
            "no server listening": (b'{"session_id":"x"}', "http://127.0.0.1:9/api/notify"),
            "malformed json": (b"{not json", None),
            "empty stdin": (b"", None),
            "not an object": (b"[1,2,3]", None),
        }
        for why, (payload, url) in cases.items():
            with self.subTest(why=why):
                self.assertEqual(0, self.run_hook(payload, url).returncode)

    def test_refuses_to_forward_off_loopback(self) -> None:
        # The script is wired into lifecycle hooks and sees prompts and session
        # ids; an edited settings file must not turn it into an exfiltration
        # path. A prefix check (startswith "http://localhost") accepted several
        # of these — the host is parsed instead.
        for url in (
            "https://evil.example/collect",
            "http://10.0.0.5:4553/api/notify",
            "file:///etc/passwd",
            "http://localhost.evil.com/collect",
            "http://127.0.0.1.evil.com/collect",
            "http://localhost@evil.com/collect",
            "http://[::1]@evil.com/collect",
            "https://127.0.0.1/collect",  # https is not what the server speaks
            "",
        ):
            with self.subTest(url=url):
                self.assertFalse(dashboard_hook.is_loopback_url(url))
                self.assertFalse(dashboard_hook.forward(url, b"{}"))

    def test_accepts_every_loopback_spelling(self) -> None:
        for url in (
            "http://127.0.0.1:4553/api/notify",
            "http://localhost:9999/api/notify",
            "http://[::1]:4553/api/notify",
        ):
            with self.subTest(url=url):
                self.assertTrue(dashboard_hook.is_loopback_url(url))

    def test_an_http_proxy_cannot_carry_the_payload_off_the_machine(self) -> None:
        # urllib's default opener honours http_proxy/HTTP_PROXY, which is
        # routine in corporate environments. A POST to 127.0.0.1 was handed to
        # the proxy instead, carrying prompts and session ids off the machine
        # and defeating the loopback check entirely.
        proxied: list[bytes] = []

        class Proxy(http.server.BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length") or 0)
                proxied.append(self.rfile.read(length))
                self.send_response(200)
                self.send_header("Content-Length", "0")
                self.end_headers()

            def log_message(self, *args: Any) -> None:
                pass

        httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Proxy)
        thread = threading.Thread(target=poll_fast(httpd), daemon=True)
        thread.start()
        try:
            with mock.patch.dict(
                os.environ,
                {
                    "http_proxy": f"http://127.0.0.1:{httpd.server_port}",
                    "HTTP_PROXY": f"http://127.0.0.1:{httpd.server_port}",
                },
            ):
                # Port 9 (discard) is not listening, so anything the proxy
                # receives can only have come from proxy routing.
                delivered = dashboard_hook.forward(
                    "http://127.0.0.1:9/api/notify", b'{"secret":"prompt text"}'
                )
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=2)

        self.assertEqual([], proxied, "payload was routed through the proxy")
        self.assertFalse(delivered)

    def test_does_not_follow_a_redirect_off_the_machine(self) -> None:
        # urllib follows redirects by default, and 307/308 preserve method and
        # body — so a hostile listener on the loopback port could otherwise
        # bounce the payload off this machine, defeating the check above.
        received: list[str] = []

        class Redirector(http.server.BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                received.append(self.path)
                self.send_response(307)
                self.send_header("Location", "https://evil.example/collect")
                self.send_header("Content-Length", "0")
                self.end_headers()

            def log_message(self, *args: Any) -> None:
                pass

        httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Redirector)
        thread = threading.Thread(target=poll_fast(httpd), daemon=True)
        thread.start()
        try:
            url = f"http://127.0.0.1:{httpd.server_port}/api/notify"
            delivered = dashboard_hook.forward(url, b'{"session_id":"x"}')
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=2)

        self.assertEqual(["/api/notify"], received, "first request should still be sent")
        self.assertFalse(delivered, "a refused redirect must not report success")


class HookOrderingTest(unittest.TestCase):
    def setUp(self) -> None:
        # This class does not inherit CompassServerTest's shared reset, and
        # these tests mutate process-wide hook state.
        with state_of().hook_lock:
            state_of().hook_notifications.clear()
            state_of().last_session_state.clear()
            state_of().hook_generation.clear()
            state_of().last_popup.clear()
            state_of().last_popup_message.clear()

    def test_session_end_is_not_undone_by_a_slow_notification(self) -> None:
        # Notification handling does transcript lookups outside the lock. A
        # SessionEnd arriving during one used to be silently overwritten when
        # the notification committed its now-stale state.
        started = threading.Event()
        release = threading.Event()

        def slow_lookup(*_args: object) -> bool:
            started.set()
            release.wait(timeout=30)
            return False

        def request(payload: dict[str, Any]) -> Any:
            return notify_handler(payload)

        session = "deadbeef-0000-0000-0000-000000000000"
        with (
            mock.patch.object(claude_data, "prefix_is_agent", slow_lookup),
            mock.patch.object(notifications, "notify_mac"),
        ):
            notification = request(
                {
                    "session_id": session,
                    "hook_event_name": "Notification",
                    "notification_type": "permission_prompt",
                    "message": "permission",
                }
            )
            thread = threading.Thread(target=notification.do_POST)
            thread.start()
            self.assertTrue(started.wait(timeout=30))
            request({"session_id": session, "hook_event_name": "SessionEnd"}).do_POST()
            release.set()
            thread.join(timeout=30)

        self.assertEqual({}, state_of().hook_notifications, "SessionEnd was undone")

    def test_session_end_during_a_collection_neither_blocks_nor_pops(self) -> None:
        # The POST-side generation guard does not help a collection that
        # already read the hook. Without re-checking, an exited session was
        # still announced as blocked and burned the global popup cooldown.
        now = 1_700_000_000.0
        prefix = "abcdef12"
        with state_of().hook_lock:
            state_of().hook_notifications[prefix] = {"ts": now, "message": "permission"}
        popups: list[Any] = []
        original = notifications.current_hook

        def session_ends_mid_collection(st: Any, pfx: str, event: str | None, ts: float) -> Any:
            hook = original(st, pfx, event, ts)
            with state_of().hook_lock:  # SessionEnd lands exactly here
                state_of().hook_notifications.pop(pfx, None)
                state_of().last_session_state.pop(pfx, None)
                state_of().hook_generation[pfx] = state_of().hook_generation.get(pfx, 0) + 1
            return hook

        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "projects" / "-w-proj"
            project.mkdir(parents=True)
            transcript = project / f"{prefix}-0000-0000-0000-000000000000.jsonl"
            transcript.write_text(json.dumps({"type": "user", "uuid": "u"}) + "\n")
            os.utime(transcript, (now - 200, now - 200))  # quiet, so the hook decides
            with (
                store_patch(PROJECTS_DIR=str(Path(tmp) / "projects")),
                store_patch(TASKS_DIR=str(Path(tmp) / "tasks")),
                mock.patch.object(notifications, "current_hook", session_ends_mid_collection),
            ):
                collection = _claude_application(*runtime(), now=now, popups=popups).collect(
                    show_all=True
                )
                sessions = collection["sessions"]

        self.assertEqual("idle", sessions[0]["state"], "exited session shown as blocked")
        self.assertEqual([], popups, "popped for a session that had already ended")

    def _collect_with_session_end_injected(
        self, *, at: str, records: list[dict[str, Any]], standing_hook: bool
    ) -> tuple[str, int]:
        """Run one collection with a SessionEnd landing at ``at``."""
        now = 1_700_000_000.0
        prefix = "abcdef12"
        if standing_hook:
            with state_of().hook_lock:
                state_of().hook_notifications[prefix] = {"ts": now, "message": "permission"}
        popups: list[Any] = []

        def end_session() -> None:
            with state_of().hook_lock:
                state_of().hook_notifications.pop(prefix, None)
                state_of().last_session_state.pop(prefix, None)
                state_of().hook_generation[prefix] = state_of().hook_generation.get(prefix, 0) + 1

        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "projects" / "-w-proj"
            project.mkdir(parents=True)
            transcript = project / f"{prefix}-0000-0000-0000-000000000000.jsonl"
            transcript.write_text("\n".join(json.dumps(r) for r in records) + "\n")
            os.utime(transcript, (now - 300, now - 300))  # quiet, so state is decided above

            # Patched to a no-op rather than used as the recorder: the popups
            # below are counted off the application's injected notifier, and this
            # only keeps any other path away from osascript.
            notif_patches: dict[str, Any] = {"notify_mac": lambda *_a, **_k: None}
            data_patches: dict[str, Any] = {}
            if at == "analyze":
                real_analyze = claude_data.analyze_transcript

                def analyze(cfg: Any, st: Any, path: str) -> Any:
                    end_session()
                    return real_analyze(cfg, st, path)

                data_patches["analyze_transcript"] = analyze
            elif at == "popup":
                real_popup = notifications.maybe_popup

                def popup(*args: Any, **kwargs: Any) -> None:
                    end_session()
                    real_popup(*args, **kwargs)

                notif_patches["maybe_popup"] = popup

            with (
                store_patch(PROJECTS_DIR=str(Path(tmp) / "projects")),
                store_patch(TASKS_DIR=str(Path(tmp) / "tasks")),
                mock.patch.multiple(notifications, **notif_patches),
                # patch.multiple rejects an empty mapping, so re-patch the real
                # function when this variant does not intercept it.
                mock.patch.multiple(
                    claude_data,
                    **(data_patches or {"analyze_transcript": claude_data.analyze_transcript}),
                ),
            ):
                collection = _claude_application(*runtime(), now=now, popups=popups).collect(
                    show_all=True
                )
                sessions = collection["sessions"]
        return sessions[0]["state"], len(popups)

    ASK_USER_QUESTION: ClassVar[list[dict[str, Any]]] = [
        {
            "type": "assistant",
            "timestamp": "2023-11-14T00:00:00+00:00",
            "message": {"content": [{"type": "tool_use", "id": "t1", "name": "AskUserQuestion"}]},
        }
    ]
    PLAIN_USER: ClassVar[list[dict[str, Any]]] = [{"type": "user", "uuid": "u"}]

    def test_session_end_during_analysis_clears_a_transcript_detected_block(self) -> None:
        # The guard was sampled after analyze_transcript, which is the slow
        # part, and did not cover transcript-detected needs-input at all — so
        # an unanswered AskUserQuestion in a session the user had quit stayed
        # on screen and popped.
        state, popups = self._collect_with_session_end_injected(
            at="analyze", records=self.ASK_USER_QUESTION, standing_hook=False
        )
        self.assertEqual("idle", state)
        self.assertEqual(0, popups)

    def test_session_end_at_popup_time_suppresses_the_popup(self) -> None:
        # Checking the generation in the caller left a window before
        # maybe_popup took the lock. The state is a snapshot and may still read
        # blocked until the next refresh, but the popup is irreversible and
        # must not fire for a session that has exited.
        _state, popups = self._collect_with_session_end_injected(
            at="popup", records=self.PLAIN_USER, standing_hook=True
        )
        self.assertEqual(0, popups)

    def test_a_standing_hook_still_blocks_and_pops_when_nothing_races(self) -> None:
        state, popups = self._collect_with_session_end_injected(
            at="none", records=self.PLAIN_USER, standing_hook=True
        )
        self.assertEqual("needs_input", state)
        self.assertEqual(1, popups)

    def _race_against_slow_notification(self, second: dict[str, Any]) -> dict[str, Any]:
        """Start an actionable Notification, land ``second`` mid-flight."""
        started = threading.Event()
        release = threading.Event()

        def slow_lookup(*_args: object) -> bool:
            started.set()
            release.wait(timeout=30)
            return False

        def request(payload: dict[str, Any]) -> Any:
            return notify_handler(payload)

        session = "deadbeef-0000-0000-0000-000000000000"
        first = request(
            {
                "session_id": session,
                "hook_event_name": "Notification",
                "notification_type": "permission_prompt",
                "message": "NEEDS PERMISSION",
            }
        )
        with (
            mock.patch.object(claude_data, "prefix_is_agent", slow_lookup),
            mock.patch.object(notifications, "notify_mac"),
        ):
            thread = threading.Thread(target=first.do_POST)
            thread.start()
            self.assertTrue(started.wait(timeout=30))
            with mock.patch.object(claude_data, "prefix_is_agent", lambda *_a: False):
                request(second).do_POST()
            release.set()
            thread.join(timeout=30)
        return dict(state_of().hook_notifications)

    def test_a_clearing_notification_does_not_drop_a_racing_permission_prompt(self) -> None:
        # Only SessionEnd means "this session is gone". agent_completed and
        # idle_prompt end one alert, not the session — invalidating on those
        # dropped an actionable prompt that merely overlapped a clearing one,
        # losing a real "Claude is blocked" signal.
        for kind in ("agent_completed", "idle_prompt", "elicitation_complete"):
            with self.subTest(kind=kind):
                self.setUp()
                survived = self._race_against_slow_notification(
                    {
                        "session_id": "deadbeef-0000-0000-0000-000000000000",
                        "hook_event_name": "Notification",
                        "notification_type": kind,
                        "message": "done",
                    }
                )
                self.assertIn("deadbeef", survived, f"{kind} dropped a permission prompt")

    def test_session_end_still_supersedes_a_racing_notification(self) -> None:
        survived = self._race_against_slow_notification(
            {"session_id": "deadbeef-0000-0000-0000-000000000000", "hook_event_name": "SessionEnd"}
        )
        self.assertEqual({}, survived, "SessionEnd was undone")

    def test_an_unraced_notification_still_records(self) -> None:
        session = "cafebabe-0000-0000-0000-000000000000"
        handler = notify_handler(
            {
                "session_id": session,
                "hook_event_name": "Notification",
                "notification_type": "permission_prompt",
                "message": "permission",
            }
        )
        with (
            mock.patch.object(claude_data, "prefix_is_agent", lambda *_a: False),
            mock.patch.object(notifications, "notify_mac"),
        ):
            handler.do_POST()
        self.assertIn("cafebabe", state_of().hook_notifications)


class NativeNotifierTest(unittest.TestCase):
    """Pure in platform_name, so both branches run on every runner rather than
    only the host's (design decision D-4 in docs/design-cross-platform.md)."""

    def test_backend_per_platform(self) -> None:
        self.assertEqual("osascript", notifications.native_notifier("darwin"))
        # No native backend yet on these (tracked in
        # docs/plans/native-notifications.md). Until then the
        # empty string tells the page to raise the notification itself.
        for platform_name in ("linux", "win32", "freebsd14", "cygwin"):
            with self.subTest(platform=platform_name):
                self.assertEqual("", notifications.native_notifier(platform_name))

    def test_notify_mac_is_a_no_op_without_a_backend(self) -> None:
        # The backend comes from config.platform_name, not ambient sys.platform.
        linux = make_config(platform_name="linux")
        with mock.patch("compass_runtime.notifications.subprocess.run") as run:
            notifications.notify_mac(linux, "title", "message")
        run.assert_not_called()

    def test_api_data_reports_who_owns_popups(self) -> None:
        # The page reads this to decide whether to notify; if it went missing,
        # macOS would double-notify and Linux would notify not at all.
        with mock.patch.object(sys, "platform", "darwin"):
            self.assertEqual("osascript", collect(24, False)["native_notify"])
        with mock.patch.object(sys, "platform", "win32"):
            self.assertEqual("", collect(24, False)["native_notify"])


class NoNativeNotificationTest(RuntimeTestCase):
    """The refusal that keeps a unit run off the operator's own notification centre.

    DRC-4431: `test_observation` and `test_http_api` between them sent four real
    banners, three of them byte-identical — so anyone reproducing this has to
    count SPAWNS, not banners, because macOS coalesces identical alerts into one
    visible notification while still playing every sound.
    """

    def test_the_refusal_is_already_in_force(self) -> None:
        # False means the package import installed it, which is the only way it
        # covers a test module that never thought about notifications.
        self.assertFalse(
            forbid_native_notifications(),
            "importing the tests package must install the notification refusal",
        )

    def test_the_argv_notify_mac_composes_is_refused(self) -> None:
        script = 'display notification "m" with title "t" sound name "Glass"'
        shapes: tuple[Any, ...] = (
            ["/usr/bin/osascript", "-e", script],
            # Neither shape matched the argv[0] equality this replaces: a bare
            # name resolved off PATH, and a string argv for shell=True.
            ["osascript", "-e", script],
            f"/usr/bin/osascript -e '{script}'",
        )
        for argv in shapes:
            with self.subTest(argv=argv):
                before = len(REFUSED_NOTIFICATIONS)
                with self.assertRaises(AssertionError):
                    subprocess.run(argv, check=False)
                self.assertEqual(before + 1, len(REFUSED_NOTIFICATIONS))

    def test_an_unrelated_spawn_still_runs(self) -> None:
        # test_lifecycle subprocesses server.py --diagnose; a blanket subprocess
        # ban would take the suite with it.
        #
        # `sys.executable` rather than a shell utility: this class runs on the
        # windows-latest leg of `platform-tests` too, and an earlier `/bin/echo`
        # here failed there with WinError 2 while passing on both POSIX legs.
        done = subprocess.run(
            [sys.executable, "-c", "print('ok')"], capture_output=True, text=True, check=True
        )
        self.assertEqual("ok", done.stdout.strip())

    def test_the_refusal_widens_with_a_future_backend(self) -> None:
        # Backend-agnostic by construction: the refused set is read off
        # `native_notifier`, so the Linux backend in
        # docs/plans/native-notifications.md arrives already covered.
        self.assertEqual(frozenset({"osascript"}), notifier_binaries())
        self.assertFalse(is_native_notification(["/usr/bin/notify-send", "hi"]))
        with mock.patch.object(
            notifications,
            "native_notifier",
            lambda name: "notify-send" if name == "linux" else "",
        ):
            self.assertEqual(frozenset({"notify-send"}), notifier_binaries())
            self.assertTrue(is_native_notification(["/usr/bin/notify-send", "hi"]))


class GlobUnderTest(unittest.TestCase):
    HOSTILE = "A [Contractor]"

    def test_notify_session_id_cannot_inject_a_glob_pattern(self) -> None:
        # The prefix reaches this glob straight from a POST body, so it must be
        # escaped rather than interpreted.
        with tempfile.TemporaryDirectory() as tmp:
            projects = Path(tmp) / "projects"
            (projects / "proj").mkdir(parents=True)
            (projects / "proj" / "aaaaaaaa.jsonl").write_text(
                json.dumps({"type": "user", "agentName": "worker", "teamName": "session-bbbbbbbb"})
                + "\n"
            )
            with store_patch(PROJECTS_DIR=str(projects)):
                config, state = runtime()
                self.assertFalse(claude_data.prefix_is_agent(config, state, "[a-z]*"))
                config, state = runtime()
                self.assertTrue(claude_data.prefix_is_agent(config, state, "aaaaaaaa"))


class InstalledContractCharacterizationTest(unittest.TestCase):
    """The installed executable contract that extraction must preserve."""

    def setUp(self) -> None:
        with state_of().hook_lock:
            state_of().hook_notifications.clear()
            state_of().last_popup.clear()
            state_of().last_popup_message.clear()
            state_of().last_session_state.clear()
            state_of().hook_generation.clear()
        with state_of().collect_memo_lock:
            state_of().snapshot.clear()
        # Route-shape tests run the notification code but do not assert native
        # delivery, so keep its osascript process off the host.
        short_circuit_native_notifications(self)

    def tearDown(self) -> None:
        with state_of().collect_memo_lock:
            state_of().snapshot.clear()

    @staticmethod
    def _response(
        port: int,
        method: str,
        path: str,
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, email.message.Message, bytes]:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
        try:
            conn.request(method, path, body=body, headers=headers or {})
            response = conn.getresponse()
            return response.status, response.headers, response.read()
        finally:
            conn.close()

    def test_session_end_cannot_be_undone_by_a_slow_notification(self) -> None:
        httpd = make_server()
        thread = serve_until_closed(httpd)
        entered = threading.Event()
        release = threading.Event()
        notification: list[tuple[int, bytes]] = []

        def slow_lookup(*_: Any) -> tuple[bool, str]:
            entered.set()
            self.assertTrue(release.wait(timeout=30), "test did not release notification")
            return True, "user-event"

        def post_notification() -> None:
            code, _, body = self._response(
                httpd.server_port,
                "POST",
                "/api/notify",
                json.dumps(
                    {
                        "session_id": "12345678-session",
                        "message": "permission needed",
                        "transcript_path": "/slow.jsonl",
                    }
                ).encode(),
            )
            notification.append((code, body))

        try:
            with (
                mock.patch.object(claude_data, "hook_user_event", side_effect=slow_lookup),
                mock.patch.object(notifications, "notify_mac"),
            ):
                worker = threading.Thread(target=post_notification)
                worker.start()
                self.assertTrue(entered.wait(timeout=30), "notification did not begin")
                code, _, body = self._response(
                    httpd.server_port,
                    "POST",
                    "/api/notify",
                    b'{"session_id":"12345678-session","hook_event_name":"SessionEnd"}',
                )
                self.assertEqual(200, code)
                self.assertEqual({"ok": True, "cleared": "session_end"}, json.loads(body))
                release.set()
                worker.join(timeout=30)
            self.assertFalse(worker.is_alive())
            self.assertEqual([(200, b'{"ok":true,"superseded":true}')], notification)
            self.assertNotIn("12345678", state_of().hook_notifications)
        finally:
            release.set()
            httpd.shutdown()
            thread.join(timeout=5)


class HarnessNeutralTitleTest(unittest.TestCase):
    """The native popup names the harness, not always Claude.

    The design makes this the prerequisite for a second harness reporting Needs
    input: both the native notifier and the browser hardcoded Claude, so no other
    harness could raise a truthful alert.
    """

    def test_the_title_names_the_harness(self) -> None:
        self.assertEqual("Claude is waiting on you", notifications.waiting_title("Claude"))
        self.assertEqual(
            "Antigravity is waiting on you", notifications.waiting_title("Antigravity")
        )

    def test_the_popup_uses_the_label_it_was_given(self) -> None:
        config, state = make_runtime()
        fired: list[tuple[str, str]] = []
        notifications.maybe_popup(
            config,
            state,
            notifications.PopupSubject(
                harness="antigravity", label="Antigravity", prefix="abcdef12", activity=0.0
            ),
            "needs_input",
            "[proj] a question",
            popup_notifier=lambda title, message: fired.append((title, message)),
        )
        self.assertEqual([("Antigravity is waiting on you", "[proj] a question")], fired)

    def test_no_field_of_the_subject_has_a_default(self) -> None:
        # A defaulted label would let a second harness's collector wire itself in
        # and silently claim to be Claude, which is the exact failure this exists
        # to prevent. A defaulted activity reading is the same shape of mistake
        # one layer down: 0 reads as "this session has not moved", so forgetting
        # it would keep a lapsed dismissal suppressing the popup forever. mypy
        # catches both, and so does this.
        for missing in ("harness", "label", "prefix", "activity"):
            fields: dict[str, Any] = {
                "harness": "claude",
                "label": "Claude",
                "prefix": "abcdef12",
                "activity": 0.0,
            }
            del fields[missing]
            with self.subTest(missing=missing), self.assertRaises(TypeError):
                notifications.PopupSubject(**fields)

    def test_the_notify_route_label_is_a_property_of_the_route(self) -> None:
        # /api/notify is Claude Code's own Notification hook and nothing else
        # posts there, so the label is fixed rather than read from the body: a
        # `harness` field in that payload would be a value the server had to
        # trust from an unauthenticated caller.
        self.assertEqual("Claude", notifications.NOTIFY_HARNESS_LABEL)


class AskPopupTest(unittest.TestCase):
    """The alert for a question a session registered, which had none at all.

    The gate lane and this one are deliberately separate functions rather than
    one widened `maybe_popup`: four of that function's six gates are meaningless
    for an ask (there is no prior state to transition from, no SessionEnd
    generation, no repeated message) and two are harmful (its
    `last_session_state` write is per-session-prefix and only `clear_session`
    ever removes an entry).
    """

    def _rec(self) -> tuple[list[tuple[str, str]], Any]:
        fired: list[tuple[str, str]] = []
        return fired, lambda title, message: fired.append((title, message))

    def test_a_question_pops_with_the_label_the_registry_resolved(self) -> None:
        config, state = make_runtime()
        fired, rec = self._rec()
        notifications.maybe_ask_popup(
            config,
            state,
            notifications.AskSubject(
                harness="claude",
                sid="s-1",
                label="Claude",
                question="Ship it?",
                project="repo/proj",
            ),
            now=1000.0,
            popup_notifier=rec,
        )
        self.assertEqual([("Claude is asking you", "Ship it? · repo/proj")], fired)

        # An empty label is the common case, not an edge: the shipped stdio
        # server reports `unknown` for every client but Claude Code, and the
        # registry resolves that to "".
        config, state = make_runtime()
        fired, rec = self._rec()
        notifications.maybe_ask_popup(
            config,
            state,
            notifications.AskSubject(
                harness="claude", sid="s-1", label="", question="Ship it?", project="repo/proj"
            ),
            now=1000.0,
            popup_notifier=rec,
        )
        self.assertEqual([("An agent is asking you", "Ship it? · repo/proj")], fired)

        config, state = make_runtime()
        fired, rec = self._rec()
        notifications.maybe_ask_popup(
            config,
            state,
            notifications.AskSubject(
                harness="claude", sid="s-1", label="Claude", question="Ship it?", project=""
            ),
            now=1000.0,
            popup_notifier=rec,
        )
        self.assertEqual([("Claude is asking you", "Ship it?")], fired)

        self.assertEqual("Antigravity is asking you", notifications.asking_title("Antigravity"))
        self.assertEqual("An agent is asking you", notifications.asking_title(""))

    def test_a_burst_raises_one_popup_and_a_later_question_raises_another(self) -> None:
        config, state = make_runtime()
        fired, rec = self._rec()

        def ask(now: float) -> None:
            notifications.maybe_ask_popup(
                config,
                state,
                notifications.AskSubject(
                    harness="claude", sid="s-1", label="Claude", question=f"q{now}", project="p"
                ),
                now=now,
                popup_notifier=rec,
            )

        ask(1000.0)
        ask(1001.0)
        ask(1005.0)
        self.assertEqual(1, len(fired), "a burst outran the floor")
        ask(1000.0 + config.global_popup_cooldown_sec)
        self.assertEqual(2, len(fired))

        # The whole of the ask lane's floor bookkeeping. A per-ask key would be an
        # unbounded namespace in a cache that evicts by insertion order, and a
        # session prefix would leak into a map only `clear_session` cleans.
        self.assertEqual({"_ask"}, set(state.last_popup))
        self.assertEqual(1000.0 + config.global_popup_cooldown_sec, state.last_popup["_ask"])
        self.assertEqual({}, dict(state.last_session_state))

    def test_neither_lane_swallows_the_other(self) -> None:
        # A gate popup and an ask popup are answered in different places and
        # recover differently: Claude re-emits a standing gate notification for
        # as long as the session stays blocked, while nothing ever re-registers a
        # question and the sweep deletes it unanswered at `ask_deadline_sec`.
        # `maybe_popup` also consumes the transition (it writes
        # `last_session_state` above its cooldown gates), so a gate suppressed by
        # a shared floor is not delayed — it is gone for the whole block. So the
        # two lanes read and write separate floor keys.
        config, state = make_runtime()
        fired, rec = self._rec()

        def gate(prefix: str) -> None:
            notifications.maybe_popup(
                config,
                state,
                notifications.PopupSubject(
                    harness="claude", label="Claude", prefix=prefix, activity=0.0
                ),
                "needs_input",
                "[proj] gate",
                popup_notifier=rec,
            )

        def ask(now: float) -> None:
            notifications.maybe_ask_popup(
                config,
                state,
                notifications.AskSubject(
                    harness="claude", sid="s-1", label="Claude", question="q", project="p"
                ),
                now=now,
                popup_notifier=rec,
            )

        with mock.patch.object(time, "time", side_effect=[1000.0, 2001.0]):
            gate("aaaaaaaa")
            ask(1001.0)  # 1s after a gate popup, inside the 15s gate floor
            ask(2000.0)
            gate("bbbbbbbb")  # 1s after an ask popup

        self.assertEqual(
            [
                ("Claude is waiting on you", "[proj] gate"),
                ("Claude is asking you", "q · p"),
                ("Claude is asking you", "q · p"),
                ("Claude is waiting on you", "[proj] gate"),
            ],
            fired,
        )

    def test_a_long_question_never_publishes_a_truncated_project(self) -> None:
        # The defect `_ask_project` was written for, one layer up: `notify_mac`
        # bounds the message at 180 characters and `safe_text` keeps the head, so
        # composing question-then-project and letting that trim would publish a
        # path that is a prefix of the real one and reads as a whole directory.
        config, state = make_runtime()
        project = "/Users/dev/repos/exampleorg/compassxxxx/.claude/worktrees/drc-4183"
        # 66 characters, and the number is load-bearing: 111 + len(" \u00b7 ") + 66 is
        # exactly the 180-character bound, which is the boundary this pins.
        self.assertEqual(66, len(project))
        fits = "q" * 111
        fired, rec = self._rec()
        notifications.maybe_ask_popup(
            config,
            state,
            notifications.AskSubject(
                harness="claude", sid="s-1", label="Claude", question=fits, project=project
            ),
            now=1000.0,
            popup_notifier=rec,
        )
        self.assertEqual([("Claude is asking you", f"{fits} · {project}")], fired)
        self.assertEqual(180, len(fired[0][1]))

        config, state = make_runtime()
        fired, rec = self._rec()
        notifications.maybe_ask_popup(
            config,
            state,
            notifications.AskSubject(
                harness="claude", sid="s-1", label="Claude", question=fits + "q", project=project
            ),
            now=1000.0,
            popup_notifier=rec,
        )
        # One character over: the path is dropped whole rather than cut. A
        # dropped path is honest; a head-truncated one names a directory that
        # does not exist.
        self.assertEqual([("Claude is asking you", fits + "q")], fired)

        config, state = make_runtime()
        fired, rec = self._rec()
        notifications.maybe_ask_popup(
            config,
            state,
            notifications.AskSubject(
                harness="claude",
                sid="s-1",
                label="Claude",
                question="short",
                project="/" + "d" * 511,
            ),
            now=1000.0,
            popup_notifier=rec,
        )
        self.assertEqual([("Claude is asking you", "short")], fired)

    def test_the_ask_popup_runs_with_the_hook_lock_released(self) -> None:
        # hook_lock is a plain Lock and osascript has a 5s timeout. Notifying
        # inside the critical section would stall every hook POST and every
        # collection for that long.
        config, state = make_runtime()
        held: list[bool] = []

        def notifier(_title: str, _message: str) -> None:
            acquired = state.hook_lock.acquire(blocking=False)
            held.append(acquired)
            if acquired:
                state.hook_lock.release()

        notifications.maybe_ask_popup(
            config,
            state,
            notifications.AskSubject(
                harness="claude", sid="s-1", label="Claude", question="q", project="p"
            ),
            now=1000.0,
            popup_notifier=notifier,
        )
        self.assertEqual([True], held, "popup fired while still holding hook_lock")

    def test_no_field_of_the_ask_subject_has_a_default(self) -> None:
        # `label` is the field that can lie, and "" is a legal value meaning "not
        # a registry key" — so a default would make forgetting it look like
        # working code that titles every question with someone else's name.
        for missing in ("label", "question", "project"):
            fields: dict[str, Any] = {"label": "Claude", "question": "q", "project": "p"}
            del fields[missing]
            with self.subTest(missing=missing), self.assertRaises(TypeError):
                notifications.AskSubject(**fields)


def _popup_spec(key: str, label: str, rows: list[dict[str, Any]]) -> aggregate.HarnessSpec:
    """A stub harness publishing exactly the rows it was handed."""

    def discover(config: Any, state: Any) -> bool:
        del config, state
        return True

    def collect(
        config: Any,
        state: Any,
        now: float,
        window_hours: float,
        show_all: bool,
    ) -> list[Any]:
        del now, window_hours, show_all
        out = []
        for row in rows:
            session = runtime_sessions.base_session(key, row["sid"], "proj")
            session.update({k: v for k, v in row.items() if k != "ends_mid_collection"})
            if row.get("ends_mid_collection"):
                # A SessionEnd committing while this collection is in flight,
                # which is the window `expect_generation` exists to close.
                notifications.clear_session(state, config, str(row["sid"]))
            out.append(session)
        return out

    return aggregate.HarnessSpec(key=key, label=label, discover=discover, collect=collect)


class _StubOverlays:
    """An `OverlaySource` answering from a fixed table."""

    def __init__(self, table: dict[tuple[str, str], list[Any]]) -> None:
        self.table = table
        self.noted: set[tuple[str, str]] = set()

    def overlays_for(self, harness: str, sid: str) -> list[Any]:
        return list(self.table.get((harness, sid), ()))

    def finished_at(self, harness: str, sid: str) -> float:
        del harness, sid
        return 0.0

    def ended_at(self, harness: str, sid: str) -> float:
        """No end observed: this stub answers only about stops."""
        del harness, sid
        return 0.0

    def git_for(self, harness: str, sid: str) -> None:
        """Never probed: this stub has no repository behind it."""
        del harness, sid

    def focusable(self, harness: str, sid: str) -> bool:
        """No terminal identity: this stub observed no session start."""
        del harness, sid
        return False

    def note_rows(self, keys: set[tuple[str, str]]) -> None:
        self.noted = set(keys)

    def drop_counters(self) -> dict[str, int]:
        return {}

    def command_reports(self) -> list[dict[str, Any]]:
        return []


class ApplicationPopupTest(unittest.TestCase):
    """Who notifies for a gate, once the row is final rather than mid-collection.

    Every test here builds its own application over stub harnesses, so the
    subject is the layer that decides rather than any real store.
    """

    def setUp(self) -> None:
        self._home = tempfile.TemporaryDirectory()
        self.addCleanup(self._home.cleanup)
        self.popups: list[tuple[str, str]] = []

    def runtime(self, **changes: Any) -> tuple[Any, Any]:
        # `darwin`, because that is the platform the defect is on: the server
        # has a native backend there, so the browser layer stands down.
        return make_runtime(
            state_home=self._home.name,
            state_dir=Path(self._home.name),
            platform_name="darwin",
            **changes,
        )

    def application(
        self,
        harnesses: tuple[aggregate.HarnessSpec, ...],
        *,
        config: Any,
        state: Any,
        clock: float = 5_000.0,
        overlays: Any = None,
    ) -> aggregate.Application:
        return aggregate.Application(
            config,
            state,
            harnesses,
            native_notifier=notifications.native_notifier,
            popup_notifier=lambda title, message: self.popups.append((title, message)),
            diagnostic_sink=lambda _line: None,
            clock=lambda: clock,
            overlays=overlays,
        )

    def _gate_row(self, sid: str, **changes: Any) -> dict[str, Any]:
        row = {
            "sid": sid,
            "state": "needs_input",
            "state_detail": "permission requested",
            "active": True,
            "last_activity": 4_000.0,
        }
        row.update(changes)
        return row

    def test_a_non_claude_gate_pops_on_the_platform_where_the_browser_stands_down(self) -> None:
        # The defect itself. On macOS `native_notify` is non-empty, so notify.js
        # hands the alert to the server -- and the server fired for Claude alone,
        # because `maybe_popup` had one caller and it was Claude's collector. A
        # Codex row at a real gate therefore alerted nobody.
        spec = _popup_spec("codex", "Codex", [self._gate_row("codex-1")])
        config, state = self.runtime()
        collection = self.application((spec,), config=config, state=state).collect(show_all=False)

        self.assertEqual("osascript", collection["native_notify"])
        self.assertEqual([("Codex is waiting on you", "[proj] permission requested")], self.popups)

    def test_a_wait_only_the_event_lane_knows_about_pops(self) -> None:
        # The second half, silent for Claude too: the popup read the collector's
        # state, and `_apply_overlays` runs after every collector has returned.
        spec = _popup_spec(
            "claude",
            "Claude",
            [
                {
                    "sid": "abcd1234",
                    "state": "working",
                    "state_detail": "running Bash",
                    "active": True,
                    "last_activity": 4_000.0,
                }
            ],
        )
        config, state = self.runtime()
        # Built by the production reducer rather than by hand. `overlay_for`
        # sets no `detail` for any kind, so a hand-written one carrying a
        # question is a shape this lane cannot produce, and asserting against it
        # hid the body every event-lane gate actually gets.
        overlay = runtime_events.overlay_for(
            runtime_events.Event(
                harness="claude",
                event="input_requested",
                sid="abcd1234",
                session_id="abcd1234",
                timestamp=4_500.0,
                arrival_seq=1,
            ),
            config=config,
        )
        self.assertIsNone(overlay.detail if overlay else "")
        overlays = _StubOverlays({("claude", "abcd1234"): [overlay]})
        collection = self.application(
            (spec,), config=config, state=state, overlays=overlays
        ).collect(show_all=False)

        self.assertEqual(["needs_input"], [s["state"] for s in collection["sessions"]])
        # notify.js's own fallback, `(s.state_detail || "needs your input")`. The
        # server composes the body, so `maybe_popup`'s "Session … needs your
        # input" default cannot fire on a truthy f-string.
        self.assertEqual([("Claude is waiting on you", "[proj] needs your input")], self.popups)

    def test_a_standing_gate_pops_once_and_not_on_every_collection(self) -> None:
        spec = _popup_spec("codex", "Codex", [self._gate_row("codex-1")])
        config, state = self.runtime()
        application = self.application((spec,), config=config, state=state)
        application.collect(show_all=False)
        application.collect(show_all=False)
        application.collect(show_all=False)
        self.assertEqual(1, len(self.popups))

    def test_a_gate_the_machine_wide_floor_delayed_pops_once_the_floor_lifts(self) -> None:
        # Ten harnesses now share the floor only Claude used to write, so a gate
        # on one row can arrive while another row's popup still holds it. The
        # floor must DELAY that popup, never consume it: `maybe_popup` records
        # the transition into `last_session_state`, and a transition recorded
        # while floored fails the edge test on every later collection, so the
        # second gate is silent for as long as it stands. `maybe_ask_popup`
        # calls that same loss "actively harmful" and keys its floor apart to
        # avoid it.
        codex = _popup_spec("codex", "Codex", [self._gate_row("codex-1")])
        claude = _popup_spec("claude", "Claude", [self._gate_row("abcd1234")])
        config, state = self.runtime()
        application = self.application((codex, claude), config=config, state=state)
        application.collect(show_all=False)
        self.assertEqual([("Codex is waiting on you", "[proj] permission requested")], self.popups)

        # `maybe_popup` reads the wall clock, so the floor is retired by moving
        # the mark rather than the application's injected clock.
        state.last_popup["_global"] -= config.global_popup_cooldown_sec + 1
        application.collect(show_all=False)

        self.assertEqual(
            [
                ("Codex is waiting on you", "[proj] permission requested"),
                ("Claude is waiting on you", "[proj] permission requested"),
            ],
            self.popups,
        )

    def test_a_dismissed_gate_pops_for_nobody(self) -> None:
        spec = _popup_spec("codex", "Codex", [self._gate_row("codex-1")])
        config, state = self.runtime()
        dismissals.dismiss(config, state, "codex", "codex-1", now=4_500.0)
        self.application((spec,), config=config, state=state).collect(show_all=False)
        self.assertEqual([], self.popups)

    def test_a_session_that_ended_mid_collection_pops_for_nobody(self) -> None:
        # `expect_generation` is sampled before the harness loop and re-checked
        # under `hook_lock`, so a SessionEnd committing while the collection is
        # in flight cannot have the state it just cleared re-created by a popup.
        spec = _popup_spec(
            "claude", "Claude", [self._gate_row("abcd1234", ends_mid_collection=True)]
        )
        config, state = self.runtime()
        self.application((spec,), config=config, state=state).collect(show_all=False)
        self.assertEqual([], self.popups)

    def test_an_inactive_row_pops_for_nobody(self) -> None:
        spec = _popup_spec(
            "codex", "Codex", [self._gate_row("codex-1", active=False, last_activity=1.0)]
        )
        config, state = self.runtime()
        self.application((spec,), config=config, state=state).collect(show_all=True)
        self.assertEqual([], self.popups)

    def test_every_registry_row_is_titled_by_its_own_label(self) -> None:
        # `PopupSubject` keeps `harness` and `label` apart so a popup cannot name
        # the wrong harness. Whatever supplies them now has to get both right for
        # all ten rows, so this asserts against the registry, not a literal.
        # One runtime per harness, because the machine-wide floor would otherwise
        # swallow every popup after the first.
        for spec in REGISTRY:
            with self.subTest(harness=spec.key):
                self.popups.clear()
                stub = _popup_spec(spec.key, spec.label, [self._gate_row(f"{spec.key}-1")])
                config, state = self.runtime()
                self.application((stub,), config=config, state=state).collect(show_all=False)
                self.assertEqual(
                    [(f"{spec.label} is waiting on you", "[proj] permission requested")],
                    self.popups,
                )


class QuietHoursTest(RuntimeTestCase):
    def test_parse_quiet_hours(self) -> None:
        self.assertEqual((22, 0, 8, 0), notifications.parse_quiet_hours("22:00-08:00"))
        self.assertEqual((13, 30, 15, 45), notifications.parse_quiet_hours("13:30-15:45"))
        self.assertEqual((9, 5, 17, 30), notifications.parse_quiet_hours("9:05-17:30"))
        self.assertIsNone(notifications.parse_quiet_hours("invalid"))
        self.assertIsNone(notifications.parse_quiet_hours("25:00-08:00"))
        self.assertIsNone(notifications.parse_quiet_hours("12:60-14:00"))
        self.assertIsNone(notifications.parse_quiet_hours("12:00-12:00"))
        self.assertIsNone(notifications.parse_quiet_hours(""))
        self.assertIsNone(notifications.parse_quiet_hours(None))

    def test_is_quiet_hours_daytime_window(self) -> None:
        base_config, _ = runtime()
        config = dataclasses.replace(
            base_config, quiet_hours_enabled=True, quiet_hours="13:00-15:00"
        )

        # Construct timestamps with known local hours and minutes
        # 12:59
        t_1259 = time.mktime(datetime(2026, 9, 16, 12, 59, 0).timetuple())
        # 13:00
        t_1300 = time.mktime(datetime(2026, 9, 16, 13, 0, 0).timetuple())
        # 14:30
        t_1430 = time.mktime(datetime(2026, 9, 16, 14, 30, 0).timetuple())
        # 15:00
        t_1500 = time.mktime(datetime(2026, 9, 16, 15, 0, 0).timetuple())

        self.assertFalse(notifications.is_quiet_hours(config, now=t_1259))
        self.assertTrue(notifications.is_quiet_hours(config, now=t_1300))
        self.assertTrue(notifications.is_quiet_hours(config, now=t_1430))
        self.assertFalse(notifications.is_quiet_hours(config, now=t_1500))

    def test_is_quiet_hours_overnight_window(self) -> None:
        base_config, _ = runtime()
        config = dataclasses.replace(
            base_config, quiet_hours_enabled=True, quiet_hours="22:00-08:00"
        )

        t_2159 = time.mktime(datetime(2026, 9, 16, 21, 59, 0).timetuple())
        t_2200 = time.mktime(datetime(2026, 9, 16, 22, 0, 0).timetuple())
        t_2330 = time.mktime(datetime(2026, 9, 16, 23, 30, 0).timetuple())
        t_0200 = time.mktime(datetime(2026, 9, 16, 2, 0, 0).timetuple())
        t_0759 = time.mktime(datetime(2026, 9, 16, 7, 59, 0).timetuple())
        t_0800 = time.mktime(datetime(2026, 9, 16, 8, 0, 0).timetuple())
        t_1200 = time.mktime(datetime(2026, 9, 16, 12, 0, 0).timetuple())

        self.assertFalse(notifications.is_quiet_hours(config, now=t_2159))
        self.assertTrue(notifications.is_quiet_hours(config, now=t_2200))
        self.assertTrue(notifications.is_quiet_hours(config, now=t_2330))
        self.assertTrue(notifications.is_quiet_hours(config, now=t_0200))
        self.assertTrue(notifications.is_quiet_hours(config, now=t_0759))
        self.assertFalse(notifications.is_quiet_hours(config, now=t_0800))
        self.assertFalse(notifications.is_quiet_hours(config, now=t_1200))

    def test_quiet_hours_disabled_flag_overrides(self) -> None:
        base_config, _ = runtime()
        config = dataclasses.replace(
            base_config, quiet_hours_enabled=False, quiet_hours="22:00-08:00"
        )

        t_2330 = time.mktime(datetime(2026, 9, 16, 23, 30, 0).timetuple())
        self.assertFalse(notifications.is_quiet_hours(config, now=t_2330))

    def test_maybe_popup_suppressed_during_quiet_hours(self) -> None:
        base_config, state = runtime()
        config = dataclasses.replace(
            base_config, quiet_hours_enabled=True, quiet_hours="22:00-08:00"
        )

        t_quiet = time.mktime(datetime(2026, 9, 16, 23, 0, 0).timetuple())
        fired: list[tuple[str, str]] = []

        with mock.patch.object(time, "time", return_value=t_quiet):
            notifications.maybe_popup(
                config,
                state,
                notifications.PopupSubject(
                    harness="claude", label="Claude", prefix="sess1", activity=0.0
                ),
                "needs_input",
                "Needs input",
                popup_notifier=lambda t, m: fired.append((t, m)),
            )
        self.assertEqual([], fired)

        # Outside quiet hours, it fires
        t_active = time.mktime(datetime(2026, 9, 16, 10, 0, 0).timetuple())
        with mock.patch.object(time, "time", return_value=t_active):
            notifications.maybe_popup(
                config,
                state,
                notifications.PopupSubject(
                    harness="claude", label="Claude", prefix="sess2", activity=0.0
                ),
                "needs_input",
                "Needs input",
                popup_notifier=lambda t, m: fired.append((t, m)),
            )
        self.assertEqual([("Claude is waiting on you", "Needs input")], fired)

    def test_handle_payload_suppressed_during_quiet_hours(self) -> None:
        base_config, state = runtime()
        config = dataclasses.replace(
            base_config, quiet_hours_enabled=True, quiet_hours="22:00-08:00"
        )

        t_quiet = time.mktime(datetime(2026, 9, 16, 23, 0, 0).timetuple())
        fired: list[tuple[str, str]] = []

        payload = {
            "session_id": "sess12345678",
            "message": "Claude needs input",
            "notification_type": "permission_prompt",
        }
        res = notifications.handle_payload(
            config,
            state,
            payload,
            now=t_quiet,
            popup_notifier=lambda t, m: fired.append((t, m)),
        )
        self.assertTrue(res.get("ok"))
        self.assertEqual([], fired)
        # Hook is still saved for the dashboard UI
        self.assertIn("sess1234", state.hook_notifications)

    def test_maybe_ask_popup_not_suppressed_during_quiet_hours(self) -> None:
        base_config, state = runtime()
        config = dataclasses.replace(
            base_config, quiet_hours_enabled=True, quiet_hours="22:00-08:00"
        )

        t_quiet = time.mktime(datetime(2026, 9, 16, 23, 0, 0).timetuple())
        fired: list[tuple[str, str]] = []

        subject = notifications.AskSubject(
            harness="claude",
            sid="session-1",
            label="Claude",
            question="May I run command?",
            project="test-project",
        )
        notifications.maybe_ask_popup(
            config,
            state,
            subject,
            now=t_quiet,
            popup_notifier=lambda t, m: fired.append((t, m)),
        )
        # Direct questions are NOT suppressed
        self.assertEqual(
            [("Claude is asking you", "May I run command? \u00b7 test-project")], fired
        )

    def test_unasked_departure_suppressed_during_quiet_hours(self) -> None:
        base_config, _ = runtime()
        config = dataclasses.replace(
            base_config, quiet_hours_enabled=True, quiet_hours="22:00-08:00"
        )
        t_quiet = time.mktime(datetime(2026, 9, 16, 23, 0, 0).timetuple())
        fired: list[tuple[str, str]] = []
        lane = unasked.Lane(
            config,
            popup_notifier=lambda t, m: fired.append((t, m)),
            harness_label=lambda _h: "Claude",
        )
        row = {"harness": "claude", "sid": "s1"}
        raised: list[departures.Check] = [
            {
                "harness": "claude",
                "sid": "s1",
                "at": t_quiet,
                "constraint": "Goal",
                "clause": "Stay on topic",
                "reading": "drifted",
                "evidence": "irrelevant code",
                "revision": 1,
                "cutoff": t_quiet,
                "cutoff_text": "1 message",
                "withdrawn": False,
            }
        ]
        lane._raise(row, raised, now=t_quiet)
        self.assertEqual([], fired)

    def test_aggregate_collect_suppresses_reach_during_quiet_hours(self) -> None:
        base_config, state = runtime()
        config = dataclasses.replace(
            base_config, quiet_hours_enabled=True, quiet_hours="22:00-08:00"
        )
        t_quiet = time.mktime(datetime(2026, 9, 16, 23, 0, 0).timetuple())
        app = aggregate.Application(
            config,
            state,
            (),
            native_notifier=lambda _p: "",
            popup_notifier=lambda _t, _m: None,
            diagnostic_sink=lambda _line: None,
            clock=lambda: t_quiet,
        )
        with mock.patch("compass_runtime.reach.maybe_reach_nudge") as reach_mock:
            collection = app.collect(show_all=False)
            reach_mock.assert_not_called()
            self.assertTrue(collection["in_quiet_hours"])
