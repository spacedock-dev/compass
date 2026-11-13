"""DEC-22 keeps the source words, clock and provenance together."""

from __future__ import annotations

import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest import mock

from compass_runtime import annotations as annotation_store
from compass_runtime import history, http_api, reading, reading_route, transcripts
from compass_runtime.state import build_runtime_state

from . import test_http_api, test_reading, test_transcripts, test_unasked
from .support import make_runtime


class PromptPublicationTest(unittest.TestCase):
    def test_codex_latest_timestamp_belongs_to_the_published_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as home:
            config, state = make_runtime()
            path = Path(home, "rollout.jsonl")
            path.write_text(
                json.dumps(
                    test_transcripts.CodexInstructionTest._user_old(
                        10, "Build the parser and test every token type"
                    )
                )
                + "\n"
            )
            result = transcripts.codex_instruction(config, state, str(path))
            self.assertEqual(1780000010.0, result.get("prompt_at"))

    def test_first_prompt_is_recorded_user_text_not_a_title_or_compaction(self) -> None:
        first = getattr(transcripts, "first_prompt", None)
        self.assertIsNotNone(first, "no recorded first-prompt producer exists")
        assert first is not None
        with tempfile.TemporaryDirectory() as home:
            config, state = make_runtime()
            path = Path(home, "claude.jsonl")
            rows = [
                {"type": "ai-title", "aiTitle": "Agent invented title"},
                {
                    "type": "user",
                    "isCompactSummary": True,
                    "message": {
                        "role": "user",
                        "content": "A generated summary naming work we did",
                    },
                },
                {
                    "type": "user",
                    "isSidechain": True,
                    "timestamp": "2026-05-29T01:46:40Z",
                    "message": {
                        "role": "user",
                        "content": "Worker instructions must not become the root goal",
                    },
                },
                {
                    "type": "user",
                    "timestamp": "2026-05-29T01:46:50Z",
                    "message": {
                        "role": "user",
                        "content": "Build the parser and test every token type",
                    },
                },
                {
                    "type": "user",
                    "timestamp": "2026-05-29T01:47:00Z",
                    "message": {
                        "role": "user",
                        "content": "Now change the lexer and leave the parser alone",
                    },
                },
            ]
            path.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
            result = first(config, state, str(path), "claude")
            self.assertEqual("Build the parser and test every token type", result["first_prompt"])
            self.assertEqual(1780019210.0, result["first_prompt_at"])


class AdoptionStoreTest(unittest.TestCase):
    def test_adoption_preserves_source_time_and_typed_edit_removes_it(self) -> None:
        with tempfile.TemporaryDirectory() as home:
            config, state = make_runtime(state_home=home, state_dir=Path(home))
            adopt = getattr(annotation_store, "adopt", None)
            self.assertIsNotNone(adopt, "no adoption through the annotation writer")
            assert adopt is not None
            row = {
                "harness": "claude",
                "sid": "s1",
                "instruction": {"label": "asked", "text": "Build the parser", "at": 10.0},
            }
            result = adopt(
                config,
                state,
                row,
                source="latest-prompt",
                expected_text="Build the parser",
                expected_at=10.0,
                now=30.0,
            )
            self.assertEqual(annotation_store.OUTCOME_STORED, result)
            entry = annotation_store.find(annotation_store.load(config), "claude", "s1")
            assert entry is not None
            revision = entry["revisions"][-1]
            self.assertEqual(30.0, revision["at"])
            self.assertEqual(10.0, revision["goal_source_at"])
            self.assertEqual("latest-prompt", revision["goal_source"])
            annotation_store.annotate(config, state, "claude", "s1", output="An AST", now=31.0)
            self.assertEqual(
                "latest-prompt", annotation_store.load(config)[0]["revisions"][-1]["goal_source"]
            )
            annotation_store.annotate(
                config, state, "claude", "s1", goal="Build the parser", now=32.0
            )
            self.assertEqual(
                "typed", annotation_store.published(annotation_store.load(config)[0])["goal_source"]
            )

    def test_adopted_baseline_uses_source_time_for_final_eligibility(self) -> None:
        effective = getattr(reading, "baseline_at", None)
        self.assertIsNotNone(effective, "adopted source clock has no eligibility path")
        assert effective is not None
        revision = {"at": 30.0, "goal_source": "first-prompt", "goal_source_at": 10.0}
        scope, why = reading.eligibility(
            {"state": "idle", "ended_at": 20.0},
            latest_revision_at=effective(revision),
            now=100.0,
            settle_sec=8.0,
        )
        self.assertEqual(("final", ""), (scope, why))


class AdoptionRouteTest(unittest.TestCase):
    def test_one_press_adopts_before_the_mocked_reading(self) -> None:
        helper = test_http_api.ReadingRouteTest()
        self.addCleanup(helper.doCleanups)
        config, state = helper._runtime(observer_model_enabled=False)
        app = helper._app(config, state)
        row = {
            "harness": "claude",
            "sid": "adopt",
            "state": "working",
            "instruction": {"label": "asked", "text": "Build the parser", "at": 1700000000.0},
        }
        app.collect_json = lambda **_: (1, json.dumps({"sessions": [row]}).encode())
        handler: Any = object.__new__(http_api._RequestHandler)
        handler.server = SimpleNamespace(application=app)
        replies = []
        handler._send = lambda body, *_args: replies.append(json.loads(body))
        handler._reject = lambda code: self.fail(f"unexpected refusal {code}")
        payload = {
            "harness": "claude",
            "sid": "adopt",
            "press": True,
            "observer_model": 1,
            "adopt": "latest-prompt",
            "expected_prompt": "Build the parser",
            "expected_prompt_at": 1700000000.0,
            # What the page names for a Claude Code session with only Codex on PATH.
            "provider": "codex",
        }
        body = json.dumps(payload).encode()
        handler.headers = test_http_api._headers(
            {"Host": "127.0.0.1:4580", "Content-Length": str(len(body))}
        )
        handler.client_address = ("127.0.0.1", 10000)
        handler.server.server_port = 4580
        handler.rfile = io.BytesIO(body)
        codex_on_path = mock.patch.object(
            shutil, "which", lambda name: f"/usr/local/bin/{name}" if name == "codex" else None
        )
        # This machine's endpoint settings must not decide an adoption test:
        # with no nameable destination the press asks nothing about tool output.
        unnamed = mock.patch.object(reading_route, "destination", return_value="")
        with (
            codex_on_path,
            unnamed,
            mock.patch.object(
                handler, "_compose_reading", return_value=(None, "test", False)
            ) as compose,
        ):
            handler._reading()
        self.assertEqual(1, compose.call_count)
        self.assertEqual("Build the parser", compose.call_args.args[1]["revisions"][-1]["goal"])
        self.assertTrue(replies[-1]["ok"])
        annotation_store.clear(config, state, "claude", "adopt", now=1700000050.0)
        handler.rfile = io.BytesIO(body)
        original_send = handler._send_reading

        def changed_before_send(*args: Any, **kwargs: Any) -> None:
            annotation_store.annotate(
                config, state, "claude", "adopt", goal="A different typed goal", now=1700000101.0
            )
            original_send(*args, **kwargs)

        with (
            codex_on_path,
            mock.patch.object(reading_route, "destination", return_value=""),
            mock.patch.object(handler, "_send_reading", side_effect=changed_before_send),
            mock.patch.object(
                handler, "_compose_reading", return_value=(None, "test", False)
            ) as compose,
        ):
            handler._reading()
        self.assertEqual(0, compose.call_count, "check ran against the replacement goal")
        self.assertTrue(replies[-1]["adoption_refused"])


class APersonAnalyzesADraft(unittest.TestCase):
    def setUp(self) -> None:
        self.route = test_http_api.ReadingRouteTest()
        self.addCleanup(self.route.doCleanups)
        self.config, self.state = self.route._runtime()
        self.application = self.route._app(
            self.config,
            self.state,
            harness="claude",
            row={"first_prompt": "Build the parser", "first_prompt_at": 1_700_000_000.0},
        )
        Path(annotation_store.store_path(self.config)).unlink()
        self.payload = self.route._press(
            harness="claude",
            adopt="first-prompt",
            expected_prompt="Build the parser",
            expected_prompt_at=1_700_000_000.0,
            expected_revision=0,
        )

    def entry(self) -> Any:
        return annotation_store.find(annotation_store.load(self.config), "claude", "s1")

    def test_a_persons_discard_survives_keep_when_no_analysis_starts(self) -> None:
        # Losing the Keep opt-in to the locked discard guard resurrects the
        # draft: both the unsaved page and a discard publish revision zero.
        for boundary in ("before press", "before locked write"):
            with self.subTest(boundary=boundary):
                Path(annotation_store.store_path(self.config)).unlink(missing_ok=True)
                other = build_runtime_state(self.config, started=1_700_000_050.0)
                discarded: list[Any] = []

                def discard(other: Any = other, discarded: list[Any] = discarded) -> None:
                    annotation_store.annotate(
                        self.config, other, "claude", "s1", goal="Another tabs goal"
                    )
                    annotation_store.clear(self.config, other, "claude", "s1")
                    discarded.append(self.entry())

                original = annotation_store.adopt

                def discard_then_adopt(
                    *args: Any,
                    boundary: str = boundary,
                    discard: Any = discard,
                    original: Any = original,
                    **kwargs: Any,
                ) -> str:
                    if boundary == "before locked write":
                        discard()
                    return cast("str", original(*args, **kwargs))

                if boundary == "before press":
                    discard()
                with (
                    self.route._counting_model(harness="claude") as calls,
                    self.route._serving(self.application) as port,
                    mock.patch.object(annotation_store, "adopt", side_effect=discard_then_adopt),
                ):
                    status, raw = self.route._post(
                        port,
                        {**self.payload, "settle_through": 1_700_000_050.0},
                        path="/api/annotate",
                    )
                answer = json.loads(raw)
                self.assertEqual((200, "refused"), (status, answer["outcome"]))
                self.assertFalse(answer["persisted"], "Keep claimed the draft was saved")
                self.assertIsNone(answer["saved_revision"], "Keep issued a success receipt")
                self.assertIsNone(answer["revision"])
                self.assertTrue(annotation_store.is_discarded(self.entry()))
                self.assertEqual(discarded[0], self.entry(), "Keep changed the discarded words")
                self.assertEqual([], calls, "Keep started an analysis")
                self.assertEqual({}, reading.published_jobs(self.config))
                self.assertEqual([], self.route.outcomes)

    def test_a_persons_discard_survives_analyze_before_and_after_prompt_recollection(self) -> None:
        # Removing the locked discard guard, or failing to opt Analyze into it,
        # resurrects the goal and starts a model from words the reader discarded.
        for boundary in (
            "before recollection",
            "before locked write",
            "Keep before recollection",
            "Keep before locked write",
        ):
            for other_dashboard in (False, True):
                with self.subTest(boundary=boundary, other_dashboard=other_dashboard):
                    Path(annotation_store.store_path(self.config)).unlink(missing_ok=True)
                    writer = (
                        build_runtime_state(self.config, started=1_700_000_100.0)
                        if other_dashboard
                        else self.state
                    )
                    discarded: list[Any] = []
                    target = (
                        http_api._RequestHandler
                        if boundary.endswith("before recollection")
                        else annotation_store
                    )
                    name = "_adopt_prompt" if boundary.endswith("before recollection") else "adopt"
                    original = getattr(target, name)

                    def discard_then_adopt(
                        *args: Any,
                        writer: Any = writer,
                        discarded: list[Any] = discarded,
                        original: Any = original,
                        **kwargs: Any,
                    ) -> str:
                        annotation_store.annotate(
                            self.config, writer, "claude", "s1", goal="Another tabs goal"
                        )
                        annotation_store.clear(self.config, writer, "claude", "s1")
                        discarded.append(self.entry())
                        return cast("str", original(*args, **kwargs))

                    with (
                        self.route._counting_model(harness="claude") as calls,
                        self.route._serving(self.application) as port,
                        mock.patch.object(
                            target, name, autospec=True, side_effect=discard_then_adopt
                        ),
                    ):
                        status, raw = self.route._post(
                            port,
                            {
                                **self.payload,
                                **(
                                    {"settle_through": 1_700_000_050.0}
                                    if boundary.startswith("Keep")
                                    else {}
                                ),
                            },
                        )
                    answer = json.loads(raw)
                    self.assertFalse(answer["ok"], "Analyze claimed success after a discard")
                    self.assertTrue(annotation_store.is_discarded(self.entry()))
                    self.assertEqual(discarded[0], self.entry())
                    self.assertEqual(
                        (422, False, False, True),
                        (status, answer["ok"], answer["produced"], answer["adoption_refused"]),
                    )
                    self.assertEqual([], calls, "Analyze read resurrected words")
                    self.assertEqual({}, reading.published_jobs(self.config))

    def test_a_person_can_analyze_a_draft_without_losing_saved_outcome_lines(self) -> None:
        annotation_store.annotate(
            self.config, self.state, "claude", "s1", goal="", lines=["An AST", "Parser tests pass"]
        )
        before = self.entry()["revisions"][-1]["lines"]
        with (
            self.route._counting_model(harness="claude") as calls,
            self.route._serving(self.application) as port,
        ):
            status, raw = self.route._post(port, {**self.payload, "expected_revision": 1})
        self.assertEqual(202, status, raw)
        self.assertTrue(json.loads(raw)["ok"])
        self.assertEqual(1, len(calls))
        self.assertEqual("Build the parser", self.entry()["revisions"][-1]["goal"])
        self.assertEqual(before, self.entry()["revisions"][-1]["lines"])


class PromptHistoryTest(unittest.TestCase):
    def test_first_prompt_and_provenance_are_retained_under_additive_schema(self) -> None:
        self.assertIn("first_prompt", history.PROMPT_TEXT_ALLOWLIST)
        row = {
            "harness": "claude",
            "sid": "s1",
            "project": "demo",
            "state": "working",
            "last_activity": 30.0,
            "first_prompt": "Build the parser",
            "first_prompt_at": 10.0,
            "annotation_goal": "Build the parser",
            "annotation_goal_source": "first-prompt",
            "annotation_goal_source_at": 10.0,
        }
        observed = history.observation(row)
        self.assertIsNotNone(observed)
        assert observed is not None
        self.assertEqual("Build the parser", observed["first_prompt"])
        self.assertEqual("first-prompt", observed["annotation_goal_source"])
        self.assertGreaterEqual(history.SCHEMA_VERSION, 3)
        self.assertIn(1, history.READABLE_VERSIONS)
        self.assertIn(2, history.READABLE_VERSIONS)


class AdoptionBoundaryTest(unittest.TestCase):
    def test_secret_crossing_first_prompt_bound_is_redacted_before_clipping(self) -> None:
        first = transcripts.first_prompt
        secret = "ghp_" + "a" * 36
        with tempfile.TemporaryDirectory() as home:
            config, state = make_runtime()
            path = Path(home, "rollout.jsonl")
            row = test_transcripts.CodexInstructionTest._user_old(
                10, "Implement the new parser " + "x" * 90 + " " + secret
            )
            path.write_text(json.dumps(row) + "\n")
            text = first(config, state, str(path), "codex")["first_prompt"]
            self.assertNotIn("a" * 10, text)
            self.assertIn("REDACTED", text)

    def test_stale_time_and_new_typed_goal_never_get_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as home:
            config, state = make_runtime(state_home=home, state_dir=Path(home))
            row = {
                "harness": "claude",
                "sid": "s1",
                "instruction": {"label": "asked", "text": "Build parser", "at": 20.0},
            }
            self.assertEqual(
                annotation_store.OUTCOME_REFUSED,
                annotation_store.adopt(
                    config,
                    state,
                    cast("Any", row),
                    source="latest-prompt",
                    expected_text="Build parser",
                    expected_at=10.0,
                    now=30.0,
                ),
            )
            annotation_store.annotate(
                config, state, "claude", "s1", goal="Keep this typed goal", now=25.0
            )
            self.assertEqual(
                annotation_store.OUTCOME_REFUSED,
                annotation_store.adopt(
                    config,
                    state,
                    cast("Any", row),
                    source="latest-prompt",
                    expected_text="Build parser",
                    expected_at=20.0,
                    now=30.0,
                ),
            )
            self.assertEqual(
                "Keep this typed goal", annotation_store.load(config)[0]["revisions"][-1]["goal"]
            )

    def test_refused_sources_and_invalid_times_are_not_adopted(self) -> None:
        with tempfile.TemporaryDirectory() as home:
            config, state = make_runtime(state_home=home, state_dir=Path(home))
            for row in [
                {
                    "harness": "claude",
                    "sid": "s",
                    "instruction": {"label": "agent", "text": "Build parser", "at": 10.0},
                },
                {
                    "harness": "claude",
                    "sid": "s",
                    "instruction": {"label": "earlier", "text": "Build parser", "at": 10.0},
                },
                {
                    "harness": "codex",
                    "sid": "s",
                    "title": "yes",
                    "prompt_states_work": False,
                    "prompt_at": 10.0,
                },
                {"harness": "pi", "sid": "s", "title": "Build parser", "prompt_at": 10.0},
            ]:
                self.assertEqual(
                    annotation_store.OUTCOME_REFUSED,
                    annotation_store.adopt(
                        config,
                        state,
                        cast("Any", row),
                        source="latest-prompt",
                        expected_text="Build parser",
                        expected_at=10.0,
                        now=30.0,
                    ),
                )
            for at in [None, True, 0.0, float("nan"), float("inf"), 40.0]:
                row = {
                    "harness": "codex",
                    "sid": "s",
                    "title": "Build parser",
                    "prompt_states_work": True,
                    "prompt_at": at,
                }
                self.assertEqual(
                    annotation_store.OUTCOME_REFUSED,
                    annotation_store.adopt(
                        config,
                        state,
                        cast("Any", row),
                        source="latest-prompt",
                        expected_text="Build parser",
                        expected_at=at,
                        now=30.0,
                    ),
                )


class AdoptedReadingTest(unittest.TestCase):
    def test_real_producer_uses_source_time_and_retains_immutable_provenance(self) -> None:
        producer = test_reading.WhatOnePressActuallyCostsAndProduces()
        producer.setUp()
        revision = {
            "n": 1,
            "at": 150.0,
            "goal": "Build parser",
            "output": "",
            "goal_source": "first-prompt",
            "goal_source_at": 50.0,
        }
        assessment, why, spent = producer._produce(
            revisions=[revision], row={"state": "idle", "ended_at": 100.0}, now=200.0
        )
        self.assertEqual("", why)
        self.assertTrue(spent)
        self.assertIsNotNone(assessment)
        assert assessment is not None
        self.assertEqual("first-prompt", assessment["goal_source"])
        with tempfile.TemporaryDirectory() as home:
            config, state = make_runtime(
                state_home=home, state_dir=Path(home), annotation_max_revisions=1
            )
            row = {
                "harness": "claude",
                "sid": "s1",
                "first_prompt": "Build parser",
                "first_prompt_at": 50.0,
            }
            annotation_store.adopt(
                config,
                state,
                row,
                source="first-prompt",
                expected_text="Build parser",
                expected_at=50.0,
                now=150.0,
            )
            annotation_store.record_reading(config, state, "claude", "s1", assessment=assessment)
            annotation_store.annotate(
                config, state, "claude", "s1", goal="A typed replacement", now=201.0
            )
            stored = annotation_store.load(config)[0]
            self.assertEqual(1, len(stored["revisions"]))
            self.assertEqual("first-prompt", stored["assessment"]["goal_source"])
            self.assertEqual("typed", annotation_store.published(stored)["goal_source"])
            annotation_store.clear(config, state, "claude", "s1", now=202.0)
            cleared = annotation_store.load(config)[0]
            self.assertFalse(cleared["revisions"])
            self.assertNotIn("assessment", cleared)

    def test_current_adopted_goal_with_typed_output_never_enters_unasked_lane(self) -> None:
        with tempfile.TemporaryDirectory() as home:
            lane = test_unasked._Harness(
                test_unasked._config(Path(home)), test_unasked._assessment("departure")
            )
            entry = test_unasked._annotation()
            entry["revisions"][-1]["goal_source"] = "first-prompt"
            entry["revisions"][-1]["goal_source_at"] = 10.0
            entry["revisions"][-1]["lines"] = ({"text": "Typed output", "source": "typed"},)
            for state in ["working", "idle"]:
                lane.lane.consider(
                    lane.state, [test_unasked._row(state=state)], [entry], now=5000.0
                )
            self.assertEqual([], lane.readings)


class UnknownProvenanceTest(unittest.TestCase):
    def test_unknown_latest_source_cannot_restore_an_old_typed_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as home:
            config, state = make_runtime(state_home=home, state_dir=Path(home))
            annotation_store.annotate(
                config, state, "claude", "s1", goal="Old typed goal", now=10.0
            )
            path = Path(annotation_store.store_path(config))
            value = json.loads(path.read_text())
            value["entries"][0]["revisions"].append(
                {
                    "n": 2,
                    "at": 30.0,
                    "goal": "Unknown adopted goal",
                    "output": "",
                    "goal_source": "future-source",
                    "goal_source_at": 20.0,
                }
            )
            path.write_text(json.dumps(value))
            self.assertFalse(
                annotation_store.load(config),
                "invalid new provenance restored older typed eligibility",
            )
