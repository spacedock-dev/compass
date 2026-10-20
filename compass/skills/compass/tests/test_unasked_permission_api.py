"""The existing reading POST accepts only deliberate, current unasked grants."""

from __future__ import annotations

import json
import shutil
import unittest
from typing import Any
from unittest import mock

from compass_runtime import reading, reading_policy

from . import test_http_api as api_tests
from .reading_pins import named_machine


class UnaskedGrantHTTPTest(unittest.TestCase):
    def setUp(self) -> None:
        self.api = api_tests.ReadingRouteTest()
        self.addCleanup(self.api.doCleanups)

    def _runtime(self, **changes: Any) -> Any:
        return self.api._runtime(**changes)

    def _app(self, config: Any, state: Any, harness: str) -> Any:
        return self.api._app(config, state, harness)

    def _serving(self, application: Any) -> Any:
        return self.api._serving(application)

    def _post(self, port: Any, payload: Any, **kwargs: Any) -> tuple[int, bytes]:
        return self.api._post(port, payload, **kwargs)

    def _body(self, **changes: Any) -> dict[str, Any]:
        return {
            "harness": "codex",
            "sid": "s1",
            "provider": "codex",
            "words_destination": "OpenAI",
            "unasked_grant": True,
            "press": True,
            "observer_model": 1,
            **changes,
        }

    def test_a_deliberate_toggle_grants_and_revokes_without_starting_analysis(self) -> None:
        config, state = self._runtime(unasked_enabled=True)
        reading_policy.store_path(config).unlink()
        app = self._app(config, state, "codex")
        app.unasked_lane = mock.Mock()
        with (
            named_machine(),
            mock.patch.object(shutil, "which", return_value="/bin/codex"),
            mock.patch.object(reading, "produce", side_effect=AssertionError("a model ran")),
            self._serving(app) as port,
        ):
            status, body = self._post(port, self._body())
            self.assertEqual(200, status, body)
            self.assertTrue(json.loads(body)["reading"]["words"]["codex"])
            self.assertEqual(0, json.loads(body)["reading"]["used"])
            status, body = self._post(port, self._body(unasked_grant=False))
            self.assertEqual(200, status, body)
            self.assertFalse(json.loads(body)["reading"]["words"]["codex"])
            self.assertFalse(json.loads(body)["reading"]["off"])
            app.unasked_lane.stop.assert_called_once_with("codex")

    def test_navigation_non_loopback_or_a_stale_destination_never_writes_a_grant(self) -> None:
        config, state = self._runtime(unasked_enabled=True)
        reading_policy.store_path(config).unlink()
        app = self._app(config, state, "codex")
        app.unasked_lane = mock.Mock()
        with (
            named_machine(),
            mock.patch.object(shutil, "which", return_value="/bin/codex"),
            self._serving(app) as port,
        ):
            for headers in (
                {"Sec-Fetch-Mode": "navigate", "Sec-Fetch-Dest": "document"},
                {"Host": "example.com"},
                {"Sec-Fetch-Site": "cross-site"},
            ):
                status, body = self._post(port, self._body(), headers=headers)
                self.assertEqual(403, status, body)
            status, body = self._post(port, self._body(words_destination="old.example"))
            self.assertEqual(409, status, body)
            status, body = self._post(port, self._body(provider="claude"))
            self.assertEqual(409, status, body)
            self.assertFalse(
                reading_policy.status(config, now=100.0, destinations={"codex": "OpenAI"})["words"][
                    "codex"
                ]
            )

    def test_pause_disabled_run_and_missing_flag_refuse_the_toggle(self) -> None:
        for changes, lane, expected in (
            ({"unasked_enabled": False}, False, 503),
            ({"unasked_enabled": True, "model_calls_disabled": True}, False, 503),
            # Paused, with the lane attached: refused as a conflict, and the pause stays.
            ({"unasked_enabled": True}, True, 409),
        ):
            with self.subTest(changes=changes):
                config, state = self._runtime(**changes)
                reading_policy.set_consent(config, False, now=100.0)
                app = self._app(config, state, "codex")
                if lane:
                    app.unasked_lane = mock.Mock()
                with (
                    named_machine(),
                    mock.patch.object(shutil, "which", return_value="/bin/codex"),
                    self._serving(app) as port,
                ):
                    status, body = self._post(port, self._body())
                self.assertEqual(expected, status, body)
                if not changes.get("model_calls_disabled"):
                    self.assertTrue(reading_policy.status(config, now=101.0)["off"])
                answer = reading_policy.resume(config, now=101.0)
                self.assertFalse(answer["words"]["codex"])

    def test_a_claude_routed_session_needs_no_grant(self) -> None:
        config, state = self._runtime(unasked_enabled=True)
        reading_policy.store_path(config).unlink()
        app = self._app(config, state, "claude")
        app.unasked_lane = mock.Mock()
        with (
            named_machine(),
            mock.patch.object(shutil, "which", return_value="/bin/tool"),
            self._serving(app) as port,
        ):
            status, body = self._post(port, self._body(harness="claude", provider="claude"))
        self.assertEqual(409, status, body)
        self.assertEqual("no-grant-needed", json.loads(body)["reason"])


class UnaskedGrantRouteDriftTest(UnaskedGrantHTTPTest):
    """A grant must match today's route; a revoke must not have to."""

    def test_a_revoke_through_a_claude_routed_session_deletes_the_codex_grant(self) -> None:
        config, state = self._runtime(unasked_enabled=True)
        reading_policy.store_path(config).unlink()
        app = self._app(config, state, "claude")
        app.unasked_lane = mock.Mock()
        with (
            named_machine(),
            mock.patch.object(
                shutil, "which", side_effect=lambda name: "/bin/codex" if name == "codex" else None
            ),
            self._serving(app) as port,
        ):
            # Codex-only machine: the Claude Code session falls back to Codex.
            status, body = self._post(port, self._body(harness="claude"))
            self.assertEqual(200, status, body)
            self.assertTrue(json.loads(body)["reading"]["words"]["codex"])
        with (
            named_machine(),
            mock.patch.object(shutil, "which", side_effect=lambda name: f"/bin/{name}"),
            self._serving(app) as port,
        ):
            # Claude Code is now on PATH and takes the route.
            status, body = self._post(
                port, self._body(harness="claude", provider="", unasked_grant=False)
            )
        self.assertEqual(200, status, body)
        self.assertFalse(json.loads(body)["reading"]["words"]["codex"])
        app.unasked_lane.stop.assert_called_once_with("codex")

    def test_a_grant_for_another_model_is_refused_and_the_snapshot_cleared(self) -> None:
        config, state = self._runtime(unasked_enabled=True)
        reading_policy.store_path(config).unlink()
        app = self._app(config, state, "codex")
        app.unasked_lane = mock.Mock()
        with (
            named_machine(),
            mock.patch.object(shutil, "which", return_value="/bin/codex"),
            mock.patch.object(app.state.snapshot, "clear", wraps=app.state.snapshot.clear) as clear,
            self._serving(app) as port,
        ):
            status, body = self._post(port, self._body(model="not-the-route-model"))
        self.assertEqual(409, status, body)
        self.assertEqual("model-changed", json.loads(body)["reason"])
        clear.assert_called_once_with()
        self.assertFalse(
            reading_policy.status(config, now=100.0, destinations={"codex": "OpenAI"})["words"][
                "codex"
            ]
        )

    def test_without_annotations_the_toggle_is_refused(self) -> None:
        config, state = self._runtime(unasked_enabled=True, annotations_enabled=False)
        reading_policy.store_path(config).unlink()
        app = self._app(config, state, "codex")
        app.unasked_lane = mock.Mock()
        with (
            named_machine(),
            mock.patch.object(shutil, "which", return_value="/bin/codex"),
            self._serving(app) as port,
        ):
            status, body = self._post(port, self._body())
        self.assertEqual(503, status, body)
