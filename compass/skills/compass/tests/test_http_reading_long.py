"""Long preview reads metadata; long ingress cannot enter ordinary Analyze."""

from __future__ import annotations

import http.client
import json
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from compass_runtime import (
    aggregate,
    observer,
    reading_long_plan,
    reading_policy,
    reading_route,
    settings,
)
from compass_runtime import annotations as annotations_store

from . import test_http_api as http_tests


class LongReadingHTTPTest(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = http_tests.ReadingRouteTest()
        self.addCleanup(self.fixture.doCleanups)
        self.config, self.state = self.fixture._runtime()
        self.app: aggregate.Application = self.fixture._app(self.config, self.state, "claude")
        self.row = {"harness": "claude", "sid": "s1", "activity": "working"}
        self.state.snapshot.publish(
            (self.config.window_hours, False),
            json.dumps(
                {
                    "sessions": [self.row],
                    "reading": reading_policy.status(self.config, now=self.app.clock()),
                }
            ).encode(),
        )
        self.path = Path(self.config.state_home) / "native.jsonl"
        self.path.write_bytes(b"PRIVATE SOURCE MUST NOT BE READ")
        with mock.patch.object(reading_route, "_state", return_value="usable"):
            self.route = reading_route.resolve(
                "claude",
                environ={},
                root=self.path.parent,
                binary_resolver=lambda _name: "/fixture/cli",
            )

    def get(
        self,
        port: int,
        query: str = "harness=claude&sid=s1",
        headers: dict[str, str] | None = None,
    ) -> tuple[int, bytes]:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        try:
            conn.request("GET", "/api/reading-long-plan?" + query, headers=headers or {})
            response = conn.getresponse()
            return response.status, response.read()
        finally:
            conn.close()

    def press(self, **over: Any) -> dict[str, Any]:
        payload = self.fixture._claude_press(
            mode="long",
            plan_binding="a" * 64,
            expected_revision=1,
            model=self.route["model"],
            provider=self.route["provider"],
            destination=self.route["destination"],
            words_destination=self.route["words_destination"],
        )
        return {**payload, **over}

    def test_preview_is_exact_descriptor_without_collection_or_permission_writes(self) -> None:
        before = reading_policy.store_path(self.config).read_bytes()
        entry = annotations_store.find(annotations_store.load(self.config), "claude", "s1")
        expected = reading_long_plan.describe(
            row=self.row,
            entry=entry,
            route=self.route,
            preferences=settings.load(self.config),
            policy_status=reading_policy.status(self.config, now=self.app.clock()),
            source=reading_long_plan.SourceEstimate(
                "claude", "s1", "native-claude", self.path.stat().st_size, self.app.clock()
            ),
            now=self.app.clock(),
            settle_sec=self.config.reading_settle_sec,
        )
        with (
            mock.patch.object(reading_route, "resolve", return_value=self.route),
            mock.patch.object(observer, "resolve_transcript", return_value=str(self.path)),
            mock.patch.object(self.app, "collect_json", side_effect=AssertionError("collection")),
            mock.patch.object(
                reading_policy, "status", side_effect=AssertionError("writer status")
            ),
            self.fixture._serving(self.app) as port,
        ):
            status, body = self.get(port)
        self.assertEqual(200, status, body)
        self.assertEqual({"ok": True, "long_plan": expected}, json.loads(body))
        self.assertEqual(before, reading_policy.store_path(self.config).read_bytes())
        self.assertNotIn(b"PRIVATE SOURCE", body)

    def test_invalid_mode_precedes_pause_and_other_mutation_dispatch(self) -> None:
        with self.fixture._serving(self.app) as port:
            modes: tuple[Any, ...] = ("other", "", None, True, [], {})
            for mode in modes:
                with self.subTest(mode=mode):
                    status, _ = self.fixture._post(
                        port,
                        {
                            "mode": mode,
                            "consent": "off",
                            "press": True,
                            "observer_model": 1,
                        },
                    )
                    self.assertEqual(400, status)
                    self.assertFalse(
                        reading_policy.status(self.config, now=self.app.clock())["off"]
                    )

    def test_valid_long_mode_never_falls_through_ordinary_analyze(self) -> None:
        with (
            mock.patch.object(reading_route, "resolve", return_value=self.route),
            mock.patch.object(observer, "resolve_transcript", return_value=str(self.path)),
            mock.patch.object(self.app, "collect_json", side_effect=AssertionError("collection")),
            self.fixture._serving(self.app) as port,
        ):
            status, body = self.get(port)
            self.assertEqual(200, status)
            payload = self.press()
            payload["plan_binding"] = json.loads(body)["long_plan"]["binding"]
            status, body = self.fixture._post(port, payload)
        self.assertEqual(503, status, body)
        self.assertEqual("long-unavailable", json.loads(body)["reason"])
        self.assertEqual([], self.fixture.outcomes)

    def test_explicit_empty_tool_destination_preserves_preview_binding_and_long_dispatch(
        self,
    ) -> None:
        route = {**self.route, "destination": ""}
        before = reading_policy.store_path(self.config).read_bytes()
        with (
            mock.patch.object(reading_route, "resolve", return_value=route),
            mock.patch.object(observer, "resolve_transcript", return_value=str(self.path)),
            mock.patch.object(self.app, "collect_json", side_effect=AssertionError("collection")),
            mock.patch.object(
                reading_policy, "status", side_effect=AssertionError("policy writer")
            ),
            self.fixture._serving(self.app) as port,
        ):
            status, body = self.get(port)
            self.assertEqual(200, status, body)
            preview = json.loads(body)["long_plan"]
            self.assertEqual("", preview["route"]["destination"])
            self.assertIsNotNone(preview["binding"])
            payload = self.press(plan_binding=preview["binding"], destination="")
            status, body = self.fixture._post(port, payload)
            self.assertEqual(503, status, body)
            self.assertEqual("long-unavailable", json.loads(body)["reason"])
            payload["destination"] = "foreign"
            status, body = self.fixture._post(port, payload)
            self.assertEqual(409, status, body)
            self.assertEqual("plan-changed", json.loads(body)["reason"])
        self.assertEqual(before, reading_policy.store_path(self.config).read_bytes())
        self.assertEqual([], self.fixture.outcomes)

    def test_unknown_cold_and_unsupported_sources_never_resolve_or_collect(self) -> None:
        self.state.snapshot.publish(
            (self.config.window_hours, True),
            json.dumps({"sessions": [{"harness": "codex", "sid": "s1"}]}).encode(),
        )
        with (
            mock.patch.object(reading_route, "resolve", return_value=self.route),
            mock.patch.object(
                observer, "resolve_transcript", side_effect=AssertionError("body resolver")
            ),
            mock.patch.object(self.app, "collect_json", side_effect=AssertionError("collection")),
            mock.patch.object(
                reading_policy, "status", side_effect=AssertionError("policy writer")
            ),
            self.fixture._serving(self.app) as port,
        ):
            for query, reason in (
                ("harness=claude&sid=missing", "source-unavailable"),
                ("harness=codex&sid=s1", "unsupported-source"),
                ("harness=pi&sid=s1", "unsupported-source"),
            ):
                with self.subTest(query=query):
                    status, body = self.get(port, query)
                    self.assertEqual(200, status, body)
                    preview = json.loads(body)["long_plan"]
                    self.assertEqual(reason, preview["reason"])
                    self.assertFalse(preview["supported"])
                    self.assertIsNone(preview["allowance"]["remaining"])
            self.state.snapshot.clear()
            status, body = self.get(port)
            self.assertEqual(200, status)
            self.assertEqual("source-unavailable", json.loads(body)["long_plan"]["reason"])

    def test_preview_refuses_duplicate_invalid_and_oversized_queries_before_resolution(
        self,
    ) -> None:
        with (
            mock.patch.object(
                observer, "resolve_transcript", side_effect=AssertionError("resolver")
            ),
            self.fixture._serving(self.app) as port,
        ):
            for query in (
                "",
                "harness=claude&sid=",
                "harness=claude&sid=s1&sid=s2",
                "harness=claude&sid=s1&extra=1",
                "harness=claude&sid=../../private",
                "harness=claude&sid=" + "a" * 129,
            ):
                with self.subTest(query=query):
                    self.assertEqual(400, self.get(port, query)[0])
            for headers in (
                {"Sec-Fetch-Mode": "navigate", "Sec-Fetch-Dest": "document"},
                {"Sec-Fetch-Site": "cross-site"},
                {"Sec-Fetch-Site": "same-site"},
                {"Origin": "https://other.example"},
            ):
                with self.subTest(headers=headers):
                    self.assertEqual(403, self.get(port, headers=headers)[0])

    def test_closed_long_fields_refuse_before_settings_keep_adoption_or_unasked(self) -> None:
        payloads = [
            {"plan_binding": "a" * 64},
            self.press(mode="single"),
            self.press(plan_binding=None),
            self.press(plan_binding="A" * 64),
            self.press(plan_binding="a" * 65),
            self.press(expected_revision=True),
            self.press(expected_revision=2**53),
            self.press(expected_revision=-1),
            self.press(provider=[]),
            self.press(model=""),
            self.press(destination=None),
            self.press(words_destination=""),
            self.press(consent="on"),
            self.press(ci_read="on"),
            self.press(unasked_grant=True),
        ]
        for key in (
            "plan_binding",
            "expected_revision",
            "provider",
            "model",
            "destination",
            "words_destination",
        ):
            payload = self.press()
            del payload[key]
            payloads.append(payload)
        before = reading_policy.store_path(self.config).read_bytes()
        with (
            mock.patch.object(
                observer, "resolve_transcript", side_effect=AssertionError("resolver")
            ),
            mock.patch.object(self.app, "collect_json", side_effect=AssertionError("collection")),
            self.fixture._serving(self.app) as port,
        ):
            for payload in payloads:
                with self.subTest(payload=payload):
                    payload.update(
                        {
                            "press": True,
                            "observer_model": 1,
                            "settle_through": "bad",
                            "adopt": "bad",
                        }
                    )
                    self.assertEqual(400, self.fixture._post(port, payload)[0])
        self.assertEqual(before, reading_policy.store_path(self.config).read_bytes())
        self.assertEqual([], self.fixture.outcomes)

    def test_stale_intent_route_or_binding_refuses_without_keeping_or_adopting(self) -> None:
        with (
            mock.patch.object(reading_route, "resolve", return_value=self.route),
            mock.patch.object(observer, "resolve_transcript", return_value=str(self.path)),
            mock.patch.object(self.app, "collect_json", side_effect=AssertionError("collection")),
            self.fixture._serving(self.app) as port,
        ):
            _, body = self.get(port)
            binding = json.loads(body)["long_plan"]["binding"]
            for changes in (
                {"plan_binding": "f" * 64},
                {"expected_revision": 2},
                {"model": "changed"},
                {"destination": "foreign"},
                {"words_destination": "foreign"},
            ):
                with self.subTest(changes=changes):
                    status, body = self.fixture._post(
                        port,
                        self.press(
                            **{
                                "plan_binding": binding,
                                "settle_through": "bad",
                                "adopt": "bad",
                                **changes,
                            }
                        ),
                    )
                    self.assertEqual(409, status, body)
                    self.assertEqual("plan-changed", json.loads(body)["reason"])
            annotations_store.annotate(
                self.config,
                self.state,
                "claude",
                "s1",
                goal="NEW PRIVATE INTENT",
                output="",
                now=20.0,
            )
            status, body = self.fixture._post(port, self.press(plan_binding=binding))
            self.assertEqual(409, status, body)
        self.assertEqual([], self.fixture.outcomes)

    def test_missing_cached_policy_stays_unknown_without_creating_a_database(self) -> None:
        reading_policy.store_path(self.config).unlink()
        self.state.snapshot.publish(
            (self.config.window_hours, False), json.dumps({"sessions": [self.row]}).encode()
        )
        with (
            mock.patch.object(reading_route, "resolve", return_value=self.route),
            mock.patch.object(observer, "resolve_transcript", return_value=str(self.path)),
            self.fixture._serving(self.app) as port,
        ):
            status, body = self.get(port)
        self.assertEqual(200, status, body)
        allowance = json.loads(body)["long_plan"]["allowance"]
        self.assertEqual("unknown", allowance["state"])
        self.assertIsNone(allowance["remaining"])
        self.assertFalse(reading_policy.store_path(self.config).exists())

    def test_omitted_mode_retains_one_call_ordinary_analyze(self) -> None:
        with (
            self.fixture._counting_model(installed=("claude",), harness="claude") as calls,
            self.fixture._serving(self.app) as port,
        ):
            status, body = self.fixture._post(port, self.fixture._claude_press(provider="claude"))
        self.assertEqual(202, status, body)
        self.assertEqual(1, len(calls))

    def test_settings_change_requires_an_explicit_new_preview(self) -> None:
        with (
            mock.patch.object(reading_route, "resolve", return_value=self.route),
            mock.patch.object(observer, "resolve_transcript", return_value=str(self.path)),
            self.fixture._serving(self.app) as port,
        ):
            _, body = self.get(port)
            old = json.loads(body)["long_plan"]
            settings.save(self.config, {"analyze_prompt_bytes": 256 * 1024})
            status, body = self.fixture._post(port, self.press(plan_binding=old["binding"]))
            self.assertEqual(409, status, body)
            _, body = self.get(port)
            current = json.loads(body)["long_plan"]
            self.assertNotEqual(old["binding"], current["binding"])
            self.assertEqual(256 * 1024, current["prompt"]["saved_ceiling_bytes"])

    def test_unreadable_or_symlink_native_metadata_does_not_claim_supported_source(self) -> None:
        link = self.path.with_name("symlink.jsonl")
        link.symlink_to(self.path)
        with (
            mock.patch.object(reading_route, "resolve", return_value=self.route),
            mock.patch.object(observer, "resolve_transcript") as resolve,
            self.fixture._serving(self.app) as port,
        ):
            for path in (str(link), str(self.path.with_name("missing.jsonl")), None):
                with self.subTest(path=path):
                    resolve.return_value = path
                    status, body = self.get(port)
                    self.assertEqual(200, status, body)
                    preview = json.loads(body)["long_plan"]
                    self.assertFalse(preview["supported"])
                    self.assertEqual("source-unavailable", preview["reason"])
