"""Quota acquisition: the outbound fetch, the pushed-in receipts, and the cache.

Two sources fill one cache, and collectors read it back without caring which
filled it.

**The fetch** is the whole of Compass's outbound network surface, and it is
bound by the "Usage quota reads" section of SECURITY.md: each request carries
the vendor's own OAuth token and nothing else, the token is never refreshed,
never written, never logged and never served, and at most one request per
vendor leaves every five minutes. A violation of any of those is a security
bug, not a defect. Diagnostics emitted here are fixed category words plus
exception type names for that reason — never a value read from a credential
source or a response.

Two vendors fetch: Claude and Cursor. Each gets its own credential reader,
endpoint and response parser, and its own pair of gates, so a vendor that is
slow or broken cannot delay or suppress the other's refresh. `FETCH_VENDORS`
is the whole list, and every endpoint in it is named in SECURITY.md.

**The receipts** are the opposite direction and involve no credential at all.
A harness that publishes its own quota to a user-configured command can have
that forwarded to `POST /api/usage`, and `receive_statusline` shapes what
arrives. Antigravity works this way. Nothing here reaches the network, so the
receipt path is outside the fetch contract above, but it inherits the rule
that only derived scalars are published: the shaping code builds a fresh
entry rather than passing a payload through, because these payloads carry an
account email that must never reach `/api/data`.
"""

from __future__ import annotations

import collections
import copy
import hashlib
import http.client
import json
import math
import ntpath
import operator
import posixpath
import subprocess
import threading
import time
import urllib.error
import urllib.request
from typing import TYPE_CHECKING, Any, Final

from . import https_transport, records, sessions
from . import io as runtime_io
from .config import primary_store
from .reach import build_reach_opener

if TYPE_CHECKING:
    from collections.abc import Callable
    from contextlib import AbstractContextManager

    from .config import RuntimeConfig
    from .state import RuntimeState

    # One vendor's credential read plus its outbound request, shaped into
    # entries: (config, now, opener, runner) -> (entries, problem category).
    VendorReader = Callable[
        [RuntimeConfig, float, Callable[..., Any], Callable[..., Any]],
        tuple[list[dict[str, Any]], str | None],
    ]

# The endpoints this module may call, spelled exactly as SECURITY.md names
# them. A new vendor's endpoint must be named there before it is added here.
USAGE_ENDPOINT = "https://api.anthropic.com/api/oauth/usage"
USAGE_BETA_VALUE = "oauth-2025-04-20"
# Cursor's own CLI calls this RPC for its `/usage` command, against the
# backend its config records as `serverConfigCache.backendUrl`. Reached with a
# plain bearer header: no cookie, and no browser-session impersonation.
CURSOR_USAGE_ENDPOINT = "https://api2.cursor.sh/aiserver.v1.DashboardService/GetCurrentPeriodUsage"
# Where Claude Code keeps its OAuth credentials: a Keychain generic password
# on macOS, a JSON file beside the projects store everywhere else.
KEYCHAIN_SERVICE = "Claude Code-credentials"
CREDENTIALS_FILENAME = ".credentials.json"
# Cursor CLI keeps its session token in the macOS Keychain and nowhere else we
# have verified. Where it lands on Linux and Windows is deliberately not
# guessed: a wrong path would read some other file and call it a credential,
# so off macOS the reader reports no credential and Cursor stays out of the
# band. NOTE for SECURITY.md: Cursor stores the identical value under
# `cursor-refresh-token`, so this token can also mint sessions. It is sent as
# a bearer token and never exchanged.
CURSOR_KEYCHAIN_SERVICE = "cursor-access-token"
# The first Keychain read can raise a user-facing permission prompt, so the
# subprocess must be allowed to sit through a human answering it. On timeout
# the read fails as "unavailable" and the poll floor schedules the retry.
KEYCHAIN_TIMEOUT_SEC = 120.0
# How long each named window slot lasts, for the vendors that publish a name
# rather than a duration. Claude's response names `five_hour` and `seven_day`
# and carries no length field; Antigravity's status line names `-5h` and
# `-weekly`. Codex is deliberately absent from this table: it publishes
# `window_minutes` outright, so its collector reads the real duration and a
# constant here would override a measurement with an assumption.
SLOT_WINDOW_SEC: Final[dict[str, int]] = {"fiveH": 5 * 3600, "week": 7 * 86400}

# Cursor reports money in integer cents. Naming the divisor keeps the unit
# visible: reading these as dollars overstates every figure a hundredfold,
# which a small balance hides rather than reveals.
CENTS_PER_UNIT = 100
# Anthropic's `limits[]` carries one element per metered limit, and the
# per-model sub-limits are the elements whose `kind` is this word. `kind` is the
# discriminator and `group` cannot be: the recorded response collapsed three
# kinds onto two groups, so `group` cannot tell a whole-plan weekly limit from a
# per-model one, and those are exactly the two that have to be labelled apart.
SCOPED_LIMIT_KIND = "weekly_scoped"
# A model's display name is vendor text on its way to the page, so it is bounded
# here as well as escaped there. Forty characters holds any product name the
# endpoint has business sending and refuses a paragraph.
MODEL_LABEL_CAP_CHARS = 40
# How much of a name is read before the label is cut out of it. The published
# label stays at the cap above; this is the bound on the text that cap is applied
# *to*, and the two have to differ because a name has to be read past the cap to
# be cut anywhere but the end. Four times the cap is generous for a product name
# and still refuses a paragraph, and it bounds the digest's input as well.
MODEL_NAME_CAP_CHARS = 160
# Hex characters of the tag that separates two names the cap alone cannot. Eight
# is 32 bits: with the eight rows this field publishes at most, two distinct
# names landing on one tag is a one-in-a-hundred-million event, against a plain
# truncation that collides whenever two names share their first forty characters.
MODEL_LABEL_DIGEST_CHARS = 8
# The furthest ahead a reset stamp is read at all, a century past the epoch.
# `datetime.fromtimestamp` raises outside the platform's `time_t` and a JSON
# number carries no such bound, so an absurd stamp is refused here rather than
# left to raise inside the formatter. Nothing resets in 2070: a stamp past this
# is a broken field, and refusing it costs a countdown nobody could have used.
MAX_RESET_EPOCH = 3_155_760_000.0
# How many per-model rows may be published. The recorded account carried exactly
# one, so this is a design-for-N bound rather than a measured one: a plan that
# metered every model family Anthropic offers still fits well inside it, and a
# list that ran away cannot fill the band.
MAX_SCOPED_LIMITS = 8


def credentials_path(config: RuntimeConfig) -> str:
    """The harness's credential file, derived from the resolved projects store.

    Deriving from `claude.projects` keeps one source of truth for where the
    Claude home is: a `CLAUDE_CONFIG_DIR` override moves both together.
    """
    windows = config.platform_name == "win32"
    dirname = ntpath.dirname if windows else posixpath.dirname
    join = ntpath.join if windows else posixpath.join
    return join(dirname(primary_store(config, "claude.projects")), CREDENTIALS_FILENAME)


def _keychain_secret(
    runner: Callable[..., Any],
    service: str,
) -> tuple[str | None, str | None]:
    """(secret, problem category) from one macOS Keychain generic password.

    Shared by every vendor that keeps its credential there. The service name
    is the only thing that varies, and the secret is returned to the caller
    rather than logged: problem categories are fixed words plus exception type
    names precisely so that nothing read from the Keychain reaches diagnostics.
    """
    try:
        result = runner(
            ["/usr/bin/security", "find-generic-password", "-s", service, "-w"],
            capture_output=True,
            text=True,
            timeout=KEYCHAIN_TIMEOUT_SEC,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return None, f"keychain {type(exc).__name__}"
    if result.returncode != 0 or not str(result.stdout).strip():
        return None, "keychain item unavailable"
    return str(result.stdout), None


def _bearer_value(token: str) -> str | None:
    """The token as it may appear after `Bearer `, or None when it cannot.

    Surrounding whitespace is how a credential store ends a line, so it is
    stripped. Anything else outside visible ASCII has no place in a bearer token,
    and a CR or LF would end the header line and start another, so such a token is
    refused rather than repaired: the caller reports a category and sends nothing.
    """
    value = token.strip()
    if not value or any(not ("!" <= char <= "~") for char in value):
        return None
    return value


def _read_token(
    config: RuntimeConfig,
    runner: Callable[..., Any],
) -> tuple[str | None, float | None, str | None]:
    """(access token, expiry epoch seconds, problem category).

    Problem categories are fixed words plus exception type names because they
    reach diagnostics; no value read from the Keychain or the file ever does.
    """
    if config.platform_name == "darwin":
        secret, problem = _keychain_secret(runner, KEYCHAIN_SERVICE)
        if problem:
            return None, None, problem
        raw = secret or ""
    else:
        try:
            raw = runtime_io.read_prefix_bytes(
                credentials_path(config),
                max_bytes=config.usage_credentials_cap_bytes,
            ).decode("utf-8", "replace")
        except OSError:
            return None, None, "no credential file"
    try:
        payload = json.loads(raw)
    except ValueError:
        return None, None, "malformed credentials"
    oauth = records.as_dict(records.as_dict(payload).get("claudeAiOauth"))
    token = oauth.get("accessToken")
    if not isinstance(token, str) or not token.strip():
        return None, None, "no oauth token"
    token = _bearer_value(token)
    if token is None:
        return None, None, "malformed oauth token"
    expires = oauth.get("expiresAt")
    expiry = (
        expires / 1000.0
        if isinstance(expires, (int, float)) and not isinstance(expires, bool) and expires > 0
        else None
    )
    return token, expiry, None


def _finite(raw: Any) -> float | None:
    """A real, finite number, or nothing. **Every numeric read starts here.**

    JSON is not the constraint it is usually assumed to be. `json.loads` accepts
    bare `NaN`, `Infinity` and `-Infinity` by default, and an integer literal in
    JSON has no width at all, so a vendor response or a pushed receipt can put
    any of those into any field this module reads. `round()` and `int()` raise on
    the first two, `float()` raises on an integer too large to hold, and
    `datetime.fromtimestamp` raises on an infinity — so a parser that reached one
    would raise instead of returning a category, and a raising parser is what
    turns the five-minute floor into an unbounded fetch loop (see `fetch_usage`,
    which now survives one, and this, which stops it happening).

    Booleans are refused for the older reason: `True` is an `int` in Python, and
    a bar drawn at 1 percent is not what a vendor sending `true` meant.
    """
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return None
    try:
        value = float(raw)
    except OverflowError:
        return None
    return value if math.isfinite(value) else None


def _epoch(raw: Any) -> float | None:
    """A reset stamp as epoch seconds: the endpoint has sent both shapes.

    The string branch defers to `records.iso_epoch`, so an offset-less stamp is
    read as UTC here exactly as it is everywhere else. It matters most on this
    path: a `resets_at` misread by the server's own UTC offset moves every reset
    countdown and the budget-versus-clock reading described in
    [Q-12](docs/design-usage-quota.md#q-12).
    The live capture records all four `resets_at` fields arriving with an explicit
    `+00:00`, so the naive branch is a guard rather than the normal case.

    Both branches end at the same plausibility bound, because both feed
    `sessions.reset_fields` and it formats through `datetime.fromtimestamp`,
    which raises rather than declines on a stamp outside `time_t`.
    """
    value = _finite(raw)
    if value is None:
        value = records.iso_epoch(raw)
    if value is None or not 0 < value <= MAX_RESET_EPOCH:
        return None
    return value


def _epoch_millis(raw: Any) -> float | None:
    """A stamp as epoch seconds, given epoch milliseconds.

    Cursor sends these as decimal *strings*, which is how protobuf's JSON
    mapping encodes 64-bit integers, so `_epoch` cannot read them: it would try
    ISO parsing and fail. Rejected rather than trusted blindly, because a value
    already in seconds would otherwise be divided into 1970.
    """
    if isinstance(raw, bool):
        return None
    if isinstance(raw, str):
        try:
            raw = int(raw)
        except ValueError:
            return None
    value = _finite(raw)
    if value is None or not 0 < value / 1000.0 <= MAX_RESET_EPOCH:
        return None
    return value / 1000.0


def _percent(raw: Any) -> int | None:
    """A number already on a 0-to-100 percent scale, as an integer, or nothing.

    Shared between the named windows and the per-model sub-limits, and the
    sharing is a decision rather than a convenience. The two arrive under
    different keys and in different types — `five_hour.utilization` is a float,
    `limits[].percent` an int — so this is not one field with two spellings and
    it does not read either of them. What it holds is the one step they do have
    in common: how a number on that scale becomes a bar. Keeping the clamp and
    the rounding in one place is what stops the two from disagreeing about
    whether 63.5 is 63 or 64, which the page would show as two bars at different
    heights for the same figure.

    Both sides are measured on that scale (see
    [Q-2](docs/design-usage-quota.md#q-2)), so
    the round is a round and never a conversion. A fraction read as a percent
    would publish 1 for a window at 90, and a band reading almost-empty while
    the allowance is nearly gone is the failure this module exists to avoid.

    The clamp does not make the round safe on its own — `round()` raises on a
    non-finite float and never reaches it — which is why the number is taken
    through `_finite` first.
    """
    value = _finite(raw)
    if value is None:
        return None
    return max(0, min(100, round(value)))


def _shape_window(now: float, raw: Any, window_sec: int | None = None) -> dict[str, Any] | None:
    """One usage window mapped onto the payload contract, or nothing.

    `window_sec` is the window's own length, and it is published because the
    page cannot derive it. The reading it serves is `pct` against how much of
    the window has elapsed, and elapsed is `windowSec - (resetAt - now)`; with
    no length there is no elapsed and the page withholds that half rather than
    assuming one. A vendor that states only a name gets the constant its name
    implies, a vendor that states a duration gets the duration, and a vendor
    that states neither gets nothing.
    """
    win = records.as_dict(raw)
    pct = _percent(win.get("utilization"))
    if pct is None:
        return None
    shaped: dict[str, Any] = {"pct": pct}
    if window_sec is not None:
        shaped["windowSec"] = window_sec
    resets = _epoch(win.get("resets_at"))
    if resets:
        shaped.update(sessions.reset_fields(now, resets))
    return shaped


def _elide(text: str, limit: int) -> str:
    """`text` bounded to `limit` characters, cut in the middle rather than at the end.

    The end of a model name is where it says which model it is. The vendor's
    names run family, then version, then qualifier — the shared part first and
    the distinguishing part last — so a plain truncation keeps exactly the half
    that two long names have in common and throws away the half that tells them
    apart. Eliding the middle spends the same bound on both ends, which is why
    the cap can stay where it is: the fix for two names colliding at forty
    characters is not a bigger forty.
    """
    if len(text) <= limit:
        return text
    keep = limit - 1
    head = (keep + 1) // 2
    tail = keep - head
    return text[:head] + "…" + (text[-tail:] if tail else "")


def _label_digest(name: str) -> str:
    """A short stable tag for one model name, used only to tell two rows apart.

    Stable in the name and in nothing else. The obvious discriminator — the
    element's position in `limits[]` — would renumber the rows whenever the
    vendor reordered the list or metered one more model, so a row's identity
    would shift under the reader between two polls, which is the failure this
    whole field is being held to. A digest of the name moves only when the name
    does. It is not a security boundary and is not treated as one: it separates
    two labels, and nothing downstream reads it as anything else.
    """
    return hashlib.blake2s(
        name.encode("utf-8"), digest_size=MODEL_LABEL_DIGEST_CHARS // 2
    ).hexdigest()


def _distinct_labels(rows: list[tuple[str, dict[str, Any]]]) -> list[dict[str, Any]]:
    """Rows whose labels tell their models apart, from rows that may not.

    A per-model row's label is its whole identity. `scope.model.id` arrived null
    in the capture, so there is no other field to hang identity on, and the page
    renders the label twice: once in a column ten characters wide, and once in
    the hover, which is the only place the whole of it is legible. Two models
    whose names agree to the cap therefore render as two stacked bars, same
    label, different percentages, and the hover repeats the same string — a
    reader cannot tell which figure belongs to which model, and there is nothing
    further to open. Two limits presented as one is the failure mode this module
    is written against, so the labels are made distinct before they are
    published, in two steps and for two different reasons:

    **Same name, twice.** The vendor sent two elements the vendor itself gives no
    way to tell apart — the same name as far as `MODEL_NAME_CAP_CHARS` reads it,
    which is the outer edge of what this module can distinguish at all. They
    collapse to one row carrying the worse percentage,
    the same resolution `shape_statusline` uses for two families reporting one
    window: the band answers "am I about to run out", so the binding constraint
    is the honest figure. Publishing both would put two contradictory numbers
    under one name, which reads as a rendering bug rather than as two limits.

    **Different names, one label.** The elision has already spent the bound on
    both ends, so names that reach here differ somewhere in the middle that no
    forty-character window can show. They are relabelled with a shorter elision
    plus `_label_digest`, which keeps the label inside the cap and makes it
    injective in the name: the reader still cannot read the difference, but the
    rows no longer claim to be the same model, and the hover text differs, which
    is what turns "these are one thing" back into "these are two".
    """
    groups: dict[str, list[tuple[str, dict[str, Any]]]] = {}
    for name, row in rows:
        groups.setdefault(row["label"], []).append((name, row))
    published: list[dict[str, Any]] = []
    for group in groups.values():
        worst: dict[str, dict[str, Any]] = {}
        for name, row in group:
            standing = worst.get(name)
            if standing is None or row["pct"] > standing["pct"]:
                worst[name] = row
        if len(worst) == 1:
            published.extend(worst.values())
            continue
        for name, row in worst.items():
            head = _elide(name, MODEL_LABEL_CAP_CHARS - 1 - MODEL_LABEL_DIGEST_CHARS)
            row["label"] = f"{head}…{_label_digest(name)}"
            published.append(row)
    return published


def _scoped_limit(now: float, raw: Any) -> tuple[str, dict[str, Any]] | None:
    """One `limits[]` element as (model name, published row), or nothing.

    The name is returned beside the row because the row's label is a bounded cut
    of it and the cut is not injective: `_distinct_labels` needs the whole name
    to tell two rows apart, and it is deliberately not carried as a field on the
    row, because a field on the row is a field on the wire.

    Elements of any other `kind` are not rows: see `_scoped_limits` for why the
    list is only partly consumed.
    """
    element = records.as_dict(raw)
    if element.get("kind") != SCOPED_LIMIT_KIND:
        return None
    model = records.as_dict(records.as_dict(element.get("scope")).get("model"))
    # `scope.model.id` arrived null in the capture, so the display name is the
    # only label there is, and it is untrusted vendor text: bounded here, escaped
    # by the page. Two ways of having no label, both refused. An element with
    # nothing usable is dropped rather than published under a placeholder,
    # because an unnamed per-model bar sitting beneath the weekly bar reads as a
    # second weekly figure disagreeing with the first. And a name that is not a
    # string is refused before bounding rather than coerced: `safe_text` would
    # happily publish the repr of whatever arrived, and the repr of a number or
    # an object is not the model's name — it is a wrong label on a real
    # percentage. The number beside it is refused just as strictly, in `_percent`.
    raw_label = model.get("display_name")
    name = (
        records.safe_text(raw_label, MODEL_NAME_CAP_CHARS).strip()
        if isinstance(raw_label, str)
        else ""
    )
    pct = _percent(element.get("percent"))
    if not name or pct is None:
        return None
    row: dict[str, Any] = {"label": _elide(name, MODEL_LABEL_CAP_CHARS), "pct": pct}
    # The scoped element in the capture carried no `resets_at` at all, so a
    # per-model row is a percentage that may have no countdown behind it. Missing
    # stays missing rather than defaulting to anything, and `reset_fields` is the
    # only writer of the pair, so the words and the instant are either both here
    # or both absent.
    resets = _epoch(element.get("resets_at"))
    if resets:
        row.update(sessions.reset_fields(now, resets))
    return name, row


def _scoped_limits(now: float, payload: dict[str, Any]) -> list[dict[str, Any]]:
    """The response's per-model sub-limits, shaped for the `models` field.

    **The published shape.** An entry's existing quota fields are named window
    slots — `fiveH`, `week`, `month` — whose meaning the page knows in advance.
    Per-model limits are not that: they are a list of unknown length whose rows
    are labelled by the vendor, so no slot can hold them and minting `weekOpus`
    and `weekSonnet` beside the others would put this repository in the business
    of tracking Anthropic's model line-up in a frontend table. The field is
    therefore a list of its own:

        models: [{label, pct, reset, resetAt}, ...]

    `label` is the vendor's display name, bounded to `MODEL_LABEL_CAP_CHARS` and
    guaranteed to differ from every other label in the list — see
    `_distinct_labels` for why that guarantee is the point rather than a nicety.
    `pct` is an integer percent on the same scale as every other bar on the
    band. `reset` and `resetAt` come as a pair from `sessions.reset_fields` and
    are present only when the vendor sent a stamp. The list is absent rather
    than empty when there is nothing to say, exactly like the window slots, and
    it is capped at `MAX_SCOPED_LIMITS` rows.

    Rows are ordered by label, which is the one field on a row that does not
    tick. Ordering on `pct` would move rows under the reader between polls, and
    the vendor's own order is nowhere documented to be stable, so inheriting it
    would make the order a coin flip that only shows up as flicker. The sort
    runs after the labels are made distinct, since that is the step that decides
    what a label finally says.

    **Only `weekly_scoped` elements are read, on purpose.** The list also carries
    a `session` element and a `weekly_all` element, and those two are the same
    figures the top-level `five_hour` and `seven_day` objects already publish.
    Those stay the canonical source for the two named windows, so a list that is
    parsed and then only partly consumed is the intended outcome here rather than
    an oversight.

    **`is_active` and `severity` are deliberately not read.** Both are in the
    capture and neither has established semantics. `is_active` **moves**: the two
    recorded readings a day apart disagree about which element carries it, so it
    describes something that varies rather than the kind of limit, and a renderer
    keyed on it would call the 5h window the live constraint one day and the
    weekly one the next with nothing to say which was right. `severity` is a
    vendor-computed enum
    of which only `normal` has ever been observed. Publishing a field the page
    cannot honestly render is how that guess would get made downstream, so they
    stay out of the payload until a measurement says what they mean.
    """
    rows: list[tuple[str, dict[str, Any]]] = []
    for raw in records.as_list(payload.get("limits")):
        shaped = _scoped_limit(now, raw)
        if shaped is None:
            continue
        rows.append(shaped)
    # Bound by severity, not by arrival. Which rows survive an over-long list is
    # arbitrary as to *identity* and emphatically not as to *severity*: taking the
    # first eight as they arrived published eight rows at 3% and dropped a row at
    # 99%, because the vendor happened to send it last. That is the same rule
    # `_distinct_labels` applies to a same-name collision one function up, and for
    # the same reason — this band answers "am I about to run out", so the binding
    # constraint is the row that has to survive. Deduplicate first, so a name that
    # collides cannot occupy two of the eight places.
    kept = sorted(_distinct_labels(rows), key=operator.itemgetter("pct"), reverse=True)
    return sorted(kept[:MAX_SCOPED_LIMITS], key=operator.itemgetter("label"))


def _unreadable_entry(now: float, harness: str, state: str) -> dict[str, Any]:
    """An entry that carries no figures, and the reason it carries none.

    Two reasons reach this, and they are not the same fact. `lapsed` is a stamp
    read out of local storage with no request made; `refused` is a request the
    vendor answered 401/403. One shared `expired` published them as one, so the
    a reader could only advise one remedy for both, and that advice was wrong
    for the commoner case; design-usage-quota.md records the distinction.
    """
    return {"harness": harness, "state": state, "asOf": int(now)}


# One resolver slot per endpoint, not one for the module: the two vendors fetch
# on threads of their own at the same moment, and a shared slot would fail
# whichever asked second as busy.
_DNS_SLOTS: dict[str, threading.BoundedSemaphore] = {}
_DNS_SLOTS_LOCK = threading.Lock()


def _open_endpoint(
    request: urllib.request.Request,
    timeout: float,
) -> AbstractContextManager[https_transport.BoundedResponse]:
    """The production opener: a listed endpoint, over HTTPS, inside one deadline.

    `urllib.request.urlopen` was the default here, and each of its defaults was a
    way for the credential to leave by another route: it followed redirects
    (re-sending the authorization header to wherever a 307 pointed), it read
    `HTTPS_PROXY` and on macOS the system proxy settings, and its timeout bound
    each socket read rather than the exchange, so a response trickling a byte at
    a time held the vendor in flight indefinitely and no later fetch could start.
    The URL is checked against the endpoint list at call time, so a request for
    anywhere else is refused before anything is resolved.
    """
    if request.full_url not in (USAGE_ENDPOINT, CURSOR_USAGE_ENDPOINT):
        raise ValueError("unlisted usage endpoint")
    with _DNS_SLOTS_LOCK:
        slot = _DNS_SLOTS.setdefault(request.full_url, threading.BoundedSemaphore(1))
    return https_transport.open_bounded(
        build_reach_opener(), request, timeout=timeout, dns_slot=slot
    )


def _fetch_windows(
    config: RuntimeConfig,
    token: str,
    now: float,
    opener: Callable[..., Any],
) -> tuple[list[dict[str, Any]], str | None]:
    """The one outbound request, shaped into usage entries.

    The request is a GET with no body and exactly two headers of ours: the
    authorization carrying the token, and the beta header the endpoint
    requires. Anything more is a contract violation.
    """
    request = urllib.request.Request(
        USAGE_ENDPOINT,
        headers={"Authorization": f"Bearer {token}", "anthropic-beta": USAGE_BETA_VALUE},
    )
    try:
        with opener(request, timeout=config.usage_fetch_timeout_sec) as response:
            body = response.read(config.usage_response_cap_bytes)
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            # Refused, and that is the whole of what a 401 here supports: the
            # endpoint does not say whether the token went stale or the account
            # is not served, so the entry claims neither. Never a refresh —
            # that could race the harness for its own session.
            return [_unreadable_entry(now, "claude", "refused")], None
        return [], f"HTTP {exc.code}"
    except (urllib.error.URLError, OSError, ValueError, http.client.HTTPException) as exc:
        return [], type(exc).__name__
    try:
        payload = records.as_dict(json.loads(body))
    except ValueError:
        return [], "malformed response"
    entry: dict[str, Any] = {"harness": "claude", "state": "ok", "asOf": int(now)}
    for key, field_name in (("fiveH", "five_hour"), ("week", "seven_day")):
        shaped = _shape_window(now, payload.get(field_name), SLOT_WINDOW_SEC.get(key))
        if shaped:
            entry[key] = shaped
    if "fiveH" not in entry and "week" not in entry:
        # A per-model row cannot rescue this. Every one of them is a sub-limit
        # *of* the weekly window, so a response that lost `seven_day` and kept
        # its scoped children is one this parser no longer understands, and the
        # diagnostic category is worth more than a row of children with no
        # parent figure to be a fraction of.
        return [], "response carried no windows"
    scoped = _scoped_limits(now, payload)
    if scoped:
        entry["models"] = scoped
    return [entry], None


def _claude_entries(
    config: RuntimeConfig,
    now: float,
    opener: Callable[..., Any],
    runner: Callable[..., Any],
) -> tuple[list[dict[str, Any]], str | None]:
    token, expiry, problem = _read_token(config, runner)
    if problem:
        # No token is neither `lapsed` nor `refused`. A denied Keychain prompt
        # or a missing file means Claude stays absent from the band entirely,
        # because both of those entries say something about a credential that
        # was read, and here none was.
        return [], problem
    if expiry is not None and expiry <= now:
        # A stamp, not a verdict. Nothing was asked and nothing refused: Claude
        # Code rewrites the stored credential only while it runs, so a session
        # already open holds a live token in memory and keeps working. A lapsed
        # stamp beside healthy sessions is therefore the expected pairing for
        # anyone who has not started the harness yet today, which is why this
        # entry must not reach the page as a refusal.
        return [_unreadable_entry(now, "claude", "lapsed")], None
    return _fetch_windows(config, token or "", now, opener)


def _cents(amount: Any) -> int | None:
    """A non-negative integer cent amount, or nothing."""
    value = _finite(amount)
    if value is None or value < 0:
        return None
    return int(value)


def _money(cents: int) -> str:
    return f"${cents / CENTS_PER_UNIT:.2f}"


def _cursor_entry(now: float, payload: dict[str, Any]) -> dict[str, Any] | None:
    """Cursor's billing-period usage as one entry, or nothing.

    The percentage is computed from spend against the included limit rather
    than taken from the payload's own `totalPercentUsed`. That field's
    denominator is not the included allowance: on a $20 plan with 18 cents
    spent it reads 0.0521739, which is neither 0.9 (percent) nor 0.009
    (fraction). Spend over limit reproduces Cursor's own `displayMessage`
    ("You've used 1% of your included usage"), so it is the honest figure.

    Both amounts are integer cents. `used` carries the money as well, because
    a lone percentage near zero hides whether the plan is nearly untouched or
    the allowance is tiny.
    """
    plan = records.as_dict(payload.get("planUsage"))
    spend = _cents(plan.get("totalSpend"))
    if spend is None:
        return None
    entry: dict[str, Any] = {"harness": "cursor", "state": "ok", "asOf": int(now)}
    limit = _cents(plan.get("limit"))
    if limit:
        window: dict[str, Any] = {"pct": max(0, min(100, round(spend * 100 / limit)))}
        resets = _epoch_millis(payload.get("billingCycleEnd"))
        if resets:
            window.update(sessions.reset_fields(now, resets))
        entry["month"] = window
        entry["used"] = f"{_money(spend)} of {_money(limit)}"
    else:
        # An unlimited or limit-less plan spends without a denominator, so
        # there is nothing for a bar to be a fraction of. Same shape as
        # Copilot: the money, and no gauge pretending to be one.
        entry["used"] = _money(spend)
    return entry


def _cursor_token(
    config: RuntimeConfig,
    runner: Callable[..., Any],
) -> tuple[str | None, str | None]:
    """(session token, problem category) for Cursor.

    Only macOS is supported, because that is the only place the token's
    location has been verified. Elsewhere this reports no credential source,
    which keeps Cursor out of the band instead of advising a sign-in that would
    not help.
    """
    if config.platform_name != "darwin":
        return None, "no credential source on this platform"
    return _keychain_secret(runner, CURSOR_KEYCHAIN_SERVICE)


def _cursor_entries(
    config: RuntimeConfig,
    now: float,
    opener: Callable[..., Any],
    runner: Callable[..., Any],
) -> tuple[list[dict[str, Any]], str | None]:
    """Cursor's quota: one credential read and one outbound POST."""
    token, problem = _cursor_token(config, runner)
    if problem:
        return [], problem
    bearer = _bearer_value(token or "")
    if bearer is None:
        return [], "malformed token"
    request = urllib.request.Request(
        CURSOR_USAGE_ENDPOINT,
        data=b"{}",
        headers={
            "Authorization": f"Bearer {bearer}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with opener(request, timeout=config.usage_fetch_timeout_sec) as response:
            body = response.read(config.usage_response_cap_bytes)
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            # Cursor answers a stale token with 401 and `actionRequired:
            # "login"`, so here the sign-in remedy is measured rather than
            # assumed. Cursor is the only harness for which that remedy may be
            # claimed. There is no local expiry check on this path, so
            # `refused` is the only unreadable state Cursor has.
            return [_unreadable_entry(now, "cursor", "refused")], None
        return [], f"HTTP {exc.code}"
    except (urllib.error.URLError, OSError, ValueError, http.client.HTTPException) as exc:
        return [], type(exc).__name__
    return _cursor_parse(now, body)


def _cursor_parse(now: float, body: bytes) -> tuple[list[dict[str, Any]], str | None]:
    """One response body as entries, or a category naming why it was not."""
    try:
        payload = records.as_dict(json.loads(body))
    except ValueError:
        return [], "malformed response"
    entry = _cursor_entry(now, payload)
    if entry is None:
        return [], "response carried no plan usage"
    return [entry], None


# Every vendor the fetcher knows, paired with the reader that produces its
# entries. The gates in `request_fetch` are applied per vendor, so one slow or
# broken vendor cannot delay or suppress another's refresh.
FETCH_VENDORS: tuple[tuple[str, VendorReader], ...] = (
    ("claude", _claude_entries),
    ("cursor", _cursor_entries),
)


def fetch_usage(
    config: RuntimeConfig,
    state: RuntimeState,
    vendor: str,
    reader: VendorReader,
    *,
    clock: Callable[[], float] = time.time,
    opener: Callable[..., Any] = _open_endpoint,
    runner: Callable[..., Any] = subprocess.run,
    diagnostic_sink: Callable[[str], object] = print,
) -> None:
    """One vendor's fetch, synchronous, ending in a cache write.

    A failure caches an empty entry list on purpose: the write stamps the
    attempt, and the poll floor reads that stamp, so a broken endpoint or a
    missing credential is retried on the same five-minute cadence as success,
    never in a storm.

    **A reader that raises is a failure like any other, and that is the whole
    reason for the catch.** Without it the cache write never runs, so the floor
    never arms, so the next `/api/data` request starts another fetch — one
    outbound request per page refresh instead of one per five minutes, against a
    vendor endpoint, carrying a credential. The module header calls that class of
    thing a security bug rather than a defect, and it does not depend on which
    line raised: any reader, any exception, one cadence. So the catch is
    deliberately blind, and the diagnostic stays inside the fixed vocabulary the
    rest of the module uses — a category word and an exception type name, never a
    message, because an exception raised while parsing a response can carry the
    response into its own text.

    The stamp is written before the note is reported, so a diagnostic sink that
    fails cannot cost the floor either.
    """
    now = clock()
    try:
        entries, note = reader(config, now, opener, runner)
    except Exception as exc:  # noqa: BLE001 — a raising reader must still arm the floor
        entries, note = [], f"reader {type(exc).__name__}"
    with state.usage_fetch_lock:
        state.usage_fetch_cache[vendor] = {"ts": clock(), "entries": entries}
    if note:
        runtime_io.diag(f"[{vendor}] usage fetch: {note}", diagnostic_sink)


def _spawn_thread(run: Callable[[], None]) -> None:
    threading.Thread(target=run, daemon=True).start()


def request_fetch(
    config: RuntimeConfig,
    state: RuntimeState,
    *,
    clock: Callable[[], float] = time.time,
    opener: Callable[..., Any] = _open_endpoint,
    runner: Callable[..., Any] = subprocess.run,
    diagnostic_sink: Callable[[str], object] = print,
    spawn: Callable[[Callable[[], None]], None] = _spawn_thread,
) -> bool:
    """Maybe start a background fetch per vendor; never block the caller.

    This is the only entry point the serving path calls, and it holds every
    gate of the polling posture: nothing with the feature off, nothing while
    a fetch is already in flight, and nothing inside the five-minute floor of
    the last attempt. It is invoked only from `/api/data` requests that carry
    the page's consent, which is what makes "no polling while no dashboard
    page is connected" structural rather than scheduled.

    The gates are per vendor, so Cursor still refreshes while a Claude fetch
    sits in flight, and a vendor whose endpoint is down cannot hold the others
    off. Returns whether *any* vendor started, which is all the caller uses.
    """
    if not config.usage_fetch_enabled:
        return False
    now = clock()
    started = False
    for vendor, reader in FETCH_VENDORS:
        with state.usage_fetch_lock:
            if vendor in state.usage_fetch_inflight:
                continue
            cached = state.usage_fetch_cache.get(vendor)
            if cached and now - cached["ts"] < config.usage_poll_floor_sec:
                continue
            state.usage_fetch_inflight.add(vendor)

        def run(vendor: str = vendor, reader: VendorReader = reader) -> None:
            # Bound as defaults, not closed over: every thread would otherwise
            # see the loop's final vendor and one cache key would take them all.
            try:
                fetch_usage(
                    config,
                    state,
                    vendor,
                    reader,
                    clock=clock,
                    opener=opener,
                    runner=runner,
                    diagnostic_sink=diagnostic_sink,
                )
            finally:
                with state.usage_fetch_lock:
                    state.usage_fetch_inflight.discard(vendor)

        spawn(run)
        started = True
    return started


# The window slots a pace can be measured for. `month` is absent because the one
# producer that publishes it, Cursor, meters money over a billing cycle whose
# start it never sends, so there is no elapsed fraction to read a pace against.
PACE_SLOTS: Final[tuple[str, ...]] = ("fiveH", "week")


def _sample_key(harness: str, slot: str) -> str:
    return f"{harness}:{slot}"


def _record_sample(
    config: RuntimeConfig,
    state: RuntimeState,
    key: str,
    at: float,
    pct: int,
    window_start: float | None = None,
) -> tuple[tuple[float, int], ...]:
    """This window's kept readings after admitting `(at, pct)`, if it is new.

    Three refusals, and each one exists because admitting it would publish a
    reassuring number rather than no number:

    A stamp that has not advanced is not a new reading. Codex's `asOf` is the
    epoch of the newest snapshot it found on disk, so it stands still between
    that harness's turns while the page polls every few seconds; counting those
    repeats divides an unchanged level by a growing span and calls the result
    calm. The same stamp can also regress, because the snapshot is chosen as the
    newest of a bounded set of rollout tails and a file with a newer mtime can
    displace the one that held it.

    A level that has FALLEN is a window that reset. Subtracting across a reset
    gives a negative pace, and clamping one would report zero, so the ring starts
    again from the reset rather than measuring through it.

    A falling level is not the only sign of a reset, though, and it is the weaker
    one: a window that rolls while spend continues can come back at or above
    where it was, and the pace would then be measured straight through the
    boundary. `window_start` is the stronger test, derived from the two fields
    the entry already carries — `resetAt - windowSec` — so samples older than
    the current window are dropped whatever the levels did. It is optional
    because a window that publishes no length cannot supply one, and there the
    falling-level test is all there is.
    """
    with state.usage_fetch_lock:
        ring = state.usage_samples.get(key)
        if ring is None:
            ring = collections.deque(maxlen=max(2, config.usage_samples_max))
            state.usage_samples[key] = ring
        if ring:
            newest_at, newest_pct = ring[-1]
            if at <= newest_at:
                return tuple(ring)
            if pct < newest_pct:
                ring.clear()
            elif window_start is not None:
                while ring and ring[0][0] < window_start:
                    ring.popleft()
        ring.append((at, pct))
        return tuple(ring)


def _pace(samples: tuple[tuple[float, int], ...]) -> dict[str, Any] | None:
    """Points per minute across the kept readings, with the basis it rests on.

    Two readings are the minimum, and the basis travels with the figure so the
    page can say what it was measured over instead of presenting a rate as if it
    were the window's own.
    """
    if len(samples) < 2:
        return None
    (first_at, first_pct), (last_at, last_pct) = samples[0], samples[-1]
    span = last_at - first_at
    if span <= 0:
        return None
    return {
        "pctPerMin": round((last_pct - first_pct) / (span / 60.0), 4),
        "samples": len(samples),
        "spanSec": int(span),
    }


def observe_windows(
    config: RuntimeConfig,
    state: RuntimeState,
    entries: list[dict[str, Any]],
) -> None:
    """Record each window's level, and annotate it with the pace so far.

    Called once per collection, over the entries as published. `recent` appears
    on a window exactly when two or more distinct readings support it; a window
    with one reading, a stale one, or one that just reset carries none, and the
    page reads that absence as "not measured" rather than as a pace of zero.

    Nothing here re-checks how old the reading is because nothing stale reaches
    it: the two cache readers, `cached_entries` and `receipt_entries`, gate on
    the activity window before publishing, and the Codex disk reader gates its
    own snapshot. Publishing `asOf` is not that gate — it is a figure for the
    page, and no reader compares it to now.
    """
    for entry in entries:
        harness = entry.get("harness")
        at = _finite(entry.get("asOf"))
        if not isinstance(harness, str) or not harness or at is None:
            continue
        for slot in PACE_SLOTS:
            window = entry.get(slot)
            if not isinstance(window, dict):
                continue
            pct = window.get("pct")
            if not isinstance(pct, int) or isinstance(pct, bool):
                continue
            # The current window's start, where both fields are published, so a
            # sample from a previous window cannot be measured through the
            # boundary. `_shape_window` states the same relation the other way
            # round for the page's elapsed figure.
            reset_at = _finite(window.get("resetAt"))
            length = _finite(window.get("windowSec"))
            window_start = (
                reset_at - length if reset_at is not None and length and length > 0 else None
            )
            samples = _record_sample(
                config, state, _sample_key(harness, slot), at, pct, window_start
            )
            pace = _pace(samples)
            if pace is not None:
                window["recent"] = pace


def _detached(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Entries a caller cannot use to reach back into the cache.

    `dict(entry)` is not enough: every entry holds nested window dicts, and a
    shallow copy leaves those shared, so mutating a published `fiveH` would
    edit stored state. `deepcopy` is safe here because entries hold only the
    JSON scalars and dicts the shaping code built.
    """
    return [copy.deepcopy(entry) for entry in entries]


def _within_window(
    config: RuntimeConfig,
    now: float,
    entry: dict[str, Any],
    window_hours: float,
) -> bool:
    """Whether an entry's own reading time is inside the activity window.

    Measured on `asOf` rather than on the cache's `ts`, which stamps the last
    *attempt*: `asOf` is the field the page renders the reading's age from, and a
    gate resting on a different stamp than the one shown is how the two come to
    disagree.

    A stamp that is missing, non-numeric or non-finite fails the gate. That entry
    is the worse case, not the safer one: nothing downstream can date it either —
    `observe_windows` skips it, so it carries no pace and no age — so publishing
    it would put a bare percentage on the page with nothing to say how old it is.
    """
    at = _finite(entry.get("asOf"))
    return at is not None and sessions.is_fresh(config, now, at, window_hours * 3600)


def cached_entries(
    config: RuntimeConfig,
    state: RuntimeState,
    vendor: str,
    now: float,
    window_hours: float,
) -> list[dict[str, Any]]:
    """One vendor's last fetch, still current, copied so the cache is safe.

    The vendor is required rather than defaulted: a wrong default would quietly
    publish another vendor's numbers under this harness's name.

    The freshness gate is here rather than in each collector because this is the
    function that owns the cache. Both fetch-backed rows read it, so one gate
    fixes both, and a third fetch-backed provider inherits the rule instead of
    being the next one to forget it — which is how this defect arose, with one
    of the two collectors gating and the other not. `records.iso_epoch` states
    the same preference for the same reason: a rule every reader has to remember
    separately is a rule some reader will not.

    A stale entry is withheld, not evicted. The published result is identical
    either way — `observe_windows` runs over the published list, so dropping is
    already enough to keep an old reading out of the pace ring — and leaving the
    cache alone keeps it a faithful record of what the last fetch actually
    returned, which is what the poll floor beside it is stamped against.
    """
    with state.usage_fetch_lock:
        cached = state.usage_fetch_cache.get(vendor)
        entries = _detached(cached["entries"]) if cached else []
    return [entry for entry in entries if _within_window(config, now, entry, window_hours)]


# The status-line payload names its windows rather than describing them by
# length, so the mapping is a suffix match and nothing is inferred. A bucket
# matching neither suffix is dropped: an unknown future window is better
# absent than mislabelled as one of these two.
_RECEIPT_WINDOWS = (("-5h", "fiveH"), ("-weekly", "week"))


def _receipt_window(now: float, raw: Any, slot: str) -> tuple[int, dict[str, Any]] | None:
    """One status-line bucket as (percent used, shaped window), or nothing."""
    bucket = records.as_dict(raw)
    remaining = _finite(bucket.get("remaining_fraction"))
    if remaining is None:
        return None
    # The payload reports what is LEFT; the contract publishes what is USED.
    pct = max(0, min(100, round((1.0 - remaining) * 100)))
    shaped: dict[str, Any] = {"pct": pct}
    length = SLOT_WINDOW_SEC.get(slot)
    if length is not None:
        shaped["windowSec"] = length
    resets = _epoch(bucket.get("reset_time"))
    if resets:
        shaped.update(sessions.reset_fields(now, resets))
    return pct, shaped


def shape_statusline(payload: dict[str, Any], now: float) -> list[dict[str, Any]]:
    """Antigravity's status-line payload as usage entries, or nothing.

    A fresh entry is built field by field rather than derived from the payload,
    because the payload also carries an account email and a transcript path,
    and neither may reach ``/api/data``.

    Two model families report the same two windows (``gemini-*`` and ``3p-*``
    for third-party models), so each slot has two candidates. The worse of the
    pair wins: the band exists to answer "am I about to run out", and the
    binding constraint is the honest number to show. The cost is that the tile
    does not say which family it came from.
    """
    quota = records.as_dict(payload.get("quota"))
    if not quota:
        return []
    best: dict[str, tuple[int, dict[str, Any]]] = {}
    for key, raw in quota.items():
        # JSON object keys are always strings, so the suffix match is safe.
        slot = next((name for suffix, name in _RECEIPT_WINDOWS if key.endswith(suffix)), None)
        if slot is None:
            continue
        mapped = _receipt_window(now, raw, slot)
        if mapped is None:
            continue
        current = best.get(slot)
        if current is None or mapped[0] > current[0]:
            best[slot] = mapped
    if not best:
        return []
    entry: dict[str, Any] = {"harness": "antigravity", "state": "ok", "asOf": int(now)}
    for slot, (_pct, shaped) in best.items():
        entry[slot] = shaped
    return [entry]


def receive_statusline(
    state: RuntimeState,
    payload: dict[str, Any],
    *,
    now: float,
    config: RuntimeConfig | None = None,
) -> dict[str, Any]:
    """Store a pushed status-line receipt. Returns the endpoint's wire response.

    Storing an empty entry list on an unusable payload is deliberate: it stamps
    the arrival, so a harness that stops reporting quota goes stale and drops
    out of the band rather than showing whatever it last said forever.

    With server-side usage disabled the quota fields are dropped before storage,
    not rejected at the door: SECURITY.md promises nothing is retained with the
    feature off, and the response still reports success so a harness's status
    line never surfaces a Compass error.
    """
    enabled = True if config is None else config.usage_fetch_enabled
    entries = shape_statusline(payload, now) if enabled else []
    with state.usage_fetch_lock:
        state.usage_receipts["antigravity"] = {"ts": now, "entries": entries}
    return {"ok": True, "usage": len(entries)}


def receipt_entries(
    config: RuntimeConfig,
    state: RuntimeState,
    now: float,
    window_hours: float,
) -> list[dict[str, Any]]:
    """Pushed entries still inside the activity window, copied.

    The receipt only arrives while the harness runs, so a stored figure can be
    arbitrarily old. Dropping past the window matches the Codex tile: an empty
    band is more honest than a percentage whose window has itself reset.
    """
    with state.usage_fetch_lock:
        cached = state.usage_receipts.get("antigravity")
        if not cached:
            return []
        stamp, entries = cached["ts"], _detached(cached["entries"])
    if not sessions.is_fresh(config, now, stamp, window_hours * 3600):
        return []
    return entries
