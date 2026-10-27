"""Find goal: a goal quoted from the reader's own prompts, found only on a press.

The producer is held to recorded answers, one per way a model can answer: a clear end state
quoted from the prompts, nothing, a paraphrase, a quote cited under the wrong prompt, a goal it
calls unclear and a reply that is not the shape asked for. The route is held by counting calls:
a press runs one, and nothing else (a board collection, a pause, a spent day, a session with no
prompts) runs none.
"""

from __future__ import annotations

import contextlib
import http.client
import json
import shutil
import tempfile
import threading
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from compass_runtime import aggregate, goal_find, http_api, reading_policy
from compass_runtime import annotations as annotation_store
from compass_runtime import observer as runtime_observer
from compass_runtime import reading as runtime_reading
from compass_runtime import reading_route as runtime_reading_route
from compass_runtime import sessions as runtime_sessions
from compass_runtime import supervise as runtime_supervise

from .support import make_runtime, make_server, serve_until_closed

NOW = 1_700_000_100.0
CAP = 240


def person(fact_id: str, at: float, words: str, *, harness: str = "claude") -> dict[str, Any]:
    return {
        "fact_id": fact_id,
        "type": "user_message",
        "at": at,
        "source_session": {"harness": harness, "sid": "s1"},
        runtime_reading.WORDS_FIELD: words,
    }


PROMPTS_TEXT = (
    "Please add a retry to the upload client so a dropped connection resumes.",
    "Also make sure the existing tests still pass.",
    "Thanks, that looks right.",
)


def prompts() -> list[goal_find.Prompt]:
    return goal_find.prompts_from_facts(
        [
            person("f1", 1_700_000_001.0, PROMPTS_TEXT[0]),
            person("f2", 1_700_000_002.0, PROMPTS_TEXT[1]),
            person("f3", 1_700_000_003.0, PROMPTS_TEXT[2]),
        ],
        ordinal={"f1": 1, "f2": 3, "f3": 5}.get,
    )


def answering(reply: Any, status: str = "ok") -> Any:
    """A model that records what it was sent and answers with `reply`."""
    calls: list[str] = []

    def model(prompt: str, *, output_cap_bytes: int) -> tuple[str, str]:
        del output_cap_bytes
        calls.append(prompt)
        return (reply if isinstance(reply, str) else json.dumps(reply)), status

    model.calls = calls  # type: ignore[attr-defined]
    return model


CLEAR: dict[str, Any] = {
    "goal": "The upload client retries a dropped connection and resumes the upload, with the existing tests passing.",
    "clear": True,
    "quotes": [
        {"prompt": 1, "text": "add a retry to the upload client so a dropped connection resumes"},
        {"prompt": 2, "text": "make sure the existing tests still pass"},
    ],
}


class WhatTheModelIsSentTest(unittest.TestCase):
    def test_only_the_readers_prompts_are_numbered_and_sent(self) -> None:
        facts = [
            person("f1", 1_700_000_001.0, PROMPTS_TEXT[0]),
            {**person("a1", 1_700_000_002.0, "I finished the retry."), "type": "agent_message"},
            {
                **person("c1", 1_700_000_003.0, "pasted correction"),
                runtime_reading.COPIED_FLAG: True,
            },
            person("f2", 1_700_000_004.0, PROMPTS_TEXT[1]),
        ]
        found = goal_find.prompts_from_facts(facts, ordinal=lambda _fact_id: None)
        self.assertEqual(["f1", "f2"], [p.fact_id for p in found])
        self.assertEqual([1, 2], [p.number for p in found])
        model = answering({"goal": None})
        goal_find.find(found, model, goal_cap=CAP)
        (sent,) = model.calls
        self.assertIn(PROMPTS_TEXT[0], sent)
        self.assertIn(PROMPTS_TEXT[1], sent)
        self.assertNotIn("I finished the retry", sent)
        self.assertNotIn("pasted correction", sent)

    def test_the_prompt_says_to_quote_to_refuse_a_vague_goal_and_to_treat_prompts_as_data(
        self,
    ) -> None:
        text = goal_find.build_prompt(prompts())
        self.assertIn("untrusted", text)
        self.assertIn("exact words", text)
        self.assertIn("end state the work can be read against", text)
        self.assertIn("end state the work can be read against", runtime_reading.GOAL_UNCLEAR_RULE)

    def test_many_prompts_keep_the_first_and_the_latest_and_stay_bounded(self) -> None:
        facts = [
            person(f"f{n}", 1_700_000_000.0 + n, f"prompt number {n} " + "x" * 3000)
            for n in range(1, 101)
        ]
        found = goal_find.prompts_from_facts(facts, ordinal=lambda _fact_id: None)
        self.assertLessEqual(len(found), goal_find.MAX_PROMPTS)
        self.assertEqual("f1", found[0].fact_id)
        self.assertEqual("f100", found[-1].fact_id)
        self.assertLessEqual(sum(len(p.text) for p in found), goal_find.TOTAL_CHARS)

    def test_no_prompts_runs_no_call(self) -> None:
        model = answering(CLEAR)
        result = goal_find.find([], model, goal_cap=CAP)
        self.assertEqual([], model.calls)
        self.assertIsNone(result.found)
        self.assertEqual(goal_find.WHY_NO_PROMPTS, result.why)
        self.assertFalse(result.called)


class ARecordedAnswerTest(unittest.TestCase):
    def test_a_clear_end_state_is_found_with_a_citation_for_each_prompt_it_quotes(self) -> None:
        result = goal_find.find(prompts(), answering(CLEAR), goal_cap=CAP)
        self.assertTrue(result.called)
        self.assertEqual("", result.why)
        found = result.found
        assert found is not None
        self.assertEqual(CLEAR["goal"], found["goal"])
        self.assertEqual(
            [
                {
                    "fact_id": "f1",
                    "ordinal": 1,
                    "at": 1_700_000_001.0,
                    "quotes": ["add a retry to the upload client so a dropped connection resumes"],
                },
                {
                    "fact_id": "f2",
                    "ordinal": 3,
                    "at": 1_700_000_002.0,
                    "quotes": ["make sure the existing tests still pass"],
                },
            ],
            found["cites"],
        )

    def test_conflicting_prompts_the_model_will_not_resolve_find_nothing(self) -> None:
        result = goal_find.find(
            prompts(), answering({"goal": None, "clear": False, "quotes": []}), goal_cap=CAP
        )
        self.assertIsNone(result.found)
        self.assertEqual(goal_find.WHY_NONE, result.why)
        self.assertTrue(result.called)

    def test_a_paraphrase_is_dropped_because_its_quote_is_not_in_a_sent_prompt(self) -> None:
        paraphrased = {
            **CLEAR,
            "quotes": [{"prompt": 1, "text": "add retries to the uploader so it resumes"}],
        }
        result = goal_find.find(prompts(), answering(paraphrased), goal_cap=CAP)
        self.assertIsNone(result.found)
        self.assertEqual(goal_find.WHY_PARAPHRASED, result.why)

    def test_one_paraphrased_quote_drops_the_goal_even_beside_a_verbatim_one(self) -> None:
        mixed = {
            **CLEAR,
            "quotes": [
                CLEAR["quotes"][0],
                {"prompt": 2, "text": "keep the old tests green"},
            ],
        }
        result = goal_find.find(prompts(), answering(mixed), goal_cap=CAP)
        self.assertIsNone(result.found)
        self.assertEqual(goal_find.WHY_PARAPHRASED, result.why)

    def test_a_quote_is_checked_against_the_prompt_it_cites_and_no_other(self) -> None:
        wrong = {**CLEAR, "quotes": [{"prompt": 2, "text": CLEAR["quotes"][0]["text"]}]}
        result = goal_find.find(prompts(), answering(wrong), goal_cap=CAP)
        self.assertIsNone(result.found)
        self.assertEqual(goal_find.WHY_PARAPHRASED, result.why)

    def test_a_quote_of_a_prompt_that_was_not_sent_is_dropped(self) -> None:
        absent = {**CLEAR, "quotes": [{"prompt": 9, "text": "add a retry"}]}
        result = goal_find.find(prompts(), answering(absent), goal_cap=CAP)
        self.assertIsNone(result.found)
        self.assertEqual(goal_find.WHY_PARAPHRASED, result.why)

    def test_a_quote_differing_only_in_case_is_not_verbatim(self) -> None:
        shouted = {**CLEAR, "quotes": [{"prompt": 1, "text": "ADD A RETRY TO THE UPLOAD CLIENT"}]}
        result = goal_find.find(prompts(), answering(shouted), goal_cap=CAP)
        self.assertEqual(goal_find.WHY_PARAPHRASED, result.why)

    def test_a_quote_may_differ_from_a_prompt_in_whitespace_alone(self) -> None:
        spaced = {**CLEAR, "quotes": [{"prompt": 1, "text": "add a  retry\nto the upload client"}]}
        result = goal_find.find(prompts(), answering(spaced), goal_cap=CAP)
        self.assertIsNotNone(result.found)

    def test_a_goal_with_no_quote_is_dropped(self) -> None:
        for quotes in (
            [],
            None,
            "none",
            [{"prompt": 1, "text": ""}],
            [{"prompt": 1}],
            [{"prompt": 1, "text": "retry"}],
            [{"prompt": True, "text": CLEAR["quotes"][0]["text"]}],
        ):
            with self.subTest(quotes=quotes):
                result = goal_find.find(
                    prompts(), answering({**CLEAR, "quotes": quotes}), goal_cap=CAP
                )
                self.assertIsNone(result.found)
                self.assertEqual(goal_find.WHY_UNQUOTED, result.why)

    def test_a_goal_the_model_calls_unclear_is_never_shown(self) -> None:
        for clear in (False, None, "yes", 1):
            with self.subTest(clear=clear):
                result = goal_find.find(
                    prompts(), answering({**CLEAR, "clear": clear}), goal_cap=CAP
                )
                self.assertIsNone(result.found)
                self.assertEqual(goal_find.WHY_UNCLEAR, result.why)

    def test_a_goal_longer_than_the_field_holds_is_dropped_not_cut(self) -> None:
        long = {**CLEAR, "goal": "It works. " * 40}
        result = goal_find.find(prompts(), answering(long), goal_cap=CAP)
        self.assertIsNone(result.found)
        self.assertEqual(goal_find.WHY_TOO_LONG, result.why)

    def test_a_reply_that_is_not_the_asked_shape_is_dropped(self) -> None:
        for reply in (
            "",
            "no goal",
            "[]",
            '{"goal": 3}',
            "{not json",
            '{"goal": "x", "clear": true}',
        ):
            with self.subTest(reply=reply):
                result = goal_find.find(prompts(), answering(reply), goal_cap=CAP)
                self.assertIsNone(result.found)

    def test_a_reply_wrapped_in_a_fence_is_read(self) -> None:
        fenced = "```json\n" + json.dumps(CLEAR) + "\n```"
        self.assertIsNotNone(goal_find.find(prompts(), answering(fenced), goal_cap=CAP).found)

    def test_a_failed_call_is_reported_as_one(self) -> None:
        result = goal_find.find(prompts(), answering("", "failed"), goal_cap=CAP)
        self.assertIsNone(result.found)
        self.assertEqual(goal_find.WHY_MODEL_FAILED, result.why)
        unavailable = goal_find.find(prompts(), answering("", "unavailable"), goal_cap=CAP)
        self.assertEqual(goal_find.WHY_MODEL_UNAVAILABLE, unavailable.why)
        self.assertFalse(unavailable.called)


class FindGoalRouteTest(unittest.TestCase):
    """POST /api/goal/find over a real socket, counting what it sends and charges."""

    def _runtime(self, **changes: Any) -> Any:
        home = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, home, True)
        patcher = mock.patch.object(runtime_supervise, "_SHUTDOWN", threading.Event())
        patcher.start()
        self.addCleanup(patcher.stop)
        changes.setdefault("annotations_enabled", True)
        changes.setdefault("observer_model_enabled", True)
        config, state = make_runtime(state_home=home, state_dir=Path(home), **changes)
        reading_policy.set_consent(config, True, now=NOW)
        return config, state

    @staticmethod
    def _harness(harness: str = "claude") -> Any:
        def collect(*_args: Any) -> list[dict[str, Any]]:
            row = runtime_sessions.base_session(harness, "s1", "proj")
            row.update({"state": "working", "active": True, "last_activity": 1_700_000_000.0})
            return [row]

        return aggregate.HarnessSpec(
            key=harness, label=harness.title(), discover=lambda *_: True, collect=collect
        )

    def _app(self, config: Any, state: Any, harness: str = "claude") -> Any:
        return aggregate.Application(
            config,
            state,
            (self._harness(harness),),
            native_notifier=lambda _p: "",
            popup_notifier=lambda _t, _b: None,
            diagnostic_sink=lambda _m: None,
            clock=lambda: NOW,
        )

    @contextlib.contextmanager
    def _serving(self, application: Any) -> Any:
        httpd = make_server(application=application)
        thread = serve_until_closed(httpd)
        try:
            yield httpd.server_port
        finally:
            httpd.shutdown()
            thread.join(timeout=5)

    @contextlib.contextmanager
    def _model(
        self, reply: Any = CLEAR, *, status: str = "ok", facts: list[dict[str, Any]] | None = None
    ) -> Any:
        """A Claude model that counts calls, and the reader's prompts the route finds."""
        calls: list[str] = []
        sent = (
            facts
            if facts is not None
            else [
                person("f1", 1_700_000_001.0, PROMPTS_TEXT[0]),
                person("f2", 1_700_000_002.0, PROMPTS_TEXT[1]),
            ]
        )

        class Model:
            unavailable_reason = runtime_reading.WITHHELD_CLAUDE_UNAVAILABLE

            def __init__(self, _config: Any, **_kw: Any) -> None:
                pass

            def __call__(self, prompt: str, **_kw: Any) -> tuple[str, str]:
                calls.append(prompt)
                return (reply if isinstance(reply, str) else json.dumps(reply)), status

            def available(self) -> bool:
                return True

        with (
            mock.patch.object(runtime_reading, "ClaudeReadingModel", Model),
            mock.patch.object(runtime_reading, "CodexReadingModel", Model),
            mock.patch.object(
                shutil, "which", lambda name: f"/usr/local/bin/{name}" if name == "claude" else None
            ),
            mock.patch.object(runtime_reading_route, "destination", lambda *_a, **_k: ""),
            mock.patch.object(http_api, "_prompt_facts", lambda *_a, **_k: sent),
            mock.patch.object(http_api, "_session_context", lambda *_a, **_k: {}),
        ):
            yield calls

    @staticmethod
    def _press(**over: Any) -> dict[str, Any]:
        body = {
            "harness": "claude",
            "sid": "s1",
            "press": True,
            "observer_model": 1,
            "provider": "claude",
            "model": runtime_observer.CLAUDE_READING_MODEL,
        }
        body.update(over)
        return body

    @staticmethod
    def _post(port: int, payload: Any, *, headers: dict[str, str] | None = None) -> tuple[int, Any]:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        try:
            conn.request(
                "POST",
                "/api/goal/find",
                body=json.dumps(payload).encode(),
                headers={"Content-Type": "application/json", **(headers or {})},
            )
            response = conn.getresponse()
            body = response.read()
            return response.status, (json.loads(body) if body.startswith(b"{") else body)
        finally:
            conn.close()

    def _used(self, config: Any) -> int:
        return reading_policy.status(config, now=NOW)["used"]

    def test_a_press_runs_one_call_charges_one_and_answers_the_goal(self) -> None:
        config, state = self._runtime()
        with self._model() as calls, self._serving(self._app(config, state)) as port:
            status, body = self._post(port, self._press())
        self.assertEqual(200, status, body)
        self.assertEqual(1, len(calls))
        self.assertEqual(1, self._used(config))
        self.assertTrue(body["produced"])
        self.assertEqual(CLEAR["goal"], body["found"]["goal"])
        self.assertEqual(["f1", "f2"], [cite["fact_id"] for cite in body["found"]["cites"]])
        self.assertEqual("Claude Code", body["route"]["label"])
        self.assertIn(PROMPTS_TEXT[0], calls[0])

    def test_nothing_runs_without_a_press(self) -> None:
        config, state = self._runtime()
        application = self._app(config, state)
        with self._model() as calls, self._serving(application) as port:
            for _ in range(3):
                application.collect_json(show_all=False)
            for body in (self._press(press=False), self._press(press=None)):
                status, _ = self._post(port, body)
                self.assertEqual(400, status)
            status, _ = self._post(port, self._press(observer_model=0))
            self.assertEqual(400, status)
        self.assertEqual([], calls)
        self.assertEqual(0, self._used(config))

    def test_nothing_runs_while_model_calls_are_paused(self) -> None:
        config, state = self._runtime()
        reading_policy.set_consent(config, False, now=NOW)
        with self._model() as calls, self._serving(self._app(config, state)) as port:
            status, body = self._post(port, self._press())
        self.assertEqual(403, status, body)
        self.assertEqual("model-calls-paused", body["reading"]["reason"])
        self.assertFalse(body["produced"])
        self.assertEqual([], calls)
        self.assertEqual(0, self._used(config))

    def test_nothing_runs_under_the_startup_switch_that_turns_model_calls_off(self) -> None:
        config, state = self._runtime(model_calls_disabled=True)
        with self._model() as calls, self._serving(self._app(config, state)) as port:
            status, _ = self._post(port, self._press())
        self.assertEqual(503, status)
        self.assertEqual([], calls)

    def test_a_spent_day_refuses_before_the_model_and_a_press_counts_against_it(self) -> None:
        config, state = self._runtime()
        with self._model() as calls, self._serving(self._app(config, state)) as port:
            for _ in range(reading_policy.DAILY_CAP):
                status, _ = self._post(port, self._press())
                self.assertEqual(200, status)
            status, body = self._post(port, self._press())
        self.assertEqual(429, status)
        self.assertEqual("daily-cap", body["reading"]["reason"])
        self.assertEqual(reading_policy.DAILY_CAP, len(calls))

    def test_a_reply_goes_out_after_the_press_is_no_longer_marked_running(self) -> None:
        # Measured in CI 2026-10-23: the mark was cleared after the reply, so a press sent as soon
        # as the last answer arrived could be refused "in-flight" (the spent-day test above, 409).
        held_at_send: list[int] = []
        send = http_api._RequestHandler._send

        def spy(handler: Any, *args: Any, **kwargs: Any) -> None:
            with http_api._GOAL_FINDING_LOCK:
                held_at_send.append(len(http_api._GOAL_FINDING))
            send(handler, *args, **kwargs)

        config, state = self._runtime()
        with (
            self._model(),
            mock.patch.object(http_api._RequestHandler, "_send", spy),
            self._serving(self._app(config, state)) as port,
        ):
            status, _ = self._post(port, self._press())
            self.assertEqual(200, status)
            with mock.patch.object(reading_policy, "DAILY_CAP", 1):
                status, _ = self._post(port, self._press())
            self.assertEqual(429, status)
        self.assertEqual([0, 0], held_at_send)

    def test_a_paraphrase_is_charged_because_the_call_ran_but_shows_no_goal(self) -> None:
        config, state = self._runtime()
        paraphrased = {**CLEAR, "quotes": [{"prompt": 1, "text": "add retries to the uploader"}]}
        with self._model(paraphrased) as calls, self._serving(self._app(config, state)) as port:
            status, body = self._post(port, self._press())
        self.assertEqual(200, status)
        self.assertEqual(1, len(calls))
        self.assertEqual(1, self._used(config))
        self.assertFalse(body["produced"])
        self.assertIsNone(body["found"])
        self.assertEqual(goal_find.WHY_PARAPHRASED, body["why"])

    def test_a_session_with_no_prompts_sends_nothing_and_charges_nothing(self) -> None:
        config, state = self._runtime()
        with self._model(facts=[]) as calls, self._serving(self._app(config, state)) as port:
            status, body = self._post(port, self._press())
        self.assertEqual(200, status)
        self.assertEqual([], calls)
        self.assertEqual(0, self._used(config))
        self.assertEqual(goal_find.WHY_NO_PROMPTS, body["why"])

    def test_a_receiver_that_moved_since_the_page_drew_it_is_refused_before_any_call(self) -> None:
        config, state = self._runtime()
        with self._model() as calls, self._serving(self._app(config, state)) as port:
            status, body = self._post(port, self._press(provider="codex"))
            self.assertEqual(409, status)
            self.assertEqual("provider-changed", body["reason"])
            status, body = self._post(port, self._press(model="another-model"))
            self.assertEqual(409, status)
        self.assertEqual([], calls)

    def test_an_unknown_session_answers_like_a_known_one_that_found_nothing(self) -> None:
        config, state = self._runtime()
        with self._model() as calls, self._serving(self._app(config, state)) as port:
            status, body = self._post(port, self._press(sid="nope"))
        self.assertEqual(200, status)
        self.assertFalse(body["produced"])
        self.assertEqual([], calls)

    def test_a_harness_with_no_prompt_to_adopt_is_not_read(self) -> None:
        config, state = self._runtime()
        with self._model() as calls, self._serving(self._app(config, state, "pi")) as port:
            status, body = self._post(port, self._press(harness="pi", provider="codex"))
        self.assertEqual(200, status)
        self.assertFalse(body["produced"])
        self.assertEqual([], calls)

    def test_a_lured_request_runs_nothing(self) -> None:
        config, state = self._runtime()
        with self._model() as calls, self._serving(self._app(config, state)) as port:
            for headers in (
                {"Sec-Fetch-Site": "same-site"},
                {"Sec-Fetch-Mode": "navigate", "Sec-Fetch-Dest": "document"},
            ):
                status, _ = self._post(port, self._press(), headers=headers)
                self.assertEqual(403, status)
        self.assertEqual([], calls)
        self.assertEqual(0, self._used(config))

    def test_nothing_is_stored_in_the_annotation_store(self) -> None:
        config, state = self._runtime()
        with self._model() as _calls, self._serving(self._app(config, state)) as port:
            self._post(port, self._press())
        self.assertIsNone(annotation_store.find(annotation_store.load(config), "claude", "s1"))


if __name__ == "__main__":
    unittest.main()
