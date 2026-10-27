"""An explicit unasked grant never comes from a requested reading or Resume."""

from __future__ import annotations

import contextlib
import dataclasses
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from compass_runtime import io as runtime_io
from compass_runtime import reading_policy, reading_route, supervise

from .support import make_runtime


class UnaskedPermissionTest(unittest.TestCase):
    def setUp(self) -> None:
        home = tempfile.TemporaryDirectory()
        self.addCleanup(home.cleanup)
        self.config, _ = make_runtime(
            state_home=home.name, state_dir=Path(home.name), unasked_enabled=True
        )
        patcher = mock.patch.object(supervise, "_SHUTDOWN", threading.Event())
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_codex_needs_a_deliberate_destination_bound_grant_and_revoke_stops_the_next_send(
        self,
    ) -> None:
        model = mock.Mock(return_value=("{}", "ok"))
        guarded = reading_policy.GuardedModel(
            self.config, model, lambda: 100.0, provider="codex", destination="OpenAI", unasked=True
        )
        with self.assertRaises(reading_policy.RefusedError):
            guarded("words", output_cap_bytes=100)
        model.assert_not_called()
        reading_policy.set_unasked_grant(
            self.config, True, now=100.0, provider="codex", destination="OpenAI"
        )
        self.assertEqual(("{}", "ok"), guarded("words", output_cap_bytes=100))
        reading_policy.set_unasked_grant(
            self.config, False, now=100.0, provider="codex", destination="OpenAI"
        )
        self.assertTrue(reading_policy.status(self.config, now=100.0)["consent"])
        with self.assertRaises(reading_policy.RefusedError):
            guarded("words", output_cap_bytes=100)
        self.assertEqual(1, model.call_count)

    def test_claude_needs_no_grant_but_pause_and_startup_refusals_still_win(self) -> None:
        model = mock.Mock(return_value=("{}", "ok"))
        guarded = reading_policy.GuardedModel(
            self.config,
            model,
            lambda: 100.0,
            provider="claude",
            destination="Anthropic",
            unasked=True,
        )
        self.assertEqual(("{}", "ok"), guarded("words", output_cap_bytes=100))
        self.assertEqual(0, reading_policy.status(self.config, now=100.0)["used"])
        reading_policy.set_consent(self.config, False, now=101.0)
        with self.assertRaises(reading_policy.RefusedError):
            guarded("words", output_cap_bytes=100)
        answer = reading_policy.set_unasked_grant(
            self.config, True, now=102.0, provider="codex", destination="OpenAI"
        )
        self.assertEqual("model-calls-paused", answer["reason"])
        reading_policy.resume(self.config, now=103.0)
        self.assertFalse(
            reading_policy.status(self.config, now=103.0, destinations={"codex": "OpenAI"})[
                "words"
            ]["codex"]
        )
        for config in (
            dataclasses.replace(self.config, model_calls_disabled=True),
            dataclasses.replace(self.config, unasked_enabled=False),
        ):
            with self.assertRaises(reading_policy.RefusedError):
                reading_policy.GuardedModel(
                    config, model, lambda: 104.0, provider="claude", unasked=True
                )("words", output_cap_bytes=100)

    def test_analyze_budget_does_not_replace_the_unasked_lanes_own_caps(self) -> None:
        for _ in range(reading_policy.DAILY_CAP):
            reading_policy.reserve(self.config, now=100.0)
        answer = reading_policy.set_unasked_grant(
            self.config, True, now=100.0, provider="codex", destination="OpenAI"
        )
        self.assertEqual("daily-cap", answer["reason"])
        model = mock.Mock(return_value=("{}", "ok"))
        guarded = reading_policy.GuardedModel(
            self.config, model, lambda: 100.0, provider="codex", destination="OpenAI", unasked=True
        )
        self.assertEqual(("{}", "ok"), guarded("words", output_cap_bytes=100))
        self.assertEqual(
            reading_policy.DAILY_CAP, reading_policy.status(self.config, now=100.0)["used"]
        )

    def test_revoking_an_older_mixed_store_does_not_turn_it_into_a_master_pause(self) -> None:
        reading_policy.set_consent(self.config, True, now=100.0, destination="OpenAI")
        assert runtime_io.sqlite_module is not None
        with contextlib.closing(
            runtime_io.sqlite_module.connect(reading_policy.store_path(self.config))
        ) as db:
            db.execute("INSERT INTO provider_permission VALUES ('claude', 0)")
            db.commit()
        answer = reading_policy.set_unasked_grant(
            self.config, False, now=101.0, provider="codex", destination="OpenAI"
        )
        self.assertTrue(answer["consent"])
        self.assertFalse(answer["off"])
        self.assertFalse(answer["words"]["codex"])

    def test_the_grant_does_not_follow_a_destination_change_or_widen_content(self) -> None:
        answer = reading_policy.set_unasked_grant(
            self.config, True, now=100.0, provider="codex", destination="OpenAI"
        )
        self.assertTrue(answer["words"]["codex"])
        self.assertFalse(answer["providers"]["codex"])
        self.assertEqual({}, answer["tool_output"])
        with self.assertRaises(reading_policy.RefusedError):
            reading_policy.GuardedModel(
                self.config,
                mock.Mock(),
                lambda: 100.0,
                provider="codex",
                destination="",
                unasked=True,
            )("words", output_cap_bytes=100)

    def test_the_unasked_lane_takes_its_own_provider_and_claude_first_elsewhere(self) -> None:
        for harness in ("claude", "codex", "pi", "gemini", "opencode"):
            for present in ({"claude", "codex"}, {"claude"}, {"codex"}):
                with self.subTest(harness=harness, present=present):
                    expected = (
                        "codex"
                        if harness == "codex" and "codex" in present
                        else "claude"
                        if "claude" in present
                        else "codex"
                    )

                    def which(name: str, present: set[str] = present) -> str | None:
                        return f"/bin/{name}" if name in present else None

                    route = reading_route.resolve(harness, binary_resolver=which, unasked=True)
                    self.assertEqual(expected, route["provider"])

    def test_analyze_keeps_codex_first_where_no_own_producer_exists(self) -> None:
        # The 2026-10-20 ruling changed the unasked lane's provider, not Analyze's.
        def which(name: str) -> str:
            return f"/bin/{name}"

        self.assertEqual("codex", reading_route.resolve("pi", binary_resolver=which)["provider"])
        self.assertEqual(
            "claude", reading_route.resolve("pi", binary_resolver=which, unasked=True)["provider"]
        )
        self.assertEqual(
            [],
            [
                part
                for part in reading_route.unasked_parts(
                    reading_route.resolve("claude", binary_resolver=which, unasked=True)
                )
                if "agent's messages" in part or "outcome lines" in part
            ],
        )
