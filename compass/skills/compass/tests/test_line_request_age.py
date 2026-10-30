"""A later, verified request cannot judge earlier work as its own departure."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest import mock

from compass_runtime import annotations as annotation_store
from compass_runtime import (
    correction,
    http_api,
    levels,
    live_estimate,
    project_context,
    reading,
    record_pages,
)
from compass_runtime import observer as runtime_observer

from .support import make_runtime

PARENT = {"harness": "claude", "sid": "parent"}
REQUEST_AT = 120.0
SAVE_AT = 200.0


def _request(**over: Any) -> dict[str, Any]:
    return {
        "fact_id": "request-1",
        "type": "user_message",
        "at": REQUEST_AT,
        "source_session": PARENT,
        "summary": "Write the result as JSON",
        "evidence": {"source": "transcript", "confidence": "exact"},
        "request_source_digest": "a" * 64,
        "request_words_digest": reading._request_digest("Write the result as JSON"),
        **over,
    }


def _binding(facts: list[dict[str, Any]] | None = None) -> Any:
    return reading.line_request_binding(
        facts if facts is not None else [_request()],
        source_id="request-1",
        text="Write the result as JSON",
        harness="claude",
        sid="parent",
        now=SAVE_AT,
    )


def _line() -> dict[str, Any]:
    return {
        "text": "Write the result as JSON",
        "source": "entry",
        "source_id": "request-1",
        "request": _binding(),
    }


def _revision(line: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"n": 1, "at": SAVE_AT, "goal": "Make the export", "lines": (line or _line(),)}


class ALineNeedsItsActualParentRequest(unittest.TestCase):
    def test_initial_add_edits_and_incomplete_sources_cannot_inherit_request_time(self) -> None:
        self.assertIsNotNone(_binding())
        for facts, text in (
            ([_request()], "Write XML instead"),
            ([_request(request_words_digest="")], "Write the result as JSON"),
            (
                [
                    _request(
                        request_words_digest=reading._request_digest(
                            "Write the result as JSON and then run all tests"
                        )
                    )
                ],
                "Write the result as JSON",
            ),
        ):
            with self.subTest(facts=facts, text=text):
                self.assertIsNone(
                    reading.line_request_binding(
                        facts,
                        source_id="request-1",
                        text=text,
                        harness="claude",
                        sid="parent",
                        now=SAVE_AT,
                    )
                )

    def test_source_proof_does_not_bypass_the_listed_parent_identity(self) -> None:
        self.assertEqual([], reading.listed_request_sources([], [_request()]))
        self.assertEqual([], reading.listed_request_sources([_request(at=121.0)], [_request()]))
        self.assertEqual(
            [],
            reading.listed_request_sources(
                [_request(source_session={**PARENT, "sid": "child"})], [_request()]
            ),
        )
        self.assertEqual(
            [],
            reading.listed_request_sources([_request(**{reading.COPIED_FLAG: True})], [_request()]),
        )
        self.assertEqual([], reading.listed_request_sources([_request(), _request()], [_request()]))
        self.assertEqual([_request()], reading.listed_request_sources([_request()], [_request()]))
        self.assertEqual(
            [],
            reading.listed_request_sources(
                [_request()], [_request(), _request(fact_id="unlisted-request")]
            ),
        )

    def test_verified_request_binding_contains_no_source_or_line_words(self) -> None:
        binding = _binding()
        self.assertEqual(REQUEST_AT, binding["at"])
        self.assertEqual({"at", "session_digest", "source_digest", "line_digest"}, set(binding))
        for name in ("session_digest", "source_digest", "line_digest"):
            self.assertRegex(binding[name], r"\A[0-9a-f]{64}\Z")
        self.assertNotIn("Write", json.dumps(binding))

    def test_request_binding_does_not_trust_other_sessions_or_nonperson_sources(self) -> None:
        for over in (
            {"source_session": {"harness": "claude", "sid": "child"}},
            {"type": "agent_message"},
            {reading.COPIED_FLAG: True},
            {"at": SAVE_AT},
            {"at": SAVE_AT + 1},
            {"at": float("nan")},
            {"at": True},
            {"summary": ""},
            {"request_source_digest": ""},
        ):
            with self.subTest(over=over):
                self.assertIsNone(_binding([_request(**over)]))

    def test_duplicate_identity_or_same_time_requests_are_ambiguous(self) -> None:
        for extra in (_request(), _request(fact_id="request-2")):
            with self.subTest(extra=extra):
                self.assertIsNone(_binding([_request(), extra]))

    def test_line_floor_is_revalidated_against_the_actual_current_record(self) -> None:
        self.assertEqual(
            REQUEST_AT,
            reading.line_request_at(_line(), [_request()], "claude", "parent", until=SAVE_AT),
        )
        for facts in (
            [],
            [_request(summary="Write XML instead")],
            [_request(at=REQUEST_AT + 1)],
            [_request(request_source_digest="b" * 64)],
        ):
            with self.subTest(facts=facts):
                self.assertIsNone(
                    reading.line_request_at(_line(), facts, "claude", "parent", until=SAVE_AT)
                )

    def test_edits_typed_and_legacy_lines_have_unknown_request_age(self) -> None:
        for line in (
            {**_line(), "text": "Write XML instead"},
            {"text": "Write the result as JSON", "source": "typed"},
            {"text": "Write the result as JSON", "source": "entry", "source_id": "request-1"},
        ):
            with self.subTest(line=line):
                self.assertIsNone(
                    reading.line_request_at(line, [_request()], "claude", "parent", until=SAVE_AT)
                )

    def test_rewritten_binding_is_not_a_new_request_time(self) -> None:
        for key, value in (
            ("at", 100.0),
            ("line_digest", hashlib.sha256(b"different").hexdigest()),
            ("source_digest", "0" * 64),
            ("session_digest", "0" * 64),
            ("unexpected", "untrusted"),
        ):
            line = _line()
            line["request"][key] = value
            with self.subTest(key=key):
                self.assertIsNone(
                    reading.line_request_at(line, [_request()], "claude", "parent", until=SAVE_AT)
                )

    def test_floor_map_is_empty_for_other_session_and_newer_than_save_sources(self) -> None:
        self.assertEqual(
            {}, reading.line_request_floors(_revision(), [_request()], "claude", "other")
        )
        self.assertEqual(
            {},
            reading.line_request_floors(
                {**_revision(), "at": 110.0}, [_request()], "claude", "parent"
            ),
        )
        self.assertEqual(
            {"line_1": REQUEST_AT},
            reading.line_request_floors(_revision(), [_request()], "claude", "parent"),
        )


class RequestAgeSurvivesOnlyUnchangedStoredWords(unittest.TestCase):
    def test_load_discards_cross_session_and_after_save_bindings_without_deleting_words(
        self,
    ) -> None:
        for sid, at in (("other", SAVE_AT), ("parent", 110.0), ("parent", REQUEST_AT)):
            raw = {"harness": "claude", "sid": sid, "revisions": [{**_revision(), "at": at}]}
            with self.subTest(sid=sid, at=at):
                entry = annotation_store._entry(
                    json.loads(json.dumps(raw)), text_cap=240, revision_cap=8
                )
                assert entry is not None
                line = entry["revisions"][-1]["lines"][0]
                self.assertEqual("Write the result as JSON", line["text"])
                self.assertNotIn("request", line)

    def test_loading_bad_request_metadata_keeps_the_line_words(self) -> None:
        line = _line()
        line["request"]["at"] = True
        loaded = annotation_store._line(line, 240)
        assert loaded is not None
        self.assertEqual("Write the result as JSON", loaded["text"])
        self.assertNotIn("request", loaded)

    def test_loading_changed_words_discards_their_request_binding(self) -> None:
        line = {**_line(), "text": "Write XML instead"}
        loaded = annotation_store._line(line, 240)
        assert loaded is not None
        self.assertEqual("Write XML instead", loaded["text"])
        self.assertNotIn("request", loaded)

    def test_unchanged_reordered_and_duplicate_lines_do_not_share_request_age(self) -> None:
        first = cast("annotation_store.OutcomeLine", _line())
        second: annotation_store.OutcomeLine = {"text": "Another line", "source": "typed"}
        reordered = annotation_store._sourced(
            ["Another line", first["text"]], (first, second), (1, 0)
        )
        self.assertEqual(first["request"], reordered[1]["request"])
        duplicate = annotation_store._sourced([first["text"], first["text"]], (first,))
        self.assertIn("request", duplicate[0])
        self.assertNotIn("request", duplicate[1])
        edited = annotation_store._sourced(["Write XML instead"], (first,))
        self.assertEqual("typed", edited[0]["source"])
        self.assertNotIn("request", edited[0])

    def test_actual_save_and_reload_keeps_only_server_verified_binding(self) -> None:
        with tempfile.TemporaryDirectory() as home:
            config, state = make_runtime(state_home=home, state_dir=Path(home))
            annotation_store.annotate(
                config, state, "claude", "parent", goal="Make the export", now=100.0
            )
            outcome = annotation_store.add_direction(
                config,
                state,
                PARENT,
                source_id="request-1",
                text="Write the result as JSON",
                entry_at=REQUEST_AT,
                source_facts=[_request()],
                expected_revision=1,
                now=SAVE_AT,
            )
            self.assertEqual(annotation_store.OUTCOME_STORED, outcome)
            entry = annotation_store.find(annotation_store.load(config), "claude", "parent")
            assert entry is not None
            self.assertEqual(
                {"line_1": REQUEST_AT},
                reading.line_request_floors(
                    entry["revisions"][-1], [_request()], "claude", "parent"
                ),
            )


class EarlierWorkCannotAnswerALaterLine(unittest.TestCase):
    def _resolve(
        self, action_at: float, *, requested: bool = True, result_at: float | None = None
    ) -> Any:
        fact: reading.LedgerEntry = {
            "id": "agent-1",
            "type": reading.AGENT_MESSAGE_TYPE,
            "by": "agent",
            "author": reading.AUTHOR_AGENT,
            "summary": "I wrote CSV",
            "source": "transcript",
            "at": action_at,
            "work": False,
        }
        if result_at is not None:
            fact.update(
                {
                    "type": "tool_report",
                    "subject": "check",
                    "result": "failed",
                    "result_at": result_at,
                    "work": True,
                }
            )
        selection = reading.Selection(
            (fact,), lines=("Write the result as JSON",), asked_output=True
        )
        return reading.resolve(
            {
                "goal": {"token": "unverifiable", "cites": ()},
                "line_1": {
                    "token": "departure",
                    "cites": (1,),
                    "detail": "The record describes CSV",
                },
            },
            selection,
            goal="Make the export",
            lines=("Write the result as JSON",),
            detail_cap_chars=240,
            line_requests={"line_1": REQUEST_AT} if requested else {},
        )["line_1"]

    def test_only_later_actions_can_raise_a_sourced_line_departure(self) -> None:
        # A failed check carries the departure: a line's departure on a message alone gives way
        # whenever it was said (DEC-17, 2026-10-30), which would hide the request floor tested here.
        for at in (110.0, REQUEST_AT):
            with self.subTest(at=at):
                self.assertEqual(
                    reading.RESULT_UNVERIFIABLE, self._resolve(at, result_at=at)["result"]
                )
        self.assertEqual(reading.RESULT_DEPARTURE, self._resolve(130.0, result_at=130.0)["result"])

    def test_delayed_result_is_not_proof_the_action_followed_the_request(self) -> None:
        self.assertEqual(
            reading.RESULT_UNVERIFIABLE, self._resolve(110.0, result_at=130.0)["result"]
        )
        self.assertEqual(reading.RESULT_DEPARTURE, self._resolve(130.0, result_at=140.0)["result"])

    def test_typed_request_age_remains_unknown_even_when_annotated_later(self) -> None:
        self.assertEqual(
            reading.RESULT_DEPARTURE,
            self._resolve(110.0, requested=False, result_at=110.0)["result"],
        )


class TheCurrentPageReceivesOnlyVerifiedRequestAges(unittest.TestCase):
    def test_context_map_is_bound_to_the_current_revision_and_parent_request(self) -> None:
        entry = cast("annotation_store.Annotation", {**PARENT, "revisions": [_revision()]})
        self.assertEqual(
            [
                {
                    **PARENT,
                    "revision": 1,
                    "lines": {"line_1": {"at": REQUEST_AT, "source_id": "request-1"}},
                }
            ],
            http_api._line_requests(entry, [_request()], PARENT),
        )
        for facts in (
            [],
            [_request(summary="Changed source")],
            [_request(source_session={**PARENT, "sid": "other"})],
        ):
            with self.subTest(facts=facts):
                self.assertEqual([], http_api._line_requests(entry, facts, PARENT))

    def test_analysis_does_not_raise_medium_from_a_before_request_agent_message(self) -> None:
        fact = {
            "fact_id": "agent-1",
            "type": "agent_message",
            "summary": "I wrote CSV",
            "at": 110.0,
            "source_session": PARENT,
            "evidence": {"source": "transcript", "confidence": "exact"},
        }
        assessment = {
            "read_at": 210.0,
            "window_start": 100.0,
            "scope": reading.SCOPE_LAST_TURN,
            "criteria": {
                "goal": {
                    "result": reading.RESULT_UNVERIFIABLE,
                    "cites": (),
                    "detail": "",
                    "clause": "",
                },
                "line_1": {
                    "result": reading.RESULT_DEPARTURE,
                    "cites": ("agent-1",),
                    "detail": "",
                    "clause": "Write the result as JSON",
                },
            },
        }
        evidence = levels.Evidence((fact,), {}, 0)
        self.assertEqual(
            levels.MEDIUM, levels.analysis_level(assessment, evidence, outcome_lines=1).level
        )
        self.assertEqual(
            levels.NOT_ENOUGH,
            levels.analysis_level(
                assessment, evidence, outcome_lines=1, line_requests={"line_1": REQUEST_AT}
            ).level,
        )


class AProducedReadingUsesItsVerifiedLineRequest(unittest.TestCase):
    def test_an_earlier_agent_action_is_not_published_as_the_later_lines_departure(self) -> None:
        with tempfile.TemporaryDirectory() as home:
            config, _state = make_runtime(state_home=home, state_dir=Path(home))
            # A failed check, which carries a line's departure on its own; a message no longer
            # does (DEC-17, 2026-10-30), and the request floor is what this test reads.
            fact = {
                "fact_id": "agent-1",
                "type": "tool_report",
                "subject": "check",
                "result": "failed",
                "result_source": "flag",
                "summary": "python3 -m pytest tests/test_export.py",
                "at": 110.0,
                "source_session": PARENT,
                "branch": {**PARENT, "record_id": "call-1"},
                "evidence": {"source": "Claude Bash call and paired result", "confidence": "exact"},
            }
            granted = reading.ToolOutput(destination="Anthropic", label="Claude Code")
            answer = json.dumps(
                {
                    "goal": {"result": "unverifiable", "cites": []},
                    "line_1": {
                        "result": "departure",
                        "cites": [1],
                        "detail": "The record describes CSV",
                    },
                }
            )
            prompts = []
            for recovered, expected in (
                ([_request()], reading.RESULT_UNVERIFIABLE),
                (None, reading.RESULT_DEPARTURE),
                ([_request(request_source_digest="b" * 64)], reading.RESULT_DEPARTURE),
            ):
                with self.subTest(recovered=recovered):
                    lookup = mock.Mock(return_value=recovered) if recovered is not None else None

                    def model(prompt: str, **_kw: Any) -> tuple[str, str]:
                        prompts.append(prompt)
                        return answer, "ok"

                    assessment, why, spent = reading.produce(
                        config,
                        {**PARENT, "state": "working", "ended_at": None},
                        [{**_revision(), "window_start": 100.0}],
                        [_request(), fact],
                        now=400.0,
                        stamp_text="synthetic stop",
                        model=model,
                        goal_source_lookup=lookup,
                        tool_output=granted,
                        read_lines=True,
                        read_agent_words=True,
                    )
                    self.assertEqual("", why)
                    self.assertTrue(spent)
                    assert assessment is not None
                    self.assertEqual(expected, assessment["criteria"]["line_1"]["result"])
                    if lookup is not None:
                        lookup.assert_called_once_with()
            self.assertEqual(1, len(set(prompts)))
            self.assertNotIn("a" * 64, prompts[0])
            self.assertNotIn(_request()["request_words_digest"], prompts[0])


class SourceContinuityIncludesWordsOutsideTheVisibleClip(unittest.TestCase):
    def test_an_incomplete_extraction_never_certifies_a_complete_line(self) -> None:
        self.assertEqual(
            "",
            project_context._complete_request_digest(
                project_context.DirectionText("Write JSON", True)
            ),
        )
        self.assertEqual(
            reading._request_digest("Write JSON"),
            project_context._complete_request_digest(project_context.DirectionText("Write JSON")),
        )

    def test_one_cached_source_read_serves_page_and_level_then_invalidates_on_change(self) -> None:
        with tempfile.TemporaryDirectory() as home:
            config, state = make_runtime(state_home=home, state_dir=Path(home))
            path = Path(home) / "parent.jsonl"
            path.write_bytes(self._short_raw("A"))
            sources = project_context.transcript_user_facts(
                config, state, str(path), "claude", "parent"
            )
            source = sources[0]
            saved_at = float(source["at"]) + 10
            line = {
                "text": "Write JSON",
                "source": "entry",
                "source_id": source["fact_id"],
                "request": reading.line_request_binding(
                    sources,
                    source_id=source["fact_id"],
                    text="Write JSON",
                    harness="claude",
                    sid="parent",
                    now=saved_at,
                ),
            }
            entry = cast(
                "annotation_store.Annotation",
                {
                    **PARENT,
                    "revisions": [{"n": 1, "at": saved_at, "goal": "Export", "lines": [line]}],
                },
            )
            listed = [
                {
                    key: value
                    for key, value in source.items()
                    if not key.startswith("request_source_")
                }
            ]
            app = SimpleNamespace(config=config, state=state)
            with (
                mock.patch.object(runtime_observer, "resolve_transcript", return_value=str(path)),
                mock.patch.object(
                    record_pages,
                    "scan_source",
                    wraps=record_pages.scan_source,
                ) as reads,
            ):
                verified = http_api._request_sources(app, PARENT, listed, entry)
                self.assertTrue(http_api._line_requests(entry, verified, PARENT))
                self.assertEqual(0, reads.call_count)
                path.write_bytes(self._short_raw("B"))
                changed = http_api._request_sources(app, PARENT, listed, entry)
                self.assertEqual([], http_api._line_requests(entry, changed, PARENT))
                self.assertEqual(1, reads.call_count)

    def test_page_publication_and_analysis_share_the_same_verified_source(self) -> None:
        with tempfile.TemporaryDirectory() as home:
            config, state = make_runtime(state_home=home, state_dir=Path(home))
            config = replace(config, annotations_enabled=True)
            path = Path(home) / "parent.jsonl"
            path.write_bytes(self._short_raw("A"))
            sources = project_context.transcript_user_facts(
                config, state, str(path), "claude", "parent"
            )
            source = sources[0]
            requested_at = float(source["at"])
            saved_at = requested_at + 10
            line = {
                "text": "Write JSON",
                "source": "entry",
                "source_id": source["fact_id"],
                "request": reading.line_request_binding(
                    sources,
                    source_id=source["fact_id"],
                    text="Write JSON",
                    harness="claude",
                    sid="parent",
                    now=saved_at,
                ),
            }
            assessment = {
                "revision_read": 1,
                "read_at": saved_at + 10,
                "window_start": requested_at - 10,
                "scope": reading.SCOPE_LAST_TURN,
                "criteria": {
                    "line_1": {
                        "result": reading.RESULT_DEPARTURE,
                        "cites": ["agent-1"],
                        "detail": "",
                        "clause": "",
                    }
                },
            }
            entry = cast(
                "annotation_store.Annotation",
                {
                    **PARENT,
                    "revisions": [{"n": 1, "at": saved_at, "goal": "Export", "lines": [line]}],
                    "assessment": assessment,
                },
            )
            listed = {
                key: value for key, value in source.items() if not key.startswith("request_source_")
            }
            agent = {
                "fact_id": "agent-1",
                "type": "agent_message",
                "summary": "CSV",
                "at": requested_at - 1,
                "source_session": PARENT,
                "evidence": {"source": "transcript", "confidence": "exact"},
            }
            context = {"semantic": {"facts": [listed, agent]}}
            row = {**PARENT, "project": "billing"}
            app = SimpleNamespace(config=config, state=state, clock=lambda: saved_at + 20)
            with (
                mock.patch.object(annotation_store, "active", return_value=[]),
                mock.patch.object(annotation_store, "find", return_value=entry),
                mock.patch.object(runtime_observer, "resolve_transcript", return_value=str(path)),
                mock.patch.object(live_estimate, "for_session", return_value={}),
                mock.patch.object(
                    http_api, "_request_sources", wraps=http_api._request_sources
                ) as lookup,
            ):
                published = http_api._with_levels(
                    app, context, [row], ("claude", "parent"), "billing"
                )
            work = published["sources"]["work"]
            self.assertEqual(requested_at, work["line_requests"][0]["lines"]["line_1"]["at"])
            self.assertEqual(levels.NOT_ENOUGH, work["analysis_levels"][0]["level"])
            lookup.assert_called_once()
            cast("list[annotation_store.Revision]", entry["revisions"]).append(
                cast(
                    "annotation_store.Revision",
                    {
                        "n": 2,
                        "at": saved_at + 30,
                        "goal": "Export",
                        "lines": [{"text": "Use XML", "source": "typed"}],
                    },
                )
            )
            self.assertEqual([], http_api._line_requests(entry, sources, row))
            historical = http_api._analysis_levels(
                app, context, row, entry, saved_at, request_sources=sources
            )
            self.assertEqual(levels.MEDIUM, historical[0]["level"])

    def test_a_duplicate_after_the_fact_cap_cannot_keep_a_source_binding(self) -> None:
        with tempfile.TemporaryDirectory() as home:
            config, _state = make_runtime(state_home=home, state_dir=Path(home))
            first = self._raw("A")
            later = first.replace(b"00:02:00", b"00:03:00")
            with mock.patch.object(project_context, "TRANSCRIPT_USER_FACTS_MAX", 2):
                facts = project_context._transcript_user_scan(
                    config, first + later + first, "claude", "parent"
                )
            self.assertEqual(2, len(facts))
            self.assertEqual("", facts[0]["request_source_digest"])

    def test_a_different_same_time_request_after_the_fact_cap_is_also_ambiguous(self) -> None:
        with tempfile.TemporaryDirectory() as home:
            config, _state = make_runtime(state_home=home, state_dir=Path(home))
            first = self._raw("A")
            later = first.replace(b"00:02:00", b"00:03:00")
            with mock.patch.object(project_context, "TRANSCRIPT_USER_FACTS_MAX", 2):
                facts = project_context._transcript_user_scan(
                    config,
                    first + later + self._raw("B").replace(b"Write JSON", b"Use XML"),
                    "claude",
                    "parent",
                )
            self.assertEqual(2, len(facts))
            self.assertEqual("", facts[0]["request_source_digest"])

    def _short_raw(self, ending: str) -> bytes:
        record = json.loads(self._raw(ending))
        record["message"]["content"] = "Write JSON"
        record["source_marker"] = "x" * 1200 + ending
        return (json.dumps(record) + "\n").encode()

    def _raw(self, ending: str) -> bytes:
        return (
            json.dumps(
                {
                    "type": "user",
                    "timestamp": "2026-01-01T00:02:00Z",
                    "message": {"role": "user", "content": "Write JSON. " + "x" * 1200 + ending},
                }
            )
            + "\n"
        ).encode()

    def test_long_source_cannot_prove_a_shortened_line_even_when_its_clip_matches(self) -> None:
        with tempfile.TemporaryDirectory() as home:
            config, state = make_runtime(state_home=home, state_dir=Path(home))
            path = Path(home) / "parent.jsonl"
            path.write_bytes(self._raw("A"))
            first = project_context.transcript_user_facts(
                config, state, str(path), "claude", "parent"
            )
            path.write_bytes(self._raw("B"))
            second = project_context.transcript_user_facts(
                config, state, str(path), "claude", "parent"
            )
            self.assertEqual(first[0]["fact_id"], second[0]["fact_id"])
            self.assertEqual(first[0][reading.WORDS_FIELD], second[0][reading.WORDS_FIELD])
            self.assertNotEqual(
                first[0]["request_source_digest"], second[0]["request_source_digest"]
            )
            source = first[0]
            at = float(source["at"])
            line = {
                "text": "Write JSON",
                "source": "entry",
                "source_id": source["fact_id"],
                "request": reading.line_request_binding(
                    first,
                    source_id=source["fact_id"],
                    text="Write JSON",
                    harness="claude",
                    sid="parent",
                    now=at + 10,
                ),
            }
            self.assertIsNone(line["request"])
            self.assertIsNone(
                reading.line_request_at(line, second, "claude", "parent", until=at + 10)
            )

    def test_inode_replacement_cannot_reuse_a_source_fingerprint(self) -> None:
        with tempfile.TemporaryDirectory() as home:
            config, state = make_runtime(state_home=home, state_dir=Path(home))
            path = Path(home) / "parent.jsonl"
            path.write_bytes(self._raw("A"))
            stamp = path.stat()
            first = project_context.transcript_user_facts(
                config, state, str(path), "claude", "parent"
            )
            replacement = Path(home) / "replacement.jsonl"
            replacement.write_bytes(self._raw("B"))
            os.utime(replacement, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
            replacement.replace(path)
            second = project_context.transcript_user_facts(
                config, state, str(path), "claude", "parent"
            )
            self.assertNotEqual(
                first[0]["request_source_digest"], second[0]["request_source_digest"]
            )

    def test_private_source_proofs_never_reach_the_page(self) -> None:
        body = {"semantic": {"facts": [{**_request(), "request_source_stamp": [1, 2, 3, 4]}]}}
        published = project_context.for_page(body)
        fact = published["semantic"]["facts"][0]
        self.assertNotIn("request_source_digest", fact)
        self.assertNotIn("request_source_stamp", fact)
        self.assertNotIn("request_words_digest", fact)


class ACorrectionUsesActionTimeForTheLine(unittest.TestCase):
    def test_prior_and_same_time_actions_are_unknown_but_later_and_typed_are_retained(self) -> None:
        assessment = {
            "revision_read": 1,
            "read_at": 210.0,
            "window_start": 100.0,
            "scope": reading.SCOPE_LAST_TURN,
            "criteria": {
                "line_1": {
                    "result": reading.RESULT_DEPARTURE,
                    "cites": ["agent-1"],
                    "detail": "",
                    "clause": "",
                }
            },
        }
        row = {
            **PARENT,
            "annotation_goal": "Make the export",
            "annotation_line_1": "Write JSON",
            "annotation_revision": 1,
            "annotation_assessment": assessment,
            "annotation_window_start": 100.0,
        }
        for at, requested, expected in (
            (110.0, True, False),
            (120.0, True, False),
            (130.0, True, True),
            (110.0, False, True),
        ):
            with self.subTest(at=at, requested=requested):
                fact = {
                    "fact_id": "agent-1",
                    "type": "agent_message",
                    "summary": "CSV",
                    "at": at,
                    "source_session": PARENT,
                    "evidence": {"source": "transcript", "confidence": "exact"},
                }
                result = correction.compose(
                    row,
                    [fact],
                    floor=200.0,
                    lines_judged=True,
                    line_requests={"line_1": REQUEST_AT} if requested else {},
                )
                text = "".join(part for part in result.get("parts", []) if isinstance(part, str))
                self.assertEqual(expected, "departed at" in text)

    def test_delayed_check_result_does_not_make_its_call_follow_the_request(self) -> None:
        criteria = {
            "line_1": {
                "result": reading.RESULT_DEPARTURE,
                "cites": ["check"],
                "detail": "",
                "clause": "",
            }
        }
        for at, expected in ((110.0, "not-shown"), (130.0, "departed")):
            with self.subTest(at=at):
                fact = {
                    "fact_id": "check",
                    "type": "tool_report",
                    "subject": "check",
                    "result": "failed",
                    "at": at,
                    "result_at": 140.0,
                    "source_session": PARENT,
                    "evidence": {"source": "transcript", "confidence": "exact"},
                }
                rows = correction._Rows(
                    {"criteria": criteria, "window_start": 100.0},
                    [fact],
                    "claude",
                    unsettled=False,
                    lines_judged=True,
                    sid="parent",
                    line_requests={"line_1": REQUEST_AT},
                )
                self.assertEqual(expected, rows.state("line_1")[0])
