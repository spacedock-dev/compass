"""The reader's reading limits: the store, its two routes, and the press that reads them.

Measured on an 18-hour Claude Code session (2026-10-28): the press read back to the window's start,
then kept 103 of 187 messages under the project's 100-event cap, listed 12 of its checks and sent a
16,384-byte prompt, and the reading said it could not tell. These pin that the reader's settings,
not those constants, now bound a press, and that the page keeps its own.
"""

from __future__ import annotations

import contextlib
import http.client
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest import mock

from compass_runtime import (
    analyze_capacity,
    claude_settings,
    cli,
    observer,
    project_context,
    reading,
    reading_route,
    settings,
)

from . import test_press_message_reach as reach_tests
from .support import make_runtime, make_server, serve_until_closed


class StoreTest(unittest.TestCase):
    def setUp(self) -> None:
        home = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, home, True)
        self.config = SimpleNamespace(state_home=home)
        self.path = settings.store_path(self.config)  # type: ignore[arg-type]

    def load(self) -> settings.Settings:
        return settings.load(self.config)  # type: ignore[arg-type]

    def save(self, changes: dict[str, Any]) -> settings.Settings:
        return settings.save(self.config, changes)  # type: ignore[arg-type]

    def test_no_store_reads_as_the_defaults_and_they_exceed_the_old_constants(self) -> None:
        self.assertEqual(settings.DEFAULTS, self.load())
        self.assertGreater(
            settings.DEFAULTS.analyze_prompt_bytes, observer.OBSERVER_MODEL_MAX_PROMPT_BYTES
        )
        self.assertGreater(
            settings.DEFAULTS.analyze_record_events, project_context.MAX_PROJECT_EVENTS
        )
        self.assertGreater(
            settings.DEFAULTS.analyze_listed_checks, project_context.TOOL_REPORT_MAX_ENTRIES
        )
        self.assertGreater(settings.DEFAULTS.analyze_scan_megabytes * 1024 * 1024, 8 * 1024 * 1024)

    def test_no_setting_can_read_less_than_the_constants_it_replaced(self) -> None:
        floors = {limit.key: limit.minimum for limit in settings.LIMITS}
        self.assertEqual(
            {
                "analyze_prompt_bytes": observer.OBSERVER_MODEL_MAX_PROMPT_BYTES,
                "analyze_record_events": project_context.MAX_PROJECT_EVENTS,
                "analyze_listed_checks": project_context.TOOL_REPORT_MAX_ENTRIES,
                # The board's `turn_scan_max_bytes`, in MiB.
                "analyze_scan_megabytes": 8,
            },
            floors,
        )

    def test_a_saved_value_is_read_back_and_only_changes_are_stored(self) -> None:
        saved = self.save({"analyze_record_events": 500})
        self.assertEqual(500, saved.analyze_record_events)
        self.assertEqual(500, self.load().analyze_record_events)
        with open(self.path, encoding="utf-8") as handle:
            self.assertEqual({"analyze_record_events": 500}, json.load(handle))
        self.assertEqual(0o600, os.stat(self.path).st_mode & 0o777)

    def test_null_restores_the_default(self) -> None:
        self.save({"analyze_prompt_bytes": 32_768})
        self.assertEqual(settings.DEFAULTS, self.save({"analyze_prompt_bytes": None}))

    def test_opt_in_large_prompt_preferences_round_trip_and_keep_the_default(self) -> None:
        limit = next(item for item in settings.LIMITS if item.key == "analyze_prompt_bytes")
        self.assertEqual(2_097_152, limit.maximum)
        self.assertEqual(524_288, limit.default)
        for value in (513 * 1024, 2048 * 1024):
            with self.subTest(value=value):
                self.save({"analyze_prompt_bytes": value})
                self.assertEqual(value, self.load().analyze_prompt_bytes)
        before = Path(self.path).read_bytes()
        with self.assertRaises(settings.InvalidSettingError):
            self.save({"analyze_prompt_bytes": 2_097_153, "analyze_record_events": 1234})
        self.assertEqual(before, Path(self.path).read_bytes())
        self.assertEqual(524_288, self.save({"analyze_prompt_bytes": None}).analyze_prompt_bytes)

    def test_one_bad_value_writes_nothing(self) -> None:
        self.save({"analyze_listed_checks": 40})
        for bad in (
            {"analyze_listed_checks": 50, "analyze_prompt_bytes": 1},
            {"analyze_listed_checks": 50, "analyze_prompt_bytes": 2_097_153},
            {"analyze_listed_checks": 50, "analyze_prompt_bytes": "65536"},
            {"analyze_listed_checks": 50, "analyze_prompt_bytes": True},
            {"analyze_listed_checks": 50, "analyze_prompt_bytes": 65_536.0},
            {"analyze_listed_checks": 50, "unknown": 1},
        ):
            with self.subTest(bad=bad), self.assertRaises(settings.InvalidSettingError):
                self.save(bad)
            self.assertEqual(40, self.load().analyze_listed_checks)

    def test_a_damaged_store_reads_as_defaults_value_by_value(self) -> None:
        for content in (
            b"not json",
            b"[1, 2]",
            b"\xff\xfe",
            b" " * 5000 + b"{}",
            json.dumps({"analyze_prompt_bytes": 1, "analyze_record_events": 300}).encode(),
        ):
            with self.subTest(content=content[:20]):
                Path(self.path).write_bytes(content)
                loaded = self.load()
                self.assertEqual(
                    settings.DEFAULTS.analyze_prompt_bytes, loaded.analyze_prompt_bytes
                )
        # The valid value beside an invalid one is kept.
        self.assertEqual(300, self.load().analyze_record_events)

    def test_published_names_every_limit_with_its_bounds(self) -> None:
        published = settings.published(self.load())
        self.assertEqual(settings.DEFAULTS._asdict(), published["values"])
        self.assertEqual(
            [limit.key for limit in settings.LIMITS],
            [limit["key"] for limit in published["limits"]],
        )
        for limit in published["limits"]:
            self.assertLessEqual(limit["minimum"], limit["default"])
            self.assertLessEqual(limit["default"], limit["maximum"])


class RoutesTest(unittest.TestCase):
    def setUp(self) -> None:
        home = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, home, True)
        self.config, state = make_runtime(state_home=home, state_dir=Path(home))
        self.application = cli.build_application(self.config, state, clock=lambda: 1_000.0)

    @contextlib.contextmanager
    def serving(self) -> Any:
        httpd = make_server(application=self.application)
        thread = serve_until_closed(httpd)
        try:
            yield httpd.server_port
        finally:
            httpd.shutdown()
            thread.join(timeout=5)

    @staticmethod
    def request(
        port: int, method: str, body: Any = None, headers: dict[str, str] | None = None
    ) -> tuple[int, bytes]:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        try:
            data = None if body is None else json.dumps(body).encode()
            conn.request(method, "/api/settings", body=data, headers=headers or {})
            response = conn.getresponse()
            return response.status, response.read()
        finally:
            conn.close()

    def test_get_answers_the_defaults_and_their_bounds(self) -> None:
        with self.serving() as port:
            status, body = self.request(port, "GET")
        self.assertEqual(200, status)
        published = json.loads(body)
        self.assertEqual(
            settings.published(settings.DEFAULTS),
            {key: published[key] for key in ("values", "limits")},
        )
        self.assertEqual({"claude", "codex"}, set(published["capacities"]))

    def test_post_saves_and_answers_what_is_now_in_force(self) -> None:
        with self.serving() as port:
            status, body = self.request(port, "POST", {"values": {"analyze_listed_checks": 75}})
            _status, after = self.request(port, "GET")
        self.assertEqual(200, status)
        self.assertEqual(75, json.loads(body)["values"]["analyze_listed_checks"])
        self.assertEqual(75, json.loads(after)["values"]["analyze_listed_checks"])

    def test_get_post_publish_the_same_capacities_without_clamping_preference(self) -> None:
        with (
            mock.patch.object(
                claude_settings,
                "resolve",
                return_value=claude_settings.Controls(deployment="direct"),
            ) as controls,
            self.serving() as port,
        ):
            status, posted = self.request(
                port, "POST", {"values": {"analyze_prompt_bytes": 2_097_152}}
            )
            self.assertEqual(200, status)
            _, fetched = self.request(port, "GET")
            self.assertEqual(json.loads(posted), json.loads(fetched))
            capacities = json.loads(fetched)["capacities"]
            self.assertEqual(2_097_152, capacities["claude"]["maximum_prompt_bytes"])
            self.assertEqual(524_288, capacities["codex"]["maximum_prompt_bytes"])
            controls.return_value = claude_settings.Controls(
                deployment="direct", window_limits=(145_000,)
            )
            _, reduced = self.request(port, "GET")
            reduced_body = json.loads(reduced)
            self.assertEqual(2_097_152, reduced_body["values"]["analyze_prompt_bytes"])
            self.assertEqual(1674, reduced_body["capacities"]["claude"]["maximum_prompt_bytes"])
            self.assertFalse(reduced_body["capacities"]["claude"]["can_lower_prompt_setting"])
            self.assertEqual(2_097_152, settings.load(self.config).analyze_prompt_bytes)
            admission = analyze_capacity.Admission(
                "claude",
                self.config.claude_reading_model,
                observer.CLAUDE_READING_SYSTEM_PROMPT,
                requested_maximum=settings.load(self.config).analyze_prompt_bytes,
            )
            self.assertIsNone(admission("small 界🙂"))

    def test_an_out_of_range_post_is_refused_and_writes_nothing(self) -> None:
        with self.serving() as port:
            status, body = self.request(port, "POST", {"values": {"analyze_prompt_bytes": 10}})
        self.assertEqual(400, status)
        # The caller's key never reaches the reply: the reason is written into the status line.
        self.assertNotIn(b"analyze_prompt_bytes", body)
        self.assertFalse(os.path.exists(settings.store_path(self.config)))

    def test_a_body_without_values_is_refused(self) -> None:
        for body in ({}, {"values": [1]}, [1], "x"):
            with self.subTest(body=body), self.serving() as port:
                status, _body = self.request(port, "POST", body)
            self.assertEqual(400, status)

    def test_a_cross_site_post_is_refused(self) -> None:
        with self.serving() as port:
            status, _body = self.request(
                port,
                "POST",
                {"values": {"analyze_listed_checks": 75}},
                {"Sec-Fetch-Site": "cross-site"},
            )
        self.assertEqual(403, status)
        self.assertFalse(os.path.exists(settings.store_path(self.config)))


class CapacityPreviewTest(unittest.TestCase):
    def preview(self, **kwargs: Any) -> Any:
        self.assertTrue(
            hasattr(analyze_capacity, "preview"), "preview must not imply a measured empty prompt"
        )
        return analyze_capacity.preview(
            "claude", "claude-sonnet-5-5", observer.CLAUDE_READING_SYSTEM_PROMPT, **kwargs
        )

    def test_preview_publishes_allowance_without_actual_input_or_admission_claims(self) -> None:
        with mock.patch.object(
            claude_settings, "resolve", return_value=claude_settings.Controls(deployment="direct")
        ):
            preview = self.preview()
        self.assertEqual("estimated", preview["reason"])
        self.assertEqual(2_097_152, preview["maximum_prompt_bytes"])
        self.assertFalse(preview["fit_verified"])
        self.assertFalse(preview["policy_verified"])
        self.assertTrue(preview["can_lower_prompt_setting"])
        for key in (
            "allowed",
            "prompt_bytes",
            "estimated_input_tokens",
            "estimated_total_tokens",
            "requested_maximum",
        ):
            self.assertNotIn(key, preview)

    def test_preview_preserves_unknown_gateway_dynamic_and_lower_controls(self) -> None:
        cases = (
            (claude_settings.Controls(deployment="gateway"), 524_288, "estimated"),
            (
                claude_settings.Controls(deployment="unknown", window_limits=(200_000,)),
                166_674,
                "estimated",
            ),
            (
                claude_settings.Controls(deployment="direct", window_limits=(128_000,)),
                0,
                "context-no-room",
            ),
            (
                claude_settings.Controls(deployment="direct", window_limits=(145_000,)),
                1674,
                "estimated",
            ),
            (claude_settings.Controls(refusal="dynamic-policy"), 0, "context-dynamic"),
            (claude_settings.Controls(refusal="context-config"), 0, "context-config"),
        )
        for controls, maximum, reason in cases:
            with (
                self.subTest(reason=reason, maximum=maximum),
                mock.patch.object(claude_settings, "resolve", return_value=controls),
            ):
                preview = self.preview()
                self.assertEqual(maximum, preview["maximum_prompt_bytes"])
                self.assertEqual(reason, preview["reason"])
                self.assertEqual(maximum >= 16_384, preview["can_lower_prompt_setting"])

    def preview_with_remote_cache(self, document: dict[str, Any]) -> Any:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        cache = root / "Users/r/.claude/remote-settings.json"
        cache.parent.mkdir(parents=True)
        cache.write_text(json.dumps(document), encoding="utf-8")
        return self.preview(environ={"HOME": "/Users/r", "USER": "r"}, root=root)

    def test_a_reader_with_an_org_cache_that_only_enables_channels_still_sees_an_allowance(
        self,
    ) -> None:
        preview = self.preview_with_remote_cache({"channelsEnabled": True})
        self.assertEqual("estimated", preview["reason"])
        self.assertGreater(preview["maximum_prompt_bytes"], 0)
        self.assertEqual("", preview["configuration_reason"])

    def test_a_reader_with_an_org_cache_that_overrides_models_is_refused_as_before(self) -> None:
        preview = self.preview_with_remote_cache({"modelOverrides": {"claude-sonnet-5-5": "x"}})
        self.assertEqual(reading.WITHHELD_CONTEXT_DYNAMIC, preview["reason"])
        self.assertEqual(0, preview["maximum_prompt_bytes"])
        refusal, spent = reading._STATUS_FAILURES[preview["reason"]]
        self.assertFalse(spent)
        self.assertIn("managed policy that can change at launch", reading.WITHHELD[refusal])

    def test_tiny_window_admits_small_actual_text_and_refuses_without_bad_setting_advice(
        self,
    ) -> None:
        with mock.patch.object(
            claude_settings,
            "resolve",
            return_value=claude_settings.Controls(deployment="direct", window_limits=(145_000,)),
        ):
            admission = analyze_capacity.Admission(
                "claude",
                "claude-sonnet-5-5",
                observer.CLAUDE_READING_SYSTEM_PROMPT,
                requested_maximum=2_097_152,
            )
            self.assertIsNone(admission("small 界🙂"))
            status = admission("x" * 2000)
            self.assertEqual("context-small-window", status)
            assert status is not None
            self.assertNotIn("Lower Prompt size", reading.WITHHELD[status])

    def test_selected_route_preview_uses_actual_provider_and_model(self) -> None:
        with mock.patch.object(
            claude_settings, "resolve", return_value=claude_settings.Controls(deployment="direct")
        ) as controls:
            route = reading_route.resolve(
                "claude", binary_resolver=lambda name: f"/synthetic/{name}"
            )
            self.assertIn("capacity", route)
            self.assertEqual(2_097_152, route["capacity"]["maximum_prompt_bytes"])
            controls.assert_called_with(route["model"], environ=None, root=None)
            codex = reading_route.resolve(
                "codex", binary_resolver=lambda name: f"/synthetic/{name}"
            )
            self.assertEqual(524_288, codex["capacity"]["maximum_prompt_bytes"])
            unasked = reading_route.resolve(
                "claude", binary_resolver=lambda name: f"/synthetic/{name}", unasked=True
            )
            self.assertNotIn("capacity", unasked)

    def test_future_model_preview_and_large_gateway_override_remain_conservative(self) -> None:
        self.assertTrue(hasattr(analyze_capacity, "preview"))
        for model, controls in (
            ("claude-sonnet-6", claude_settings.Controls(deployment="direct")),
            (
                "claude-sonnet-5-5",
                claude_settings.Controls(deployment="gateway", window_limits=(10_000_000,)),
            ),
        ):
            with (
                self.subTest(model=model),
                mock.patch.object(claude_settings, "resolve", return_value=controls),
            ):
                preview = analyze_capacity.preview(
                    "claude", model, observer.CLAUDE_READING_SYSTEM_PROMPT
                )
                self.assertEqual(524_288, preview["maximum_prompt_bytes"])
                self.assertFalse(preview["fit_verified"])


class ThePressReadsTheSettings(reach_tests.TheHttpPressAsksForItsOwnWindow):
    def test_the_window_carries_the_readers_record_listing_and_scan_limits(self) -> None:
        settings.save(
            self.config,
            {
                "analyze_record_events": 750,
                "analyze_listed_checks": 90,
                "analyze_scan_megabytes": 64,
            },
        )
        _got, asked = self.press(self.context())
        self.assertEqual(750, asked[0].cap)
        self.assertEqual(90, asked[0].listed)
        self.assertEqual(64 * 1024 * 1024, asked[0].scan_bytes)

    def test_the_prompt_is_bounded_by_the_readers_setting(self) -> None:
        settings.save(self.config, {"analyze_prompt_bytes": 65_536})
        with mock.patch.object(reading, "produce", return_value=(None, "", False)) as produce:
            self.press(self.context())
        self.assertEqual(65_536, produce.call_args.kwargs["max_prompt_bytes"])

    def test_without_settings_a_press_reads_the_defaults(self) -> None:
        with mock.patch.object(reading, "produce", return_value=(None, "", False)) as produce:
            _got, asked = self.press(self.context())
        self.assertEqual(settings.DEFAULTS.analyze_record_events, asked[0].cap)
        self.assertEqual(settings.DEFAULTS.analyze_listed_checks, asked[0].listed)
        self.assertEqual(
            settings.DEFAULTS.analyze_prompt_bytes, produce.call_args.kwargs["max_prompt_bytes"]
        )


class TheCapsFollowThePress(reach_tests.PressReachTestCase):
    def test_a_press_cap_above_the_projects_keeps_the_whole_window(self) -> None:
        for index in range(project_context.MAX_PROJECT_EVENTS + 20):
            self.say(f"Step {index}.")
        window = self.window_at()._replace(cap=project_context.MAX_PROJECT_EVENTS * 3)
        context = self.collect(reach=window)
        self.assertIs(context["sources"]["message_reach"]["tail_truncated"], False)
        self.assertEqual(
            project_context.MAX_PROJECT_EVENTS + 20, len(self.facts(context, "agent_message"))
        )

    def test_a_press_listing_cap_lists_more_checks_and_the_page_keeps_twelve(self) -> None:
        for index in range(30):
            self.session.write(self.file(f"src/f{index}.py"))

        def writes(context: dict[str, Any]) -> int:
            return sum(
                fact.get("subject") == "write" for fact in self.facts(context, "tool_report")
            )

        self.assertEqual(30, writes(self.collect(reach=self.window_at()._replace(listed=100))))
        self.assertEqual(project_context.TOOL_REPORT_MAX_ENTRIES, writes(self.collect()))


class OnePressBuildsOneTally(reach_tests.PressReachTestCase):
    def test_inside_a_press_the_listing_and_the_tails_share_one_build(self) -> None:
        self.session.write(self.file("src/a.py"))
        self.session.save(self.path)
        path = str(self.path)
        with mock.patch.object(
            project_context, "_built_tally", wraps=project_context._built_tally
        ) as built:
            with project_context.shared_tallies():
                first = project_context._claude_tally(self.config, path)
                second = project_context._claude_tally(self.config, path)
            third = project_context._claude_tally(self.config, path)
        self.assertIs(first, second)
        self.assertIsNot(first, third)
        self.assertEqual(2, built.call_count)

    def test_a_press_scan_bound_reaches_the_tails_it_sends(self) -> None:
        self.session.write(self.file("src/a.py"))
        self.session.save(self.path)
        state = SimpleNamespace(ci_remotes=None)
        with (
            mock.patch.object(observer, "resolve_transcript", return_value=str(self.path)),
            mock.patch.object(project_context, "claude_check_press") as press,
        ):
            project_context.press_checks(
                self.config, cast("Any", state), "claude", "s", scan_bytes=64 * 1024 * 1024
            )
        self.assertEqual(64 * 1024 * 1024, press.call_args.args[0].turn_scan_max_bytes)


class TheStoreIsReadAsARegularFileOnly(StoreTest):
    def test_a_link_or_a_fifo_at_the_path_reads_as_the_defaults(self) -> None:
        target = Path(self.path).with_name("elsewhere.json")
        target.write_text(json.dumps({"analyze_listed_checks": 40}))
        os.symlink(target, self.path)
        self.assertEqual(settings.DEFAULTS, self.load())
        os.unlink(self.path)
        os.mkfifo(self.path)
        self.assertEqual(settings.DEFAULTS, self.load())
