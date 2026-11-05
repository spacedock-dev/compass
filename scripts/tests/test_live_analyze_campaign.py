"""Live study bindings follow the invocation; synthetic accounts never call a provider."""

from __future__ import annotations

import importlib
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import abstention_ledger as ledger
import analyze_campaign
import live_analyze_campaign
import score_abstention

if TYPE_CHECKING:
    from tests import test_analyze_campaign as campaign_cases
else:
    import test_analyze_campaign as campaign_cases


class LiveInvocationBinding(unittest.TestCase):
    def setUp(self) -> None:
        config, _, _ = score_abstention._runtime()
        self.observer = importlib.import_module("compass_runtime.observer")
        assert self.observer.__file__ is not None
        self.source = Path(self.observer.__file__).parent
        controls = importlib.import_module("compass_runtime.claude_settings")
        route = importlib.import_module("compass_runtime.reading_route")
        self.supervise = importlib.import_module("compass_runtime.supervise")
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.config = config.build_runtime_config(
            environ={"HOME": str(self.root)},
            platform_name="darwin",
            os_name="posix",
            launcher_path=self.root / "server.py",
        )
        binary = self.root / "never-executed-claude"
        binary.write_text("synthetic verified identity, never executable")
        self.verified = score_abstention.VerifiedClaude(
            "synthetic-cli",
            "synthetic-version",
            str(binary),
            "synthetic-signature",
            score_abstention.file_identity(str(binary)),
        )
        for patcher in (
            mock.patch.object(route, "destination", return_value=route.VENDORS["claude"]),
            mock.patch.object(
                controls, "resolve", return_value=controls.Controls(deployment="direct")
            ),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def binding(self, *, analyze: bool = False) -> dict[str, Any]:
        return analyze_campaign.verified_transport_binding(
            self.config,
            self.verified,
            self.observer,
            claude_executor=self.observer.claude_exec,
            analyze=analyze,
        )

    def test_default_binding_is_unchanged_and_analyze_binds_its_distinct_controls(self) -> None:
        baseline = analyze_campaign.verified_transport_binding(
            self.config,
            self.verified,
            self.observer,
            claude_executor=self.observer.claude_exec,
        )
        self.assertEqual(baseline, self.binding(analyze=False))
        self.assertEqual(self.observer.claude_reading_provenance(self.config), baseline["reading"])
        self.assertEqual(
            score_abstention.argv_digest("claude", self.config), baseline["argv_digest"]
        )
        changed = self.binding(analyze=True)
        self.assertEqual(
            self.observer.claude_reading_provenance(self.config, analyze=True), changed["reading"]
        )
        self.assertNotEqual(
            baseline["reading"]["envelope_digest"], changed["reading"]["envelope_digest"]
        )
        self.assertNotEqual(baseline["argv_digest"], changed["argv_digest"])

    def test_live_wrapper_binds_and_forwards_each_flag_without_starting_a_process(self) -> None:
        for analyze in (False, True):
            with self.subTest(analyze=analyze):
                invocations: list[tuple[list[str], dict[str, Any]]] = []

                def runner(
                    command: list[str],
                    *,
                    captured: list[tuple[list[str], dict[str, Any]]] = invocations,
                    **kwargs: Any,
                ) -> Any:
                    captured.append((command, kwargs))
                    kwargs["stdout"].write(b"local test answer")
                    return SimpleNamespace(returncode=0)

                def inner(config: Any, prompt: str, **kwargs: Any) -> tuple[str, str]:
                    if kwargs["runner"] is self.supervise.run:
                        kwargs["runner"] = runner
                    return cast(
                        "tuple[str, str]", self.observer.claude_exec(config, prompt, **kwargs)
                    )

                observer = SimpleNamespace(
                    __file__=self.observer.__file__,
                    claude_exec=inner,
                    claude_reading_provenance=self.observer.claude_reading_provenance,
                )
                campaign = mock.Mock()
                campaign.request_slot.return_value = "live000"
                campaign.reserve.return_value = "synthetic-charge"
                with mock.patch.object(analyze_campaign, "Campaign", return_value=campaign):
                    wrapper = live_analyze_campaign.LiveTransport(observer, verified=self.verified)
                observer.claude_exec = wrapper
                expected = analyze_campaign.request_digest(
                    "local prompt",
                    self.binding(analyze=analyze),
                    analyze_campaign.runtime_source_digest(wrapper.source),
                    100,
                )
                self.assertEqual(
                    ("local test answer", "ok"),
                    wrapper(
                        self.config,
                        "local prompt",
                        output_cap_bytes=100,
                        analyze=analyze,
                    ),
                )
                campaign.request_slot.assert_called_once_with("live", expected)
                campaign.reserve.assert_called_once_with("live", "live000", expected, retry=False)
                self.assertEqual(1, len(invocations))
                command, options = invocations[0]
                self.assertEqual("local prompt", options["input"])
                self.assertEqual(analyze, "--settings" in command)
                if analyze:
                    self.assertEqual(
                        '{"switchModelsOnFlag":false}', command[command.index("--settings") + 1]
                    )
                    self.assertEqual("1", options["env"]["DISABLE_COMPACT"])

    def test_an_old_reviewed_request_cannot_charge_the_altered_live_invocation(self) -> None:
        fixture = campaign_cases.CampaignReservations()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        source = analyze_campaign.runtime_source_digest(self.source)
        old_request = analyze_campaign.request_digest("local prompt", self.binding(), source, 100)
        slot = fixture.slots["live"][0]
        fixture.body["requests"]["live"][slot] = old_request
        fixture.activate()
        campaign = fixture.campaign()
        campaign_cases.seed_predecessor(campaign, "replay")
        campaign_cases.seed_predecessor(campaign, "qualification")
        before = fixture.state.read_bytes()
        observer = SimpleNamespace(
            __file__=self.observer.__file__,
            claude_exec=self.observer.claude_exec,
            claude_reading_provenance=self.observer.claude_reading_provenance,
        )
        with mock.patch.object(analyze_campaign, "Campaign", return_value=campaign):
            wrapper = live_analyze_campaign.LiveTransport(observer, verified=self.verified)
        observer.claude_exec = wrapper
        with (
            mock.patch.object(
                self.supervise, "run", side_effect=AssertionError("no process may start")
            ),
            mock.patch.object(campaign, "reserve", wraps=campaign.reserve) as reserve,
            self.assertRaisesRegex(ledger.LedgerError, "next frozen campaign request"),
        ):
            wrapper(self.config, "local prompt", output_cap_bytes=100, analyze=True)
        reserve.assert_not_called()
        self.assertEqual(before, fixture.state.read_bytes())
        changed = analyze_campaign.request_digest(
            "local prompt", self.binding(analyze=True), source, 100
        )
        with self.assertRaises(ledger.LedgerError):
            campaign.reserve("live", slot, changed)
        self.assertEqual(before, fixture.state.read_bytes())
        self.assertEqual(
            [], [call for call in campaign._state()["calls"] if call["lane"] == "live"]
        )
