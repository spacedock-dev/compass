"""`sources.work.drift_views`: the Drift card's answer, published on the focused context only.

The view is the page's own derivation, held to it by `test_drift_view`; this module holds the
attachment: where it rides, on which routes and rows it never does, and that it reaches a harness
whose level the server does not compute
([DEC-26](docs/design-reading-a-session.md#dec-26-four-drift-levels-and-a-live-estimate-after-every-turn)
keeps the level off rows and off the reading route's context).
"""

from __future__ import annotations

import types
import unittest
from typing import Any
from unittest import mock

from compass_runtime import drift_view, http_api

from .test_claude_checks import SHORT
from .test_live_lease_http import LeaseRoute


def _application() -> Any:
    return types.SimpleNamespace(diagnostic_sink=lambda _message: None)


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

        self.assertNotIn("drift_views", attached["sources"]["work"])

    def test_a_session_under_another_project_is_not_given_one(self) -> None:
        row = _row("claude", project="other")

        attached = http_api._with_drift_view(
            _application(), _context("claude"), _payload(row), ("claude", "s1"), "p", b"k"
        )

        self.assertNotIn("drift_views", attached["sources"]["work"])

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

        self.assertNotIn("drift_views", attached["sources"]["work"])


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

    def test_the_lease_standing_is_what_turns_the_monitor_on_in_the_view(self) -> None:
        with self.serving() as port:
            before = self.focused(port)["sources"]["work"]["drift_views"][0]
            self.lease(port, "start")
            after = self.focused(port)["sources"]["work"]["drift_views"][0]

        self.assertEqual((False, True), (before["live_on"], after["live_on"]))


if __name__ == "__main__":
    unittest.main()
