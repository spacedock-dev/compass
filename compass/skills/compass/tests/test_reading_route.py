"""Who reads a session, and what a reader is told about it before they press.

DRC-4650 built the Claude Code producer behind its own gate; the owner accepted
it on 2026-10-02. A Claude Code session is read by Claude Code when `claude` is
on PATH and by Codex when it is not, and the page says which before the press.
Every test here is about what a person is told or what spends their capacity,
and the route is the single place both are decided.
"""

from __future__ import annotations

import itertools
import json
import os
import platform
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, ClassVar, cast
from unittest import mock

from compass_runtime import (
    aggregate,
    observer,
    project_context,
    reading,
    reading_route,
    sessions,
)
from compass_runtime import annotations as annotation_store

from .reading_pins import named_machine, named_platform
from .support import make_config, make_runtime

HARNESSES = ("claude", "codex", "pi", "gemini")
STATES = ("usable", "missing", "unqualified")


def _resolver(installed: set[str]) -> Any:
    asked: list[str] = []

    def which(name: str) -> str | None:
        asked.append(name)
        return f"/usr/local/bin/{name}" if name in installed else None

    which.asked = asked  # type: ignore[attr-defined]
    return which


def _world(claude: str, codex: str) -> tuple[Any, Any]:
    """Patches for one machine: each provider usable, missing, or gated."""
    installed = {
        name for name, state in (("claude", claude), ("codex", codex)) if state != "missing"
    }
    gate = mock.patch.multiple(
        annotation_store,
        CLAUDE_ABSTENTION_CHECK=(
            annotation_store.ABSTENTION_CHECK_NOT_RUN
            if claude == "unqualified"
            else annotation_store.ABSTENTION_CHECK_PASSED
        ),
        ABSTENTION_CHECK=(
            annotation_store.ABSTENTION_CHECK_NOT_RUN
            if codex == "unqualified"
            else annotation_store.ABSTENTION_CHECK_ACCEPTED
        ),
    )
    return gate, _resolver(installed)


class TheOwnerAcceptedTheClaudeCodeCheck(unittest.TestCase):
    """Owner, 2026-10-02: the Claude Code producer is accepted, as Codex's was on
    2026-09-14, knowing every scored run failed. Accepted is not passed."""

    def test_the_claude_code_check_is_recorded_as_accepted_and_never_as_passed(self) -> None:
        self.assertEqual(
            annotation_store.ABSTENTION_CHECK_ACCEPTED, annotation_store.CLAUDE_ABSTENTION_CHECK
        )
        self.assertNotEqual(
            annotation_store.ABSTENTION_CHECK_PASSED, annotation_store.CLAUDE_ABSTENTION_CHECK
        )
        self.assertTrue(annotation_store.provider_enabled("claude"))
        self.assertTrue(annotation_store.provider_enabled("codex"))

    def test_each_gate_opens_only_its_own_provider(self) -> None:
        for check in (
            annotation_store.ABSTENTION_CHECK_PASSED,
            annotation_store.ABSTENTION_CHECK_ACCEPTED,
        ):
            with (
                self.subTest(check=check),
                mock.patch.multiple(
                    annotation_store,
                    CLAUDE_ABSTENTION_CHECK=check,
                    ABSTENTION_CHECK=annotation_store.ABSTENTION_CHECK_NOT_RUN,
                ),
            ):
                self.assertTrue(annotation_store.provider_enabled("claude"))
                self.assertFalse(annotation_store.provider_enabled("codex"))
                self.assertFalse(annotation_store.reading_enabled())
                self.assertTrue(annotation_store.any_reading_enabled())

    def test_no_other_name_is_a_provider(self) -> None:
        for name in ("", "gemini", "pi", "Claude", "openai"):
            with self.subTest(name=name):
                self.assertFalse(annotation_store.provider_enabled(name))

    def test_reading_enabled_still_means_the_codex_check(self) -> None:
        with mock.patch.multiple(
            annotation_store,
            ABSTENTION_CHECK=annotation_store.ABSTENTION_CHECK_NOT_RUN,
            CLAUDE_ABSTENTION_CHECK=annotation_store.ABSTENTION_CHECK_NOT_RUN,
        ):
            self.assertFalse(annotation_store.reading_enabled())
            self.assertFalse(annotation_store.any_reading_enabled())


class WhoReadsAClaudeCodeSessionOnThisBuild(unittest.TestCase):
    """The owner's routing, on the build as shipped with no gate patched: Claude Code
    reads a Claude Code session when `claude` is on PATH, and Codex reads it when not."""

    def setUp(self) -> None:
        patcher = named_machine()
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_with_claude_on_path_claude_code_reads_it_and_the_page_names_anthropic(
        self,
    ) -> None:
        for installed in ({"claude"}, {"codex", "claude"}):
            with self.subTest(installed=sorted(installed)):
                route = reading_route.resolve("claude", binary_resolver=_resolver(installed))
                self.assertEqual(("claude", False), (route["provider"], route["fallback"]))
                self.assertEqual(reading_route.REASON_OWN_HARNESS, route["reason"])
                self.assertEqual("This session's own harness reads it.", route["note"])
                self.assertIn("Anthropic", route["disclosure"])
                self.assertNotIn("OpenAI", route["disclosure"])
                self.assertNotIn("qualified", route["disclosure"])
                self.assertEqual(observer.CLAUDE_READING_MODEL, route["model"])

    def test_without_claude_on_path_codex_reads_it_and_says_why_before_the_press(self) -> None:
        route = reading_route.resolve("claude", binary_resolver=_resolver({"codex"}))
        self.assertEqual(("codex", True), (route["provider"], route["fallback"]))
        self.assertEqual(reading_route.REASON_FALLBACK_MISSING, route["reason"])
        self.assertIn("Claude Code CLI was not found", route["note"])
        self.assertIn("so Codex reads this session", route["note"])
        self.assertIn("OpenAI", route["disclosure"])
        self.assertNotIn("Anthropic", route["disclosure"])
        self.assertNotIn("qualified", route["note"])
        self.assertEqual(observer.OBSERVER_MODEL, route["model"])

    def test_with_neither_on_path_nothing_reads_it_and_it_says_not_installed(self) -> None:
        route = reading_route.resolve("claude", binary_resolver=_resolver(set()))
        self.assertEqual("", route["provider"])
        self.assertEqual(reading_route.REASON_NOT_INSTALLED, route["reason"])
        self.assertNotIn("qualified", route["note"])

    def test_a_closed_gate_is_read_before_the_machine_so_claude_is_never_looked_up(self) -> None:
        which = _resolver({"claude", "codex"})
        with mock.patch.object(
            annotation_store, "CLAUDE_ABSTENTION_CHECK", annotation_store.ABSTENTION_CHECK_NOT_RUN
        ):
            route = reading_route.resolve("claude", binary_resolver=which)
        self.assertNotIn("claude", which.asked)
        self.assertEqual(reading_route.REASON_FALLBACK_UNQUALIFIED, route["reason"])
        self.assertIn("Claude Code checks are not qualified on this build", route["note"])

    def test_without_codex_not_qualified_is_its_own_state_and_not_not_installed(self) -> None:
        with mock.patch.object(
            annotation_store, "CLAUDE_ABSTENTION_CHECK", annotation_store.ABSTENTION_CHECK_NOT_RUN
        ):
            gated = reading_route.resolve("claude", binary_resolver=_resolver({"claude"}))
        self.assertEqual("", gated["provider"])
        self.assertEqual("", gated["disclosure"])
        self.assertEqual(reading_route.REASON_UNQUALIFIED_OTHER_MISSING, gated["reason"])
        self.assertIn("Claude Code checks are not qualified on this build", gated["note"])
        self.assertIn("Codex CLI was not found", gated["note"])
        self.assertNotIn("Claude Code CLI was not found", gated["note"])
        bare = reading_route.resolve("claude", binary_resolver=_resolver(set()))
        self.assertEqual(reading_route.REASON_NOT_INSTALLED, bare["reason"])
        self.assertNotEqual(gated["note"], bare["note"])
        self.assertNotIn("qualified", bare["note"])

    def test_a_codex_session_is_read_by_codex(self) -> None:
        route = reading_route.resolve("codex", binary_resolver=_resolver({"codex", "claude"}))
        self.assertEqual(("codex", False), (route["provider"], route["fallback"]))
        self.assertEqual(reading_route.REASON_OWN_HARNESS, route["reason"])
        self.assertEqual("This session's own harness reads it.", route["note"])

    def test_a_codex_session_without_codex_falls_back_to_claude_code_and_says_so(self) -> None:
        # DEC-21 item 4 as written, which the 2026-09-23 amendment held back until the gate
        # opened: the other provider, named before the press.
        route = reading_route.resolve("codex", binary_resolver=_resolver({"claude"}))
        self.assertEqual(("claude", True), (route["provider"], route["fallback"]))
        self.assertIn("Codex CLI was not found", route["note"])
        self.assertIn("so Claude Code reads this session", route["note"])
        self.assertIn("Anthropic", route["disclosure"])

    def test_a_harness_with_no_producer_says_plainly_that_codex_reads_it(self) -> None:
        for harness in ("pi", "gemini", "opencode"):
            with self.subTest(harness=harness):
                route = reading_route.resolve(harness, binary_resolver=_resolver({"codex"}))
                self.assertEqual("codex", route["provider"])
                self.assertFalse(route["fallback"])
                self.assertEqual(reading_route.REASON_NO_OWN_PRODUCER, route["reason"])
                self.assertIn("no reading producer of its own", route["note"])
                self.assertIn("Codex reads this session", route["note"])

    def test_a_cli_found_only_by_a_relative_path_is_not_installed(self) -> None:
        for relative in ("codex", "./codex", "bin/codex"):
            with self.subTest(path=relative):
                route = reading_route.resolve(
                    "codex", binary_resolver=mock.Mock(return_value=relative)
                )
                self.assertEqual("", route["provider"])
                self.assertIn("Codex CLI was not found", route["note"])

    def test_resolving_a_route_never_starts_a_model(self) -> None:
        with mock.patch("subprocess.run", side_effect=AssertionError("a model started")) as run:
            for harness in HARNESSES:
                reading_route.resolve(harness, binary_resolver=_resolver({"codex", "claude"}))
        run.assert_not_called()


class WhoReadsASessionOnceClaudeCodeIsQualified(unittest.TestCase):
    """DEC-21 item 4, reached by patching the gate open: own harness first."""

    def setUp(self) -> None:
        patcher = named_machine()
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_claude_code_session_is_read_by_claude_code_and_the_page_names_anthropic(
        self,
    ) -> None:
        gate, which = _world("usable", "usable")
        with gate:
            route = reading_route.resolve("claude", binary_resolver=which)
        self.assertEqual(("claude", False), (route["provider"], route["fallback"]))
        self.assertEqual("Claude Code", route["label"])
        self.assertEqual(observer.CLAUDE_READING_MODEL, route["model"])
        self.assertIn("Anthropic", route["disclosure"])
        self.assertIn("your Claude Code CLI and its sign-in", route["disclosure"])
        self.assertNotIn("OpenAI", route["disclosure"])
        self.assertNotIn("Codex", route["disclosure"])

    def test_a_missing_claude_code_falls_back_to_codex_and_says_it_was_missing(self) -> None:
        gate, which = _world("missing", "usable")
        with gate:
            route = reading_route.resolve("claude", binary_resolver=which)
        self.assertEqual(("codex", True), (route["provider"], route["fallback"]))
        self.assertEqual(reading_route.REASON_FALLBACK_MISSING, route["reason"])
        self.assertIn("Claude Code CLI was not found", route["note"])
        self.assertIn("OpenAI", route["disclosure"])

    def test_a_codex_session_without_codex_falls_back_to_a_qualified_claude_code(self) -> None:
        gate, which = _world("usable", "missing")
        with gate:
            route = reading_route.resolve("codex", binary_resolver=which)
        self.assertEqual(("claude", True), (route["provider"], route["fallback"]))
        self.assertIn("Codex CLI was not found", route["note"])
        self.assertIn("Anthropic", route["disclosure"])


class EveryMachineGetsExactlyOneTrueAnswer(unittest.TestCase):
    """The whole table: every harness, every install state, every gate."""

    def _all(self) -> list[tuple[str, str, str, dict[str, Any]]]:
        rows = []
        for harness, claude, codex in itertools.product(HARNESSES, STATES, STATES):
            gate, which = _world(claude, codex)
            # A machine whose endpoint the resolver can name, so neither this
            # runner's environment nor its OS decides the `To:` item.
            with gate, named_platform():
                route = reading_route.resolve(
                    harness, binary_resolver=which, environ={}, root=Path("/nonexistent")
                )
                rows.append((harness, claude, codex, dict(route)))
        return rows

    def test_own_harness_first_then_the_other_then_nothing(self) -> None:
        for harness, claude, codex, route in self._all():
            with self.subTest(harness=harness, claude=claude, codex=codex):
                state = {"claude": claude, "codex": codex}
                preferred = "claude" if harness == "claude" else "codex"
                other = "codex" if preferred == "claude" else "claude"
                if state[preferred] == "usable":
                    expected = preferred
                elif state[other] == "usable":
                    expected = other
                else:
                    expected = ""
                self.assertEqual(expected, route["provider"])
                self.assertEqual(bool(expected) and expected != preferred, route["fallback"])
                self.assertIn(route["reason"], reading_route.REASONS)
                self.assertTrue(route["note"])
                self.assertEqual(harness, route["harness"])

    def test_every_disclosure_names_its_receiver_and_never_the_other_vendor(self) -> None:
        for harness, claude, codex, route in self._all():
            with self.subTest(harness=harness, claude=claude, codex=codex):
                if not route["provider"]:
                    self.assertEqual("", route["disclosure"])
                    self.assertEqual("", route["model"])
                    continue
                vendor = reading_route.VENDORS[route["provider"]]
                elsewhere = ({"OpenAI", "Anthropic"} - {vendor}).pop()
                self.assertIn(vendor, route["disclosure"])
                self.assertNotIn(elsewhere, route["disclosure"])
                self.assertIn(f"your {route['label']} CLI and its sign-in", route["disclosure"])
                self.assertIn("spending your capacity", route["disclosure"])
                self.assertTrue(route["disclosure"].startswith(route["note"]))
                self.assertIn("never a verification", route["disclosure"])

    def test_the_disclosure_parts_join_to_the_disclosure_word_for_word(self) -> None:
        # DRC-4758: the consent step shows the parts as a short list, so the
        # list must be the disclosure itself and not a rewording of it.
        for harness, claude, codex, route in self._all():
            with self.subTest(harness=harness, claude=claude, codex=codex):
                parts = route["disclosure_parts"]
                self.assertEqual(route["disclosure"], " ".join(parts))
                if not route["provider"]:
                    self.assertEqual([], parts)
                    continue
                self.assertEqual(route["note"], parts[0])
                self.assertTrue(all(part and part == part.strip() for part in parts))
                self.assertTrue(parts[-1].endswith("."))
                if route["tool_output"]:
                    # Tool output comes before the `To:` item, which says where all of it goes.
                    at = parts.index(route["tool_output"])
                    self.assertTrue(parts[at + 1].startswith("To: "), parts)
                # One item carries the caveat, and it closes the list (owner, 2026-10-02).
                self.assertEqual(1, sum("never a verification" in part for part in parts), parts)
                self.assertIn("never a verification", parts[-1])

    def test_the_parts_for_a_claude_code_reading_hold_what_its_cli_adds_on_their_own(
        self,
    ) -> None:
        parts = reading_route._base_parts("claude")
        added = [part for part in parts if "device identifier" in part]
        self.assertEqual(1, len(added))
        self.assertTrue(added[0].startswith("That CLI also sends"), added[0])
        self.assertFalse(
            any("device identifier" in part for part in reading_route._base_parts("codex"))
        )

    def test_a_claude_code_reading_discloses_what_its_cli_adds(self) -> None:
        # Owner ruling of 2026-09-27 on the review's Sent F1: under OAuth
        # sign-in the CLI adds the account's email address and ID to every
        # reading, and its environment block beside it. Accepted, so said.
        text = reading_route._base_disclosure("claude")
        for words in (
            "email address",
            "account ID",
            "working directory",
            "platform",
            "device identifier",
        ):
            with self.subTest(words=words):
                self.assertIn(words, text)
        self.assertNotIn("email address", reading_route._base_disclosure("codex"))

    def test_no_two_states_with_no_reader_share_a_sentence(self) -> None:
        seen: dict[str, tuple[str, str, str]] = {}
        for harness, claude, codex, route in self._all():
            if route["provider"] or harness == "gemini":
                continue
            key = route["note"]
            with self.subTest(harness=harness, claude=claude, codex=codex):
                self.assertNotIn(key, seen, f"shared with {seen.get(key)}")
            seen[key] = (harness, claude, codex)
        self.assertGreaterEqual(len(seen), 8)


class ThePagePublishesARoutePerHarnessNotOneDisclosure(unittest.TestCase):
    """The page renders the route for THAT session's harness, so the payload
    carries one per harness on the board and no board-wide sentence."""

    def setUp(self) -> None:
        patcher = named_machine()
        patcher.start()
        self.addCleanup(patcher.stop)

    def _collection(self, harnesses: tuple[str, ...], installed: set[str]) -> dict[str, Any]:
        home = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, home, True)
        config, state = make_runtime(
            state_home=home, state_dir=Path(home), annotations_enabled=True
        )

        def spec(harness: str) -> Any:
            def collect(*_args: Any) -> list[dict[str, Any]]:
                row = sessions.base_session(harness, "s1", "proj")
                row.update({"state": "working", "active": True, "last_activity": 1_700_000_000.0})
                return [row]

            return aggregate.HarnessSpec(
                key=harness, label=harness.title(), discover=lambda *_: True, collect=collect
            )

        application = aggregate.Application(
            config,
            state,
            tuple(spec(h) for h in harnesses),
            native_notifier=lambda _p: "",
            popup_notifier=lambda _t, _b: None,
            diagnostic_sink=lambda _m: None,
            clock=lambda: 1_700_000_100.0,
        )
        with mock.patch.object(shutil, "which", _resolver(installed)):
            _revision, body = application.collect_json(show_all=False)
        return dict(json.loads(body))

    def test_a_claude_row_and_a_pi_row_each_name_their_actual_receiver(self) -> None:
        data = self._collection(("claude", "pi", "codex"), {"codex", "claude"})
        self.assertNotIn("reading_disclosure", data)
        routes = data["reading_routes"]
        self.assertEqual({"claude", "pi", "codex"}, set(routes))
        self.assertEqual("claude", routes["claude"]["provider"])
        self.assertIn("Anthropic", routes["claude"]["disclosure"])
        self.assertNotIn("OpenAI", routes["claude"]["disclosure"])
        self.assertEqual("codex", routes["codex"]["provider"])
        self.assertIn("OpenAI", routes["codex"]["disclosure"])
        self.assertIn("no reading producer of its own", routes["pi"]["disclosure"])

    def test_with_claude_code_closed_the_claude_row_names_openai(self) -> None:
        with mock.patch.object(
            annotation_store, "CLAUDE_ABSTENTION_CHECK", annotation_store.ABSTENTION_CHECK_NOT_RUN
        ):
            data = self._collection(("claude",), {"codex", "claude"})
        route = data["reading_routes"]["claude"]
        self.assertEqual("codex", route["provider"])
        self.assertIn("Claude Code checks are not qualified on this build", route["disclosure"])
        self.assertIn("OpenAI", route["disclosure"])

    def test_the_published_permission_says_which_providers_are_allowed(self) -> None:
        data = self._collection(("claude",), {"codex"})
        self.assertEqual({"codex": False, "claude": False}, data["reading"]["providers"])

    def test_one_collection_looks_each_cli_up_at_most_once(self) -> None:
        which = _resolver({"codex"})
        with mock.patch.object(
            annotation_store, "CLAUDE_ABSTENTION_CHECK", annotation_store.ABSTENTION_CHECK_PASSED
        ):
            reading_route.resolve_all(("claude", "codex", "pi", "gemini"), binary_resolver=which)
        self.assertEqual(sorted(set(which.asked)), sorted(which.asked))


class TheBuildGateThePageReadsIsEitherProvider(unittest.TestCase):
    """`reading_check` is the page's build-wide gate. With Codex closed and
    Claude Code qualified, a published `not-run` would refuse a route the
    server offers, so the page is told the check that opens one."""

    def test_the_published_check_is_codexs_while_codex_is_open(self) -> None:
        data = ThePagePublishesARoutePerHarnessNotOneDisclosure._collection(
            cast("Any", self), ("claude",), {"codex"}
        )
        self.assertEqual(annotation_store.ABSTENTION_CHECK, data["reading_check"])

    def test_a_qualified_claude_code_opens_the_page_when_codex_is_closed(self) -> None:
        with mock.patch.multiple(
            annotation_store,
            ABSTENTION_CHECK=annotation_store.ABSTENTION_CHECK_NOT_RUN,
            CLAUDE_ABSTENTION_CHECK=annotation_store.ABSTENTION_CHECK_PASSED,
        ):
            data = ThePagePublishesARoutePerHarnessNotOneDisclosure._collection(
                cast("Any", self), ("claude",), {"claude"}
            )
        self.assertEqual(annotation_store.ABSTENTION_CHECK_PASSED, data["reading_check"])
        self.assertEqual("claude", data["reading_routes"]["claude"]["provider"])

    def test_with_both_closed_the_page_is_told_not_run(self) -> None:
        with mock.patch.multiple(
            annotation_store,
            ABSTENTION_CHECK=annotation_store.ABSTENTION_CHECK_NOT_RUN,
            CLAUDE_ABSTENTION_CHECK=annotation_store.ABSTENTION_CHECK_NOT_RUN,
        ):
            data = ThePagePublishesARoutePerHarnessNotOneDisclosure._collection(
                cast("Any", self), ("claude",), {"claude", "codex"}
            )
        self.assertEqual(annotation_store.ABSTENTION_CHECK_NOT_RUN, data["reading_check"])


class WhereToolOutputWouldGoIsNamedOrItIsNotSent(unittest.TestCase):
    """DEC-23 item 7: a reader allowing tool output is told where it goes as
    configured on this machine, and where that cannot be named, nothing of it
    is sent. The paths are the ones measured in the live 2.1.281 Claude Code
    and 0.156.1 Codex binaries on 2026-09-24; each test lays them out under a
    scratch root so no real machine setting is read."""

    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, True)

    def _write(self, path: str, text: str) -> None:
        target = self.root / path.lstrip("/")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")

    def _claude(self, environ: dict[str, str], system: str = "Darwin") -> str:
        return reading_route.destination(
            "claude",
            environ={"HOME": "/Users/r", "USER": "r", **environ},
            root=self.root,
            system=system,
        )

    def _codex(self, environ: dict[str, str], system: str = "Darwin") -> str:
        return reading_route.destination(
            "codex",
            environ={"HOME": "/Users/r", "USER": "r", **environ},
            root=self.root,
            system=system,
        )

    def test_a_reader_with_no_endpoint_setting_is_told_anthropic(self) -> None:
        self.assertEqual("Anthropic", self._claude({}))

    def test_a_reader_with_a_base_url_is_told_its_host_and_nothing_of_its_secret(self) -> None:
        named = self._claude(
            {"ANTHROPIC_BASE_URL": "https://me:hunter2@gw.corp.example:8443/v1?k=z"}
        )
        self.assertEqual("gw.corp.example:8443", named)

    def test_a_reader_on_bedrock_or_vertex_is_told_that_cloud(self) -> None:
        self.assertEqual("Amazon Bedrock", self._claude({"CLAUDE_CODE_USE_BEDROCK": "1"}))
        self.assertEqual("Google Vertex AI", self._claude({"CLAUDE_CODE_USE_VERTEX": "true"}))
        self.assertEqual("Anthropic", self._claude({"CLAUDE_CODE_USE_BEDROCK": "0"}))

    def test_a_reader_whose_settings_cannot_be_named_sends_no_tool_output(self) -> None:
        for environ in (
            {"CLAUDE_CODE_USE_BEDROCK": "1", "CLAUDE_CODE_USE_VERTEX": "1"},
            {"CLAUDE_CODE_USE_FOUNDRY": "1"},
            {"CLAUDE_CODE_USE_BEDROCK": "maybe"},
            {"CLAUDE_CODE_USE_BEDROCK": "1", "ANTHROPIC_BEDROCK_BASE_URL": "https://x.example"},
            {"ANTHROPIC_BASE_URL": "not a url"},
            {"CLAUDE_CODE_MANAGED_SETTINGS_PATH": "/opt/policy"},
            # M1: a second endpoint variable with no cloud switch, alone or
            # beside ANTHROPIC_BASE_URL.
            {"ANTHROPIC_BEDROCK_BASE_URL": "https://bedrock.corp"},
            {"ANTHROPIC_VERTEX_BASE_URL": "https://v.corp", "ANTHROPIC_BASE_URL": "https://a.corp"},
            {"ANTHROPIC_BASE_URL": "ftp://gw.corp"},
            # K4: the FedStart OAuth host and a unix-socket session both move
            # the API host somewhere this build does not read.
            {"CLAUDE_CODE_CUSTOM_OAUTH_URL": "https://claude.fedstart.com"},
            {"ANTHROPIC_UNIX_SOCKET": "/tmp/claude.sock"},
        ):
            with self.subTest(environ=environ):
                self.assertEqual("", self._claude(environ))

    def test_an_oauth_host_in_managed_settings_names_nothing(self) -> None:
        self._write(
            "/Library/Application Support/ClaudeCode/managed-settings.json",
            json.dumps({"env": {"CLAUDE_CODE_CUSTOM_OAUTH_URL": "https://claude.fedstart.com"}}),
        )
        self.assertEqual("", self._claude({}))

    @unittest.skipIf(sys.platform == "win32", "Windows has no password file, and names nothing")
    def test_with_no_home_or_user_the_password_file_is_read_instead(self) -> None:
        import pwd  # noqa: PLC0415

        entry = pwd.getpwuid(os.getuid())
        self._write(
            f"{entry.pw_dir}/.claude/remote-settings.json",
            json.dumps({"env": {"CLAUDE_CODE_USE_BEDROCK": "1"}}),
        )
        named = reading_route.destination("claude", environ={}, root=self.root, system="Darwin")
        self.assertEqual("Amazon Bedrock", named)

    def test_with_no_home_and_no_password_entry_nothing_is_named(self) -> None:
        with mock.patch.object(reading_route, "_account", return_value=("", "")):
            named = reading_route.destination("claude", environ={}, root=self.root, system="Darwin")
            codex = reading_route.destination("codex", environ={}, root=self.root, system="Darwin")
        self.assertEqual(("", ""), (named, codex))

    def test_a_proxy_does_not_change_the_vendor_a_reader_is_told(self) -> None:
        proxy = {"HTTPS_PROXY": "http://proxy.corp.example:3128", "NO_PROXY": "*"}
        self.assertEqual("Anthropic", self._claude(proxy))
        self.assertEqual("OpenAI", self._codex(proxy))

    def test_managed_settings_still_apply_so_their_endpoint_is_the_one_named(self) -> None:
        self._write(
            "/Library/Application Support/ClaudeCode/managed-settings.json",
            json.dumps({"env": {"CLAUDE_CODE_USE_BEDROCK": "1"}}),
        )
        self.assertEqual("Amazon Bedrock", self._claude({}))

    def test_a_managed_drop_in_moves_the_endpoint_too(self) -> None:
        self._write(
            "/etc/claude-code/managed-settings.d/10-gateway.json",
            json.dumps({"env": {"ANTHROPIC_BASE_URL": "https://gw.example"}}),
        )
        self.assertEqual("gw.example", self._claude({}, system="Linux"))

    def test_remote_managed_settings_cached_on_this_machine_count(self) -> None:
        self._write(
            "/Users/r/.claude/remote-settings.json",
            json.dumps({"env": {"CLAUDE_CODE_USE_VERTEX": "1"}}),
        )
        self.assertEqual("Google Vertex AI", self._claude({}))

    def test_two_sources_disagreeing_about_the_endpoint_name_nothing(self) -> None:
        self._write(
            "/Library/Application Support/ClaudeCode/managed-settings.json",
            json.dumps({"env": {"ANTHROPIC_BASE_URL": "https://a.example"}}),
        )
        self.assertEqual("", self._claude({"ANTHROPIC_BASE_URL": "https://b.example"}))

    def test_an_unreadable_or_unparsable_managed_file_names_nothing(self) -> None:
        self._write("/Library/Application Support/ClaudeCode/managed-settings.json", "{nope")
        self.assertEqual("", self._claude({}))

    def test_a_managed_preferences_profile_names_nothing_because_it_is_not_read(self) -> None:
        for path in (
            "/Library/Managed Preferences/com.anthropic.claudecode.plist",
            "/Library/Managed Preferences/r/com.anthropic.claudecode.plist",
        ):
            with self.subTest(path=path):
                self._write(path, "<plist/>")
                self.assertEqual("", self._claude({}))
                (self.root / path.lstrip("/")).unlink()

    def test_windows_policy_is_not_read_so_nothing_is_named_there(self) -> None:
        self.assertEqual("", self._claude({}, system="Windows"))
        self.assertEqual("", self._codex({}, system="Windows"))
        # And through the route, as a Windows runner resolves it.
        with mock.patch.object(platform, "system", return_value="Windows"):
            route = reading_route.resolve(
                "claude", binary_resolver=_resolver({"codex"}), environ={}, root=self.root
            )
        self.assertEqual("", route["destination"])
        self.assertIn("is not sent", route["tool_output"])

    def test_a_codex_reader_with_no_override_is_told_openai(self) -> None:
        self.assertEqual("OpenAI", self._codex({}))

    def test_a_codex_endpoint_override_or_managed_config_names_nothing(self) -> None:
        for environ in ({"OPENAI_BASE_URL": "https://gw.example"}, {"OPENAI_API_BASE": "x"}):
            with self.subTest(environ=environ):
                self.assertEqual("", self._codex(environ))
        for path in (
            "/etc/codex/managed_config.toml",
            "/etc/codex/config.toml",
            "/Library/Managed Preferences/com.openai.codex.plist",
            "/Library/Managed Preferences/r/com.openai.codex.plist",
        ):
            with self.subTest(path=path):
                self._write(path, "")
                self.assertEqual("", self._codex({}))
                (self.root / path.lstrip("/")).unlink()


# A path-embedded key, built at run time so no credential shape sits in source.
PATH_KEY = "sk-ant-api03-" + "A" * 95


def _masked(text: str) -> str:
    return text.replace(PATH_KEY, "<key>").replace(PATH_KEY.lower(), "<key>")


class ABaseUrlTheCliCouldReadDifferentlyNamesNothing(unittest.TestCase):
    """Consent F1 and F3 (ui5): `urlsplit` and the WHATWG parser the CLI uses
    must agree on the host, or the disclosure and the Allow's binding name a
    host the words never reach. Measured on Claude Code 2.1.287: a base URL of
    `http://127.0.0.1:4597\\@127.0.0.1:4598` sent every request to 4597, where
    `urlsplit` reads 4598. Any URL the two could read differently names nothing.
    """

    def _claude(self, url: str) -> str:
        """The name, with the test's key masked so a failure never prints it."""
        return _masked(
            reading_route.destination(
                "claude",
                environ={"HOME": "/home/r", "USER": "r", "ANTHROPIC_BASE_URL": url},
                root=Path("/nonexistent-compass-root"),
                system="Linux",
            )
        )

    def test_a_backslash_before_the_userinfo_names_nothing(self) -> None:
        self.assertEqual("", self._claude("http://127.0.0.1:4597\\@127.0.0.1:4598"))

    def test_a_path_key_after_a_backslash_never_reaches_the_name(self) -> None:
        named = self._claude("https://proxy.example\\" + PATH_KEY)
        self.assertEqual("", named)

    def test_every_url_the_two_parsers_could_read_differently_names_nothing(self) -> None:
        for url in (
            "https://gw.example\\x",
            "https://gw.example\t",
            "https://gw\t.example",
            "https://gw.example\n",
            "https://gw.ex\rample",
            "https://gw.example\x01",
            "https://gw.example\x7f",
            " https://gw.example",
            "https://gw.example ",
            "https://a b.example",
            "https://%65vil.example",
            "https://\uff45vil.example",
            "https://0x7f.1",
            "https://127.1",
            "https://010.0.0.1",
            "https://gw.example.",
            "https://gw..example",
            "https://evil.example;.good",
            "https://gw.example:+80",
            "https://" + PATH_KEY + ".example",
        ):
            # Labelled by a redaction, so a failure never prints the key.
            with self.subTest(url=url.replace(PATH_KEY, "<key>")):
                self.assertEqual("", self._claude(url))

    def test_an_ordinary_base_url_is_still_named(self) -> None:
        for url, named in (
            ("https://gw.corp.example", "gw.corp.example"),
            ("https://GW.corp.example:8443/v1", "gw.corp.example:8443"),
            ("http://127.0.0.1:4000", "127.0.0.1:4000"),
            ("https://me:pw@gw_1.corp-x.example/p?k=z#f", "gw_1.corp-x.example"),
            ("http://[::1]:4000", "[::1]:4000"),
        ):
            with self.subTest(url=url):
                self.assertEqual(named, self._claude(url))

    def test_a_codex_base_url_of_any_shape_names_nothing(self) -> None:
        for url in ("https://proxy.example\\" + PATH_KEY, "http://a\\@b", "https://gw.example"):
            for key in ("OPENAI_BASE_URL", "OPENAI_API_BASE"):
                with self.subTest(url=url.replace(PATH_KEY, "<key>"), key=key):
                    named = reading_route.destination(
                        "codex",
                        environ={"HOME": "/home/r", "USER": "r", key: url},
                        root=Path("/nonexistent-compass-root"),
                        system="Linux",
                    )
                    self.assertEqual("", _masked(named))

    def test_the_key_reaches_neither_the_route_nor_its_to_item(self) -> None:
        for provider, harness, environ in (
            ("claude", "claude", {"ANTHROPIC_BASE_URL": "https://proxy.example\\" + PATH_KEY}),
            ("codex", "codex", {"OPENAI_BASE_URL": "https://proxy.example\\" + PATH_KEY}),
        ):
            with self.subTest(provider=provider), named_machine(environ):
                route = reading_route.resolve(harness, binary_resolver=_resolver({provider}))
                self.assertEqual(provider, route["provider"])
                published = json.dumps(route).lower()
                self.assertEqual("", _masked(route["words_destination"]))
                self.assertEqual("", _masked(route["destination"]))
                self.assertFalse(PATH_KEY.lower() in published, "the key reached the route")
                self.assertFalse("proxy.example" in published, "the route named the proxy")
                (to,) = [part for part in route["disclosure_parts"] if part.startswith("To:")]
                self.assertIn("which Compass cannot name", _masked(to))


class AClaudeCodeReaderIsToldWhatTheChecksSendBeforeThePress(unittest.TestCase):
    """The route carries the destination and the sentence that names it, on
    the harness whose record lists checks and on no other."""

    def test_the_fallback_route_names_tool_output_and_where_it_goes(self) -> None:
        with named_platform():
            route = reading_route.resolve(
                "claude",
                binary_resolver=_resolver({"codex"}),
                environ={},
                root=Path("/nonexistent"),
            )
        self.assertEqual("OpenAI", route["destination"])
        self.assertIn("tool output", route["tool_output"].casefold())
        # Where it goes is the `To:` item right after it (verifier ui4 V2).
        parts = route["disclosure_parts"]
        self.assertTrue(
            parts[parts.index(route["tool_output"]) + 1].startswith("To: OpenAI, off this machine")
        )
        self.assertIn("included by default", route["tool_output"])
        # K6: the grant sends the written paths too, so the sentence names them.
        self.assertIn("the paths of the files it wrote", route["tool_output"])
        self.assertIn(route["tool_output"], route["disclosure"])

    def test_a_destination_that_cannot_be_named_is_said_to_send_no_tool_output(self) -> None:
        route = reading_route.resolve(
            "claude",
            binary_resolver=_resolver({"codex"}),
            environ={"OPENAI_BASE_URL": "https://gw.example"},
            root=Path("/nonexistent"),
        )
        self.assertEqual("", route["destination"])
        self.assertIn("not sent", route["tool_output"])
        self.assertIn("cannot name where it would go", route["tool_output"])
        # The lines go with the words since the agent's messages carry them (owner,
        # 2026-10-03), so this sentence no longer says they are kept back.
        self.assertNotIn("outcome lines", route["tool_output"])
        self.assertIn("your expected outcome lines", route["disclosure"])
        # Nor is any vendor claimed for the words (verifier ui4 C1).
        self.assertIn("which Compass cannot name", route["disclosure"])

    def test_a_harness_without_checks_carries_no_tool_output_sentence(self) -> None:
        for harness in ("codex", "pi"):
            with self.subTest(harness=harness):
                route = reading_route.resolve(
                    harness, binary_resolver=_resolver({"codex"}), environ={}, root=Path("/x")
                )
                self.assertEqual("", route["tool_output"])
                self.assertNotIn("tool output", route["disclosure"])

    def test_the_words_disclosure_no_longer_keys_expected_output_on_a_harness(self) -> None:
        route = reading_route.resolve("pi", binary_resolver=_resolver({"codex"}), environ={})
        self.assertNotIn("harness that publishes work evidence", route["disclosure"])
        self.assertIn(
            "your expected outcome lines when a work result is among them", route["disclosure"]
        )


def _named(harness: str, installed: set[str]) -> dict[str, Any]:
    with named_platform():
        return dict(
            reading_route.resolve(
                harness, binary_resolver=_resolver(installed), environ={}, root=Path("/x")
            )
        )


class ToolOutputIsDisclosedByDefaultTest(unittest.TestCase):
    """A named route discloses tool output without requiring a second grant."""

    def _route(self, **changes: Any) -> dict[str, Any]:
        config = make_config(**changes)
        with named_platform():
            return dict(
                reading_route.resolve(
                    "claude",
                    binary_resolver=_resolver({"claude"}),
                    environ={},
                    root=Path("/x"),
                    config=config,
                )
            )

    def test_the_sentence_names_tool_output_included_by_default(self) -> None:
        route = self._route()
        self.assertIn("Tool output is included by default:", route["tool_output"])
        self.assertNotIn("only after you allow it", route["disclosure"])
        # What is sent is unchanged: the same four facts follow the lead.
        for fact in (
            "a check's command",
            "180 characters",
            "paths of the files it wrote",
            "the repository and number of a pull request it created",
            "the names of skills it used",
        ):
            self.assertIn(fact, route["tool_output"])
        self.assertIn(route["tool_output"], route["disclosure_parts"])

    def test_no_destination_means_no_tool_output(self) -> None:
        with mock.patch.object(reading_route, "destination", return_value=""):
            route = self._route()
        self.assertEqual("", route["destination"])
        self.assertIn("Tool output is not sent", route["tool_output"])


class TheDisclosureIsAShortListThatKeepsEveryFact(unittest.TestCase):
    """Owner, 2026-10-02: the disclosure was "long and arduous to read". It is a short list,
    one item a line, and it still says what is sent, to whom, through what, what the Claude
    Code CLI adds and that a reading is never a verification ([SECURITY.md], Observer model
    calls and Claude Code reading calls)."""

    ROUTES: ClassVar[dict[str, tuple[str, set[str]]]] = {
        "codex": ("codex", {"codex"}),
        "claude": ("claude", {"claude", "codex"}),
        "claude-by-codex": ("claude", {"codex"}),
        "codex-by-claude": ("codex", {"claude"}),
    }

    def test_each_item_is_short_and_the_whole_list_is_a_fraction_of_the_old_paragraph(
        self,
    ) -> None:
        # Words before the 2026-10-02 ruling: 128 for a Codex session, 239 for a Claude Code
        # session read by Claude Code, 202 for one read by Codex. The first short list was 75,
        # 148 and 121 in 5, 7 and 6 items, and verifier ui4 V2 found the Claude Code route still
        # repeating itself; "about five items", the owner said. The owner's ruling of
        # 2026-10-03 added five words to a Claude Code session's list: the agent's messages
        # are sent, and the outcome lines moved from the tool output item to the `Sent:` one.
        # Its review added four more: the agent's messages may quote the tool output.
        # The 2026-10-05 selected-model amendment adds two words on Claude routes: using <id>.
        # Content version 3 adds one 19-word item for the newest recorded final reply.
        # Keep the existing 31-word per-item limit and all previous disclosure facts.
        # The 2026-10-23 pull request and skill amendment adds 18 words to the tool output item,
        # which alone may run to 47, and to the two Claude Code session routes' totals.
        budgets = {
            "codex": (4, 61),
            "claude": (7, 168),
            "claude-by-codex": (6, 147),
            "codex-by-claude": (5, 100),
        }
        for name, (harness, installed) in self.ROUTES.items():
            route = _named(harness, installed)
            items, words = budgets[name]
            with self.subTest(route=name):
                parts = route["disclosure_parts"]
                self.assertLessEqual(len(parts), items, parts)
                for part in parts:
                    limit = 47 if part.startswith("Tool output is included") else 31
                    self.assertLessEqual(len(part.split()), limit, part)
                self.assertLessEqual(len(route["disclosure"].split()), words)

    def test_no_item_repeats_another(self) -> None:
        """Verifier ui4 V2: "credential shapes redacted" twice, the destination twice ("To:
        Anthropic" and "which reaches Anthropic"), and "Claude Code reads this Claude Code
        session." under a summary that already names Claude Code."""
        for name, (harness, installed) in self.ROUTES.items():
            route = _named(harness, installed)
            text, label = route["disclosure"], route["label"]
            with self.subTest(route=name):
                self.assertEqual(1, text.count("redacted"), text)
                self.assertEqual(1, text.count(route["vendor"]), text)
                self.assertLessEqual(text.count(label), 2, text)
                if route["reason"] == reading_route.REASON_OWN_HARNESS:
                    self.assertNotIn(label, route["note"])
                for mechanism in ("work evidence", "an empty temporary", "which reaches"):
                    self.assertNotIn(mechanism, text)

    def test_the_whole_final_reply_has_one_short_item_before_the_destination(self) -> None:
        for installed in ({"claude"}, {"codex"}):
            with self.subTest(provider=next(iter(installed))):
                parts = _named("claude", installed)["disclosure_parts"]
                replies = [part for part in parts if part.startswith("The agent's newest final")]
                self.assertEqual(1, len(replies))
                reply = replies[0]
                self.assertLessEqual(len(reply.split()), 19)
                self.assertIn("as its transcript records one", reply)
                self.assertIn("whole", reply)
                self.assertIn("4,096 bytes", reply)
                destination = next(part for part in parts if part.startswith("To:"))
                self.assertLess(parts.index(reply), parts.index(destination))
                self.assertNotIn("newest final", parts[1])
        self.assertFalse(
            any("newest final" in part for part in _named("codex", {"codex"})["disclosure_parts"])
        )

    def test_every_route_still_says_what_is_sent_to_whom_and_through_what(self) -> None:
        cap = f"{reading.LEDGER_WORDS_CAP_CHARS:,} characters"
        self.assertEqual(reading.LEDGER_WORDS_CAP_CHARS, reading_route._WORDS_CAP)
        for name, (harness, installed) in self.ROUTES.items():
            route = _named(harness, installed)
            text, label = route["disclosure"], route["label"]
            messages = (
                "your messages and the agent's messages"
                if harness in reading_route.AGENT_MESSAGE_HARNESSES
                else "your messages"
            )
            with self.subTest(route=name):
                for fact in (
                    "your goal",
                    "bounded set",
                    f"{messages} up to {cap} each",
                    "credential shapes redacted",
                    f"To: {route['vendor']}, off this machine",
                    f"your {label} CLI and its sign-in",
                    "spending your capacity",
                    "a model's account of the evidence",
                    "never a verification that the work was done",
                ):
                    self.assertIn(fact, text.replace("\u2019", "'"))

    def test_outcome_lines_are_named_only_where_they_can_be_sent(self) -> None:
        # They go beside work evidence or the agent's messages: on Claude Code with the
        # agent's messages, whether or not tool output may go (owner, 2026-10-03), and
        # beside a work result on Pi. A Codex session has neither, so its list is silent.
        self.assertEqual(
            set(reading.WORK_EVIDENCE_BY_HARNESS), set(reading_route.OUTCOME_HARNESSES)
        )
        self.assertEqual(
            project_context.AGENT_MESSAGE_HARNESSES, reading_route.AGENT_MESSAGE_HARNESSES
        )
        claude = _named("claude", {"claude"})
        self.assertNotIn("outcome lines", claude["tool_output"])
        sent = next(part for part in claude["disclosure_parts"] if part.startswith("Sent:"))
        self.assertIn("the agent's messages", sent)
        self.assertIn("your expected outcome lines", sent)
        pi = _named("pi", {"codex"})
        self.assertIn("expected outcome lines", pi["disclosure"])
        self.assertIn("work result", pi["disclosure"])
        codex = _named("codex", {"codex"})
        self.assertNotIn("outcome", codex["disclosure"])

    def test_the_tool_output_item_names_each_thing_it_sends(self) -> None:
        for name in ("claude", "claude-by-codex"):
            harness, installed = self.ROUTES[name]
            route = _named(harness, installed)
            sentence = route["tool_output"]
            parts = route["disclosure_parts"]
            with self.subTest(route=name):
                for fact in (
                    "included by default",
                    "command",
                    "result",
                    f"last {reading_route.TOOL_OUTPUT_TAIL_CHARS} characters of output",
                    "the paths of the files it wrote",
                    "as printed",
                ):
                    self.assertIn(fact, sentence)
                # Where it goes is the `To:` item right after it, said once for everything.
                self.assertTrue(parts[parts.index(sentence) + 1].startswith("To: "), parts)


class TheToItemNamesWhereTheWordsGoAsConfigured(unittest.TestCase):
    """Verifier ui4 C1: the `To:` item named the vendor whatever the daemon's environment said,
    so under Bedrock, a base URL or a unix socket the reader allowed Anthropic and the goal and
    their messages went elsewhere. The environment decides the endpoint (SECURITY.md, Claude
    Code reading calls), so the item says what `destination` says: the endpoint where it is
    named, and plainly that Compass cannot name it where it is not."""

    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, True)

    def _to(self, harness: str, installed: set[str], environ: dict[str, str]) -> tuple[str, str]:
        with named_platform():
            route = reading_route.resolve(
                harness,
                binary_resolver=_resolver(installed),
                environ={"HOME": "/Users/r", "USER": "r", **environ},
                root=self.root,
            )
        items = [part for part in route["disclosure_parts"] if part.startswith("To: ")]
        self.assertEqual(1, len(items), route["disclosure_parts"])
        return items[0], route["disclosure"]

    def test_with_no_endpoint_setting_the_item_names_the_vendor_off_this_machine(self) -> None:
        for harness, installed in (("claude", {"claude"}), ("codex", {"codex"})):
            vendor = reading_route.VENDORS[harness]
            with self.subTest(harness=harness):
                item, _text = self._to(harness, installed, {})
                self.assertTrue(item.startswith(f"To: {vendor}, off this machine"), item)

    def test_a_cloud_or_a_base_url_is_named_in_place_of_anthropic(self) -> None:
        # Pi as well as Claude Code: the words go there on a harness with no checks too.
        for harness in ("claude", "pi"):
            for environ, named in (
                ({"CLAUDE_CODE_USE_BEDROCK": "1"}, "To: Amazon Bedrock, off this machine"),
                ({"CLAUDE_CODE_USE_VERTEX": "1"}, "To: Google Vertex AI, off this machine"),
                ({"ANTHROPIC_BASE_URL": "https://proxy.example:8443"}, "To: proxy.example:8443,"),
            ):
                with self.subTest(harness=harness, environ=environ):
                    item, text = self._to(harness, {"claude"}, environ)
                    self.assertTrue(item.startswith(named), item)
                    self.assertNotIn("Anthropic", text)

    def test_a_base_url_is_not_said_to_be_off_this_machine(self) -> None:
        # It may be a local gateway; the build names the host and no more.
        item, _text = self._to(
            "claude", {"claude"}, {"ANTHROPIC_BASE_URL": "http://127.0.0.1:4000"}
        )
        self.assertTrue(item.startswith("To: 127.0.0.1:4000,"), item)
        self.assertNotIn("off this machine", item)

    def test_an_endpoint_that_cannot_be_named_is_said_plainly_and_no_vendor_is_claimed(
        self,
    ) -> None:
        for harness, installed, environ, label in (
            ("claude", {"claude"}, {"ANTHROPIC_UNIX_SOCKET": "/tmp/s"}, "Claude Code"),
            ("pi", {"claude"}, {"ANTHROPIC_UNIX_SOCKET": "/tmp/s"}, "Claude Code"),
            ("codex", {"codex"}, {"OPENAI_BASE_URL": "https://gw.example"}, "Codex"),
            ("pi", {"codex"}, {"OPENAI_BASE_URL": "https://gw.example"}, "Codex"),
        ):
            with self.subTest(harness=harness, environ=environ):
                item, text = self._to(harness, installed, environ)
                self.assertTrue(
                    item.startswith(
                        f"To: wherever your {label} settings send it, which Compass cannot name"
                    ),
                    item,
                )
                self.assertNotIn("off this machine", item)
                self.assertNotIn("Anthropic", text)
                self.assertNotIn("OpenAI", text)

    def test_on_windows_no_endpoint_is_named_so_none_is_claimed(self) -> None:
        with mock.patch.object(platform, "system", return_value="Windows"):
            route = reading_route.resolve(
                "codex", binary_resolver=_resolver({"codex"}), environ={}, root=self.root
            )
        self.assertIn("which Compass cannot name", route["disclosure"])
        self.assertNotIn("OpenAI", route["disclosure"])


class TheSentencesReadAsSentences(unittest.TestCase):
    def test_no_reason_chains_three_clauses_with_and(self) -> None:
        for harness, claude, codex in itertools.product(HARNESSES, STATES, STATES):
            gate, which = _world(claude, codex)
            with gate:
                note = reading_route.resolve(harness, binary_resolver=which)["note"]
            with self.subTest(harness=harness, claude=claude, codex=codex):
                self.assertLessEqual(note.count(", and "), 1, note)


if __name__ == "__main__":
    unittest.main()


class EveryRouteNamesWhereTheWordsGo(unittest.TestCase):
    """The Allow for the reader's words is bound to where they go (owner, 2026-10-02).

    `destination` is "" off a harness with checks, because it is where tool
    output goes. The words go somewhere on every route, so the route names that
    too, from the same `reading_route.destination` the policy is handed.
    """

    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, True)

    def _route(self, harness: str, installed: set[str], environ: dict[str, str]) -> Any:
        with (
            named_platform(),
            mock.patch.object(
                annotation_store,
                "CLAUDE_ABSTENTION_CHECK",
                annotation_store.ABSTENTION_CHECK_PASSED,
            ),
        ):
            return reading_route.resolve(
                harness,
                binary_resolver=_resolver(installed),
                environ={"HOME": "/Users/r", "USER": "r", **environ},
                root=self.root,
            )

    def test_each_route_names_the_destination_its_words_reach(self) -> None:
        for harness, installed, environ, expected in (
            ("claude", {"claude"}, {}, "Anthropic"),
            (
                "pi",
                {"claude"},
                {"ANTHROPIC_BASE_URL": "https://gw.corp.example"},
                "gw.corp.example",
            ),
            ("codex", {"claude"}, {"CLAUDE_CODE_USE_BEDROCK": "1"}, "Amazon Bedrock"),
            ("pi", {"codex"}, {}, "OpenAI"),
            ("pi", {"claude"}, {"ANTHROPIC_UNIX_SOCKET": "/tmp/s"}, ""),
            ("pi", set(), {}, ""),
        ):
            with self.subTest(harness=harness, installed=installed, environ=environ):
                route = self._route(harness, installed, environ)
                self.assertEqual(expected, route["words_destination"])

    def test_the_policy_is_handed_the_same_destination_the_route_names(self) -> None:
        environ = {"HOME": "/Users/r", "USER": "r", "ANTHROPIC_BASE_URL": "https://gw.example"}
        with named_platform():
            today = reading_route.destinations(environ=environ, root=self.root)
        self.assertEqual({"codex": "OpenAI", "claude": "gw.example"}, today)
        route = self._route("pi", {"claude"}, {"ANTHROPIC_BASE_URL": "https://gw.example"})
        self.assertEqual(today["claude"], route["words_destination"])
