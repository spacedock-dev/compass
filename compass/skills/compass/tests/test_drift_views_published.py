"""`sources.work.drift_views`: the Drift card's answer, published on the focused context only.

The view is the page's own derivation, held to it by `test_drift_view`; this module holds the
attachment: where it rides, on which routes and rows it never does, and that it reaches a harness
whose level the server does not compute
([DEC-26](docs/design-reading-a-session.md#dec-26-four-drift-levels-and-a-live-estimate-after-every-turn)
keeps the level off rows and off the reading route's context).
"""

from __future__ import annotations

import copy
import io
import json
import os
import threading
import types
import unittest
from typing import TYPE_CHECKING, Any
from unittest import mock
from urllib.parse import urlencode

from compass_runtime import aggregate, drift_view, http_api, terminal_drift

from .support import SERVER_PATH
from .test_claude_checks import SHORT, START
from .test_live_lease_http import LeaseRoute

if TYPE_CHECKING:
    from collections.abc import Callable


def _application() -> Any:
    return types.SimpleNamespace(
        diagnostic_sink=lambda _message: None,
        config=types.SimpleNamespace(max_cache_entries=2),
        state=types.SimpleNamespace(drift_view_cache={}, drift_view_lock=threading.Lock()),
    )


def _row(harness: str, sid: str = "s1", **over: Any) -> dict[str, Any]:
    return {
        "harness": harness,
        "sid": sid,
        "project": "p",
        "annotation_goal": "Ship the queue",
        "annotation_revision": 3,
        "annotation_revision_count": 3,
        "annotation_at": 100,
        "annotation_goal_saved_at": 100,
        "annotation_assessment": {
            "revision_read": 3,
            "revision_read_at": 100,
            "window_start": 100,
            "read_at": 200,
            "scope": "last-turn",
            "criteria": {
                "goal": {
                    "result": "departure",
                    "cites": ["m1"],
                    "clause": "Ship the queue",
                    "detail": "It went elsewhere",
                }
            },
        },
        **over,
    }


def _context(harness: str, sid: str = "s1") -> dict[str, Any]:
    fact = {
        "fact_id": "m1",
        "type": "agent_message",
        "at": 150,
        "source_session": {"harness": harness, "sid": sid},
        "evidence": {"source": "transcript", "confidence": "exact"},
    }
    return {"semantic": {"facts": [fact]}, "sources": {"work": {"live_levels": []}}}


def _payload(*rows: dict[str, Any]) -> dict[str, Any]:
    return {
        "annotate": True,
        "generated": 1000,
        "reading_routes": {"claude": {"provider": "claude"}, "codex": {"provider": "claude"}},
        "sessions": list(rows),
    }


class WhereTheViewRidesTest(unittest.TestCase):
    def test_a_codex_session_gets_its_departure_and_no_level(self) -> None:
        row = _row("codex")
        context = _context("codex")

        attached = http_api._with_drift_view(
            _application(), context, _payload(row), ("codex", "s1"), "p", b"k"
        )

        (view,) = attached["sources"]["work"]["drift_views"]
        self.assertEqual(["goal"], view["departures"])
        self.assertIsNone(view["pill"])
        self.assertIsNone(view["analysis"])
        self.assertEqual(drift_view.derive(row, _payload(row), attached), view)

    def test_a_line_resting_on_a_message_only_the_record_page_holds_keeps_it(self) -> None:
        row = _row("claude")
        row["annotation_assessment"]["criteria"]["goal"]["cites"] = ["m0"]
        older = {**_context("claude")["semantic"]["facts"][0], "fact_id": "m0", "at": 120}
        page = {"state": "ok", "entries": [older]}

        with mock.patch.object(http_api, "_record_page", return_value=page) as read:
            attached = http_api._with_drift_view(
                _application(), _context("claude"), _payload(row), ("claude", "s1"), "p", b"k"
            )

        (view,) = attached["sources"]["work"]["drift_views"]
        self.assertEqual(
            ("departs", ["m0"]), (view["lines"][0]["state"], view["lines"][0]["cites"])
        )
        self.assertEqual(
            (50, None), (read.call_args.kwargs["limit"], read.call_args.kwargs["before"])
        )

    def test_a_record_page_that_is_not_ok_is_not_merged(self) -> None:
        row = _row("claude")
        row["annotation_assessment"]["criteria"]["goal"]["cites"] = ["m0"]
        older = {**_context("claude")["semantic"]["facts"][0], "fact_id": "m0", "at": 120}

        with mock.patch.object(
            http_api, "_record_page", return_value={"state": "stale", "entries": [older]}
        ):
            attached = http_api._with_drift_view(
                _application(), _context("claude"), _payload(row), ("claude", "s1"), "p", b"k"
            )

        (view,) = attached["sources"]["work"]["drift_views"]
        self.assertEqual("cant-tell", view["lines"][0]["state"])

    def test_a_record_read_that_fails_leaves_the_view_built_from_the_context(self) -> None:
        row = _row("claude")

        with mock.patch.object(http_api, "_record_page", side_effect=OSError("gone")):
            attached = http_api._with_drift_view(
                _application(), _context("claude"), _payload(row), ("claude", "s1"), "p", b"k"
            )

        (view,) = attached["sources"]["work"]["drift_views"]
        self.assertEqual("departs", view["lines"][0]["state"])

    def test_the_other_work_sources_beside_it_are_left_as_they_were(self) -> None:
        row = _row("claude")
        context = _context("claude")

        attached = http_api._with_drift_view(
            _application(), context, _payload(row), ("claude", "s1"), "p", b"k"
        )

        self.assertEqual([], attached["sources"]["work"]["live_levels"])
        self.assertNotIn("drift_views", context["sources"]["work"])

    def test_a_session_listed_twice_is_not_guessed_at(self) -> None:
        row = _row("claude")
        context = _context("claude")

        attached = http_api._with_drift_view(
            _application(), context, _payload(row, dict(row)), ("claude", "s1"), "p", b"k"
        )

        self.assertEqual("unavailable", attached["sources"]["work"]["drift_views"][0]["state"])

    def test_a_session_under_another_project_is_not_given_one(self) -> None:
        row = _row("claude", project="other")

        attached = http_api._with_drift_view(
            _application(), _context("claude"), _payload(row), ("claude", "s1"), "p", b"k"
        )

        self.assertEqual("unavailable", attached["sources"]["work"]["drift_views"][0]["state"])

    def test_a_reading_this_build_cannot_derive_costs_the_page_nothing(self) -> None:
        row = _row("claude")
        original = drift_view.derive

        def broken(*_args: Any) -> Any:
            raise ValueError("boom")

        drift_view.derive = broken  # type: ignore[assignment]
        try:
            attached = http_api._with_drift_view(
                _application(), _context("claude"), _payload(row), ("claude", "s1"), "p", b"k"
            )
        finally:
            drift_view.derive = original

        self.assertEqual("unavailable", attached["sources"]["work"]["drift_views"][0]["state"])


class APersonReusesTheFocusedReading(unittest.TestCase):
    def test_a_person_reads_the_same_recorded_view_as_the_page(self) -> None:
        root = SERVER_PATH.parents[3] / "frontend/test/fixtures"
        data = json.loads((root / "client-contract/data-focused-drift.json").read_text())[
            "response"
        ]["body"]
        context = json.loads((root / "client-contract/context-focused-drift.json").read_text())[
            "response"
        ]["body"]
        expected = json.loads((root / "terminal-wording.json").read_text())["view"]
        self.assertEqual(expected, drift_view.derive(data["sessions"][0], data, context))

    def test_a_person_reuses_a_view_until_any_of_its_inputs_changes(self) -> None:
        root = SERVER_PATH.parents[3] / "frontend/test/fixtures/client-contract"
        payload = json.loads((root / "data-focused-drift.json").read_text())["response"]["body"]
        context = json.loads((root / "context-focused-drift.json").read_text())["response"]["body"]
        context["sources"]["work"].pop("drift_views", None)
        row = payload["sessions"][0]
        focus = row["harness"], row["sid"]
        project = row.get("project_key") or row["project"]
        record = copy.deepcopy(context["semantic"]["facts"])
        app = _application()
        with (
            mock.patch.object(
                http_api,
                "_record_page",
                side_effect=lambda *_args, **_kwargs: {"state": "ok", "entries": record},
            ),
            mock.patch.object(drift_view, "derive", wraps=drift_view.derive) as derive,
        ):

            def fetch() -> Any:
                return http_api._with_drift_view(app, context, payload, focus, project, b"k")

            first = fetch()
            self.assertEqual(first, fetch())
            self.assertEqual(1, derive.call_count, "an unchanged fetch must reuse the reading")
            changes: list[Callable[[], None]] = [
                lambda: record[0].update(subject="changed record contents"),
                lambda: row.update(annotation_goal="A changed saved goal"),
                lambda: row.update(annotation_line_1="A changed expected output"),
                lambda: payload["reading_routes"][focus[0]].update(provider="changed"),
                lambda: context["sources"]["work"].update(live_monitor={"on": True}),
                lambda: context["semantic"]["facts"][0].update(subject="changed context"),
                lambda: payload.update(annotate=False),
            ]
            for count, change in enumerate(changes, 2):
                change()
                fetch()
                self.assertEqual(count, derive.call_count)
            self.assertLessEqual(len(app.state.drift_view_cache), 2)
            latest = fetch()
            latest["sources"]["work"]["drift_views"][0]["sid"] = "changed by caller"
            self.assertEqual(focus[1], fetch()["sources"]["work"]["drift_views"][0]["sid"])


class OverARealServerTest(LeaseRoute):
    def test_the_focused_context_carries_it_and_no_row_or_project_context_does(self) -> None:
        with self.serving() as port:
            focused = self.focused(port)
            _status, project = self.call(port, "GET", "/api/project-context?project=billing")
            _status, data = self.call(port, "GET", "/api/data")

        (view,) = focused["sources"]["work"]["drift_views"]
        self.assertEqual(("claude", SHORT), (view["harness"], view["sid"]))
        self.assertNotIn("drift_views", project["sources"]["work"])
        self.assertTrue(all("drift_views" not in row for row in data["sessions"]))

    def test_a_person_is_told_why_the_view_is_unavailable_without_a_press(self) -> None:
        for reason in ("derivation-failed", "identity-not-unique"):
            with self.subTest(reason=reason):
                self._unavailable(reason)

    def _unavailable(self, reason: str) -> None:
        original = http_api._with_drift_view

        def attach(app: Any, context: Any, payload: Any, *args: Any) -> Any:
            if reason == "identity-not-unique":
                payload = {**payload, "sessions": payload["sessions"] * 2}
            return original(app, context, payload, *args)

        with (
            mock.patch.object(http_api, "_with_drift_view", side_effect=attach),
            mock.patch.object(drift_view, "derive", side_effect=ValueError("private failure"))
            if reason == "derivation-failed"
            else mock.patch.object(drift_view, "derive", wraps=drift_view.derive),
            mock.patch("compass_runtime.reading.ClaudeReadingModel") as model,
            self.serving() as port,
        ):
            test = self

            class Board:
                def data(self) -> Any:
                    return test.call(port, "GET", "/api/data")[1]

                def context(self, project: str, key: str) -> Any:
                    return test.call(
                        port, "GET", f"/api/project-context?project={project}&session={key}"
                    )[1]

                post = mock.Mock(side_effect=AssertionError("no press is allowed"))

            context = self.focused(port)
            out, err = io.StringIO(), io.StringIO()
            board = Board()
            code = terminal_drift.run(
                "claude",
                SHORT,
                again=True,
                at_shell=True,
                board=board,
                port=port,
                out=out,
                err=err,
            )
            self.assertEqual(1, code)
            sentence = (
                "Compass could not build this session's drift view"
                if reason == "derivation-failed"
                else "Compass could not uniquely identify this session for its drift view"
            )
            self.assertIn(sentence, err.getvalue())
            self.assertNotIn("does not publish", err.getvalue())
            self.assertNotIn("private failure", err.getvalue())
            board.post.assert_not_called()
            model.assert_not_called()
            self.assertEqual(reason, context["sources"]["work"]["drift_views"][0]["reason"])

    def test_a_person_reads_a_focused_view_when_optional_context_is_not_a_dictionary(self) -> None:
        original = http_api._with_drift_view
        for key in ("sources", "semantic", "work"):
            for value in (None, ["not a dictionary"]):
                with self.subTest(key=key, value=value):

                    def attach(
                        app: Any, context: Any, *args: Any, key: str = key, value: Any = value
                    ) -> Any:
                        context = copy.deepcopy(context)
                        if key == "work":
                            context["sources"]["work"] = value
                        else:
                            context[key] = value
                        return original(app, context, *args)

                    with (
                        mock.patch.object(http_api, "_with_drift_view", side_effect=attach),
                        self.serving() as port,
                    ):
                        status, context = self.call(
                            port,
                            "GET",
                            f"/api/project-context?project=billing&session=claude:{SHORT}",
                        )
                    self.assertEqual(200, status)
                    view = context["sources"]["work"]["drift_views"][0]
                    self.assertNotEqual("unavailable", view.get("state"))
                    self.assertEqual(("claude", SHORT), (view["harness"], view["sid"]))
                    self.assertEqual([], view["lines"])

    def test_a_person_is_told_when_projecting_the_focused_view_fails(self) -> None:
        with (
            mock.patch.object(
                http_api,
                "hashlib",
                mock.Mock(sha256=mock.Mock(side_effect=ValueError("private failure"))),
            ),
            self.serving() as port,
        ):
            status, context = self.call(
                port, "GET", f"/api/project-context?project=billing&session=claude:{SHORT}"
            )
        self.assertEqual(200, status)
        self.assertEqual(
            {
                "harness": "claude",
                "sid": SHORT,
                "state": "unavailable",
                "reason": "derivation-failed",
            },
            context["sources"]["work"]["drift_views"][0],
        )
        self.assertNotIn("private failure", json.dumps(context))

    def test_a_person_polling_an_unchanged_running_session_reuses_its_view(self) -> None:
        self.now = START.timestamp() + 30
        os.utime(self.path, (self.now, self.now))
        app = aggregate.Application(
            self.config,
            self.state,
            (aggregate.default_harnesses(usage_fetch_enabled=False)[0],),
            native_notifier=lambda _payload: "",
            popup_notifier=lambda _title, _body: None,
            diagnostic_sink=lambda _message: None,
            clock=lambda: self.now,
        )
        row = app.collect(show_all=True)["sessions"][0]
        path = "/api/project-context?" + urlencode(
            {"project": row["project_key"], "session": f"claude:{SHORT}"}
        )
        with (
            mock.patch.object(drift_view, "derive", wraps=drift_view.derive) as derive,
            self.serving(app) as port,
        ):
            first = self.call(port, "GET", path)[1]
            self.now += 2
            second = self.call(port, "GET", path)[1]
        self.assertEqual(
            first["sources"]["work"]["drift_views"], second["sources"]["work"]["drift_views"]
        )
        self.assertEqual(1, derive.call_count)

    def test_the_lease_standing_is_what_turns_the_monitor_on_in_the_view(self) -> None:
        with self.serving() as port:
            before = self.focused(port)["sources"]["work"]["drift_views"][0]
            self.lease(port, "start")
            after = self.focused(port)["sources"]["work"]["drift_views"][0]

        self.assertEqual((False, True), (before["live_on"], after["live_on"]))


if __name__ == "__main__":
    unittest.main()
