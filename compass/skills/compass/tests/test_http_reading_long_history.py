"""History reads never recover; explicit discard uses attributed, locked owner proof."""

from __future__ import annotations

import http.client
import json
import unittest
from typing import Any
from unittest import mock

from compass_runtime import (
    aggregate,
    observer,
    reading_long_cleanup,
    reading_long_history,
    reading_long_markers,
)
from compass_runtime import annotations as store
from compass_runtime import reading_long_recovery as recovery
from compass_runtime import reading_policy as policy

from . import test_http_api as http_tests
from . import test_reading_target_discard as discard_tests


class LongHistoryHTTPTest(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = discard_tests.TargetDiscardTest()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.config, self.state = self.fixture.config, self.fixture.state
        self.http = http_tests.ReadingRouteTest()
        self.addCleanup(self.http.doCleanups)
        self.app = aggregate.Application(
            self.config,
            self.state,
            (),
            native_notifier=lambda _: "",
            popup_notifier=lambda *_: None,
            diagnostic_sink=lambda _: None,
            clock=lambda: 104.0,
        )
        self.job_id = self.fixture.job_id
        self.payload: dict[str, Any] = {
            "harness": "claude",
            "sid": "abc123ab",
            "job": self.job_id,
            "press": True,
            "observer_model": 1,
        }

    def get(
        self,
        port: int,
        query: str = "harness=claude&sid=abc123ab",
        *,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, bytes]:
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
        try:
            connection.request("GET", "/api/reading-long-history?" + query, headers=headers or {})
            response = connection.getresponse()
            return response.status, response.read()
        finally:
            connection.close()

    def post(
        self, port: int, payload: dict[str, Any] | None = None, **kwargs: Any
    ) -> tuple[int, bytes]:
        return self.http._post(
            port,
            self.payload if payload is None else payload,
            path="/api/reading-long-discard",
            **kwargs,
        )

    def probes(self) -> None:
        self.app.long_recovery_probes = (lambda _: False, lambda _: False)

    def test_history_without_probes_is_exact_read_only_and_pause_does_not_hide_charges(
        self,
    ) -> None:
        self.fixture.fixture.reserve()
        policy.set_consent(self.config, False, now=102)
        before = self.fixture.path.read_bytes()
        db = policy.store_path(self.config).read_bytes()
        expected = reading_long_history.read(self.config, "claude", "abc123ab", now=104)
        with (
            mock.patch.object(recovery, "recover", side_effect=AssertionError),
            mock.patch.object(recovery, "publish_terminal", side_effect=AssertionError),
            mock.patch.object(recovery, "discard_terminal", side_effect=AssertionError),
            mock.patch.object(policy, "status", side_effect=AssertionError),
            mock.patch.object(policy, "capture_long_permission", side_effect=AssertionError),
            mock.patch.object(observer, "resolve_transcript", side_effect=AssertionError),
            mock.patch.object(self.app, "collect_json", side_effect=AssertionError),
            self.http._serving(self.app) as port,
        ):
            status, body = self.get(port)
            self.assertEqual(
                (200, {"ok": True, "long_history": expected}), (status, json.loads(body))
            )
            self.assertEqual(1, json.loads(body)["long_history"]["items"][0]["exact"]["calls"])
            self.assertEqual(200, self.get(port)[0])
        self.assertEqual(before, self.fixture.path.read_bytes())
        self.assertEqual(db, policy.store_path(self.config).read_bytes())
        self.assertNotIn(b"Retain words", body)
        self.assertNotIn(b"incarnation", body)

    def test_discard_requires_probes_and_explicit_press_then_real_supersession(self) -> None:
        self.fixture.base.die()
        with self.http._serving(self.app) as port:
            status, body = self.post(port)
            self.assertEqual(503, status, body)
            self.probes()
            status, body = self.post(port)
            self.assertEqual(409, status, body)
            self.assertEqual("discard-unproved", json.loads(body)["reason"])
            self.fixture.edit()
            policy.set_consent(self.config, False, now=103)
            before = store.published(self.fixture.fixture.entry())
            with (
                mock.patch.object(policy, "status", side_effect=AssertionError),
                mock.patch.object(policy, "capture_long_permission", side_effect=AssertionError),
                mock.patch.object(reading_long_markers, "reserve", side_effect=AssertionError),
                mock.patch.object(observer, "resolve_transcript", side_effect=AssertionError),
            ):
                status, body = self.post(port)
            self.assertEqual(200, status, body)
            self.assertEqual({"ok": True, "discarded": True, "reason": ""}, json.loads(body))
            self.assertFalse(self.fixture.path.exists())
            self.assertEqual(before, store.published(self.fixture.fixture.entry()))
            self.assertEqual(409, self.post(port)[0])

    def test_foreign_request_and_invalid_closed_payload_never_reach_discard(self) -> None:
        self.fixture.base.die()
        self.fixture.edit()
        self.probes()
        before = self.fixture.path.read_bytes()
        with (
            mock.patch.object(recovery, "discard_terminal", side_effect=AssertionError),
            self.http._serving(self.app) as port,
        ):
            for change, expected in (
                ({"sid": "def456de"}, 409),
                ({"harness": "codex"}, 409),
                ({"job": "A" * 32}, 400),
                ({"job": "../outside"}, 400),
                ({"press": False}, 400),
                ({"observer_model": True}, 400),
                ({"extra": "PRIVATE"}, 400),
                ({"sid": []}, 400),
            ):
                with self.subTest(change=change):
                    status, body = self.post(port, {**self.payload, **change})
                    self.assertEqual(expected, status, body)
            self.assertEqual(
                403,
                self.post(
                    port, headers={"Sec-Fetch-Mode": "navigate", "Sec-Fetch-Dest": "document"}
                )[0],
            )
        self.assertEqual(before, self.fixture.path.read_bytes())

    def test_unknown_owner_and_unknown_accounting_are_retained(self) -> None:
        self.fixture.base.die()
        self.fixture.edit()
        self.app.long_recovery_probes = (lambda _: False, lambda _: None)
        with self.http._serving(self.app) as port:
            status, body = self.post(port)
            self.assertEqual(409, status, body)
            self.assertEqual("owner-unresolved", json.loads(body)["reason"])
            self.probes()
            policy.store_path(self.config).unlink()
            status, body = self.post(port)
            self.assertEqual(409, status, body)
            self.assertEqual("accounting-unknown", json.loads(body)["reason"])
        self.assertTrue(self.fixture.path.exists())

    def test_history_bad_queries_and_navigation_are_rejected_without_reads(self) -> None:
        with (
            mock.patch.object(reading_long_history, "read", side_effect=AssertionError),
            self.http._serving(self.app) as port,
        ):
            for query in (
                "harness=claude",
                "harness=claude&sid=abc123ab&sid=abc123ab",
                "harness=claude&sid=abc123ab&extra=x",
            ):
                self.assertEqual(400, self.get(port, query)[0])
            self.assertEqual(
                403,
                self.get(
                    port, headers={"Sec-Fetch-Mode": "navigate", "Sec-Fetch-Dest": "document"}
                )[0],
            )

    def test_retired_marker_reports_receipt_cleanup_warning_without_restoring_it(self) -> None:
        self.fixture.base.die()
        self.fixture.edit()
        self.probes()
        with (
            mock.patch.object(reading_long_cleanup, "release_receipt", return_value=False),
            self.http._serving(self.app) as port,
        ):
            status, body = self.post(port)
        self.assertEqual(200, status, body)
        self.assertEqual(
            {"ok": True, "discarded": True, "reason": "receipt-unresolved"}, json.loads(body)
        )
        self.assertFalse(self.fixture.path.exists())

    def test_missing_or_symlink_marker_never_reaches_mutation_owner(self) -> None:
        self.probes()
        original = self.fixture.path.read_bytes()
        outside = self.fixture.path.with_suffix(".retained")
        outside.write_bytes(original)
        self.fixture.path.unlink()
        with (
            mock.patch.object(recovery, "discard_terminal", side_effect=AssertionError),
            self.http._serving(self.app) as port,
        ):
            self.assertEqual(409, self.post(port)[0])
            self.fixture.path.symlink_to(outside)
            self.assertEqual(409, self.post(port)[0])
        self.assertEqual(original, outside.read_bytes())
        self.assertTrue(self.fixture.path.is_symlink())

    def test_loaded_identity_does_not_bypass_mutation_owners_changed_marker_reread(self) -> None:
        self.fixture.base.die()
        self.fixture.edit()
        self.probes()
        original = reading_long_markers.load

        def loaded(*args: Any, **kwargs: Any) -> dict[str, Any] | None:
            value = original(*args, **kwargs)
            self.fixture.path.unlink()
            return value

        with (
            mock.patch.object(reading_long_markers, "load", side_effect=loaded),
            self.http._serving(self.app) as port,
        ):
            status, body = self.post(port)
        self.assertEqual(409, status, body)
        self.assertFalse(json.loads(body)["discarded"])
