"""The quota fetch, held to the SECURITY.md "Usage quota reads" contract.

Every boundary the contract names is asserted here: the request carries the
token and nothing else, the token reaches no diagnostic line and no loopback
response, no refresh path exists, the five-minute floor holds for failures as
well as successes, and neither `collect` nor `--diagnose` can trigger a fetch.
"""

from __future__ import annotations

import dataclasses
import email.message
import http.client
import json
import math
import tempfile
import threading
import time
import unittest
import urllib.error
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, Self
from unittest import mock

from compass_runtime import aggregate, cli, diagnostics, quota, sessions
from compass_runtime.collectors import claude as claude_collector
from compass_runtime.collectors import codex as codex_collector
from compass_runtime.collectors import cursor as cursor_collector
from compass_runtime.config import build_runtime_config
from compass_runtime.state import build_runtime_state

from .support import SERVER_PATH, RuntimeTestCase, make_server, poll_fast, runtime

if TYPE_CHECKING:
    from compass_runtime.config import RuntimeConfig
    from compass_runtime.state import RuntimeState

# Deliberately not credential-shaped: it appears in assertions about where a
# token must NOT show up, and those assertions read better with a value that
# could never be mistaken for a real one.
TOKEN = "usage-test-access-token"  # noqa: S105 — deliberately fake; asserted ABSENT from outputs
NOW = 1_700_000_000.0

# The two rows whose only route to a number is the fetch cache. Kept as one
# mapping so a freshness assertion cannot be written for one and forgotten
# for the other -- which is how the two collectors came to disagree.
_USAGE_PROVIDERS = {"claude": claude_collector.usage, "cursor": cursor_collector.usage}

# A sentinel distinct from every JSON value, so "no `asOf` at all" is a case
# the same table can carry alongside the malformed ones.
_MISSING = object()


def _http_error(code: int, msg: str) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(quota.USAGE_ENDPOINT, code, msg, email.message.Message(), None)


def _no_runner(*_args: Any, **_kwargs: Any) -> Any:
    raise AssertionError("the keychain must not be consulted on this platform")


def _config(
    home: str = "/nonexistent-compass-test",
    platform_name: str = "linux",
    **changes: Any,
) -> RuntimeConfig:
    config = build_runtime_config(
        environ={"HOME": home},
        platform_name=platform_name,
        os_name="posix",
        launcher_path=SERVER_PATH,
    )
    return dataclasses.replace(config, **changes) if changes else config


def _state(config: RuntimeConfig) -> RuntimeState:
    return build_runtime_state(config, started=NOW)


def _credentials(expires_at_ms: float | None = None) -> str:
    oauth: dict[str, Any] = {"accessToken": TOKEN}
    if expires_at_ms is not None:
        oauth["expiresAt"] = expires_at_ms
    return json.dumps({"claudeAiOauth": oauth})


def _keychain_runner(
    stdout: str,
    returncode: int = 0,
    calls: list[list[str]] | None = None,
    service: str = quota.KEYCHAIN_SERVICE,
) -> Any:
    """A fake `security` that answers for exactly one Keychain service.

    Scoped to a service on purpose. A runner that returned the same secret for
    every lookup would hand Claude's credentials to Cursor's reader, and Cursor
    would then fetch inside tests written to exercise Claude alone — the fixture
    leaking across vendors rather than the code doing anything wrong.
    """

    def runner(argv: list[str], **_kwargs: Any) -> SimpleNamespace:
        if calls is not None:
            calls.append(argv)
        if service not in argv:
            return SimpleNamespace(returncode=1, stdout="")
        return SimpleNamespace(returncode=returncode, stdout=stdout)

    return runner


def _asked_services(calls: list[list[str]]) -> list[str]:
    """Which Keychain services a run consulted, in order."""
    return [argv[argv.index("-s") + 1] for argv in calls if "-s" in argv]


def _fetch_claude(config: RuntimeConfig, state: RuntimeState, **overrides: Any) -> None:
    """Drive one Claude fetch through the generic per-vendor driver."""
    quota.fetch_usage(config, state, "claude", quota._claude_entries, **overrides)


class _Response:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def read(self, n: int = -1) -> bytes:
        return self._body[:n] if n > 0 else self._body

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_exc: object) -> None:
        return None


def _opener(
    body: dict[str, Any] | None = None,
    *,
    error: BaseException | None = None,
    requests: list[Any] | None = None,
    raw: bytes | None = None,
) -> Any:
    def opener(request: Any, timeout: float) -> _Response:
        del timeout
        if requests is not None:
            requests.append(request)
        if error is not None:
            raise error
        return _Response(raw if raw is not None else json.dumps(body or {}).encode())

    return opener


def _limit(kind: str, percent: Any, **changes: Any) -> dict[str, Any]:
    """One `limits[]` element carrying exactly the keys the capture recorded.

    Every element in the live response had the identical key set, so a fixture
    that omitted the fields the parser must ignore would make "ignored" vacuous:
    a parser that read `severity` would pass against a fixture that never sent
    one. `scope` is null except on the scoped kind, which is how it arrived.
    """
    element: dict[str, Any] = {
        "group": "session" if kind == "session" else "weekly",
        # Present because the capture records it on every element, and False
        # here for every kind on purpose: the recorded readings disagree about
        # which element is true, so pinning one arrangement in a fixture would
        # be inventing a measurement. Nothing reads it, which is the point.
        "is_active": False,
        "kind": kind,
        "percent": percent,
        "resets_at": NOW + 4 * 86400,
        "scope": None,
        "severity": "normal",
    }
    element.update(changes)
    return element


def _scoped(display_name: Any, percent: Any = 37, **changes: Any) -> dict[str, Any]:
    """A `weekly_scoped` element, the per-model shape.

    `id` is null and `resets_at` is absent because that is how the one recorded
    scoped element arrived: the display name is the only label available and the
    row carried no countdown at all.
    """
    element = _limit(
        "weekly_scoped",
        percent,
        scope={"model": {"display_name": display_name, "id": None}, "surface": "claude_code"},
    )
    element.pop("resets_at")
    element.update(changes)
    return element


def _usage_body(five: float = 42, week: float = 61, **changes: Any) -> dict[str, Any]:
    """The two named windows plus the three-element `limits[]` the capture had."""
    body: dict[str, Any] = {
        "five_hour": {"utilization": five, "resets_at": NOW + 3600},
        "seven_day": {"utilization": week, "resets_at": NOW + 4 * 86400},
        "limits": [_limit("session", 18), _limit("weekly_all", 61), _scoped("Fable", 37)],
    }
    body.update(changes)
    return body


def _forbidden_opener() -> Any:
    def opener(_request: Any, timeout: float) -> _Response:
        del timeout
        raise AssertionError("a request was made where the contract forbids one")

    return opener


class TokenReadTest(unittest.TestCase):
    def test_credentials_path_follows_the_claude_store(self) -> None:
        self.assertEqual(
            "/nonexistent-compass-test/.claude/.credentials.json",
            quota.credentials_path(_config()),
        )
        # A CLAUDE_CONFIG_DIR override moves the projects store, and the
        # credential file must move with it.
        moved = build_runtime_config(
            environ={"HOME": "/home/x", "CLAUDE_CONFIG_DIR": "/srv/claude-home"},
            platform_name="linux",
            os_name="posix",
            launcher_path=SERVER_PATH,
        )
        self.assertEqual("/srv/claude-home/.credentials.json", quota.credentials_path(moved))

    def test_macos_reads_the_keychain_item_by_its_service_name(self) -> None:
        calls: list[list[str]] = []
        runner = _keychain_runner(_credentials(), calls=calls)
        requests: list[Any] = []
        entries, note = quota._claude_entries(
            _config(platform_name="darwin"),
            NOW,
            _opener(_usage_body(), requests=requests),
            runner,
        )
        self.assertIsNone(note)
        self.assertEqual(1, len(entries))
        (argv,) = calls
        self.assertEqual("/usr/bin/security", argv[0])
        self.assertIn(quota.KEYCHAIN_SERVICE, argv)
        self.assertEqual(1, len(requests))

    def test_an_unavailable_keychain_item_is_a_category_never_a_value(self) -> None:
        # A denied prompt or a missing item must produce no entry at all, in
        # any state: `lapsed` and `refused` both describe a credential that was
        # read, and here none was. Whatever the subprocess did print must never
        # travel into the note either.
        runner = _keychain_runner("secret-looking stdout", returncode=1)
        entries, note = quota._claude_entries(
            _config(platform_name="darwin"), NOW, _forbidden_opener(), runner
        )
        self.assertEqual([], entries)
        self.assertEqual("keychain item unavailable", note)

    def test_missing_and_malformed_credential_files_stay_categories(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _config(home=tmp)
            entries, note = quota._claude_entries(config, NOW, _forbidden_opener(), _no_runner)
            self.assertEqual(([], "no credential file"), (entries, note))

            path = Path(quota.credentials_path(config))
            path.parent.mkdir(parents=True)
            path.write_text("{not json")
            entries, note = quota._claude_entries(config, NOW, _forbidden_opener(), _no_runner)
            self.assertEqual(([], "malformed credentials"), (entries, note))

            path.write_text(json.dumps({"claudeAiOauth": {"accessToken": "  "}}))
            entries, note = quota._claude_entries(config, NOW, _forbidden_opener(), _no_runner)
            self.assertEqual(([], "no oauth token"), (entries, note))

    def test_a_lapsed_stamp_makes_no_request_and_never_refreshes(self) -> None:
        # A stored stamp in the past is read from disk with no request made at
        # all — `_forbidden_opener` raises if one is. That is why this is not a
        # refusal: nothing refused anything. Claude Code rewrites the stored
        # credential only when it runs, so an open session keeps working on a
        # token it holds in memory, and a lapsed stamp beside healthy sessions
        # is the expected pairing rather than a fault.
        with tempfile.TemporaryDirectory() as tmp:
            config = _config(home=tmp)
            path = Path(quota.credentials_path(config))
            path.parent.mkdir(parents=True)
            path.write_text(_credentials(expires_at_ms=(NOW - 60) * 1000))
            entries, note = quota._claude_entries(config, NOW, _forbidden_opener(), _no_runner)
        self.assertIsNone(note)
        self.assertEqual([{"harness": "claude", "state": "lapsed", "asOf": int(NOW)}], entries)

    def test_a_lapsed_stamp_and_a_refusal_do_not_share_one_state(self) -> None:
        # The two Claude paths meant the same word once, and the page could only
        # render one message for both: the local check prescribed "sign in
        # again" for a token the harness refreshes by itself. Pinning the
        # inequality is what stops them being folded back together.
        with tempfile.TemporaryDirectory() as tmp:
            config = _config(home=tmp)
            path = Path(quota.credentials_path(config))
            path.parent.mkdir(parents=True)
            path.write_text(_credentials(expires_at_ms=(NOW - 60) * 1000))
            (local,), _ = quota._claude_entries(config, NOW, _forbidden_opener(), _no_runner)
        (refused,), _ = quota._fetch_windows(
            _config(), TOKEN, NOW, _opener(error=_http_error(401, "no"))
        )
        self.assertNotEqual(local["state"], refused["state"])


class FetchRequestTest(unittest.TestCase):
    def _fetch(
        self,
        opener: Any,
        *,
        config: RuntimeConfig | None = None,
    ) -> tuple[list[dict[str, Any]], str | None]:
        return quota._fetch_windows(config or _config(), TOKEN, NOW, opener)

    def test_the_request_carries_the_token_and_nothing_else(self) -> None:
        requests: list[Any] = []
        self._fetch(_opener(_usage_body(), requests=requests))
        (request,) = requests
        self.assertEqual(quota.USAGE_ENDPOINT, request.full_url)
        self.assertEqual("GET", request.get_method())
        self.assertIsNone(request.data)
        # Exactly two headers of ours. Asserting equality (not membership) is
        # what makes "nothing else" a tested claim rather than a hope.
        self.assertEqual(
            {
                "Authorization": f"Bearer {TOKEN}",
                "Anthropic-beta": quota.USAGE_BETA_VALUE,
            },
            dict(request.headers),
        )

    def test_windows_are_shaped_clamped_and_reset_stamped(self) -> None:
        entries, note = self._fetch(_opener(_usage_body(five=63.4, week=141)))
        self.assertIsNone(note)
        (entry,) = entries
        self.assertEqual("claude", entry["harness"])
        self.assertEqual("ok", entry["state"])
        self.assertEqual(int(NOW), entry["asOf"])
        self.assertEqual(63, entry["fiveH"]["pct"])
        self.assertEqual(100, entry["week"]["pct"])
        self.assertTrue(entry["fiveH"]["reset"])
        # Every window carries the instant as well as the words: the page renders
        # a countdown from the instant, so a producer that ships only the words
        # regresses the display to an absolute time that does not fit its column.
        for slot, offset in (("fiveH", 3600), ("week", 4 * 86400)):
            self.assertEqual(int(NOW + offset), entry[slot]["resetAt"], slot)

    def test_iso_reset_stamps_parse_like_epoch_ones(self) -> None:
        iso = datetime.fromtimestamp(NOW + 3600, tz=UTC).isoformat()
        body = {"five_hour": {"utilization": 10, "resets_at": iso}}
        entries, _ = self._fetch(_opener(body))
        # Shaped for the same slot on both sides, so what is compared is the two
        # stamp formats rather than the slot length that travels with them.
        self.assertEqual(
            quota._shape_window(
                NOW,
                {"utilization": 10, "resets_at": NOW + 3600},
                quota.SLOT_WINDOW_SEC["fiveH"],
            ),
            entries[0]["fiveH"],
        )

    def test_a_rejected_token_reads_as_refused_without_retry(self) -> None:
        # Both codes, and neither becomes a diagnostic category: the entry is
        # published so the tile can say why it has no numbers. `refused` is all
        # a 401 supports here — it cannot separate a token the harness would
        # refresh from an account this endpoint does not serve.
        for code in (401, 403):
            with self.subTest(code=code):
                error = _http_error(code, "no")
                entries, note = self._fetch(_opener(error=error))
                self.assertIsNone(note)
                self.assertEqual(
                    {"harness": "claude", "state": "refused", "asOf": int(NOW)}, entries[0]
                )

    def test_failures_shape_into_categories_without_the_token(self) -> None:
        cases: list[tuple[BaseException | None, bytes | None, str]] = [
            (_http_error(503, "down"), None, "HTTP 503"),
            (urllib.error.URLError("nope"), None, "URLError"),
            (TimeoutError("slow"), None, "TimeoutError"),
            (None, b"{not json", "malformed response"),
            (None, b"{}", "response carried no windows"),
        ]
        for error, raw, expected in cases:
            with self.subTest(expected=expected):
                entries, note = self._fetch(_opener(error=error, raw=raw))
                self.assertEqual([], entries)
                self.assertEqual(expected, note)
                self.assertNotIn(TOKEN, note or "")


class PerModelLimitTest(unittest.TestCase):
    """`limits[]`: the per-model sub-limits published as the `models` field.

    Element keys, types and the one absent `resets_at` come from a live response
    recorded off macOS on 2026-08-06, not from vendor documentation. That capture
    held exactly one scoped element, so the fixtures here deliberately run to
    several: the field is designed for an unknown number and verified against one.
    """

    def _models(self, body: dict[str, Any]) -> Any:
        entries, note = quota._fetch_windows(_config(), TOKEN, NOW, _opener(body))
        self.assertIsNone(note)
        (entry,) = entries
        return entry.get("models")

    def test_the_captured_shape_publishes_one_labelled_row(self) -> None:
        # Whole-list equality, not a field probe. It is what pins the shape the
        # page is being asked to render: the label, the integer percent, and
        # nothing else at all.
        self.assertEqual([{"label": "Fable", "pct": 37}], self._models(_usage_body()))

    def test_several_rows_publish_and_are_ordered_by_label(self) -> None:
        # Sent worst-first, labelled out of alphabetical order, and with the
        # percentages arranged so that ordering on `pct` in either direction
        # gives a different answer from ordering on the label. A percentage
        # ticks; rows sorted on one would move under the reader between polls.
        body = _usage_body(
            limits=[_scoped("Sonnet", 90), _scoped("Opus", 10), _scoped("Fable", 50)]
        )
        self.assertEqual(
            [
                {"label": "Fable", "pct": 50},
                {"label": "Opus", "pct": 10},
                {"label": "Sonnet", "pct": 90},
            ],
            self._models(body),
        )

    def test_a_response_with_no_scoped_limits_omits_the_field(self) -> None:
        # Absent, never an empty list: the window slots work the same way, and a
        # zero-row `models` on the wire invites a header with nothing under it.
        cases: list[tuple[str, Any]] = [
            ("no limits key", None),
            ("limits empty", []),
            ("limits not a list", {"kind": "weekly_scoped"}),
            ("limits is a string", "weekly_scoped"),
            ("only the two duplicate kinds", [_limit("session", 18), _limit("weekly_all", 61)]),
        ]
        for label, limits in cases:
            with self.subTest(case=label):
                body = _usage_body()
                if limits is None:
                    del body["limits"]
                else:
                    body["limits"] = limits
                self.assertIsNone(self._models(body))

    def test_a_scoped_limit_with_a_reset_carries_both_halves_of_the_pair(self) -> None:
        # The recorded scoped element had no `resets_at`, but the field exists on
        # the kinds that do, so a vendor that starts sending one must be read.
        resets = NOW + 3 * 86400
        body = _usage_body(limits=[_scoped("Fable", 37, resets_at=resets)])
        (row,) = self._models(body)
        self.assertEqual(sessions.format_reset(NOW, resets), row["reset"])
        self.assertEqual(int(resets), row["resetAt"])
        # An ISO stamp is the shape the capture actually carries on the windows,
        # and it must read as the same instant here.
        iso_body = _usage_body(
            limits=[
                _scoped("Fable", 37, resets_at=datetime.fromtimestamp(resets, tz=UTC).isoformat())
            ]
        )
        self.assertEqual([row], self._models(iso_body))

    def test_a_missing_reset_stays_missing_rather_than_defaulting(self) -> None:
        # Neither half of the pair may appear alone, and neither may be invented:
        # a per-model row is allowed to be a percentage with no countdown.
        cases: tuple[Any, ...] = (None, "", "not-a-date", 0, -1, True, [1], {})
        for raw in cases:
            with self.subTest(resets_at=raw):
                (row,) = self._models(_usage_body(limits=[_scoped("Fable", 37, resets_at=raw)]))
                self.assertEqual({"label": "Fable", "pct": 37}, row)

    def test_a_malformed_element_is_dropped_and_the_good_ones_survive(self) -> None:
        # One bad element in the list must not take the readable rows with it,
        # and must not become a row of its own.
        body = _usage_body(
            limits=[
                _scoped("Fable", 37),
                None,
                "weekly_scoped",
                [{"kind": "weekly_scoped"}],
                _scoped("Nameless", 40, scope=None),
                _scoped("Nameless", 40, scope={"model": None}),
                _scoped("Nameless", 40, scope={"model": {"display_name": None, "id": None}}),
                _scoped("Nameless", 40, scope={"model": {"display_name": "   ", "id": None}}),
                # A label that is not text at all. The repr of a number or an
                # object is not the model's name, so the row is refused rather
                # than published under it.
                _scoped(12, 40),
                _scoped(True, 40),
                _scoped({"display_name": "Opus"}, 40),
                # A percentage that is not a number, or is a bool.
                _scoped("Sonnet", "40"),
                _scoped("Sonnet", None),
                _scoped("Sonnet", True),
                _scoped("Opus", 55),
            ]
        )
        self.assertEqual(
            [{"label": "Fable", "pct": 37}, {"label": "Opus", "pct": 55}],
            self._models(body),
        )

    def test_a_hostile_label_is_bounded_and_sanitised(self) -> None:
        # The bound is written out as a literal, not read from
        # `MODEL_LABEL_CAP_CHARS`. Sizing the input and the expectation off the
        # constant moves both sides together, so raising the cap to four thousand
        # would still pass: the test would restate the implementation instead of
        # pinning it. Raising it should have to be a deliberate edit here too.
        (row,) = self._models(_usage_body(limits=[_scoped("O" * 400, 12)]))
        # Whole-value equality, not substring membership: `assertIn` matches a
        # fragment and would prove nothing about the truncation. Forty characters
        # out, and the cut taken from the middle rather than the end — the shape
        # is pinned here as a literal for the same reason the count is.
        self.assertEqual("O" * 20 + "…" + "O" * 19, row["label"])
        self.assertEqual(40, len(row["label"]))

        # Control characters collapse to a space, so a label cannot inject a
        # line into anything that renders it.
        (row,) = self._models(_usage_body(limits=[_scoped("Op\x00\x07us\nX", 12)]))
        self.assertEqual("Op us X", row["label"])

        # Markup is bounded here and escaped by the page, not stripped here.
        # Asserting it passes through verbatim is what documents that split: a
        # server that half-sanitised markup would leave the page unsure whether
        # it still had to escape.
        markup = "<img src=x onerror=alert(1)>"
        (row,) = self._models(_usage_body(limits=[_scoped(markup, 12)]))
        self.assertEqual(markup, row["label"])
        self.assertLessEqual(len(row["label"]), 40)

        # A label made only of control characters is nothing once sanitised, and
        # an unnamed bar under the weekly bar reads as a second weekly figure.
        self.assertIsNone(self._models(_usage_body(limits=[_scoped("\x00\x01\x02", 12)])))

    def test_two_models_that_agree_to_the_cap_still_publish_two_labels(self) -> None:
        # The reproduction. `scope.model.id` is null, so the label is a row's
        # whole identity, and two names agreeing for the first forty characters
        # used to publish two rows reading `Claude Opus 4.5 (Extended Thinking,
        # Max` with different percentages — the same string in the row and in the
        # hover, nowhere left to look, two limits presented as one.
        shared = "Claude Opus 4.5 (Extended Thinking, Max"
        rows = self._models(
            _usage_body(limits=[_scoped(shared + " Plan A", 12), _scoped(shared + " Plan B", 91)])
        )
        labels = [row["label"] for row in rows]
        self.assertEqual(len(set(labels)), len(labels), "two models published one label")
        # Distinct is not enough on its own: the difference has to be the one the
        # names actually carry, so each label is pinned whole. The cut lands in
        # the middle, which is what keeps the trailing `Plan A` / `Plan B`.
        self.assertEqual(
            [
                "Claude Opus 4.5 (Ext…hinking, Max Plan A",
                "Claude Opus 4.5 (Ext…hinking, Max Plan B",
            ],
            labels,
        )
        self.assertEqual([40, 40], [len(label) for label in labels])

    def test_names_differing_past_the_cut_are_told_apart_within_the_bound(self) -> None:
        # The case the elision cannot reach: two names that share both ends and
        # differ only in the middle, where no forty-character window can show it.
        # The rows are relabelled with a tag derived from the name, which is what
        # keeps them two rows; the label stays inside the same bound, because a
        # fix that let vendor text grow would be trading one defect for another.
        head, tail = "Claude Opus 4.5 with a very ", " long trailing qualifier here"
        limits = [_scoped(head + "A" * 40 + tail, 12), _scoped(head + "B" * 40 + tail, 91)]
        rows = self._models(_usage_body(limits=limits))
        labels = [row["label"] for row in rows]
        self.assertEqual(2, len(set(labels)))
        for label in labels:
            self.assertLessEqual(len(label), 40)
        # Stable in the name and in nothing else. Sending the same two elements
        # in the other order is the same two labels: a discriminator that counted
        # positions would renumber the rows under the reader between polls.
        reversed_rows = self._models(_usage_body(limits=list(reversed(limits))))
        self.assertEqual(rows, reversed_rows)

    def test_one_name_sent_twice_becomes_one_row_at_the_worse_figure(self) -> None:
        # Two elements the vendor itself gives no way to tell apart. A tag cannot
        # help — it would be the same tag — so they collapse, and the survivor is
        # the binding constraint, which is the resolution `shape_statusline`
        # already uses when two families report one window. Publishing both would
        # put two contradictory numbers under one name.
        rows = self._models(_usage_body(limits=[_scoped("Fable", 12), _scoped("Fable", 91)]))
        self.assertEqual([{"label": "Fable", "pct": 91}], rows)

    def test_the_duplicate_kinds_are_ignored_and_the_named_windows_stay_canonical(self) -> None:
        # `limits[]` restates the session and whole-plan weekly figures. The
        # top-level objects remain the source for those two, so the fixture gives
        # the list different numbers: a parser that read them would show them.
        body = _usage_body(
            five=42,
            week=61,
            limits=[_limit("session", 7), _limit("weekly_all", 8), _scoped("Fable", 9)],
        )
        entries, note = quota._fetch_windows(_config(), TOKEN, NOW, _opener(body))
        self.assertIsNone(note)
        (entry,) = entries
        self.assertEqual(42, entry["fiveH"]["pct"])
        self.assertEqual(61, entry["week"]["pct"])
        self.assertEqual([{"label": "Fable", "pct": 9}], entry["models"])
        self.assertEqual({"harness", "state", "asOf", "fiveH", "week", "models"}, set(entry))

    def test_kind_is_the_discriminator_and_group_is_not_consulted(self) -> None:
        # The capture's central finding: three kinds collapse onto two groups, so
        # `group` cannot tell the whole-plan weekly limit from a per-model one.
        #
        # On the recorded account that mistake is invisible, because the two
        # duplicate elements arrived with a null `scope` and would be dropped for
        # having no label whichever field was read. So this fixture deliberately
        # departs from the capture: it gives the `weekly_all` element a scope it
        # has never been observed to carry. That is the point. If Anthropic ever
        # attaches one, a parser keyed on `group` starts publishing the whole-plan
        # weekly figure as a model row sitting beside the identical weekly bar,
        # and only a test written against a shape the capture lacks catches it.
        labelled_all = _limit(
            "weekly_all",
            61,
            scope={"model": {"display_name": "Whole plan", "id": None}, "surface": "claude_code"},
        )
        body = _usage_body(limits=[labelled_all, _scoped("Fable", 37)])
        self.assertEqual([{"label": "Fable", "pct": 37}], self._models(body))

        # And the inverse: `group` absent altogether changes nothing, because it
        # is never read. A parser that required it would drop every row here.
        scoped = _scoped("Fable", 37)
        del scoped["group"]
        self.assertEqual(
            [{"label": "Fable", "pct": 37}], self._models(_usage_body(limits=[scoped]))
        )

        # An element with no `kind` at all is not a row either. Defaulting an
        # absent discriminator to the scoped kind would publish the session and
        # whole-plan figures as model rows on any response that stopped sending it.
        nameless = _scoped("Fable", 37)
        del nameless["kind"]
        self.assertIsNone(self._models(_usage_body(limits=[nameless])))

    def test_no_field_of_unestablished_meaning_reaches_the_payload(self) -> None:
        # `is_active` MOVES: the two recorded readings in
        # docs/captures/claude/usage-endpoint-macos.jsonl are a day apart and
        # disagree about which element carries it, so it tracks something that
        # varies rather than the kind of limit. `severity` is a vendor enum only
        # ever seen as `normal`. Neither may drive display or appear in the
        # payload until a measurement says what it means. The fixture sends both
        # on every element, so a parser that started reading one would fail here.
        body = _usage_body(limits=[_scoped("Fable", 37, is_active=False, severity="warning")])
        (row,) = self._models(body)
        self.assertEqual({"label", "pct"}, set(row))
        self.assertNotIn("warning", json.dumps(row))
        # And an inactive element still publishes: "inactive means ignore this"
        # would be a guess, and a row silently dropped on it is worse than a
        # percentage the reader can judge.
        self.assertEqual(37, row["pct"])

    def test_percentages_are_read_on_the_0_to_100_scale_and_clamped(self) -> None:
        # Measured as an int here and as a float on the windows, both already on
        # a percent scale. A fraction misread as a percent publishes 1 for a
        # model at 90, which is the failure the shared reader exists to prevent.
        body = _usage_body(
            limits=[
                _scoped("Fable", 90),
                _scoped("Opus", 141),
                _scoped("Sonnet", -3),
                _scoped("Zed", 63.5),
            ]
        )
        self.assertEqual(
            [
                {"label": "Fable", "pct": 90},
                {"label": "Opus", "pct": 100},
                {"label": "Sonnet", "pct": 0},
                {"label": "Zed", "pct": 64},
            ],
            self._models(body),
        )
        # The windows round identically, because both go through `_percent`.
        self.assertEqual({"pct": 64}, quota._shape_window(NOW, {"utilization": 63.5}))

    def test_the_row_count_is_bounded_at_what_the_vendor_sent(self) -> None:
        # Eight is written out rather than read from `MAX_SCOPED_LIMITS`, for the
        # same reason the label cap is: a bound sized off its own constant is not
        # a bound, because raising the constant raises the expectation with it.
        #
        # Sent in reverse-alphabetical order so the expected labels distinguish
        # bound-then-sort from sort-then-bound. Which rows survive an over-long
        # list is arbitrary either way; that the list is bounded is not.
        names = [f"model-{n:02d}" for n in reversed(range(11))]
        rows = self._models(_usage_body(limits=[_scoped(name, 20) for name in names]))
        self.assertEqual(8, len(rows))
        expected = ["model-03", "model-04", "model-05", "model-06"]
        expected += ["model-07", "model-08", "model-09", "model-10"]
        self.assertEqual(expected, [row["label"] for row in rows])

    def test_scoped_rows_do_not_rescue_a_response_with_no_named_windows(self) -> None:
        # A per-model limit is a sub-limit *of* the weekly window. Children with
        # no parent figure to be a fraction of are worth less than the category
        # naming what the response failed to carry.
        entries, note = quota._fetch_windows(
            _config(), TOKEN, NOW, _opener({"limits": [_scoped("Fable", 37)]})
        )
        self.assertEqual([], entries)
        self.assertEqual("response carried no windows", note)


class NonFiniteNumberTest(unittest.TestCase):
    """`NaN`, `Infinity`, and integers with no width, which JSON gives for free.

    Nothing in this class is a hostile-input scenario. `json.loads` accepts bare
    `NaN` and `Infinity` in its default configuration, and a JSON integer literal
    has no width at all, so any of these reaches a parser here the moment a
    vendor's serializer emits one. `round()` and `int()` raise on the first two,
    `float()` raises on an integer too large to hold, and `datetime.fromtimestamp`
    raises outside `time_t` — and a parser that raises instead of declining is
    what turned the five-minute floor into a request-per-refresh loop.
    `fetch_usage` now survives that, but a value is refused *here*, in the reader
    that read it, so the failure stays a named category rather than the blanket
    `reader ValueError` of last resort.
    """

    def _entry(self, body: str) -> dict[str, Any]:
        entries, note = quota._fetch_windows(_config(), TOKEN, NOW, _opener(raw=body.encode()))
        self.assertIsNone(note)
        (entry,) = entries
        return entry

    def test_json_really_does_hand_these_over_by_default(self) -> None:
        # The premise of the class, asserted rather than assumed. No flag is set
        # and no dialect chosen: this is what `json.loads` does out of the box,
        # which is why every reader below has to expect it.
        self.assertEqual([float("inf"), float("-inf")], json.loads("[Infinity, -Infinity]"))
        self.assertTrue(math.isnan(json.loads("NaN")))
        self.assertEqual(10**400, json.loads("1" + "0" * 400))

    def test_a_non_finite_window_reads_as_no_window_not_as_a_crash(self) -> None:
        entries, note = quota._fetch_windows(
            _config(),
            TOKEN,
            NOW,
            _opener(
                raw=b'{"five_hour": {"utilization": NaN, "resets_at": 1700003600},'
                b' "seven_day": {"utilization": Infinity}}'
            ),
        )
        # The category the response earns, not the one an exception would have
        # produced: both windows were unreadable, so there is no entry at all.
        self.assertEqual(([], "response carried no windows"), (entries, note))

    def test_a_non_finite_percentage_drops_only_its_own_row(self) -> None:
        for literal in ("NaN", "Infinity", "-Infinity", "1" + "0" * 400):
            with self.subTest(percent=literal):
                entry = self._entry(
                    '{"five_hour": {"utilization": 42}, "limits": [{"kind": "weekly_scoped",'
                    f' "percent": {literal},'
                    ' "scope": {"model": {"display_name": "Fable", "id": null}}}]}'
                )
                # The window beside it still publishes: one unreadable number is
                # a missing row, never a missing tile.
                self.assertEqual(42, entry["fiveH"]["pct"])
                self.assertNotIn("models", entry)

    def test_an_unreadable_reset_leaves_the_percentage_without_a_countdown(self) -> None:
        # `Infinity` and a finite stamp past every plausible reset both reach
        # `datetime.fromtimestamp`, which raises rather than declines outside
        # `time_t`. Neither may take the percentage down with it.
        for literal in ("Infinity", "-Infinity", "NaN", "1e300", "1" + "0" * 400):
            with self.subTest(resets_at=literal):
                entry = self._entry(
                    f'{{"five_hour": {{"utilization": 42, "resets_at": {literal}}}}}'
                )
                # `windowSec` is the slot's own length and is unrelated to the
                # reset: a window with no readable countdown still has a
                # duration, and the page needs it to place the elapsed tick.
                self.assertEqual({"pct": 42, "windowSec": 5 * 3600}, entry["fiveH"])

    def test_cursors_money_and_cycle_end_refuse_the_same_values(self) -> None:
        # Same defect class, the other fetch vendor: `int()` raises on both, and
        # Cursor's parser is reached from its own reader.
        self.assertEqual(
            ([], "response carried no plan usage"),
            quota._cursor_parse(NOW, b'{"planUsage": {"totalSpend": NaN}}'),
        )
        # An unreadable limit is a plan with no denominator, which already has a
        # published shape: the money, and no gauge pretending to be one.
        entries, note = quota._cursor_parse(
            NOW, b'{"planUsage": {"totalSpend": 18, "limit": Infinity}}'
        )
        self.assertIsNone(note)
        self.assertEqual(
            {"harness": "cursor", "state": "ok", "asOf": int(NOW), "used": "$0.18"}, entries[0]
        )
        # An unreadable cycle end is a bar with no countdown, not a lost bar.
        entries, note = quota._cursor_parse(
            NOW, b'{"planUsage": {"totalSpend": 18, "limit": 2000}, "billingCycleEnd": Infinity}'
        )
        self.assertIsNone(note)
        self.assertEqual({"pct": 1}, entries[0]["month"])

    def test_a_non_finite_receipt_fraction_is_dropped(self) -> None:
        # The pushed path reads its own numbers, and its body is parsed by the
        # same `json.loads` at the endpoint, so it inherits the same values.
        for value in (float("nan"), float("inf"), float("-inf"), 10**400):
            with self.subTest(remaining_fraction=value):
                payload = {"quota": {"gemini-5h": {"remaining_fraction": value}}}
                self.assertEqual([], quota.shape_statusline(payload, NOW))


class FetchLifecycleTest(unittest.TestCase):
    def _darwin(self, **changes: Any) -> tuple[RuntimeConfig, RuntimeState]:
        config = _config(platform_name="darwin", **changes)
        return config, _state(config)

    def test_a_fetch_caches_entries_and_diagnoses_only_categories(self) -> None:
        config, state = self._darwin()
        diagnostics_log: list[str] = []
        _fetch_claude(
            config,
            state,
            clock=lambda: NOW,
            opener=_opener(_usage_body()),
            runner=_keychain_runner(_credentials()),
            diagnostic_sink=diagnostics_log.append,
        )
        self.assertEqual([], diagnostics_log)
        cached = quota.cached_entries(config, state, "claude", NOW, 24.0)
        self.assertEqual("ok", cached[0]["state"])

        _fetch_claude(
            config,
            state,
            clock=lambda: NOW,
            opener=_opener(error=urllib.error.URLError("net down")),
            runner=_keychain_runner(_credentials()),
            diagnostic_sink=diagnostics_log.append,
        )
        self.assertEqual([], quota.cached_entries(config, state, "claude", NOW, 24.0))
        self.assertTrue(any("URLError" in line for line in diagnostics_log))
        self.assertFalse(any(TOKEN in line for line in diagnostics_log))

    def test_cached_entries_returns_copies(self) -> None:
        config, state = self._darwin()
        with state.usage_fetch_lock:
            # `asOf` is here so the freshness gate lets the entry through. This
            # test is about detachment from the cache, and an entry the gate
            # withholds would assert nothing about it.
            state.usage_fetch_cache["claude"] = {
                "ts": NOW,
                "entries": [{"harness": "claude", "state": "ok", "asOf": NOW}],
            }
        quota.cached_entries(config, state, "claude", NOW, 24.0)[0]["state"] = "mangled"
        self.assertEqual("ok", quota.cached_entries(config, state, "claude", NOW, 24.0)[0]["state"])

    def test_request_fetch_holds_every_gate_of_the_polling_posture(self) -> None:
        clock_now = [NOW]
        fetched: list[Any] = []
        config, state = self._darwin()

        def inline(run: Any) -> None:
            run()

        def request(**overrides: Any) -> bool:
            return quota.request_fetch(
                overrides.pop("config", config),
                state,
                clock=lambda: clock_now[0],
                opener=overrides.pop("opener", _opener(_usage_body(), requests=fetched)),
                runner=_keychain_runner(_credentials()),
                diagnostic_sink=lambda _line: None,
                spawn=inline,
                **overrides,
            )

        # Gate 1: the feature switch. --no-usage means never, full stop.
        off = dataclasses.replace(config, usage_fetch_enabled=False)
        self.assertFalse(request(config=off, opener=_forbidden_opener()))

        # First consented request fetches.
        self.assertTrue(request())
        self.assertEqual(1, len(fetched))

        # Gate 2: the five-minute floor, inside it nothing moves.
        clock_now[0] = NOW + config.usage_poll_floor_sec - 1
        self.assertFalse(request(opener=_forbidden_opener()))

        # Past the floor the next consented request fetches again.
        clock_now[0] = NOW + config.usage_poll_floor_sec + 1
        self.assertTrue(request())
        self.assertEqual(2, len(fetched))

    def test_the_floor_applies_to_failed_fetches_too(self) -> None:
        # A missing credential must retry on the same cadence as success —
        # "a failed poll means an empty tile, never a retry storm".
        config, state = self._darwin()
        attempts: list[list[str]] = []
        for _ in range(3):
            quota.request_fetch(
                config,
                state,
                clock=lambda: NOW,
                runner=_keychain_runner("", returncode=1, calls=attempts),
                diagnostic_sink=lambda _line: None,
                spawn=lambda run: run(),
            )
        # Each vendor is attempted exactly once across all three rounds. Counting
        # per vendor rather than in total is what makes this fail if one vendor's
        # failure ever stops stamping its own cache entry.
        self.assertEqual(
            sorted([quota.KEYCHAIN_SERVICE, quota.CURSOR_KEYCHAIN_SERVICE]),
            sorted(_asked_services(attempts)),
        )

    def test_a_fetch_already_in_flight_blocks_a_second(self) -> None:
        config, state = self._darwin()
        with state.usage_fetch_lock:
            state.usage_fetch_inflight.update(vendor for vendor, _ in quota.FETCH_VENDORS)
        self.assertFalse(
            quota.request_fetch(
                config,
                state,
                clock=lambda: NOW,
                opener=_forbidden_opener(),
                spawn=lambda run: run(),
            )
        )

    def test_the_gates_are_held_per_vendor_not_globally(self) -> None:
        # One vendor in flight must not suppress another's refresh, and a
        # vendor inside its own floor must not hold a fresh one off. A single
        # shared gate would pass every other test in this class while quietly
        # starving whichever vendor came second in the registry.
        config, state = self._darwin()
        asked: list[list[str]] = []
        with state.usage_fetch_lock:
            state.usage_fetch_inflight.add("claude")
            # Claude also inside its floor, belt and braces.
            state.usage_fetch_cache["claude"] = {"ts": NOW, "entries": []}
        started = quota.request_fetch(
            config,
            state,
            clock=lambda: NOW,
            opener=_opener({}),
            runner=_keychain_runner("", returncode=1, calls=asked),
            diagnostic_sink=lambda _line: None,
            spawn=lambda run: run(),
        )
        self.assertTrue(started, "the blocked vendor suppressed the whole round")
        self.assertEqual([quota.CURSOR_KEYCHAIN_SERVICE], _asked_services(asked))
        with state.usage_fetch_lock:
            # Claude's marker is left exactly as it was found; only Cursor ran.
            self.assertEqual({"claude"}, state.usage_fetch_inflight)
            self.assertIn("cursor", state.usage_fetch_cache)

    def test_the_inflight_marker_clears_even_when_the_fetch_dies(self) -> None:
        config, state = self._darwin()
        boom = RuntimeError("thread death")
        with (
            mock.patch.object(quota, "fetch_usage", side_effect=boom),
            self.assertRaises(RuntimeError),
        ):
            quota.request_fetch(config, state, clock=lambda: NOW, spawn=lambda run: run())
        with state.usage_fetch_lock:
            self.assertEqual(set(), state.usage_fetch_inflight)

    def test_a_raising_reader_stamps_the_attempt_and_arms_the_floor(self) -> None:
        # The cache write is what the floor reads, so it has to happen on the way
        # out of every failure, including the one nobody wrote a branch for. The
        # note names the exception type and no more: an exception raised while
        # parsing a response can carry that response in its own message, and the
        # module's diagnostics are fixed words plus type names for that reason.
        config, state = self._darwin()
        log: list[str] = []

        def raiser(*_args: Any) -> Any:
            raise ValueError(f"cannot convert {TOKEN}")

        quota.fetch_usage(
            config,
            state,
            "claude",
            raiser,
            clock=lambda: NOW,
            diagnostic_sink=log.append,
        )
        self.assertEqual(["[claude] usage fetch: reader ValueError"], log)
        with state.usage_fetch_lock:
            self.assertEqual({"ts": NOW, "entries": []}, state.usage_fetch_cache["claude"])

    def test_a_raising_reader_cannot_become_a_request_per_refresh(self) -> None:
        # The consequence, measured the way it was reproduced: four consented
        # requests one second apart, well inside the five-minute floor. Before
        # the fix each one started an outbound fetch, because the thread died
        # before the cache write that arms the floor. "At most one request per
        # vendor every five minutes" is a SECURITY.md promise, and a parser bug
        # is not an exemption from it.
        config, state = self._darwin()
        attempts: list[float] = []
        ticks = [NOW]

        def raiser(_config: Any, now: float, _opener: Any, _runner: Any) -> Any:
            attempts.append(now)
            raise ValueError("a parser, on a payload nobody expected")

        with mock.patch.object(quota, "FETCH_VENDORS", (("claude", raiser),)):
            for tick in range(4):
                ticks[0] = NOW + tick
                quota.request_fetch(
                    config,
                    state,
                    clock=lambda: ticks[0],
                    diagnostic_sink=lambda _line: None,
                    spawn=lambda run: run(),
                )
        self.assertEqual([NOW], attempts)

    def test_the_default_spawn_runs_on_a_daemon_thread(self) -> None:
        seen: list[bool] = []
        done = threading.Event()

        def probe() -> None:
            seen.append(threading.current_thread().daemon)
            done.set()

        quota._spawn_thread(probe)
        self.assertTrue(done.wait(timeout=30))
        self.assertEqual([True], seen)


class CachedEntryFreshnessTest(unittest.TestCase):
    """The cache is a reading, not a fact: past the window it stops publishing.

    Both fetch-backed rows read `cached_entries`, and neither has any other
    route to a number, so this is where their staleness behaviour is pinned.
    The threshold is the collection's own `window_hours`, the same one the Codex
    disk reader uses, because the question is identical for both: a figure older
    than the window describes quota windows that have themselves reset.
    """

    WINDOW_HOURS = 24.0
    WINDOW_SEC = 24 * 3600

    def _seeded(self, vendor: str, as_of: Any) -> tuple[RuntimeConfig, RuntimeState]:
        config = _config()
        state = _state(config)
        entry: dict[str, Any] = {"harness": vendor, "state": "ok", "fiveH": {"pct": 42}}
        if as_of is not _MISSING:
            entry["asOf"] = as_of
        with state.usage_fetch_lock:
            # `ts` is deliberately current: the fetch stamp arms the poll floor
            # and says when the attempt happened, and pinning it fresh proves
            # the gate reads the entry's own reading time rather than that.
            state.usage_fetch_cache[vendor] = {"ts": NOW, "entries": [entry]}
        return config, state

    def _published(self, vendor: str, as_of: Any) -> list[dict[str, Any]]:
        config, state = self._seeded(vendor, as_of)
        return _USAGE_PROVIDERS[vendor](config, state, NOW, self.WINDOW_HOURS)

    def test_a_reading_inside_the_window_still_publishes(self) -> None:
        for vendor in _USAGE_PROVIDERS:
            with self.subTest(vendor=vendor):
                (entry,) = self._published(vendor, NOW - 3600)
                self.assertEqual(vendor, entry["harness"])
                self.assertEqual(42, entry["fiveH"]["pct"])

    def test_a_reading_past_the_window_publishes_nothing(self) -> None:
        for vendor in _USAGE_PROVIDERS:
            with self.subTest(vendor=vendor):
                self.assertEqual([], self._published(vendor, NOW - 7 * 86400))

    def test_the_window_edge_publishes_and_one_second_past_it_does_not(self) -> None:
        # `sessions.is_fresh` compares `age <= window_sec`, so the boundary
        # itself is inside. Codex inherits the same inclusive edge from the same
        # primitive; asserting it here stops a later `<` making the two disagree.
        for vendor in _USAGE_PROVIDERS:
            with self.subTest(vendor=vendor):
                self.assertTrue(self._published(vendor, NOW - self.WINDOW_SEC))
                self.assertEqual([], self._published(vendor, NOW - self.WINDOW_SEC - 1))

    def test_a_narrower_window_withholds_what_a_wider_one_publishes(self) -> None:
        # The threshold travels with the collection rather than being a constant,
        # so `--window 1` must move it. One reading, two windows, two answers.
        for vendor, provider in _USAGE_PROVIDERS.items():
            with self.subTest(vendor=vendor):
                config, state = self._seeded(vendor, NOW - 6 * 3600)
                self.assertTrue(provider(config, state, NOW, 24.0))
                self.assertEqual([], provider(config, state, NOW, 1.0))

    def test_an_unusable_stamp_publishes_nothing(self) -> None:
        # A reading whose age cannot be computed is the case that would otherwise
        # publish forever, which is worse than the stale number: nothing on the
        # page or in the pace ring would ever say how old it is.
        unusable = (
            _MISSING,
            None,
            float("nan"),
            float("inf"),
            float("-inf"),
            10**400,
            "1700000000",
            NOW + 3600,  # a stamp ahead of the collection clock past the skew allowance
        )
        for vendor in _USAGE_PROVIDERS:
            for value in unusable:
                with self.subTest(vendor=vendor, asOf=value):
                    self.assertEqual([], self._published(vendor, value))

    def test_a_stamp_inside_the_future_skew_allowance_still_publishes(self) -> None:
        # `sessions.age` clamps a small overshoot rather than rejecting it, and
        # the gate must not be stricter than the primitive it delegates to.
        config = _config()
        for vendor in _USAGE_PROVIDERS:
            with self.subTest(vendor=vendor):
                self.assertTrue(self._published(vendor, NOW + config.future_skew_tolerance_sec))

    def test_the_codex_provider_never_reaches_this_cache(self) -> None:
        # Codex gates its own disk snapshot. Proving it does not read the cache
        # is what shows the new gate cannot double-apply to it.
        config = _config()
        state = _state(config)
        with mock.patch.object(
            quota,
            "cached_entries",
            side_effect=AssertionError("the Codex reader must not read the fetch cache"),
        ):
            self.assertEqual([], codex_collector.usage(config, state, NOW, self.WINDOW_HOURS))


class CursorFetchTest(unittest.TestCase):
    """Cursor's fetch: the request shape, the units, and the honest percentage.

    Field names and shapes come from a payload captured off a live cursor-agent
    2026.07.23 install on a Pro plan, not from vendor documentation. The captured
    values were nearly zero (18 cents of 2000), where an arithmetic error is
    invisible, so the fixtures here deliberately carry a mid-range balance.
    """

    SPEND = 1350
    LIMIT = 2000

    @classmethod
    def _body(cls, **changes: Any) -> dict[str, Any]:
        plan: dict[str, Any] = {
            "totalSpend": cls.SPEND,
            "includedSpend": cls.SPEND,
            "remaining": cls.LIMIT - cls.SPEND,
            "limit": cls.LIMIT,
            # Present and deliberately inconsistent with spend/limit, exactly as
            # the live payload is. Nothing may read it.
            "autoPercentUsed": 0.06,
            "apiPercentUsed": 0,
            "totalPercentUsed": 0.05217391304347826,
        }
        plan.update(changes)
        return {
            "billingCycleStart": "1699000000000",
            "billingCycleEnd": str(int((NOW + 6 * 86400) * 1000)),
            "planUsage": plan,
            "spendLimitUsage": {"limitType": "user"},
            "displayMessage": "You've used 68% of your included usage",
            "enabled": True,
        }

    def _entries(self, **kwargs: Any) -> tuple[list[dict[str, Any]], str | None]:
        opener = kwargs.pop("opener", _opener(self._body()))
        runner = kwargs.pop(
            "runner",
            _keychain_runner(f"{TOKEN}\n", service=quota.CURSOR_KEYCHAIN_SERVICE),
        )
        config = kwargs.pop("config", _config(platform_name="darwin"))
        return quota._cursor_entries(config, NOW, opener, runner)

    def test_the_request_is_a_post_carrying_the_token_and_nothing_else(self) -> None:
        requests: list[Any] = []
        entries, note = self._entries(opener=_opener(self._body(), requests=requests))
        self.assertIsNone(note)
        (request,) = requests
        self.assertEqual(quota.CURSOR_USAGE_ENDPOINT, request.full_url)
        self.assertEqual("POST", request.get_method())
        self.assertEqual(b"{}", request.data)
        # Exactly two headers of ours. A cookie here would mean the browser-session
        # path, which was rejected: this must stay the CLI's own bearer route.
        self.assertEqual(
            {"Authorization": f"Bearer {TOKEN}", "Content-type": "application/json"},
            dict(request.headers),
        )
        self.assertEqual(1, len(entries))

    def test_money_is_read_as_cents_and_published_as_dollars(self) -> None:
        # THE unit assertion. The percentage cannot catch a cents/dollars misread,
        # because a ratio is unit-invariant; only the rendered money can. Reading
        # these as dollars would publish "$1350.00 of $2000.00".
        (entry,), _ = self._entries()
        self.assertEqual("$13.50 of $20.00", entry["used"])

    def test_the_percentage_comes_from_spend_over_limit_not_the_payloads_own(self) -> None:
        # `totalPercentUsed` in the fixture is the live value, 0.0521739, and is
        # inconsistent with spend/limit in both readings: 5 if taken as a
        # fraction, 0 if taken as a percent. The honest figure is 1350/2000, and
        # it agrees with Cursor's own displayMessage.
        (entry,), _ = self._entries()
        self.assertEqual(68, entry["month"]["pct"])
        self.assertIn("68%", self._body()["displayMessage"])

    def test_the_cycle_end_is_read_as_millisecond_epoch(self) -> None:
        # Sent as a decimal string of epoch MILLIseconds, which is how protobuf
        # JSON encodes int64. Compared against the shared formatter at the
        # instant the fixture encodes, so this pins the instant rather than the
        # wording. Dividing a seconds value by 1000 lands in 1970, which renders
        # differently — asserted, so the test cannot pass on the wrong reading.
        cycle_end = NOW + 6 * 86400
        expected = sessions.format_reset(NOW, cycle_end)
        (entry,), _ = self._entries()
        self.assertEqual(expected, entry["month"]["reset"])
        self.assertNotEqual(expected, sessions.format_reset(NOW, cycle_end / 1000))
        # The instant travels too, because the page counts down from it rather
        # than from the words. Same reading, so a millisecond misparse fails here
        # as well as in the wording above.
        self.assertEqual(int(cycle_end), entry["month"]["resetAt"])

    def test_an_unreadable_cycle_end_leaves_the_bar_without_a_reset(self) -> None:
        # The percentage is still true without one; inventing a reset is not.
        for raw in (None, "not-a-number", 0, -1, True, [1]):
            with self.subTest(cycle_end=raw):
                body = self._body()
                body["billingCycleEnd"] = raw
                (entry,), note = self._entries(opener=_opener(body))
                self.assertIsNone(note)
                self.assertEqual(68, entry["month"]["pct"])
                self.assertNotIn("reset", entry["month"])
                # Neither half of the pair may appear alone: a countdown with no
                # instant would silently fall back to absent words.
                self.assertNotIn("resetAt", entry["month"])

    def test_the_entry_fills_month_and_never_the_rolling_windows(self) -> None:
        # A monthly billing cycle in a slot labelled "5h" or "wk" would put a
        # wrong label on a real number.
        (entry,), _ = self._entries()
        self.assertEqual("cursor", entry["harness"])
        self.assertEqual("ok", entry["state"])
        self.assertEqual(int(NOW), entry["asOf"])
        self.assertNotIn("fiveH", entry)
        self.assertNotIn("week", entry)

    def test_a_plan_with_no_limit_publishes_spend_and_no_gauge(self) -> None:
        # Unlimited and limit-less plans exist; a bar needs a denominator.
        for limit in (0, None, -5, True, "2000"):
            with self.subTest(limit=limit):
                (entry,), note = self._entries(opener=_opener(self._body(limit=limit)))
                self.assertIsNone(note)
                self.assertEqual("$13.50", entry["used"])
                self.assertNotIn("month", entry)

    def test_an_unusable_spend_figure_is_a_miss_not_an_entry(self) -> None:
        spends: tuple[Any, ...] = (None, "18", -1, True, {})
        for spend in spends:
            with self.subTest(spend=spend):
                entries, note = self._entries(opener=_opener(self._body(totalSpend=spend)))
                self.assertEqual([], entries)
                self.assertEqual("response carried no plan usage", note)

    def test_a_rejected_token_is_refused_never_a_refresh(self) -> None:
        # Cursor reaches this state and no other: it has no local expiry check,
        # so the refusal is the only way its token can be reported as unusable.
        # The measured remedy (401 with `actionRequired: "login"`) is a property
        # of Cursor's answer, not of the state word, so the word is the same one
        # Claude's refusal carries and the page decides what to advise.
        for code in (401, 403):
            with self.subTest(code=code):
                (entry,), note = self._entries(opener=_opener(error=_http_error(code, "nope")))
                self.assertIsNone(note)
                self.assertEqual({"harness": "cursor", "state": "refused", "asOf": int(NOW)}, entry)

    def test_transport_and_server_failures_stay_categories(self) -> None:
        cases = (
            (_opener(error=_http_error(500, "boom")), "HTTP 500"),
            (_opener(error=urllib.error.URLError("net down")), "URLError"),
            (_opener(raw=b"not json"), "malformed response"),
        )
        for opener, expected in cases:
            with self.subTest(expected=expected):
                entries, note = self._entries(opener=opener)
                self.assertEqual([], entries)
                self.assertEqual(expected, note)

    def test_off_macos_no_credential_is_read_and_no_request_is_made(self) -> None:
        # The token's location is verified on macOS only. Guessing a path
        # elsewhere would read some other file and call it a credential.
        for platform_name in ("linux", "win32"):
            with self.subTest(platform=platform_name):
                entries, note = self._entries(
                    config=_config(platform_name=platform_name),
                    opener=_forbidden_opener(),
                    runner=_no_runner,
                )
                self.assertEqual([], entries)
                self.assertEqual("no credential source on this platform", note)

    def test_an_unavailable_keychain_item_is_a_category_never_a_value(self) -> None:
        entries, note = self._entries(
            opener=_forbidden_opener(),
            runner=_keychain_runner(
                "secret-looking stdout", returncode=1, service=quota.CURSOR_KEYCHAIN_SERVICE
            ),
        )
        self.assertEqual([], entries)
        self.assertEqual("keychain item unavailable", note)

    def test_the_reader_asks_for_cursors_own_keychain_service(self) -> None:
        calls: list[list[str]] = []
        self._entries(
            runner=_keychain_runner(
                f"{TOKEN}\n", calls=calls, service=quota.CURSOR_KEYCHAIN_SERVICE
            )
        )
        self.assertEqual([quota.CURSOR_KEYCHAIN_SERVICE], _asked_services(calls))
        # Not Claude's item: the two vendors must never read each other's.
        self.assertNotIn(quota.KEYCHAIN_SERVICE, _asked_services(calls))

    def test_the_token_reaches_neither_the_note_nor_the_entry(self) -> None:
        (entry,), note = self._entries()
        self.assertNotIn(TOKEN, json.dumps(entry))
        self.assertNotIn(TOKEN, str(note))


class NoFetchWithoutConsentTest(RuntimeTestCase):
    """The serving surface: only a consented /api/data request may trigger."""

    def _server(self) -> tuple[Any, Any]:
        application = cli.build_application(*runtime(), clock=time.time)
        httpd = make_server(application=application)
        return httpd, application

    def _get(self, port: int, path: str, headers: dict[str, str] | None = None) -> int:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
        conn.request("GET", path, headers=headers or {})
        response = conn.getresponse()
        response.read()
        status = response.status
        conn.close()
        return status

    def test_a_document_navigation_never_arms_the_fetch(self) -> None:
        """A cross-site link must not spend a credential read as a side effect.

        `_local_ok` deliberately serves a cross-site top-level navigation,
        because the initiating page cannot read a cross-origin document, so
        nothing is exfiltrated. That reasoning covers the RESPONSE and not a
        side effect: an attacker page that gets the browser to open
        `/api/data?usage=1` in a tab reads nothing back and would still have
        made Compass read a harness credential out of the Keychain and send it
        to the vendor, with the disclosure never shown. The body is still
        served, so this asserts on the trigger rather than on the status.
        """
        httpd, application = self._server()
        calls: list[bool] = []
        original = application.request_usage_fetch

        def fake_trigger() -> bool:
            calls.append(True)
            return False

        application.request_usage_fetch = fake_trigger
        thread = threading.Thread(target=poll_fast(httpd), daemon=True)
        thread.start()
        navigation = {
            "Sec-Fetch-Site": "cross-site",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Dest": "document",
        }
        try:
            status = self._get(httpd.server_port, "/api/data?usage=1", navigation)
            # Served, exactly as before: the allowance for opening the API in a
            # tab is unchanged and only the side effect is refused.
            self.assertEqual(200, status)
            self.assertEqual([], calls, "a navigation must never arm the fetch")
            # And the page's own poll, which goes through `fetch` and so reports
            # an empty destination, still arms it.
            self.assertEqual(
                200,
                self._get(
                    httpd.server_port,
                    "/api/data?usage=1",
                    {"Sec-Fetch-Site": "same-origin", "Sec-Fetch-Dest": "empty"},
                ),
            )
            self.assertEqual(1, len(calls))
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=2)
            application.request_usage_fetch = original

    def test_only_a_consented_request_triggers_and_diagnose_never_does(self) -> None:
        httpd, application = self._server()
        calls: list[bool] = []
        original = application.request_usage_fetch

        def fake_trigger() -> bool:
            calls.append(True)
            return False

        application.request_usage_fetch = fake_trigger
        thread = threading.Thread(target=poll_fast(httpd), daemon=True)
        thread.start()
        try:
            self._get(httpd.server_port, "/api/data")
            self._get(httpd.server_port, "/api/data?all=1")
            self.assertEqual([], calls, "a bare request must never trigger a fetch")
            self._get(httpd.server_port, "/api/data?usage=1")
            self.assertEqual(1, len(calls))
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=2)
            application.request_usage_fetch = original

        # --diagnose runs a full collection; a fetch riding along would be a
        # network side effect on a path documented to report local paths only.
        with (
            mock.patch.object(quota, "request_fetch") as trigger,
            mock.patch.object(quota, "fetch_usage") as fetch,
        ):
            diagnostics.diagnose(application)
            application.collect(show_all=True)
        trigger.assert_not_called()
        fetch.assert_not_called()

    def test_the_token_reaches_no_loopback_response(self) -> None:
        # End to end: a successful fetch fills the cache, the collection
        # publishes the shaped quota numbers, and the serialized payload every
        # loopback endpoint could serve carries no trace of the token.
        with tempfile.TemporaryDirectory() as tmp:
            config = _config(home=tmp, platform_name="darwin")
            Path(tmp, ".claude", "projects").mkdir(parents=True)
            state = _state(config)
            _fetch_claude(
                config,
                state,
                clock=lambda: NOW,
                opener=_opener(_usage_body()),
                runner=_keychain_runner(_credentials()),
                diagnostic_sink=lambda _line: None,
            )
            application = aggregate.Application(
                config,
                state,
                aggregate.default_harnesses(),
                native_notifier=lambda _p: "",
                popup_notifier=lambda _t, _m: None,
                diagnostic_sink=lambda _line: None,
                clock=lambda: NOW,
            )
            _revision, body = application.collect_json(show_all=True)
        self.assertNotIn(TOKEN.encode(), body)
        data = json.loads(body)
        self.assertTrue(data.get("usage_fetch"))
        (claude_entry,) = [u for u in data["usage"] if u.get("harness") == "claude"]
        self.assertEqual("ok", claude_entry["state"])
        self.assertEqual(42, claude_entry["fiveH"]["pct"])
        # The per-model rows travel the whole way too. Shaping them in the
        # fetcher is no use if the collection or the serializer drops them.
        self.assertEqual([{"label": "Fable", "pct": 37}], claude_entry["models"])


class StatuslineReceiptTest(unittest.TestCase):
    """Pushed receipts: shaping, the worst-of-pair rule, and staleness.

    Field names and the two-family shape come from a payload captured off a
    live agy 1.1.10 install, not from the vendor's documentation.
    """

    @staticmethod
    def _payload(**buckets: float | None) -> dict[str, Any]:
        """A status-line payload carrying the named buckets, plus the noise a
        real one carries. The email is deliberately present: it must never
        reach an entry."""
        quota: dict[str, Any] = {}
        for key, remaining in buckets.items():
            name = key.replace("_", "-")
            quota[name] = (
                {"remaining_fraction": remaining, "reset_time": "2026-08-04T14:16:36Z"}
                if remaining is not None
                else {}
            )
        return {
            "quota": quota,
            "email": "someone@example.com",
            "transcript_path": "/Users/someone/secret/path.jsonl",
            "plan_tier": "Google AI Ultra",
            "agent_state": "idle",
        }

    def test_the_captured_shape_becomes_one_entry(self) -> None:
        # The exact four keys the live capture carried.
        entries = quota.shape_statusline(
            self._payload(gemini_5h=1, gemini_weekly=1, **{"3p_5h": 1, "3p_weekly": 1}), NOW
        )
        self.assertEqual(1, len(entries))
        entry = entries[0]
        self.assertEqual("antigravity", entry["harness"])
        self.assertEqual("ok", entry["state"])
        self.assertEqual(int(NOW), entry["asOf"])
        self.assertEqual(0, entry["fiveH"]["pct"])
        self.assertEqual(0, entry["week"]["pct"])

    def test_remaining_fraction_is_inverted_to_percent_used(self) -> None:
        # The live capture was all 1.0, where a wrong inversion is invisible,
        # so this is the assertion that actually pins the arithmetic.
        entries = quota.shape_statusline(self._payload(gemini_5h=0.4, gemini_weekly=0.0), NOW)
        self.assertEqual(60, entries[0]["fiveH"]["pct"])
        self.assertEqual(100, entries[0]["week"]["pct"])

    def test_the_worse_of_each_family_pair_wins(self) -> None:
        # Two model families report the same windows. The band answers "am I
        # about to run out", so the binding constraint is the honest number.
        entries = quota.shape_statusline(
            self._payload(gemini_5h=0.4, gemini_weekly=1.0, **{"3p_5h": 0.9, "3p_weekly": 0.0}),
            NOW,
        )
        self.assertEqual(60, entries[0]["fiveH"]["pct"], "gemini-5h is worse than 3p-5h")
        self.assertEqual(100, entries[0]["week"]["pct"], "3p-weekly is worse than gemini-weekly")

    def test_no_payload_field_beyond_the_windows_is_published(self) -> None:
        entries = quota.shape_statusline(self._payload(gemini_5h=0.5), NOW)
        serialized = json.dumps(entries)
        for leak in ("example.com", "secret/path", "Google AI Ultra", "idle"):
            self.assertNotIn(leak, serialized)
        self.assertEqual({"harness", "state", "asOf", "fiveH"}, set(entries[0]))

    def test_unknown_and_malformed_buckets_are_dropped(self) -> None:
        cases: list[tuple[str, dict[str, Any]]] = [
            ("no quota key", {}),
            ("quota not an object", {"quota": "nope"}),
            ("empty quota", {"quota": {}}),
            ("unknown suffix", {"quota": {"gemini-monthly": {"remaining_fraction": 0.5}}}),
            ("fraction missing", {"quota": {"gemini-5h": {}}}),
            ("fraction not a number", {"quota": {"gemini-5h": {"remaining_fraction": "half"}}}),
            ("fraction is a bool", {"quota": {"gemini-5h": {"remaining_fraction": True}}}),
            ("bucket not an object", {"quota": {"gemini-5h": 0.5}}),
        ]
        for label, payload in cases:
            with self.subTest(case=label):
                self.assertEqual([], quota.shape_statusline(payload, NOW))

    def test_out_of_range_fractions_clamp(self) -> None:
        entries = quota.shape_statusline(self._payload(gemini_5h=-3, gemini_weekly=42), NOW)
        self.assertEqual(100, entries[0]["fiveH"]["pct"])
        self.assertEqual(0, entries[0]["week"]["pct"])

    def test_a_receipt_is_stored_and_read_back(self) -> None:
        config = _config()
        state = _state(config)
        response = quota.receive_statusline(state, self._payload(gemini_5h=0.25), now=NOW)
        self.assertEqual({"ok": True, "usage": 1}, response)
        entries = quota.receipt_entries(config, state, NOW, 24)
        self.assertEqual(75, entries[0]["fiveH"]["pct"])
        # Copied out, so a caller cannot mutate the stored receipt.
        entries[0]["fiveH"]["pct"] = 1
        self.assertEqual(75, quota.receipt_entries(config, state, NOW, 24)[0]["fiveH"]["pct"])

    def test_a_stale_receipt_is_dropped_rather_than_shown(self) -> None:
        # Receipts only arrive while the harness runs, so a stored figure can
        # be arbitrarily old. Past the window its own quota windows have reset.
        config = _config()
        state = _state(config)
        quota.receive_statusline(state, self._payload(gemini_5h=0.5), now=NOW)
        self.assertEqual(1, len(quota.receipt_entries(config, state, NOW + 3600, 24)))
        self.assertEqual([], quota.receipt_entries(config, state, NOW + 48 * 3600, 24))

    def test_an_unusable_payload_still_stamps_the_arrival(self) -> None:
        # Storing an empty list matters: a harness that stops reporting quota
        # must go stale and drop out, not show its last figure forever.
        config = _config()
        state = _state(config)
        quota.receive_statusline(state, self._payload(gemini_5h=0.5), now=NOW)
        response = quota.receive_statusline(state, {"quota": {}}, now=NOW + 60)
        self.assertEqual({"ok": True, "usage": 0}, response)
        self.assertEqual([], quota.receipt_entries(config, state, NOW + 60, 24))

    def test_nothing_is_read_back_before_any_receipt(self) -> None:
        config = _config()
        self.assertEqual([], quota.receipt_entries(config, _state(config), NOW, 24))


class PushedReceiptOptOutTest(unittest.TestCase):
    """--no-usage means no quota is retained, pushed or fetched.

    SECURITY.md publishes that with the feature off nothing is fetched or
    retained. A pushed receipt is a second way in, so it needs the same gate.
    """

    @staticmethod
    def _payload() -> dict[str, Any]:
        # The bucket keys a live agy status line sends; anything else shapes to
        # nothing and would make the enabled case vacuous.
        return {
            "quota": {
                "gemini-5h": {"remaining_fraction": 0.42, "reset_time": "2026-08-04T14:16:36Z"},
                "gemini-weekly": {"remaining_fraction": 0.9},
            }
        }

    def test_a_receipt_is_stored_when_usage_is_enabled(self) -> None:
        config = _config(usage_fetch_enabled=True)
        state = _state(config)
        response = quota.receive_statusline(state, self._payload(), now=NOW, config=config)
        self.assertGreater(response["usage"], 0)
        self.assertTrue(state.usage_receipts["antigravity"]["entries"])

    def test_quota_is_dropped_before_storage_when_usage_is_disabled(self) -> None:
        config = _config(usage_fetch_enabled=False)
        state = _state(config)
        response = quota.receive_statusline(state, self._payload(), now=NOW, config=config)
        self.assertEqual(0, response["usage"])
        self.assertEqual([], state.usage_receipts["antigravity"]["entries"])
        # The arrival is still stamped, so the disabled path stays consistent
        # with the unusable-payload path rather than inventing a third state.
        self.assertEqual(NOW, state.usage_receipts["antigravity"]["ts"])
        self.assertEqual([], quota.receipt_entries(config, state, NOW, 24))

    def test_the_endpoint_still_reports_success_when_disabled(self) -> None:
        """A status-line command must never see an error from Compass."""
        config = _config(usage_fetch_enabled=False)
        state = _state(config)
        response = quota.receive_statusline(state, self._payload(), now=NOW, config=config)
        self.assertTrue(response["ok"])

    def test_without_a_config_the_behaviour_is_unchanged(self) -> None:
        # Callers outside a runtime keep working: no config means no gate.
        state = _state(_config())
        response = quota.receive_statusline(state, self._payload(), now=NOW)
        self.assertEqual({"ok": True, "usage": 1}, response)


class UsageEndpointTest(RuntimeTestCase):
    """POST /api/usage: the same guards as /api/notify, and no new exposure."""

    def _post(
        self, port: int, body: bytes, headers: dict[str, str] | None = None
    ) -> tuple[int, bytes]:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
        conn.request(
            "POST",
            "/api/usage",
            body=body,
            headers={"Content-Type": "application/json", **(headers or {})},
        )
        response = conn.getresponse()
        payload = response.read()
        status = response.status
        conn.close()
        return status, payload

    def test_a_receipt_reaches_the_band_through_the_endpoint(self) -> None:
        application = cli.build_application(*runtime(), clock=time.time)
        httpd = make_server(application=application)
        thread = threading.Thread(target=poll_fast(httpd), daemon=True)
        thread.start()
        try:
            body = json.dumps(
                {
                    "quota": {
                        "gemini-5h": {"remaining_fraction": 0.3},
                        "3p-5h": {"remaining_fraction": 0.8},
                    },
                    "email": "someone@example.com",
                }
            ).encode()
            status, response = self._post(httpd.server_port, body)
            self.assertEqual(200, status)
            self.assertEqual(b'{"ok":true,"usage":1}', response)
            entries = quota.receipt_entries(application.config, application.state, time.time(), 24)
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=2)

        # Worse of the pair: 1 - 0.3 = 70, not 1 - 0.8 = 20.
        self.assertEqual(70, entries[0]["fiveH"]["pct"])
        self.assertNotIn("example.com", json.dumps(entries))

    def test_the_endpoint_rejects_what_notify_rejects(self) -> None:
        application = cli.build_application(*runtime(), clock=time.time)
        httpd = make_server(application=application)
        thread = threading.Thread(target=poll_fast(httpd), daemon=True)
        thread.start()
        try:
            cap = application.config.usage_receipt_cap_bytes
            # Oversized: refused on the declared length, before any read.
            status, _ = self._post(httpd.server_port, b"x" * (cap + 1))
            self.assertEqual(413, status)
            # Cross-site: the same _local_ok() gate as every other route.
            status, _ = self._post(httpd.server_port, b"{}", {"Sec-Fetch-Site": "cross-site"})
            self.assertEqual(403, status)
            # Malformed and non-object bodies degrade rather than raise.
            for body in (b"{not json", b"[1,2,3]", b"null", b""):
                with self.subTest(body=body):
                    status, response = self._post(httpd.server_port, body)
                    self.assertEqual(200, status)
                    self.assertEqual(b'{"ok":true,"usage":0}', response)
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=2)

    def test_the_receipt_path_never_fetches(self) -> None:
        # The whole point of this path is that it needs no credential and makes
        # no request. --diagnose runs collect(), so this must hold there too.
        application = cli.build_application(*runtime(), clock=time.time)
        quota.receive_statusline(
            application.state,
            {"quota": {"gemini-5h": {"remaining_fraction": 0.5}}},
            now=time.time(),
        )
        with (
            mock.patch.object(quota, "request_fetch") as trigger,
            mock.patch.object(quota, "fetch_usage") as fetch,
        ):
            diagnostics.diagnose(application)
            application.collect(show_all=True)
        trigger.assert_not_called()
        fetch.assert_not_called()


class PublishedWindowLengthTest(RuntimeTestCase):
    """A window must publish its own length, not leave the page to infer one.

    The page's pace reading is `pct` against how much of the window has elapsed,
    and elapsed needs the length. Inferring it from the slot name is wrong for
    exactly one producer and silently so: Codex names no windows, only durations,
    and `collectors/codex.py` files anything under a day into `fiveH`. A plan
    whose primary window is 180 minutes would then be drawn against 300, so the
    tick would sit at 60% of the bar when the window was 100% gone. The length is
    therefore published per window, measured where the vendor states it and
    constant where the vendor states only a name.
    """

    def test_claude_publishes_the_length_its_field_names_imply(self) -> None:
        entries, note = quota._fetch_windows(_config(), TOKEN, NOW, _opener(_usage_body()))
        self.assertIsNone(note)
        (entry,) = entries
        self.assertEqual(5 * 3600, entry["fiveH"]["windowSec"])
        self.assertEqual(7 * 86400, entry["week"]["windowSec"])

    def test_codex_publishes_the_duration_the_vendor_stated(self) -> None:
        # The case a slot-name constant gets wrong. 180 minutes is a real
        # window under a day, so it files into `fiveH` and must still say 180.
        mapped = codex_collector._usage_window(NOW, {"used_percent": 34, "window_minutes": 180})
        self.assertIsNotNone(mapped)
        assert mapped is not None
        slot, window = mapped
        self.assertEqual("fiveH", slot)
        self.assertEqual(180 * 60, window["windowSec"])

    def test_a_window_with_no_stated_length_publishes_none(self) -> None:
        # Cursor meters a billing cycle and publishes its END only, and cycles
        # run 28 to 31 days. Guessing one would draw a tick that is wrong by up
        # to 10%, so the slot carries no length and the page withholds the tick.
        entry = quota._cursor_entry(
            NOW,
            {
                "planUsage": {"totalSpend": 1234, "limit": 5000},
                "billingCycleEnd": int((NOW + 10 * 86400) * 1000),
            },
        )
        self.assertIsNotNone(entry)
        assert entry is not None
        self.assertNotIn("windowSec", entry.get("month", {}))


class WindowSampleRingTest(RuntimeTestCase):
    """Recent pace, measured from the vendor's own successive readings.

    In memory only: no file, no endpoint, dropped with the process. Every value
    it holds is one `/api/data` already served, so it widens no boundary.

    Three rules earn their own tests because each one, got wrong, publishes a
    reassuring number. A reading whose stamp has not advanced is not a new
    reading, and counting it would divide a zero delta by a growing span and
    call the result calm. A reading whose percentage has DROPPED is a window
    that reset, and subtracting across the reset yields a negative pace. And
    one sample is not a measurement at all.
    """

    def _observe(self, state: Any, at: float, pct: int, *, config: Any = None) -> dict[str, Any]:
        entry: dict[str, Any] = {
            "harness": "claude",
            "state": "ok",
            "asOf": int(at),
            "fiveH": {"pct": pct, "windowSec": 5 * 3600},
        }
        quota.observe_windows(config or _config(), state, [entry])
        return entry

    def test_one_reading_yields_no_pace(self) -> None:
        state = build_runtime_state(_config(), started=NOW)
        entry = self._observe(state, NOW, 20)
        # Not a pace of zero. Zero reads as "not burning", which is the one
        # thing an unmeasured window must never say.
        self.assertNotIn("recent", entry["fiveH"])

    def test_two_readings_yield_the_pace_between_them(self) -> None:
        state = build_runtime_state(_config(), started=NOW)
        self._observe(state, NOW, 20)
        entry = self._observe(state, NOW + 600, 26)
        recent = entry["fiveH"]["recent"]
        # 6 points over 10 minutes.
        self.assertAlmostEqual(0.6, recent["pctPerMin"], places=4)
        self.assertEqual(2, recent["samples"])
        self.assertEqual(600, recent["spanSec"])

    def test_a_frozen_snapshot_adds_no_sample_and_reports_no_pace(self) -> None:
        # Codex's `asOf` is the snapshot's own epoch and can stand still for
        # hours while the page polls every five seconds. Counting those repeats
        # would publish a pace that falls toward zero the longer the vendor is
        # stale, which is exactly backwards.
        state = build_runtime_state(_config(), started=NOW)
        self._observe(state, NOW, 20)
        for _ in range(5):
            entry = self._observe(state, NOW, 20)
        self.assertNotIn("recent", entry["fiveH"])

    def test_a_regressed_stamp_adds_no_sample(self) -> None:
        # Codex picks its snapshot as the newest of eight rollout tails, so a
        # file with a newer mtime can displace the one that held the newest
        # snapshot and the stamp goes backwards.
        state = build_runtime_state(_config(), started=NOW)
        self._observe(state, NOW + 600, 26)
        entry = self._observe(state, NOW, 20)
        self.assertNotIn("recent", entry["fiveH"])

    def test_a_reset_clears_the_ring_rather_than_measuring_across_it(self) -> None:
        state = build_runtime_state(_config(), started=NOW)
        self._observe(state, NOW, 80)
        self._observe(state, NOW + 600, 90)
        # The window rolled: the level fell.
        entry = self._observe(state, NOW + 1200, 4)
        self.assertNotIn("recent", entry["fiveH"])
        # And the new window measures from the reset forward, never across it.
        entry = self._observe(state, NOW + 1800, 10)
        recent = entry["fiveH"]["recent"]
        self.assertAlmostEqual(0.6, recent["pctPerMin"], places=4)
        self.assertEqual(2, recent["samples"])

    def test_the_ring_is_bounded(self) -> None:
        config = _config(usage_samples_max=4)
        state = build_runtime_state(config, started=NOW)
        for step in range(12):
            entry = self._observe(state, NOW + step * 600, step, config=config)
        self.assertEqual(4, entry["fiveH"]["recent"]["samples"])

    def test_each_vendor_and_scope_keeps_its_own_ring(self) -> None:
        # One shared ring would let Antigravity, which can push a receipt with
        # no rate limit at all, evict the Claude samples the pace exists to read.
        state = build_runtime_state(_config(), started=NOW)
        for at, pct in ((NOW, 10), (NOW + 600, 20)):
            quota.observe_windows(
                _config(),
                state,
                [
                    {"harness": "claude", "asOf": int(at), "fiveH": {"pct": pct}},
                    {"harness": "codex", "asOf": int(at), "fiveH": {"pct": pct * 3}},
                    {"harness": "claude", "asOf": int(at), "week": {"pct": pct * 2}},
                ],
            )
        entries: list[dict[str, Any]] = [
            {"harness": "claude", "asOf": int(NOW + 1200), "fiveH": {"pct": 30}},
            {"harness": "codex", "asOf": int(NOW + 1200), "fiveH": {"pct": 90}},
        ]
        quota.observe_windows(_config(), state, entries)
        # claude fiveH ran 10 -> 30 over twenty minutes; codex 30 -> 90 over the same.
        self.assertAlmostEqual(1.0, entries[0]["fiveH"]["recent"]["pctPerMin"], places=4)
        self.assertAlmostEqual(3.0, entries[1]["fiveH"]["recent"]["pctPerMin"], places=4)

    def test_a_window_with_no_percentage_is_not_sampled(self) -> None:
        state = build_runtime_state(_config(), started=NOW)
        entry: dict[str, Any] = {"harness": "claude", "asOf": int(NOW), "state": "refused"}
        quota.observe_windows(_config(), state, [entry])
        self.assertEqual({"harness": "claude", "asOf": int(NOW), "state": "refused"}, entry)
