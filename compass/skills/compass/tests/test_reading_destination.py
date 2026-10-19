"""The press check and the job agree on what an Allow covers (owner, 2026-10-02).

Since DEC-28 the coverage below is the explicit coverage the board publishes (`words`)
for the unasked lane and the current page; a press and its job run on any row that was
not turned off, and a moved destination shows the notice again instead of refusing.

"Bind the allow to the destination": an Allow for the reader's words covers a
press only while the provider's destination is exactly the one the Allow's
disclosure named. Two places decide it, and each row of one table is put to
both, after a restart, on a machine whose environment the row names:

- the press handler, over a socket (`http_api._reading_permission`);
- the job, at the reservation (`reading_policy.GuardedModel`).

The page reads the destination the board publishes and asks for an Allow when it
moved; that half is checked on the React side, against the same published route.

A Pi session read by Claude Code, so no tool-output grant is involved and the
words' own binding is the only rule that can refuse.
"""

from __future__ import annotations

import contextlib
import json
from typing import Any
from unittest import mock

from compass_runtime import io as runtime_io
from compass_runtime import reading_policy, reading_route

from . import test_http_api
from .reading_pins import named_machine
from .support import RuntimeTestCase

PRE = object()
# Built at run time, so no credential shape sits in source, and masked in every
# assertion so a failure never prints it.
PATH_KEY = "sk-ant-api03-" + "A" * 95
# The daemon's environment under which `reading_route.destination` names each.
ENVIRON: dict[str, dict[str, str]] = {
    "Anthropic": {},
    "gw.corp.example": {"ANTHROPIC_BASE_URL": "https://gw.corp.example"},
    "Amazon Bedrock": {"CLAUDE_CODE_USE_BEDROCK": "1"},
    "": {"ANTHROPIC_UNIX_SOCKET": "/tmp/compass-test.sock"},
}
# name, the Allow on record (None: none; PRE: a row from before the binding),
# whether it was then turned off, today's destination, and whether it covers.
ROWS: tuple[tuple[str, Any, bool, str, bool], ...] = (
    ("the same destination after a restart", "Anthropic", False, "Anthropic", True),
    ("Anthropic, then a base-URL host", "Anthropic", False, "gw.corp.example", False),
    ("Anthropic, then Bedrock", "Anthropic", False, "Amazon Bedrock", False),
    ("unnamed, still unnamed", "", False, "", True),
    ("named, then unnamed", "Anthropic", False, "", False),
    ("unnamed, then named", "", False, "Anthropic", False),
    ("a row from before the binding", PRE, False, "Anthropic", False),
    ("no Allow at all", None, False, "Anthropic", False),
    ("turned off, then moved", "Anthropic", True, "gw.corp.example", False),
    ("turned off, unchanged", "Anthropic", True, "Anthropic", False),
)


class ThePressAndTheJobAgree(RuntimeTestCase):
    def setUp(self) -> None:
        super().setUp()
        # The socket helpers `ReadingRouteTest` already proved can observe a
        # call, on an instance of their own: inheriting them would run that
        # whole suite again here, and binding the class at module level would
        # make the loader do the same.
        self.route = test_http_api.ReadingRouteTest("run")
        self.addCleanup(self.route.doCleanups)

    def _on(self, where: str) -> tuple[contextlib.ExitStack, list[str]]:
        """Claude Code on PATH, no Codex, and an environment naming `where`."""
        stack = contextlib.ExitStack()
        stack.enter_context(self.route._open_claude())
        calls = stack.enter_context(self.route._counting_model(("claude",)))
        # After `_counting_model`, so this machine's destination is the one read.
        stack.enter_context(named_machine(ENVIRON[where]))
        return stack, calls

    def _give(self, config: Any, state: Any, given: Any, declined: bool) -> None:
        if given is PRE:
            reading_policy.status(config, now=1_700_000_100.0)
            assert runtime_io.sqlite_module is not None
            db = runtime_io.sqlite_module.connect(reading_policy.store_path(config))
            db.execute("INSERT OR REPLACE INTO provider_permission VALUES ('claude', 1)")
            db.commit()
            db.close()
        elif given is not None:
            # An Allow an earlier build stored for `given`; no press writes one now.
            reading_policy.set_consent(
                config,
                True,
                now=1_700_000_100.0,
                provider="claude",
                destination=given,
                content=reading_policy.WORDS_CONTENT_VERSION,
            )
            stack, calls = self._on(given)
            with stack, self.route._serving(self.route._app(config, state)) as port:
                status, body = self.route._post(port, self.route._press(provider="claude"))
            self.assertEqual(202, status, body)
            self.assertEqual(1, len(calls))
        if declined:
            stack, _calls = self._on("Anthropic")
            with stack, self.route._serving(self.route._app(config, state)) as port:
                status, _ = self.route._post(
                    port, {"consent": "off", "press": True, "observer_model": 1}
                )
            self.assertEqual(200, status)

    def _today(self, config: Any, state: Any, today: str) -> dict[str, Any]:
        """A new application on the same home, as a restarted daemon is."""
        stack, calls = self._on(today)
        with stack:
            # Nothing a collection before the restart memoised survives it.
            state.snapshot.clear()
            application = self.route._app(config, state)
            _revision, body = application.collect_json(show_all=False)
            board = json.loads(body)
            route = board["reading_routes"]["pi"]
            with self.route._serving(application) as port:
                status, _ = self.route._post(port, self.route._press(provider="claude"))
            pressed = len(calls)
            model = mock.Mock(return_value=("{}", "ok"))
            guarded = reading_policy.GuardedModel(
                config,
                model,
                lambda: 1_700_000_100.0,
                provider="claude",
                content=reading_policy.WORDS_CONTENT_VERSION,
                destination=route["words_destination"],
                # As the HTTP job asks it again at the reservation (consent F4).
                resolve_destination=lambda: reading_route.destination("claude"),
            )
            # Refused or run: the count on the model says which.
            with contextlib.suppress(reading_policy.RefusedError):
                guarded("prompt", output_cap_bytes=100)
        return {
            "board": board,
            "route": route,
            "press": status,
            "pressed": pressed,
            "job": model.call_count,
        }

    def test_every_row_is_answered_the_same_by_the_press_and_the_job(self) -> None:
        for name, given, declined, today, covered in ROWS:
            with self.subTest(row=name):
                config, state = self.route._runtime()
                self._give(config, state, given, declined)
                seen = self._today(config, state, today)
                self.assertEqual(today, seen["route"]["words_destination"])
                published = seen["board"]["reading"]
                self.assertIs(covered, published["words"]["claude"])
                self.assertFalse(published["providers"]["claude"], "narrow Allow widened the grant")
                # The press and the job: refused only by a stored off (DEC-28).
                self.assertEqual(403 if declined else 202, seen["press"])
                self.assertEqual(0 if declined else 1, seen["pressed"], "sent while off")
                self.assertEqual(0 if declined else 1, seen["job"])

    def test_a_url_the_cli_reads_differently_binds_and_publishes_no_name(self) -> None:
        """Consent F1 and F3 (ui5), end to end: where the CLI's parser and this
        build's could read different hosts, the board, the `To:` item and the
        stored binding name nothing, so no host the words never reach is bound
        and no key in the URL is published or written to disk."""
        for label, url in (
            ("backslash before the userinfo", "http://127.0.0.1:4597\\@127.0.0.1:4598"),
            ("a key after a backslash", "https://proxy.example\\" + PATH_KEY),
        ):
            with self.subTest(case=label):
                ENVIRON[label] = {"ANTHROPIC_BASE_URL": url}
                self.addCleanup(ENVIRON.pop, label, None)
                config, state = self.route._runtime()
                stack, calls = self._on(label)
                with stack, self.route._serving(self.route._app(config, state)) as port:
                    application = self.route._app(config, state)
                    _revision, body = application.collect_json(show_all=False)
                    route = json.loads(body)["reading_routes"]["pi"]
                    status, _ = self.route._post(
                        port, self.route._press(provider="claude", allow=True, words_destination="")
                    )
                self.assertEqual(202, status)
                self.assertEqual(1, len(calls))
                self.assertEqual("", route["words_destination"])
                (to,) = [part for part in route["disclosure_parts"] if part.startswith("To:")]
                self.assertIn("which Compass cannot name", to)
                for text in (body.decode(), json.dumps(route)):
                    lowered = text.lower()
                    self.assertFalse(PATH_KEY.lower() in lowered, "the key was published")
                    self.assertFalse("4598" in lowered, "a host the CLI never reaches was named")
                assert runtime_io.sqlite_module is not None
                db = runtime_io.sqlite_module.connect(reading_policy.store_path(config))
                bound = db.execute("SELECT provider, destination FROM permission_destination")
                rows = [tuple(row) for row in bound]
                db.close()
                # A press binds nothing now; a legacy binding, if any, still names no host.
                self.assertNotIn("claude", [provider for provider, _where in rows])
                for _provider, where in rows:
                    self.assertFalse(PATH_KEY.lower() in where.lower(), "the key was stored")
                    self.assertFalse("4598" in where, "a host the CLI never reaches was bound")

    def test_a_press_after_a_moved_destination_runs_and_names_the_new_one(self) -> None:
        """DEC-28: a page drawn before the move presses, the reading runs, and the reply's
        notice names where the words go now, rather than a blocking Allow."""
        config, state = self.route._runtime()
        self._give(config, state, "Anthropic", False)
        stack, _calls = self._on("Anthropic")
        with stack:
            state.snapshot.clear()
            _revision, body = self.route._app(config, state).collect_json(show_all=False)
        drawn = json.loads(body)
        self.assertTrue(drawn["reading"]["words"]["claude"])
        self.assertFalse(drawn["reading"]["providers"]["claude"], "narrow Allow widened the grant")
        stack, calls = self._on("gw.corp.example")
        with stack, self.route._serving(self.route._app(config, state)) as port:
            status, raw = self.route._post(port, self.route._press(provider="claude"))
        reply = json.loads(raw)
        self.assertEqual(202, status, raw)
        self.assertEqual(1, len(calls))
        self.assertEqual("reading", reply["notice"]["kind"])
        self.assertEqual("gw.corp.example", reply["notice"]["destination"])
        # The legacy explicit coverage still says the Allow no longer covers it.
        legacy = reading_policy.status(
            config,
            now=1_700_000_100.0,
            provider="claude",
            destinations={"claude": "gw.corp.example"},
            content=reading_policy.WORDS_CONTENT_VERSION,
        )
        self.assertEqual(reading_policy.DESTINATION_CHANGED, legacy["rebind"]["claude"])
