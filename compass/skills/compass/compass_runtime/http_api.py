"""The loopback HTTP service: one server instance, one application, one assembled page."""

from __future__ import annotations

import base64
import contextlib
import errno
import hashlib
import ipaddress
import json
import os
import select
import socket
import socketserver
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar
from urllib.parse import ParseResult, parse_qs, urlparse

from compass_runtime import annotations as annotation_store
from compass_runtime import asks as runtime_asks
from compass_runtime import (
    copied_corrections,
    correction,
    departures,
    dismissals,
    entry_numbers,
    levels,
    live_estimate,
    notifications,
    quota,
    reading_policy,
    record_pages,
    records,
    session_outline,
    tripwires,
)
from compass_runtime import events as runtime_events
from compass_runtime import io as runtime_io
from compass_runtime import observer as runtime_observer
from compass_runtime import project_context as runtime_project_context
from compass_runtime import reading as runtime_reading
from compass_runtime import reading_jobs as runtime_reading_jobs
from compass_runtime import reading_route as runtime_reading_route
from compass_runtime import snapshot as runtime_snapshot
from compass_runtime import stream as runtime_stream
from compass_runtime.frontend_dev import DevelopmentFrontend

_WEBSOCKET_GUID = b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from compass_runtime.aggregate import Application
    from compass_runtime.interaction_prototype import InteractionPrototype
    from compass_runtime.observation import Observation


def _websocket_accept(value: str) -> str | None:
    try:
        raw = base64.b64decode(value, validate=True)
    except ValueError:
        return None
    if len(raw) != 16:
        return None
    digest = hashlib.sha1(value.encode("ascii") + _WEBSOCKET_GUID, usedforsecurity=False).digest()
    return base64.b64encode(digest).decode("ascii")


def _websocket_frame(opcode: int, payload: bytes) -> bytes:
    length = len(payload)
    if length < 126:
        header = bytes((0x80 | opcode, length))
    elif length <= 65_535:
        header = bytes((0x80 | opcode, 126)) + length.to_bytes(2, "big")
    else:
        header = bytes((0x80 | opcode, 127)) + length.to_bytes(8, "big")
    return header + payload


def _annotation_body_refused(payload: dict[str, Any]) -> bool:
    """Whether an annotate body carries a field of the wrong shape, which answers 400.

    The text fields are strings or absent: `records.safe_text` does
    `str(value or "")`, so a dict would publish its repr. The outcome lines are
    a list of strings and nothing else, because a line sent as an object would
    be a client naming its own source, which only the server may do
    (`annotations._sourced`). `origins` names the stored position each posted
    line came from, so two lines sharing text keep their own entries; the
    store checks the text, so a position can keep a source and never claim one.
    """
    goal, output = payload.get("goal"), payload.get("output")
    lines, expected = payload.get("lines"), payload.get("expected_revision")
    origins, replace = payload.get("origins"), payload.get("replace")
    # `add_direction` names the fact and `text` is the reader's review of it;
    # the server, not the body, makes the line an entry line.
    texts = (goal, output, payload.get("add_direction"), payload.get("text"))
    # Not accurate is a bool naming the reading it marks by its time
    # (`annotations.mark_not_accurate` checks it against the reading it holds).
    marked, read_at = payload.get("not_accurate"), payload.get("read_at")
    return (
        any(value is not None and not isinstance(value, str) for value in texts)
        or (
            "not_accurate" in payload
            and (
                not isinstance(marked, bool)
                or isinstance(read_at, bool)
                or not isinstance(read_at, (int, float))
            )
        )
        or (
            replace is not None
            and (isinstance(replace, bool) or not isinstance(replace, int) or replace < 0)
        )
        or (
            lines is not None
            and (not isinstance(lines, list) or not all(isinstance(line, str) for line in lines))
        )
        or (expected is not None and (isinstance(expected, bool) or not isinstance(expected, int)))
        or (
            origins is not None
            and (
                not isinstance(origins, list)
                or not isinstance(lines, list)
                or len(origins) != len(lines)
                or not all(
                    item is None
                    or (isinstance(item, int) and not isinstance(item, bool) and item >= 0)
                    for item in origins
                )
            )
        )
    )


def _withdraw_raises(application: Application, outcome: str, harness: str, sid: str) -> bool:
    """Take the cleared words out of the departure store as well.

    A withdrawal is one act over two stores. A departure quotes the cleared
    clause and carries a model's paragraph about it, and `/api/annotations`
    serves both for sessions that have left the board, so clearing the
    annotation alone left the words readable there: measured, a goal cleared and
    replaced served the old clause verbatim. `departures.withdraw` blanks them
    and keeps the row, because the row is what bounds the lane's spend.

    Only after a clear that landed. A refused or unwritable clear left the words
    in the annotation store, and taking the raises out beneath them would leave
    the two stores disagreeing about whether the withdrawal happened.

    Returns whether the quotations are where the reply is about to say they
    are. `persisted` and `outcome` stay about the annotation store, which is
    what the reader typed into, so this is a second answer and not a
    correction to the first: the entry is gone whatever this says. It used to
    be discarded, and the board then printed "nothing raised against those
    words quotes them any more" over rows it was redrawing with those words in
    them -- `departures.withdraw` answers False on a store it could not write,
    and `unasked.published` goes on serving every row it did not blank.
    """
    if outcome != annotation_store.OUTCOME_STORED:
        # Nothing was owed, so nothing is out of step. The caller's other
        # tokens already say the clear did not land.
        return True
    return departures.withdraw(
        application.config, harness, sid, diagnostic_sink=application.diagnostic_sink
    )


def normalize_host(value: str) -> str:
    """Reduce a ``Host`` header to a bare, lowercased hostname.

    Naive ``rsplit(":", 1)`` mishandles two legitimate forms: a bracketed IPv6
    authority (``[::1]`` with no port becomes ``[:``) and any host whose case
    differs from the allowlist, even though DNS names are case-insensitive and
    ``LOCALHOST`` is as valid as ``localhost``. Both were rejected as non-local.
    """
    host = (value or "").strip()
    if host.startswith("["):
        end = host.find("]")
        if end < 0:
            return ""
        # Only a port may follow the bracketed literal. Without this check
        # "[::1]evil.example" reduced to "::1" and passed as loopback.
        rest = host[end + 1 :]
        if rest and not (rest.startswith(":") and rest[1:].isdigit()):
            return ""
        return host[1:end].lower()
    if host.count(":") > 1:
        return host.lower()  # bare IPv6 with no port
    if ":" not in host:
        return host.lower()
    name, _, port = host.rpartition(":")
    # Same rule as the bracketed branch: only a numeric port may follow, so
    # "localhost:evil.example" does not reduce to "localhost".
    return name.lower() if port.isdigit() else ""


def reuse_address_allowed(os_name: str) -> bool:
    """Whether the listening socket should set ``SO_REUSEADDR``.

    On POSIX the option only bypasses ``TIME_WAIT``, which is what lets the
    dashboard restart immediately after a kill — worth keeping. On Windows the
    same option means something else entirely: a second process may bind a port
    that is *already bound*, with undefined delivery between the two sockets. A
    stray second Compass would silently steal half the requests, and any local
    process could hijack the port of a server handing out local session data.
    """
    return os_name != "nt"


def bind_error_message(
    exc: OSError,
    port: int,
    host: str = "127.0.0.1",
) -> str:
    """Explain a failed bind instead of dumping a raw traceback."""
    winerror = getattr(exc, "winerror", None)
    if exc.errno == errno.EADDRINUSE or winerror == 10048:  # WSAEADDRINUSE
        # 0.0.0.0 is a bind address and not a destination, so the hint keeps
        # loopback there — the wildcard is not connectable, which
        # `_host_admitted` says in as many words. Any other bind is where the
        # printed curl was pointing at the wrong machine.
        reachable = "127.0.0.1" if host in ("127.0.0.1", "0.0.0.0") else host  # noqa: S104
        return (
            f"Compass: port {port} is already in use. If that is a dashboard "
            f"already running, use it: curl -s http://{reachable}:{port}/api/data. "
            f"Otherwise pick another port with --port."
        )
    if exc.errno == errno.EACCES or winerror == 10013:  # WSAEACCES
        # On Windows this is also what an in-use port reports once
        # SO_EXCLUSIVEADDRUSE is set, so name both causes.
        return (
            f"Compass: not permitted to bind port {port} — it may already be "
            f"held by another process, reserved by the system, or blocked by "
            f"local policy. Try another port with --port."
        )
    return f"Compass: cannot bind {host}:{port} — {type(exc).__name__}: {exc}"


class CompassHTTPServer(ThreadingHTTPServer):
    """Loopback listener that refuses to share its port on Windows.

    It owns exactly one application and its assembled page, all read from the
    instance rather than from module globals, so two servers can run in one
    interpreter without either one answering with the other's data.
    """

    def __init__(
        self,
        address: tuple[str, int],
        application: Application,
        page_bytes: bytes,
        observation: Observation | None = None,
        *,
        interaction_prototype: InteractionPrototype | None = None,
    ) -> None:
        self.application = application
        # Authentication material only; pages and transcript bytes are never cached.
        self.record_cursor_key = os.urandom(32)
        self.page_bytes = page_bytes
        # None under --no-events, and None for the many test doubles that only
        # need a page and an application. `serve` reads it to decide whether to
        # run the coordinator or the older periodic producer.
        self.observation = observation
        self.interaction_prototype = interaction_prototype
        # Instance attribute, set before the bind that reads it: the class
        # default would be sampled from the host os.name at import, which is
        # the ambient read
        # [D-4](docs/design-cross-platform.md#d-4)
        # exists to stop.
        self.allow_reuse_address = reuse_address_allowed(application.config.os_name)
        # The bind host from the constructor address, read by _local_ok to
        # decide whether a non-loopback Host header is the operator's opt-in
        # (--host 0.0.0.0) rather than a DNS-rebinding probe.
        self.bound_host = address[0]
        super().__init__(address, _RequestHandler)

    def server_close(self) -> None:
        if self.interaction_prototype is not None:
            self.interaction_prototype.stop()
        super().server_close()

    def server_bind(self) -> None:
        # Windows-only socket option, and the complement of the reuse policy
        # rather than an independent switch: Winsock rejects SO_REUSEADDR on a
        # socket already carrying SO_EXCLUSIVEADDRUSE (WSAEINVAL 10022), so both
        # have to come from one decision. Clearing SO_REUSEADDR stops *us* from
        # hijacking someone else's port; this stops anyone else hijacking ours.
        # Gated on this application's config, not the host: reading the host
        # here let a posix-configured application on a Windows host ask for both
        # and fail every bind. Also gated on the constant existing, which it does
        # not on POSIX, where getattr returns None.
        exclusive = getattr(socket, "SO_EXCLUSIVEADDRUSE", None)
        if exclusive is not None and not self.allow_reuse_address:
            try:
                self.socket.setsockopt(socket.SOL_SOCKET, exclusive, 1)
            except OSError as exc:
                # Bind anyway, but say so: without this option the port can be
                # hijacked, and silently dropping the guarantee is worse than
                # a noisy one-line warning at startup.
                runtime_io.diag(
                    f"Compass: could not claim the port exclusively ({exc}); continuing",
                    self.application.diagnostic_sink,
                )
        # Deliberately NOT `super().server_bind()`. `HTTPServer.server_bind`
        # resolves the bind address to a name with `socket.getfqdn()` — a
        # reverse DNS lookup, on the startup path, for a value nothing here
        # reads. Where the resolver has no answer for 127.0.0.1 it does not fail
        # fast, it waits: on the macOS CI runner that was ~17.5s per bind, which
        # is most of what made the macOS test leg take 316s against Ubuntu's 29s,
        # and it is the same stall a person starting the dashboard on a machine
        # with a slow resolver would sit through before the page came up.
        #
        # `server_name` and `server_port` are still set, because the base class
        # promises them; the name is the host as given rather than whatever the
        # resolver would have called it.
        socketserver.TCPServer.server_bind(self)
        # Read off the bound socket rather than the requested address, so a
        # port of 0 reports the port the OS actually gave.
        bound = self.socket.getsockname()
        self.server_name = str(bound[0])
        self.server_port = int(bound[1])


def _session_context(
    application: Any,
    row: dict[str, Any],
    reach: runtime_project_context.PressWindow | None = None,
) -> dict[str, Any]:
    """One session's project context, without refreshing anything.

    `reach` is an Analyze press's own request to read the session's messages back to its window
    start; every other caller leaves it unset and reads the 400,000-byte tail as before.
    """
    context = runtime_project_context.collect(
        application.config,
        application.state,
        [row],
        str(row.get("project_key") or row.get("project") or ""),
        now=application.clock(),
        refresh=False,
        focus=(str(row.get("harness")), str(row.get("sid"))),
        model_consent=False,
        message_reach=reach,
    )
    return copied_corrections.mark(context, [row]) if isinstance(context, dict) else {}


# An Allow with no `words_destination` at all comes from a page older than the
# binding (regressions major 1, ui5): a tab left open across the upgrade. It
# names no destination, so it binds nothing and is refused. The 79bcedae page
# answers any 409 by drawing the consent card again with a line about tool
# output, so a reader pressed Allow forever. Rendered against this server, the
# one reply that page shows verbatim is a route with no provider, whose `note`
# it draws in the button's place and keeps until its next poll, so the refusal
# is a 400 carrying such a route, and its note says to reload.
PAGE_OUTDATED_REASON = "page-outdated"
PAGE_OUTDATED = (
    "This page is from an older version of Compass, so nothing was sent. Reload the page "
    "to analyze."
)


def _outdated_route(route: runtime_reading_route.Route) -> runtime_reading_route.Route:
    """The route an older page draws as "reload", in place of the one that runs."""
    return {
        **route,
        "provider": "",
        "reason": PAGE_OUTDATED_REASON,
        "note": PAGE_OUTDATED,
        "disclosure": "",
        "disclosure_parts": [],
    }


def _latest_revision(entry: annotation_store.Annotation | None) -> int:
    """The number of an entry's latest revision, or 0 where it holds none."""
    return entry["revisions"][-1]["n"] if entry and entry["revisions"] else 0


def _with_message_ordinals(
    application: Any, result: dict[str, Any], focus: tuple[str, str]
) -> dict[str, Any]:
    """The focused session's message facts, each carrying its fixed number.

    The checks and files carry theirs from the tally. Both are published for the focused session
    only, which is the one whose page numbers its list. Copies, because the facts can be shared with
    a cache.
    """
    semantic = result.get("semantic")
    if not isinstance(semantic, dict) or not isinstance(semantic.get("facts"), list):
        return result
    path = runtime_observer.resolve_transcript(
        application.config, application.state, focus[0], focus[1]
    )
    if not path:
        return result
    index = entry_numbers.message_index(application.config, application.state, path, *focus)
    if index is None:
        return result
    facts = entry_numbers.with_message_ordinals(index, semantic["facts"])
    return {**result, "semantic": {**semantic, "facts": facts}}


def _with_levels(
    application: Any,
    context: dict[str, Any],
    rows: list[dict[str, Any]],
    focus: tuple[str, str],
    project: str,
) -> dict[str, Any]:
    """The focused session's project context with its two drift levels (DRC-4696, DRC-4695).

    On this route alone, the page's: `_session_context` is what the reading
    route and the unasked lane read, and neither is given a level (item 5 of
    [DEC-26](docs/design-reading-a-session.md#dec-26-four-drift-levels-and-a-live-estimate-after-every-turn)).
    With annotations off there are no saved words to estimate against, and no
    reading either.
    """
    config = application.config
    harness, sid = focus
    # The project too, as `project_context` selects it: under another project the
    # context holds none of the session's facts, so its later directions read none.
    matching = [
        r
        for r in rows
        if r.get("harness") == harness
        and r.get("sid") == sid
        and project
        in {str(r.get("project_key") or r.get("project") or ""), str(r.get("project") or "")}
    ]
    if (
        harness not in live_estimate.HARNESSES
        or not config.annotations_enabled
        or len(matching) != 1
    ):
        return context
    row = matching[0]
    entry = annotation_store.find(annotation_store.active(config, application.state), harness, sid)
    floor = annotation_store.direction_floor(entry, row)
    raw_sources = context.get("sources")
    sources: dict[str, Any] = raw_sources if isinstance(raw_sources, dict) else {}
    raw_work = sources.get("work")
    work: dict[str, Any] = dict(raw_work) if isinstance(raw_work, dict) else {}
    request_sources = _request_sources(application, row, _facts_of(context), entry) if entry else []
    work["line_requests"] = _line_requests(entry, request_sources, row)
    work["analysis_levels"] = _analysis_levels(
        application, context, row, entry, floor, request_sources=request_sources
    )
    transcript = runtime_observer.resolve_transcript(config, application.state, harness, sid)
    if transcript:
        live = live_estimate.for_session(
            config, row, transcript, _facts_of(context), floor=floor, now=application.clock()
        )
        work["live_levels"] = [live]
    return {**context, "sources": {**sources, "work": work}}


def _line_requests(
    entry: annotation_store.Annotation | None, facts: list[Any], row: Mapping[str, Any]
) -> list[dict[str, Any]]:
    """The page receives verified times, never untrusted stored binding digests."""
    if not entry or not entry["revisions"]:
        return []
    latest = entry["revisions"][-1]
    harness, sid = str(row.get("harness") or ""), str(row.get("sid") or "")
    own = [fact for fact in facts if isinstance(fact, dict)]
    floors = runtime_reading.line_request_floors(latest, own, harness, sid)
    lines = {
        name: {"at": at, "source_id": latest["lines"][int(name.split("_")[1]) - 1]["source_id"]}
        for name, at in floors.items()
    }
    return (
        [{"harness": harness, "sid": sid, "revision": latest["n"], "lines": lines}] if lines else []
    )


def _analysis_levels(
    application: Any,
    context: dict[str, Any],
    row: dict[str, Any],
    entry: annotation_store.Annotation | None,
    floor: float | None,
    *,
    request_sources: Sequence[Mapping[str, Any]] = (),
) -> list[dict[str, Any]]:
    """The analysis-derived level of the stored reading, recomputed now and never stored.

    `levels.analysis_level` over the reading and the record as the context
    holds it: the session's tool reports, their full-scan counts and its
    unsettled later directions (items 1, 2 and 6 of
    [DEC-26](docs/design-reading-a-session.md#dec-26-four-drift-levels-and-a-live-estimate-after-every-turn)).
    The lines it must answer are those of the revision it read, not today's;
    a revision the store no longer holds gives no level rather than a guess.
    """
    assessment = entry.get("assessment") if entry else None
    if not entry or not assessment or entry.get("not_accurate") is True:
        return []
    read = next(
        (rev for rev in entry["revisions"] if rev["n"] == assessment.get("revision_read")), None
    )
    if read is None:
        return []
    harness, sid = str(row.get("harness") or ""), str(row.get("sid") or "")
    facts = _facts_of(context)
    mine = tuple(
        fact
        for fact in facts
        if isinstance(fact, dict)
        and isinstance(fact.get("source_session"), dict)
        and (fact["source_session"].get("harness"), fact["source_session"].get("sid"))
        == (harness, sid)
    )
    scan = _scan_of(context, harness, sid)
    evidence = levels.Evidence(
        mine,
        scan,
        correction.unsettled_directions(row, facts, floor=floor, until=assessment.get("read_at")),
    )
    level = levels.analysis_level(
        assessment,
        evidence,
        outcome_lines=len(read["lines"]),
        lines=runtime_reading.outcome_lines(read),
        line_requests=runtime_reading.line_request_floors(read, request_sources, harness, sid)
        if read["n"] == entry["revisions"][-1]["n"]
        else {},
    )
    return [
        {
            "harness": harness,
            "sid": sid,
            "revision_read": assessment.get("revision_read"),
            "read_at": assessment.get("read_at"),
            "computed_at": application.clock(),
            "level": level.level,
            "reasons": list(level.reasons),
            "cites": list(level.cites),
        }
    ]


def _request_sources(
    application: Any,
    row: Mapping[str, Any],
    facts: list[Any],
    entry: annotation_store.Annotation | None = None,
) -> list[Mapping[str, Any]]:
    """One version-checked newest and opening read, shared by this operation's consumers."""
    if entry is not None and (
        not entry["revisions"] or not runtime_reading.has_line_requests(entry["revisions"][-1])
    ):
        return []
    harness, sid = str(row.get("harness") or ""), str(row.get("sid") or "")
    path = runtime_observer.resolve_transcript(application.config, application.state, harness, sid)
    recovered = (
        runtime_project_context.transcript_user_facts(
            application.config, application.state, path, harness, sid
        )
        if path
        else []
    )
    return runtime_reading.listed_request_sources(
        [fact for fact in facts if isinstance(fact, dict)], recovered
    )


# One sentence per refusal a direction lookup gives, for pages that predate its token.
_DIRECTION_WHY = {
    "out_of_reach": "Compass's search stopped before reaching that direction "
    "in the session's record. Nothing was opened.",
    "changed": "The session wrote to its record while Compass was reading it. "
    "Nothing was opened. Press again.",
    "not_found": "Compass could not find that later direction "
    "in the session's current record. Nothing was opened.",
}


def _prompt_facts(
    application: Any,
    row: Mapping[str, Any],
    facts: list[Any],
    coverage: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Verify this session's person words from the native source when the menu opens."""
    harness, sid = str(row.get("harness") or ""), str(row.get("sid") or "")
    wanted = {"harness": harness, "sid": sid}
    path = runtime_observer.resolve_transcript(application.config, application.state, harness, sid)
    source = (
        runtime_project_context.transcript_user_facts(
            application.config,
            application.state,
            path,
            harness,
            sid,
            goal_choices=True,
            coverage=coverage,
        )
        if path
        else []
    )
    copied_ids = {
        fact.get("fact_id")
        for fact in facts
        if isinstance(fact, dict)
        and fact.get(runtime_reading.COPIED_FLAG) is True
        and fact.get("source_session") == wanted
    }
    marked = copied_corrections.mark({"semantic": {"facts": source}}, [row])
    return [
        fact
        for fact in marked["semantic"]["facts"]
        if fact.get("source_session") == wanted
        and fact.get("fact_id") not in copied_ids
        and runtime_reading.author_of(fact) == runtime_reading.AUTHOR_PERSON
    ]


def _with_prompt_choices(
    application: Any,
    context: dict[str, Any],
    rows: list[dict[str, Any]],
    focus: tuple[str, str],
    project: str,
) -> dict[str, Any]:
    """The focused session's own prompts a reader may adopt, as `prompt_choices` (Q7).

    Before `for_page`, which drops each message's whole words: the choices
    are built from them here, clipped to the goal's cap, and the words
    themselves still never reach the page. `[]` when annotations are off, on a
    harness no prompt is adopted from, or when the row is not in this project.
    """
    harness, sid = focus
    matching = [
        r
        for r in rows
        if r.get("harness") == harness
        and r.get("sid") == sid
        and project
        in {str(r.get("project_key") or r.get("project") or ""), str(r.get("project") or "")}
    ]
    coverage: dict[str, Any] = {"state": "unavailable", "bound": None}
    choices = (
        annotation_store.prompt_choices(
            matching[0],
            _prompt_facts(application, matching[0], _facts_of(context), coverage),
            application.config.annotation_text_cap_chars,
        )
        if application.config.annotations_enabled and len(matching) == 1
        else []
    )
    return {
        **context,
        "prompt_choices": sorted(choices, key=lambda choice: -choice["at"]),
        "prompt_scan": {"state": coverage["state"], "bound": coverage["bound"]},
    }


def _press_content(harness: str) -> int:
    """The disclosure version a press on this harness needs an Allow to cover.

    A Claude Code session's press carries the agent's messages, read by Claude
    Code or by Codex, so it needs an Allow given under the disclosure that names
    them. A press on any other harness carries none of them, and an Allow from
    before that disclosure still covers it (final review, 2026-10-03).
    """
    return (
        reading_policy.CONTENT_VERSION
        if harness in runtime_project_context.AGENT_MESSAGE_HARNESSES
        else reading_policy.WORDS_CONTENT_VERSION
    )


def _scan_of(context: dict[str, Any], harness: str, sid: str) -> dict[str, Any]:
    """The full-scan metadata for this session, beside its bounded fact ledger."""
    work = (context.get("sources") or {}).get("work") or {}
    scans = work.get("tool_reports") if isinstance(work, dict) else None
    return next(
        (
            s
            for s in (scans if isinstance(scans, list) else [])
            if isinstance(s, dict) and s.get("harness") == harness and s.get("sid") == sid
        ),
        {},
    )


def _facts_of(context: dict[str, Any]) -> list[Any]:
    semantic = context.get("semantic")
    facts = semantic.get("facts", []) if isinstance(semantic, dict) else []
    return list(facts) if isinstance(facts, list) else []


class _RequestHandler(BaseHTTPRequestHandler):
    server: CompassHTTPServer

    # Loopback-origin requests only: the Host check defeats DNS rebinding,
    # the Origin check defeats cross-site fetch()es from web pages (both
    # reach 127.0.0.1-bound servers through the victim's browser).
    LOCAL_HOSTS: ClassVar[set[str]] = {"127.0.0.1", "localhost", "::1"}

    # How much of a rejected POST's body to read and throw away. Generously above
    # every accept-path cap so a rejection drains whatever a legitimate client
    # sent, and still a hard bound so a hostile declared length cannot turn a
    # refusal into an unbounded read.
    REJECT_DRAIN_CAP_BYTES: ClassVar[int] = 1 << 20

    # How long to spend draining a rejected body. Bounded in time as well as in
    # bytes: a peer may declare a length it never sends, which a limit test does
    # on purpose and a hostile client would do to stall a handler.
    REJECT_DRAIN_SECONDS: ClassVar[float] = 0.25

    # The store's token for the settlement a Keep press wrote, or None when the
    # press carried none. Reset per request: a kept-alive connection reuses
    # this handler for the next one.
    _keep_outcome: str | None = None

    # Body bytes this request has already taken off the wire. Reset per request,
    # and a class default so a handler-level test that calls one method directly
    # still has it.
    _body_consumed: int = 0

    def _read_body(self, length: int) -> bytes:
        """Read a declared body, remembering how much of it is now gone.

        Every refusal that follows a successful read used to re-drain the same
        bytes: `_drain_body` reads Content-Length again, the peer has nothing
        left to send, and `read1` blocks until REJECT_DRAIN_SECONDS gives up. So
        a validation 400 — an unusable question, a bad option list — cost its
        handler thread the full 250ms drain, measured on the shipped /api/ask
        route. Counting what was consumed leaves the drain for what it is for: a
        peer still mid-write.
        """
        body: bytes = self.rfile.read(length)
        self._body_consumed += len(body)
        return body

    def _drain_body(self) -> None:
        """Read and discard a rejected request's body before answering.

        Closing a socket that still holds unread inbound data makes the OS send
        RST rather than FIN, and an RST can discard the reply already written.
        The client then sees ECONNRESET, or WSAECONNABORTED on Windows, instead
        of the 403 or 413 it was told to expect. That is what failed on the
        macOS and Windows runners.

        Bounded three ways, and all three are load-bearing. By the declared
        length, so a well-behaved client is drained exactly. By
        REJECT_DRAIN_CAP_BYTES, so a hostile declared length cannot turn a
        refusal into an unbounded read. And by REJECT_DRAIN_SECONDS, because a
        peer that declares more than it sends would otherwise stall this handler
        until the connection timeout: `read1` blocks for at least one byte, and
        a request-limit test sends exactly that shape deliberately.
        """
        try:
            declared = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return
        remaining = max(0, min(declared - self._body_consumed, self.REJECT_DRAIN_CAP_BYTES))
        if not remaining:
            return
        deadline = time.monotonic() + self.REJECT_DRAIN_SECONDS
        previous = None
        try:
            previous = self.connection.gettimeout()
            self.connection.settimeout(self.REJECT_DRAIN_SECONDS)
        except (OSError, AttributeError):
            previous = None  # not a real socket, as in a handler-level test
        try:
            while remaining > 0 and time.monotonic() < deadline:
                try:
                    # read1, not read: one syscall returning what is available,
                    # rather than blocking until the full count arrives.
                    chunk = self.rfile.read1(min(remaining, 65_536))
                except (OSError, ValueError, AttributeError):
                    return
                if not chunk:
                    return  # end of stream, or nothing more is coming
                remaining -= len(chunk)
        finally:
            if previous is not None:
                with contextlib.suppress(OSError):
                    self.connection.settimeout(previous)

    def _reject(self, code: int, why: str | None = None) -> None:
        """Refuse a POST without stranding the peer mid-write.

        `why` reaches the caller in the status line and the error body. Passed
        only where the refusal is a rule the client can obey rather than a
        malformed request: a client told "this names a session" can stop sending
        one, where a bare 400 reads as a bug in its own encoder.
        """
        self._drain_body()
        if why is None:
            self.send_error(code)
        else:
            self.send_error(code, why)

    def _host_admitted(self, host: str) -> bool:
        """Whether a host string is local enough for this server's bind.

        The default loopback bind keeps the exact LOCAL_HOSTS gate. A
        non-loopback bind (--host 0.0.0.0 or an explicit address) is the
        operator's opt-in to remote access, so the gate widens to the address
        they asked for: exactly that address, or under 0.0.0.0 any address a
        client could reach the machine on.

        It widens to *addresses*, never to names, and that is the whole
        rebinding defense rather than a tidiness rule. `Host` and `Origin` are
        attacker-chosen strings, so admitting any non-empty one hands a page on
        `http://evil.example:4553` both `/api/data` and every POST route the
        moment its DNS points at this machine — measured before this narrowing,
        against a 0.0.0.0 bind. Rebinding needs a name to rebind; an operator
        typing a remote dashboard's URL has a literal address to type, so
        refusing every name costs them nothing and closes it.
        """
        if host in self.LOCAL_HOSTS:
            return True
        bound = getattr(self.server, "bound_host", "127.0.0.1")
        if bound == "127.0.0.1":
            return False
        try:
            literal = ipaddress.ip_address(host)
        except ValueError:
            return False  # a DNS name, or garbage
        if bound == "0.0.0.0":  # noqa: S104
            # The operator asked for every interface, so any address a client
            # could have arrived on is theirs. The wildcard itself is not a
            # connectable destination, and neither is a multicast group.
            return not (literal.is_unspecified or literal.is_multicast)
        # `cli.BIND_HOSTS` no longer produces a bind that reaches here, but this
        # server is constructible directly, so the gate answers for whatever
        # address it was actually given rather than assuming the launcher.
        return host == bound

    def _development_authority_ok(self) -> bool:
        config = getattr(getattr(self.server, "application", None), "config", None)
        dev = getattr(config, "frontend_dev", None)
        # Only an admitted immutable startup identity selects this policy.
        if not isinstance(dev, DevelopmentFrontend):
            return True
        hosts = self.headers.get_all("Host", [])
        origins = self.headers.get_all("Origin", [])
        return hosts == [dev.python_origin.removeprefix("http://")] and (
            not origins or origins == [dev.python_origin]
        )

    def _local_ok(self, *, allow_cross_site_navigation: bool = False) -> bool:
        if not self._development_authority_ok() or not self._host_admitted(
            normalize_host(self.headers.get("Host") or "")
        ):
            return False
        if (self.headers.get("Sec-Fetch-Site") or "").lower() == "cross-site" and not (
            allow_cross_site_navigation and self._is_document_navigation()
        ):
            return False
        origin = self.headers.get("Origin")
        if not origin:
            return True  # same-origin GETs send none
        # Compare the whole origin, not just the host. Every port on this
        # machine is the *same site*, so Sec-Fetch-Site reports "same-site" for
        # a page served from another local port — and a hostname-only check
        # then trusted it. Any unrelated local dev server could POST here
        # (text/plain is CORS-safelisted, so no preflight would stop it).
        parsed = urlparse(origin)
        if parsed.scheme != "http" or not self._host_admitted(parsed.hostname or ""):
            return False
        listening_port = getattr(self.server, "server_port", None)
        try:
            # Browsers omit the port when it is the scheme default, so
            # "http://localhost" is a legitimate same-origin value on port 80.
            origin_port = parsed.port if parsed.port is not None else 80
        except ValueError:
            return False  # unparseable port in the Origin header
        return origin_port == listening_port

    def _is_document_navigation(self) -> bool:
        """Whether this is the browser navigating a tab to us, top level.

        Chrome labels *any* navigation whose initiator was another origin
        ``Sec-Fetch-Site: cross-site`` — including one the user started by
        clicking a link to the dashboard. Rejecting those returned 403 for a
        perfectly ordinary way to open the page.

        Serving them is safe: the initiating page cannot read a cross-origin
        document, so there is nothing to exfiltrate, and the Host check above
        still blocks DNS rebinding. Everything else cross-site — ``fetch``,
        XHR, an iframe, a subresource — *can* be read by its initiator and
        stays blocked, which is what ``Sec-Fetch-Dest: document`` distinguishes
        (an iframe reports ``iframe``). GET only: a cross-site form submission
        is also a "navigation", so POST never takes this path.
        """
        return (self.headers.get("Sec-Fetch-Mode") or "").lower() == "navigate" and (
            self.headers.get("Sec-Fetch-Dest") or ""
        ).lower() == "document"

    def _is_frame_navigation(self) -> bool:
        """Whether a browser is navigating a FRAME to us rather than a tab.

        The routes that hold a socket open refuse this, and the reason is the
        browser's connection pool rather than this server's own budget. Measured
        2026-09-07, Chrome, eight frames on `/api/stream` from a page on another
        loopback port: the frames took SIX sockets, not eight, because a browser
        caps concurrent HTTP/1.1 connections per origin at six, so the eight-slot
        stream budget was never drained and a seventh client still got a 200.
        What the six frames did drain was Chrome's own pool for that origin, and
        the board then would not load AT ALL in the same browser -- the
        navigation sat pending and committed the instant the frames were removed.
        `stream_max_clients` being above the browser's six is why the budget was
        never the vulnerable resource; see the note in `config`.

        So this buys exactly one thing: the framed request is refused before it
        can hold a socket, instead of holding one for as long as the framer likes.
        It is worth what `frame-ancestors` is worth and no more, since a local
        process the attacker controls sends no `Sec-Fetch` headers at all and a
        `curl` caller sends none either. SECURITY.md's disclaimer paragraph owns
        that reasoning.

        Every port on this machine is the same site, so `Sec-Fetch-Site` reads
        `same-site` for a frame from another local port and never reaches the
        cross-site check, and a frame navigation carries no `Origin` for the
        check below it. `Sec-Fetch-Dest` is the header that distinguishes it.
        """
        return (self.headers.get("Sec-Fetch-Dest") or "").lower() in {"iframe", "frame"}

    def _send(
        self,
        body: bytes,
        ctype: str,
        code: int = 200,
        *,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        # `frame-ancestors` and nothing else, and the single directive is the
        # decision rather than an unfinished policy. It is not a fetch directive
        # and has no fallback to `default-src`, so alone it restricts framing and
        # nothing on the page. A second directive is not free: this document is
        # one `data:` module script and one `data:` stylesheet that carries its fonts
        # as `data:` URIs, so a `default-src 'self'` added beside it serves a blank board.
        # A header rather than a `<meta http-equiv>` because CSP ignores
        # `frame-ancestors` delivered that way, which also leaves the page's
        # verified bytes untouched. No `X-Frame-Options: DENY` beside it:
        # `frame-ancestors` wins wherever both are present, and a browser old
        # enough to read only XFO cannot run this page. What the header does and
        # does not buy is in SECURITY.md's Known and accepted section.
        self.send_header("Content-Security-Policy", "frame-ancestors 'none'")
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def _health(self) -> None:
        """Liveness and identity, with no filesystem access.

        `/api/data` can answer "is a dashboard here?" only by scanning every
        harness store on the machine. The daemon readiness wait and --status ask
        that question in a loop, so they need an answer that costs nothing. The
        pid is part of it because "something is listening on the port" is not
        the same claim as "Compass is running on the port".

        ``started`` is the value ``build_runtime_state`` captured, read straight
        off this server's own state. Sampling a clock here instead would make
        every poll report a different uptime for the same process.
        """
        self._send(
            json.dumps(
                {
                    "ok": True,
                    "pid": os.getpid(),
                    "port": getattr(self.server, "server_port", 0),
                    "started": self.server.application.state.server_started,
                }
            ).encode(),
            "application/json",
        )

    def _shutdown(self) -> None:
        """Stop the server: `--stop` and any local client land here.

        Not the page: the dashboard's stop control was removed during the UI
        promotion
        ([D-7](docs/design-daemon.md#d-7)),
        so nothing the board serves
        posts to this route.

        Answer first, then stop. `socketserver.shutdown()` blocks until the
        accept loop notices the request and exits, which can take up to one
        poll interval (0.5s by default) — running it on its own thread lets
        this handler return and the connection close immediately, instead of
        holding the client for that long. It also keeps this correct if the
        server class ever stops being a threading one: on a non-threading
        server the handler runs on the serve loop's own thread, and calling
        `shutdown()` inline would then deadlock, exactly as `BaseServer.
        shutdown`'s docstring warns.
        """
        # Wake every stream first. shutdown() stops the accept loop but never
        # touches handler threads, and a stream is asleep in wait() rather than
        # in the socket, so nothing else would tell it to stop.
        with contextlib.suppress(Exception):
            self.server.application.state.streams.close_all()
        # And every parked poll, for the same reason: a poll is asleep in
        # wait(), not in the socket, so nothing else would tell it to stop.
        # Measured without this line, a poll mid-stop holds silently for the rest
        # of its timeout and then loses the connection when the process exits.
        # The asking session reads that as a transport failure rather than as the
        # decline the contract promises it.
        with contextlib.suppress(Exception):
            self.server.application.state.asks.decline_all()
        if self.server.interaction_prototype is not None:
            with contextlib.suppress(Exception):
                self.server.interaction_prototype.stop()
        try:
            self._send(b'{"ok":true,"stopping":true}', "application/json")
            with contextlib.suppress(OSError, ValueError):
                self.wfile.flush()
        except (OSError, ValueError):
            # The request was accepted even if the peer vanished before it
            # could read the reply. Do not let that disconnect cancel the stop.
            pass
        finally:
            threading.Thread(target=self.server.shutdown, daemon=True).start()

    def do_GET(self) -> None:
        if not self._local_ok(allow_cross_site_navigation=True):
            self.send_error(403)
            return
        url = urlparse(self.path)
        if url.path == "/" and "next" not in parse_qs(url.query, keep_blank_values=True):
            self._send(self.server.page_bytes, "text/html; charset=utf-8")
        elif url.path.startswith("/assets/"):
            self._interaction_asset(url.path)
        elif not self._get_api(url):
            self.send_error(404)

    def _loopback_resource_ok(self) -> bool:
        site = (self.headers.get("Sec-Fetch-Site") or "").lower()
        return (
            ipaddress.ip_address(self.client_address[0]).is_loopback
            and site not in {"same-site", "cross-site"}
            and self._local_ok()
        )

    def _interaction_asset(self, path: str) -> None:
        if not self._loopback_resource_ok():
            self.send_error(403)
            return
        asset = {
            "/assets/xterm.js": ("xterm.js", "text/javascript"),
            "/assets/xterm.css": ("xterm.css", "text/css"),
        }.get(path)
        if self.server.interaction_prototype is None or asset is None:
            self.send_error(404)
            return
        name, content_type = asset
        try:
            body = (Path(__file__).parent / "web" / "vendor" / name).read_bytes()
        except OSError:
            self.send_error(404)
            return
        self._send(body, content_type)

    def _get_api(self, url: ParseResult) -> bool:
        """Route one GET API path, or return False so `do_GET` can 404 it.

        Split off the page arm rather than kept as one chain: adding the
        observer route took the single method to mccabe 11 against ruff's cap
        of 10, and this file has never needed a complexity exemption. The
        split keeps the next route free rather than buying it one.

        The exact matches are a table now, for the reason `do_POST` gives at
        its own: adding `/api/annotations` took the ladder back to 11, and a
        table adds the route after it for nothing. The two prefix arms stay
        ahead of it so they cannot be shadowed by an exact key.
        """
        if url.path.startswith("/api/interaction/"):
            self._interaction_get(url)
            return True
        if url.path.startswith("/api/ask/"):
            self._ask_poll(url.path[len("/api/ask/") :])
            return True
        # Two tables, split by whether the handler reads the query rather than
        # by anything about the route, so neither grows a branch per entry.
        with_url = {
            "/api/data": self._data,
            "/api/observe": self._observe,
            "/api/project-context": self._project_context,
            "/api/session-record": self._session_record,
        }.get(url.path)
        if with_url is not None:
            with_url(url)
            return True
        bare = {
            "/api/overlays": self._overlays,
            "/api/cleared": self._cleared,
            "/api/annotations": self._annotations,
            "/api/stream": self._stream,
            "/api/health": self._health,
        }.get(url.path)
        if bare is None:
            return False
        bare()
        return True

    def _interaction_get(self, url: ParseResult) -> None:
        prototype = self.server.interaction_prototype
        if prototype is None:
            self.send_error(404)
            return
        route = url.path[len("/api/interaction/") :]
        query = parse_qs(url.query)
        if route == "origin":
            self._interaction_origin(prototype, query)
            return
        if query:
            self._reject(400)
            return
        if route == "stream":
            self._interaction_stream(prototype)
            return
        handler = {"state": prototype.state, "view": prototype.view}.get(route)
        if handler is None:
            self.send_error(404)
            return
        result = handler(self.server.server_port)
        self._send(json.dumps(result, separators=(",", ":")).encode(), "application/json")

    def _interaction_origin(
        self, prototype: InteractionPrototype, query: dict[str, list[str]]
    ) -> None:
        if set(query) != {"harness", "sid"}:
            self._reject(400)
            return
        harness, sid = query["harness"], query["sid"]
        if len(harness) != 1 or len(sid) != 1 or not harness[0] or not sid[0]:
            self._reject(400)
            return
        result = prototype.resolve_session(self.server.server_port, f"{harness[0]}:{sid[0]}")
        self._send(json.dumps(result, separators=(",", ":")).encode(), "application/json")

    def _interaction_stream(self, prototype: InteractionPrototype) -> None:
        """Upgrade one output-only socket; any client frame revokes the connection."""
        if self.headers.get("Upgrade", "").lower() != "websocket":
            self._reject(426)
            return
        connections = (
            value.strip() for value in self.headers.get("Connection", "").lower().split(",")
        )
        if "upgrade" not in connections or self.headers.get("Sec-WebSocket-Version") != "13":
            self._reject(400)
            return
        accept = _websocket_accept(self.headers.get("Sec-WebSocket-Key", ""))
        if accept is None:
            self._reject(400)
            return
        self.send_response(101)
        self.send_header("Content-Security-Policy", "frame-ancestors 'none'")
        self.send_header("Upgrade", "websocket")
        self.send_header("Connection", "Upgrade")
        self.send_header("Sec-WebSocket-Accept", accept)
        self.end_headers()
        self.close_connection = True
        sequence = 0
        try:
            while True:
                readable, _, _ = select.select([self.connection], [], [], 0)
                if readable:
                    self.connection.recv(2)
                    reason = b"read-only-capability"
                    payload = (1008).to_bytes(2, "big") + reason
                    self.connection.sendall(_websocket_frame(8, payload))
                    break
                frame = prototype.wait_stream(self.server.server_port, sequence, 0.2)
                if frame.get("state") != "streamed":
                    payload = json.dumps(frame, separators=(",", ":")).encode()
                    self.connection.sendall(_websocket_frame(1, payload))
                    break
                next_sequence = frame.get("sequence")
                if isinstance(next_sequence, int) and next_sequence > sequence:
                    payload = json.dumps(frame, separators=(",", ":")).encode()
                    self.connection.sendall(_websocket_frame(1, payload))
                    sequence = next_sequence
        except (ConnectionError, OSError, ValueError):
            pass

    def _project_context(self, url: ParseResult) -> None:
        """Read the observer and timestamped event sources for one project."""
        if not self._local_ok():
            self.send_error(403)
            return
        project = parse_qs(url.query).get("project", [""])[0]
        application = self.server.application
        if not project or len(project) > application.config.ask_project_cap_chars:
            self.send_error(400, "a bounded project label is required")
            return
        focus_raw = parse_qs(url.query).get("session", [""])[0]
        focus: tuple[str, str] | None = None
        if focus_raw:
            harness, separator, sid = focus_raw.partition(":")
            if (
                not separator
                or not harness
                or not sid
                or len(focus_raw) > application.config.ask_project_cap_chars
            ):
                self.send_error(400, "a bounded harness:session identity is required")
                return
            focus = (harness, sid)
        refresh = parse_qs(url.query).get("refresh", ["0"])[0] == "1"
        if refresh and focus is None:
            self.send_error(400, "observer refresh requires an exact focused session")
            return
        _revision, body = application.collect_json(show_all=False)
        collected = json.loads(body)
        result = runtime_project_context.collect(
            application.config,
            application.state,
            collected["sessions"],
            project,
            now=application.clock(),
            refresh=refresh,
            focus=focus,
            # As with usage=1, the page sends this only after disclosure consent.
            # Quota consent does not authorize sending transcript content.
            model_consent=(
                refresh
                and parse_qs(url.query).get("observer_model") == ["1"]
                and not self._is_document_navigation()
                and self._loopback_resource_ok()
            ),
        )
        # Marked here and in `_session_context`, the two readers the page and the
        # reading route see; the unasked lane receives no copy (item 12 of the ruling
        # `copied_corrections` cites).
        result = copied_corrections.mark(result, collected["sessions"])
        if focus is not None:
            result = _with_message_ordinals(application, result, focus)
            result = _with_levels(application, result, collected["sessions"], focus, project)
            matching = [
                row
                for row in collected["sessions"]
                if (row.get("harness"), row.get("sid")) == focus
                and project
                in {
                    str(row.get("project_key") or row.get("project") or ""),
                    str(row.get("project") or ""),
                }
            ]
            outline = (
                session_outline.for_session(application.config, application.state, *focus)
                if len(matching) == 1
                else {"state": "unavailable", "reason": "session_not_matched", "blocks": []}
            )
            result = {**result, "sources": {**result.get("sources", {}), "outline": outline}}
            if parse_qs(url.query).get("prompts", ["0"])[0] == "1":
                result = _with_prompt_choices(
                    application, result, collected["sessions"], focus, project
                )
        # The page shows titles; a reader message whole is for a reading only.
        result = runtime_project_context.for_page(result)
        self._send(
            json.dumps(result, ensure_ascii=False, separators=(",", ":")).encode(),
            "application/json",
        )

    def _session_record(self, url: ParseResult) -> None:
        """A reader-requested backward page, under the project context's guards."""
        if not self._local_ok():
            self.send_error(403)
            return
        query = parse_qs(url.query, keep_blank_values=True)
        application = self.server.application
        project = query.get("project", [""])[0]
        focus = query.get("session", [""])[0]
        harness, separator, sid = focus.partition(":")
        cap = application.config.ask_project_cap_chars
        if (
            not project
            or len(project) > cap
            or not separator
            or not harness
            or not sid
            or len(focus) > cap
        ):
            self.send_error(400, "a bounded project and harness:session identity are required")
            return
        try:
            limit = record_pages.page_limit(query.get("limit", ["50"])[0])
        except ValueError:
            self.send_error(400, "limit must be an integer")
            return
        _revision, body = application.collect_json(show_all=False)
        rows = json.loads(body)["sessions"]
        matching = [
            row
            for row in rows
            if row.get("harness") == harness
            and row.get("sid") == sid
            and project
            in {
                str(row.get("project_key") or row.get("project") or ""),
                str(row.get("project") or ""),
            }
        ]
        result = record_pages.empty(harness, sid, "unavailable")
        index = None
        if len(matching) == 1:
            path = runtime_observer.resolve_transcript(
                application.config, application.state, harness, sid
            )
            result = record_pages.read(
                application.config,
                path or "",
                harness,
                sid,
                cursor_key=self.server.record_cursor_key,
                limit=limit,
                before=query.get("before", [None])[0],
            )
            # After the page is read, so the index reaches at least as far as the page does.
            if path and result["entries"]:
                index = entry_numbers.message_index(
                    application.config, application.state, path, harness, sid
                )
        marked = copied_corrections.mark({"semantic": {"facts": result["entries"]}}, matching)
        result["entries"] = marked["semantic"]["facts"]
        if index is not None:
            # Each message's fixed number (DRC-4897), so a page of any age numbers it the same way.
            result["entries"] = entry_numbers.with_message_ordinals(index, result["entries"])
        result = runtime_project_context.for_page(result)
        self._send(
            json.dumps(result, ensure_ascii=False, separators=(",", ":")).encode(),
            "application/json",
        )

    def _data(self, url: ParseResult) -> None:
        query = parse_qs(url.query)
        show_all = query.get("all", ["0"])[0] == "1"
        # `usage=1` is the page's consent to the quota fetch riding along
        # on its poll: the page sends it only with the feature switched on
        # and the first-run disclosure already answered. The fetch is a
        # background side effect behind its own floor and in-flight gates;
        # this request is answered from whatever is already cached. A bare
        # request without the parameter never triggers network traffic.
        #
        # Never on a document navigation, and that is a security check rather
        # than a tidy-up. `_local_ok` deliberately forgives a cross-site
        # navigation because the initiating page cannot READ a cross-origin
        # document, so serving one exfiltrates nothing. A side effect is the
        # case that reasoning does not cover: an attacker page that gets the
        # browser to open `http://127.0.0.1:4553/api/data?usage=1` in a tab
        # reads nothing back and still makes Compass read a harness
        # credential out of the Keychain and send it to the vendor, with the
        # disclosure never shown. The page's own poll goes through `fetch`, so
        # it reports `Sec-Fetch-Dest: empty` and is unaffected, and a `curl`
        # caller sends no fetch metadata at all. The body is still served on
        # the navigation; only the side effect is refused.
        if query.get("usage", ["0"])[0] == "1" and not self._is_document_navigation():
            self.server.application.request_usage_fetch()
        revision, body = self.server.application.collect_json(show_all=show_all)
        # The cursor rides in a header rather than the body, so the
        # documented JSON contract and every curl caller stay untouched.
        self._send(
            body,
            "application/json",
            headers={"X-Compass-Revision": runtime_snapshot.format_revision(revision)},
        )

    def _observe(self, url: ParseResult) -> None:
        """Trigger the observer analyzer on demand and return the sidecar JSON.

        A thin trigger, not a polling endpoint: read the transcript + entity
        dir, derive goal + stage + block, write the sidecar, return the JSON.
        The operator triggers it by clicking "observe" on a session card.
        Strictly same-origin: the route answers only loopback requests.
        """
        if not self._local_ok():
            self.send_error(403)
            return
        query = parse_qs(url.query)
        harness = query.get("harness", [""])[0]
        sid = query.get("sid", [""])[0]
        if not harness or not sid:
            self.send_error(400, "harness and sid are required")
            return
        application = self.server.application
        config = application.config
        state = application.state
        transcript_path = runtime_observer.resolve_transcript(config, state, harness, sid)
        if transcript_path is None:
            self.send_error(404, "session transcript not found")
            return
        # The same clock and window the collection runs on, so the observer's
        # freshness gate and a strip's agree about what is in flight.
        now = application.clock()
        result = runtime_observer.analyze(
            config,
            state,
            transcript_path,
            now=now,
            window_sec=config.window_hours * 3600,
        )
        if runtime_observer.write_sidecar(config, harness, sid, result) is None:
            # Refused, not fallen back: the names reached the transcript resolver
            # so they are shaped ids, and there is no second place a sidecar goes.
            # A failed write reads the same here, so the message names the
            # outcome rather than one of its two causes.
            self.send_error(400, "the observation could not be recorded")
            return
        self._send(json.dumps(result).encode(), "application/json")

    def _overlays(self) -> None:
        """The live overlay ledger, for diagnosing a row the reducer produced.

        Strictly same-origin, unlike `/api/data`: nothing renders this, so
        `do_GET`'s navigation relaxation has no reason to reach it.

        503 rather than 404 with no coordinator, because under `--no-events` the
        route exists and the ledger does not, and a 404 would read as a build too
        old to have the route.

        Disputes ride along rather than getting a route of their own: they are
        read against the ledger that produced them, and two requests to compare
        them would be two instants.
        """
        if not self._local_ok():
            self.send_error(403)
            return
        observation = self.server.observation
        if observation is None:
            self.send_error(503, "no event coordinator on this server")
            return
        report = observation.ledger_report()
        state = self.server.application.state
        with state.dispute_lock:
            report["dispute_total"] = state.dispute_total
            # Copied, not referenced: an open episode's record is updated in
            # place under that lock, and serializing the live dict outside it
            # could publish a fresh `repeats` beside a stale `last_seen_at`.
            # Shallow is enough; the nested values are written once.
            report["disputes"] = [dict(record) for record in state.disputes]
        self._send(json.dumps(report).encode(), "application/json")

    def _stream(self) -> None:
        """The SSE revision stream.

        Strictly same-origin. `do_GET` relaxes its check for document
        navigations so a link to the dashboard works, and a long-lived data
        stream is not a document navigation, so re-checking here with the
        strict form is what keeps that relaxation off this route. A FRAME
        navigation is refused on top of that: it holds a socket the browser
        will not then give the real board. See `_is_frame_navigation`.
        """
        if not self._local_ok() or self._is_frame_navigation():
            self.send_error(403)
            return
        application = self.server.application
        state = application.state
        client = state.streams.register(limit=application.config.stream_max_clients)
        if client is None:
            # A refusal, not a queue: every stream costs a thread and a socket
            # for as long as it lives.
            self.send_error(503)
            return
        try:
            self._stream_forever(client)
        finally:
            state.streams.release(client)

    def _stream_forever(self, client: runtime_stream.StreamClient) -> None:
        application = self.server.application
        config = application.config
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        with contextlib.suppress(OSError):
            # A peer that stops reading must not pin this thread forever. The
            # unbounded default is the real risk here, not server_close.
            self.connection.settimeout(config.stream_write_timeout_sec)
        current = application.state.snapshot.current((config.window_hours, False))
        if current is not None and not self._emit(current[0]):
            return
        while True:
            revision = client.wait(timeout=config.stream_heartbeat_sec)
            # Checked after the wait, not in the loop condition: close() lands
            # while this thread is asleep, which is the whole point of it, and a
            # `while not client.closed` header reads to the type checker as a
            # value that cannot change inside the body.
            if client.closed:
                return
            if revision is None:
                if not self._write_raw(b": keepalive\n\n"):
                    return
                continue
            if not self._emit(revision):
                return

    def _emit(self, revision: runtime_snapshot.Revision) -> bool:
        rendered = runtime_snapshot.format_revision(revision)
        return self._write_raw(f"id: {rendered}\nevent: revision\ndata: {rendered}\n\n".encode())

    def _write_raw(self, payload: bytes) -> bool:
        """Write and flush, reporting whether the peer is still there.

        No lock is held here. A blocked write must never be able to stall a
        publisher or a collection.
        """
        try:
            self.wfile.write(payload)
            self.wfile.flush()
        except (OSError, ValueError):
            return False
        return True

    def _cleared(self) -> None:
        """The sessions marked handled: two identifiers and a timestamp each.

        Strictly same-origin, like `/api/overlays`: nothing navigates here, so
        `do_GET`'s navigation relaxation has no reason to reach it.

        A route of its own rather than a variant of `/api/data`. Publishing the
        cleared rows back into `sessions` behind a query flag would put them in
        front of every consumer that derives a total from that array — the tab
        title, the gate queue, calm's idle clip — and each would need to know
        which request it was answering. This answers a different question, so it
        is a different response.
        """
        if not self._local_ok():
            self.send_error(403)
            return
        application = self.server.application
        if not application.config.dismissals_enabled:
            self.send_error(503, "dismissals are disabled on this server")
            return
        entries = dismissals.active(application.config, application.state)
        self._send(
            json.dumps({"cleared": dismissals.rows(entries)}, separators=(",", ":")).encode(),
            "application/json",
        )

    def _annotations(self) -> None:
        """Every session the reader has typed words against, including departed ones.

        Strictly same-origin, like `/api/cleared`: nothing navigates here.

        A route of its own for `_cleared`'s reason, and for one more. The Intent
        log is a top-level view, so it has no project key to hand
        `/api/project-context`, which is the fact that settled a question the
        plan left open between those two shapes. Folding the rows into
        `/api/data` would also put up to 256 sessions of the reader's own prose
        on a body polled every few seconds; here the words leave the server when
        someone opens the log.

        The store's rows and only the store's. Session history keeps a copy of
        the goal and each outcome line for fourteen days, and reading the log out of that
        instead would resurrect words a reader withdrew: `annotations.clear`
        removes the entry because clearing the field is withdrawing the request,
        while a history observation already appended is never retro-deleted.
        """
        if not self._local_ok():
            self.send_error(403)
            return
        application = self.server.application
        if not application.config.annotations_enabled:
            self.send_error(503, "annotations are disabled on this server")
            return
        entries = annotation_store.active(application.config, application.state)
        # Read once for the whole response, and served here rather than on the
        # polled payload for the reason this route exists at all: the payload
        # only carries sessions still on the board, and the rows this route is
        # for have left it. Reading both in one pass also keeps a row and its
        # raises consistent with each other.
        raised = departures.load(application.config)
        now = application.clock()
        rows = [
            {
                "harness": entry["harness"],
                "sid": entry["sid"],
                # The binding caveat, or the log claims exact binding for every
                # row. `published`'s default is BINDING_EXACT, which is a claim
                # and not an absence: on Claude the store keys on the eight
                # characters the harness publishes, so two sessions sharing
                # them share the words, and the tab that shows one session says
                # so while a list of many did not.
                #
                # Length alone here, unlike `_attach_annotations`, which also
                # reads `resume_id` off the live row. A departed session has no
                # row to read, and the whole point of this route is that it
                # serves those. Over-disclosing the caveat on a genuinely short
                # identity is the safe direction.
                **annotation_store.published(
                    entry,
                    binding_why=(
                        annotation_store.BINDING_BY_PREFIX
                        if len(entry["sid"]) <= annotation_store.DISPLAY_ID_FLOOR
                        else annotation_store.BINDING_EXACT
                    ),
                ),
                # What was raised against these words, and — where nothing was
                # — which of the four reasons. `departures` owns both, so the
                # log cannot word a spent cap differently from the session page.
                #
                # `has_words` per entry and never a hard-coded True, even
                # though this route iterates annotations: an entry whose latest
                # revision is two empty strings is exactly what the board's
                # `clear` plus the save after it leaves behind, and a constant
                # here would look right and keep the defect on the one surface
                # that outlives the session (DRC-4560).
                "departures": departures.published(raised, entry["harness"], entry["sid"]),
                "departure_why": departures.why(
                    application.config,
                    raised,
                    entry["harness"],
                    entry["sid"],
                    has_words=annotation_store.has_typed_goal(entry),
                    discarded=annotation_store.is_discarded(entry),
                    now=now,
                ),
            }
            for entry in entries
        ]
        self._send(
            json.dumps(
                {
                    "annotations": rows,
                    "intent_revision": application.intent_revision(entries, raised, now=now),
                },
                separators=(",", ":"),
            ).encode(),
            "application/json",
        )

    def _ask_poll(self, ask_id: str) -> None:
        """One bounded hold on a question's answer, for the peer that asked it.

        Strictly same-origin, like `/api/cleared`: the poller is a local MCP
        server, and nothing navigates here.

        Bounded rather than held until a reader clicks. A request that returned
        only on an answer would pin a handler thread for as long as a human
        takes, with nothing to join it at shutdown; docs/design-ask-lane.md
        records why that was rejected in favour of a repeated short poll.
        """
        if not self._local_ok() or self._is_frame_navigation():
            self.send_error(403)
            return
        application = self.server.application
        config = application.config
        if not config.ask_enabled:
            # 503 rather than 404, the same call `/api/cleared` makes under
            # `--no-dismiss`: the route exists and the registry does not.
            self.send_error(503, "the ask lane is disabled on this server")
            return
        ask = application.state.asks.get(ask_id)
        if ask is None:
            self.send_error(404)
            return
        outcome = ask.wait(timeout=config.ask_poll_timeout_sec)
        if outcome is None:
            # 204 rather than an empty 200: "nothing yet, ask again" is already
            # in the status line, so there is no body for it to disagree with.
            self.send_response(204)
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            return
        name, index = outcome
        answer: dict[str, Any] = {"state": name}
        if index is not None:
            answer["index"] = index
        # Released before the write, not after: the outcome is settled either
        # way, and a peer that vanished mid-reply must not leave a resolved ask
        # in the table for the deadline to sweep.
        application.state.asks.release(ask_id)
        self._send(json.dumps(answer, separators=(",", ":")).encode(), "application/json")

    def _usage_receipt(self) -> None:
        """A harness's own quota, forwarded here by its status-line command.

        Guarded exactly like `/api/notify`: `_local_ok()` has already run, the
        declared length is checked before any read, a malformed or non-object
        body degrades to `{}`, and the shaping code publishes derived scalars
        only. Nothing here touches the network or the disk.
        """
        application = self.server.application
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = -1
        if not 0 <= length <= application.config.usage_receipt_cap_bytes:
            self._reject(413)
            return
        try:
            payload = json.loads(self._read_body(length) or b"{}")
        except (ValueError, json.JSONDecodeError, RecursionError):
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        response = quota.receive_statusline(
            application.state,
            payload,
            now=application.clock(),
            config=application.config,
        )
        self._send(json.dumps(response, separators=(",", ":")).encode(), "application/json")

    def _dismiss(self) -> None:
        """Mark one session handled, or put one back.

        Guarded exactly like `/api/usage`: `_local_ok()` has already run, the
        declared length is checked before any read, and a malformed or non-object
        body degrades to `{}` — which names no session and therefore does nothing.

        No capability token, and that is deliberate rather than an omission. This
        is an action the page takes on the reader's behalf, and `/api/shutdown` —
        a strictly larger power over the same server — is gated by `_local_ok()`
        alone. The body carries no timestamp, so the worst a forged request can do
        is hide a row until that session's next write.

        `persisted` is answered honestly: an unwritable home still hides the row
        for this run, and the page says so rather than implying the mark will
        survive a restart.
        """
        application = self.server.application
        config = application.config
        if not config.dismissals_enabled:
            # 503, not 404, for the reason `/api/overlays` answers 503 with no
            # coordinator: under `--no-dismiss` the route exists and the store
            # does not, and a 404 would read as a build too old to have it.
            self._reject(503)
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = -1
        if not 0 <= length <= config.dismissal_body_cap_bytes:
            self._reject(413)
            return
        try:
            payload = json.loads(self._read_body(length) or b"{}")
        except (ValueError, json.JSONDecodeError, RecursionError):
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        state = application.state
        harness, sid = payload.get("harness"), payload.get("sid")
        if payload.get("clear") is False:
            persisted = dismissals.restore(
                config, state, harness, sid, diagnostic_sink=application.diagnostic_sink
            )
        else:
            persisted = dismissals.dismiss(
                config,
                state,
                harness,
                sid,
                now=application.clock(),
                diagnostic_sink=application.diagnostic_sink,
            )
        # The published bodies are dropped rather than waited out. Without this
        # the next GET would serve the pre-dismissal payload for up to
        # `collect_memo_sec`, and a row that stays put for two seconds after the
        # click reads as a control that did not work.
        state.snapshot.clear()
        answer = {
            "ok": True,
            "persisted": persisted,
        }
        self._send(json.dumps(answer, separators=(",", ":")).encode(), "application/json")

    # The five spellings a session's identity takes across this API. `/api/lane`
    # refuses a body carrying any of them, so this is a closed list on purpose:
    # it is the thing a reviewer checks against the rest of the surface rather
    # than a filter to keep widening.
    SESSION_IDENTITY_KEYS: ClassVar[frozenset[str]] = frozenset(
        {"harness", "sid", "session", "session_id", "resume_id"}
    )

    def _lane(self) -> None:
        """Record that a dashboard tab has a working notification lane in it.

        [DEC-19](docs/design-reading-a-session.md#dec-19-the-page-may-report-a-lane-never-a-delivery):
        the page may report that a lane EXISTS and may never report a delivery.
        So the body carries two scalars about the tab and nothing about a
        session, the record is one float for the whole board, and the reply says
        only whether a lane was recorded.

        **A body naming a session is refused rather than sanitized.** Dropping
        the field and answering 200 tells a client its per-raise claim was
        accepted, and the next client to be written against this route would
        keep sending one. The named keys are the five identity spellings the
        rest of this API uses; an unknown key is ignored, because a page that
        adds a field must not start failing against an older server.

        Only a WORKING lane is a report. A tab reporting that it has no lane
        records nothing and clears nothing: several tabs can be open, and one
        without permission says nothing about another that has it. What the
        absence of any report means is the second sentence of
        [DEC-19](docs/design-reading-a-session.md#dec-19-the-page-may-report-a-lane-never-a-delivery),
        which `deliveries` owns.

        No capability token, for `/api/dismiss`'s reason: `_local_ok()` has run,
        and the largest thing a forged request can do here is claim a tab is
        open, which makes one sentence on a review surface read as weaker
        evidence than it is.
        """
        application = self.server.application
        config = application.config
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = -1
        if not 0 <= length <= config.lane_body_cap_bytes:
            self._reject(413)
            return
        try:
            payload = json.loads(self._read_body(length) or b"null")
        except (ValueError, json.JSONDecodeError, RecursionError):
            payload = None
        if not isinstance(payload, dict):
            # 400 rather than a degrade to `{}`, unlike `/api/dismiss`. There a
            # body naming nothing does nothing; here it would be read as a tab
            # reporting no lane, which this route must not invent.
            self._reject(400)
            return
        if any(key in payload for key in self.SESSION_IDENTITY_KEYS):
            self._reject(400, "the lane report names a session, and it may not")
            return
        reported = payload.get("supported") is True and payload.get("permission") == "granted"
        if reported:
            state = application.state
            with state.lane_lock:
                state.lane_reported_at = application.clock()
            # The published bodies carry the lane sentence, so they are dropped
            # for `/api/dismiss`'s reason: without this the next GET serves the
            # pre-report payload for up to `collect_memo_sec`.
            state.snapshot.clear()
        answer = {"ok": True, "reported": reported}
        self._send(json.dumps(answer, separators=(",", ":")).encode(), "application/json")

    def _tripwire(self) -> None:
        application = self.server.application
        if not application.config.tripwires_enabled:
            self._reject(503)
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = -1
        if not 0 <= length <= 1024:
            self._reject(413)
            return
        try:
            request = json.loads(self._read_body(length) or b"null")
        except (ValueError, RecursionError):
            request = None
        # Save/Rearm start from current files, even if the preceding GET was memoized.
        with application.state.collect_memo_lock:
            application.collect(show_all=False)
            answer = tripwires.mutate(
                application.config, application.state, request, application.clock()
            )
            application.snapshot.clear()
        self._send(json.dumps(answer).encode(), "application/json", code=answer["status"])

    def _annotate(self) -> None:
        """Record what the reader typed this session should achieve, or clear it.

        Guarded like `/api/dismiss`: `_local_ok()` has already run, the declared
        length is checked before any read, and a malformed body degrades to
        `{}`, which names no session and does nothing.

        The two text fields are type-checked BEFORE redaction, which is
        `/api/ask`'s discipline rather than `/api/dismiss`'s. `records.safe_text`
        does `str(value or "")`, so a dict reaching it publishes its Python repr
        — including anything inside it — where a string would have been
        redacted. That is a 400 rather than a silent stringification, because
        the reader needs to know their words were not saved.

        `persisted` is answered honestly, for `_dismiss`'s reason: an unwritable
        home still holds the annotation for this run, and the page says so
        rather than implying it will survive a restart. `outcome` beside it is
        the store's own token (`annotations.OUTCOMES`), because `persisted` is
        one bit and the page has four sentences: a refusal and a failed write
        were both `false`, a minted revision and a repeat of the last one were
        both `true`. `persisted` keeps its meaning -- true whenever the words
        are on disk, which an unchanged save's are -- so nothing that reads it
        changes truth value (decisions.md, DRC-4543).
        """
        application = self.server.application
        config = application.config
        if not config.annotations_enabled:
            # 503, not 404: under `--no-annotations` the route exists and the
            # store does not, and a 404 would read as a build too old to have it.
            self._reject(503)
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = -1
        if not 0 <= length <= config.annotation_body_cap_bytes:
            self._reject(413)
            return
        try:
            payload = json.loads(self._read_body(length) or b"{}")
        except (ValueError, json.JSONDecodeError, RecursionError):
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        harness, sid = payload.get("harness"), payload.get("sid")
        # The identity is untrusted too, and it reaches `records.safe_text` by
        # the same path the text does. An earlier version checked only the two
        # text fields, which let a dict harness land a store entry keyed on its
        # Python repr.
        if (
            _annotation_body_refused(payload)
            or not isinstance(harness, str)
            or not isinstance(sid, str)
        ):
            self._reject(400)
            return
        state = application.state
        receipt: dict[str, int] = {}
        outcome, withdrew = self._annotation_outcome(harness, sid, payload, receipt=receipt)
        # Dropped rather than waited out, for `_dismiss`'s reason: the next GET
        # would otherwise serve the pre-save payload for up to `collect_memo_sec`.
        state.snapshot.clear()
        current = annotation_store.published(
            annotation_store.find(annotation_store.active(config, state), harness, sid)
        )
        answer = {
            "ok": True,
            "persisted": outcome
            in (annotation_store.OUTCOME_STORED, annotation_store.OUTCOME_UNCHANGED),
            "outcome": outcome,
            "revision": current["revision"],
            # Stable adoption result captured under the write lock, not the
            # potentially newer current revision read above. Other arms owe
            # no adoption receipt and always answer null.
            "saved_revision": receipt.get("saved_revision"),
            "revision_count": current["revision_count"],
            # When the discard this session carries a record of happened, or
            # None. Read back through `published` like the two above it, so
            # one clear arm cannot report a record the store did not make:
            # discarding a session that never had an entry answered exactly
            # like discarding two revisions of words (DRC-4565).
            "discarded": current["discarded_at"],
            # The second store's answer, and never folded into `outcome`: the
            # six `OUTCOMES` tokens are the annotation store's closed vocabulary and the
            # page's save path reads them too. True on every arm that owes no
            # withdrawal, so a reader of the wire sees one field with one
            # meaning rather than a key that appears only sometimes.
            "withdrew": withdrew,
        }
        self._send(json.dumps(answer, separators=(",", ":")).encode(), "application/json")

    def _annotation_outcome(
        self,
        harness: str,
        sid: str,
        payload: dict[str, Any],
        *,
        receipt: dict[str, int] | None = None,
    ) -> tuple[str, bool]:
        application = self.server.application
        config = application.config
        state = application.state
        goal, output = payload.get("goal"), payload.get("output")
        settle_through = payload.get("settle_through")
        withdrew = True
        if payload.get("clear") is True:
            outcome = annotation_store.clear(
                config, state, harness, sid, diagnostic_sink=application.diagnostic_sink
            )
            withdrew = _withdraw_raises(application, outcome, harness, sid)
        elif "add_direction" in payload:
            outcome = self._add_direction(harness, sid, payload)
        elif "not_accurate" in payload:
            # A fourth arm on this route, for the settle arm's reason: the
            # subject is the same session's annotation and the reply shape is
            # the same. Only the token is stored, and nothing else is read.
            outcome = annotation_store.mark_not_accurate(
                config,
                state,
                harness,
                sid,
                read_at=payload.get("read_at"),
                on=payload.get("not_accurate"),
                diagnostic_sink=application.diagnostic_sink,
            )
        elif "adopt" in payload:
            # With `settle_through` beside it this is Keep where no analysis
            # can start (no reader, or readings off): the draft is adopted and
            # the directions settled in one write, and nothing is read.
            outcome = self._adopt_prompt(
                harness,
                sid,
                payload,
                standalone=True,
                settle_through=settle_through,
                receipt=receipt,
            )
        elif settle_through is not None:
            # A third arm on this route rather than a route of its own: the
            # subject is the same session's annotation, the reply shape is the
            # same, and `test_history`'s POST inventory is a contract on the
            # surface's WIDTH. The store clamps `settle_through` to now and
            # refuses a bool, so nothing here needs to re-check the number
            # beyond refusing what is not one.
            outcome = annotation_store.settle(
                config,
                state,
                harness,
                sid,
                through=settle_through,
                now=application.clock(),
                # Checked when sent: Keep with no reader over saved words names
                # its revision, and the older "The baseline still applies"
                # press on the page sends none.
                expected_revision=payload.get("expected_revision"),
                diagnostic_sink=application.diagnostic_sink,
            )
        else:
            # One clock read for both, so the window start is "at or before"
            # the very save it is stored beside.
            now = application.clock()
            outcome = annotation_store.annotate(
                config,
                state,
                harness,
                sid,
                goal=goal,
                output=output,
                lines=payload.get("lines"),
                expected_revision=payload.get("expected_revision"),
                origins=payload.get("origins"),
                now=now,
                window_start=self._typed_window_start(harness, sid, now),
                diagnostic_sink=application.diagnostic_sink,
            )
        return outcome, withdrew

    def _typed_window_start(self, harness: str, sid: str, saved_at: float) -> float | None:
        """Where typed words saved now start reading work, or None for the save time.

        Read from the session's record as the reading route reads it. A save
        is never refused for it: a record that cannot be read opens the window
        at the save, which is what a build without window starts did. Found in
        the all-sessions collection, because a reader can save from that view
        and the default one leaves an aged session out.
        """
        try:
            row = self._published_row(harness, sid)
            if row is None:
                return None
            facts = self._session_facts(row)
        except Exception:  # noqa: BLE001 (an unreadable record costs the window, never the save)
            return None
        return runtime_reading.typed_window_start(facts, harness, sid, saved_at)

    def _reading_refusal(self, payload: dict[str, Any]) -> int | None:
        """The status this press must be refused with, or None to proceed.

        Its own function rather than a ladder inside the handler, because
        `http_api.py` carries no complexity exemption in `pyproject.toml` and
        because every condition here is then unit-testable without a socket.

        Ordered cheapest-first and ALL of it before anything reaches the
        model. A gate that answers 503 after spending the reader's own
        capacity has not held, which is the property the route's tests assert
        by counting invocations rather than by reading status codes.

        Nine conditions against `/api/project-context`'s five. The two this
        adds beyond that route are the last two: a reading is the first thing
        in this product a reader spends capacity on by pressing a button, so
        the press is asserted rather than assumed, and nothing on render,
        poll, reconnect, resume, focus change or revision save carries it.
        """
        config = self.server.application.config
        # A table rather than a ladder, for the reason the POST routes below
        # are one: six conditions read as a list of what must be true, and a
        # ladder of early returns puts this function over ruff's return cap
        # without making any of them clearer. Every condition is a pure read,
        # so evaluating all six costs nothing and the order is documentation.
        checks: tuple[tuple[bool, int], ...] = (
            # 503 rather than 404, for `_annotate`'s reason: under
            # `--no-annotations` the route exists and the store does not.
            (not config.annotations_enabled, 503),
            (config.model_calls_disabled, 503),
            # The button and this route read the same constants, so they agree
            # by construction and a local `curl` cannot outrun the check. Any
            # provider opens the route; which one may run is the route's
            # question, answered below from the harness.
            (not annotation_store.any_reading_enabled(), 503),
            # A lured navigation reads nothing back, but it would still spend
            # the reader's capacity, which is the harm this route carries.
            (self._is_document_navigation() or not self._loopback_resource_ok(), 403),
            (payload.get("observer_model") != 1, 400),
            (payload.get("press") is not True, 400),
        )
        for failed, status in checks:
            if failed:
                return status
        return None

    def _reading(self) -> None:
        """Read one session against the words typed against it.

        No capability token. The precedent is the quota fetch rather than the
        event ingress: the harm is a side effect on the reader's own capacity
        rather than a forged claim about a session, and it is held by the
        same-origin and navigation refusals above. The accepted exposure -- a
        local process with no fetch metadata can spend one reading -- is in
        SECURITY.md rather than left to be discovered.

        An unknown session answers 200 with `produced: false` and never 404,
        for `_focus`'s ruling: a harness name is public and a session id is
        not, so a 404 here would be an existence oracle.
        """
        application = self.server.application
        config = application.config
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = -1
        if not 0 <= length <= config.annotation_body_cap_bytes:
            self._reject(413)
            return
        try:
            payload = json.loads(self._read_body(length) or b"{}")
        except (ValueError, json.JSONDecodeError, RecursionError):
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        refusal = self._reading_refusal(payload)
        if refusal is not None:
            self._reject(refusal)
            return
        if payload.get("consent") == "off":
            self._reading_permission_reply(
                reading_policy.set_consent(config, False, now=application.clock()), off=True
            )
            return
        harness, sid = payload.get("harness"), payload.get("sid")
        if not isinstance(harness, str) or not isinstance(sid, str) or not harness or not sid:
            self._reject(400)
            return
        self._reading_press(harness, sid, payload)

    def _reading_press(self, harness: str, sid: str, payload: dict[str, Any]) -> None:
        """An admitted press on one session: Keep's settlement, route, permission, job."""
        self._keep_outcome = None
        self._keep_at: float | None = None
        self._press_revision: int | None = None
        if "settle_through" in payload:
            if not self._keep(harness, sid, payload):
                return
        elif not self._press_revision_current(harness, sid, payload):
            return
        route = self._reading_route(harness, payload)
        if route is None:
            return
        permission = self._reading_permission(payload, route)
        if permission["reason"]:
            self._reading_permission_reply(permission, route=route)
            return
        self._reading_adoption(harness, sid, payload, route)

    def _press_revision_current(self, harness: str, sid: str, payload: dict[str, Any]) -> bool:
        """Whether a plain press names the revision stored now, or names none (DRC-4732).

        Checked first, before the route, any Allow write, the adoption and the
        job: the analysis composes from the stored entry, so a page drawn
        against an older revision would have the model read words its reader
        never saw. Keep checks its own revision in the store write it makes.
        A press that names none is an older page's, and is read as it was.
        """
        if "expected_revision" not in payload:
            return True
        expected = payload["expected_revision"]
        if isinstance(expected, bool) or not isinstance(expected, int):
            self._reject(400)
            return False
        application = self.server.application
        # From disk under the store's lock, not this process's copy, which
        # misses a save another dashboard made since its last collection
        # (wire review F3).
        entries = annotation_store.fresh(
            application.config, application.state, application.diagnostic_sink
        )
        if entries is None:
            self._reject(503)
            return False
        if expected == _latest_revision(annotation_store.find(entries, harness, sid)):
            self._press_revision = expected
            return True
        self._revision_changed()
        return False

    def _revision_changed(self) -> None:
        self._send(
            self._reading_json({"ok": False, "produced": False, "reason": "revision-changed"}),
            "application/json",
            409,
        )

    def _composes_what_was_pressed(
        self, entry: annotation_store.Annotation, *, adopted: bool
    ) -> bool:
        """Whether the entry about to reach the model is the one this press was checked against.

        Read again at the job, because a save can land between the check and
        here. A plain press names its revision. A Keep names the revision it
        settled, so its own settlement must still sit on the latest revision.
        An adoption is held by `_adoption_matches` instead, since it minted
        the revision itself.
        """
        latest = _latest_revision(entry)
        if self._keep_at is not None:
            settled = entry.get("settled")
            return settled is not None and (settled["at"], settled["revision"]) == (
                self._keep_at,
                latest,
            )
        return adopted or self._press_revision is None or self._press_revision == latest

    def _reading_cancel(self) -> None:
        """Cancel the named running analysis (DRC-4693).

        Guarded as the reading route is, by `_reading_refusal`, so a lured
        navigation, a cross-site fetch and a non-loopback peer are refused
        alike. The job id is required and must be the running job's, so a
        stale tab cannot cancel a newer press. No job, another job's id, a
        sealed job and an unknown session all answer one `409 not-running`
        body, so the route is not an existence oracle. It writes no consent
        and reserves nothing, and it never waits for the reap: the job's own
        thread does that.
        """
        config = self.server.application.config
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = -1
        if not 0 <= length <= config.annotation_body_cap_bytes:
            self._reject(413)
            return
        try:
            payload = json.loads(self._read_body(length) or b"{}")
        except (ValueError, json.JSONDecodeError, RecursionError):
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        refusal = self._reading_refusal(payload)
        if refusal is not None:
            self._reject(refusal)
            return
        harness, sid, job_id = payload.get("harness"), payload.get("sid"), payload.get("job")
        if not all(isinstance(part, str) and part for part in (harness, sid, job_id)):
            self._reject(400)
            return
        accepted = runtime_reading_jobs.cancel(
            self.server.application, f"{harness}:{sid}", str(job_id)
        )
        self._send(
            json.dumps(
                {"ok": True, "cancelling": True}
                if accepted
                else {"ok": False, "reason": "not-running"},
                separators=(",", ":"),
            ).encode(),
            "application/json",
            202 if accepted else 409,
        )

    def _reading_permission(
        self, payload: dict[str, Any], route: runtime_reading_route.Route
    ) -> reading_policy.Status:
        """The stored answer this press rests on, after any Allow it carried.

        Covered only where the Allow was given for the destination the route
        names now (owner, 2026-10-02). Every provider's is computed by the one
        `reading_route.destination` the board publishes from, and this route's
        own is the one its disclosure named, so the reply's `providers` is the
        board's and the job's reservation checks the same value.
        """
        application = self.server.application
        config = application.config
        provider, where = route["provider"], route["destination"]
        today = {
            **runtime_reading_route.destinations(),
            provider: route["words_destination"],
        }
        content = _press_content(route["harness"])
        permission = (
            reading_policy.set_consent(
                config,
                True,
                now=application.clock(),
                provider=provider,
                tool_output=where,
                destination=route["words_destination"],
                destinations=today,
                content=content,
            )
            if payload.get("allow") is True
            else reading_policy.status(
                config,
                now=application.clock(),
                provider=provider,
                destinations=today,
                content=content,
            )
        )
        if (
            not permission["reason"]
            and where
            and not reading_policy.tool_output_allowed(permission, provider, where)
        ):
            # Allowed for the reader's words, and not for tool output to this
            # destination: an answer given before tool output was named, or for
            # an endpoint that has since moved. Asked again, and nothing read,
            # item 7 of the ruling `reading.build_ledger` cites.
            return {**permission, "consent": False, "reason": "tool-output-consent-required"}
        return permission

    def _reading_route(
        self, harness: str, payload: dict[str, Any]
    ) -> runtime_reading_route.Route | None:
        """The one provider this press may reach, or None once refused.

        From the payload's harness alone, so the answer says nothing about
        whether the session exists. Every refusal comes before any consent
        write or reservation: "Allow and check" allowed the provider the page
        named, and when that is not the provider that would run, the answer
        was given about a different receiver and records nothing. The same
        holds for where tool output goes: an Allow whose disclosure named
        another destination, or none, records nothing either. And for where the
        words go (owner, 2026-10-02): an Allow binds to `words_destination`, so
        one whose disclosure named another, or none where one is named now, is
        refused before it could bind to a destination the reader never saw.
        The Claude model on every press must also match the selection the page
        drew; a stale or missing selection records no Allow and spends nothing.
        """
        route = runtime_reading_route.resolve(harness, config=self.server.application.config)
        allow = payload.get("allow") is True
        refusal = (
            (503, route["reason"])
            if not route["provider"]
            else (409, "provider-changed")
            if payload.get("provider") != route["provider"]
            else (400, PAGE_OUTDATED_REASON)
            if allow and "words_destination" not in payload
            else (409, "destination-changed")
            if allow
            and (
                payload.get("words_destination", "") != route["words_destination"]
                or (route["destination"] and payload.get("tool_output") != route["destination"])
            )
            else (409, "destination-changed")
            if route["provider"] == runtime_reading_route.CLAUDE
            and payload.get("model") != route["model"]
            else None
        )
        if refusal is None:
            return route
        code, reason = refusal
        if reason == PAGE_OUTDATED_REASON:
            route = _outdated_route(route)
        self._send(
            self._reading_json({"ok": False, "produced": False, "reason": reason, "route": route}),
            "application/json",
            code,
        )
        return None

    def _keep(self, harness: str, sid: str, payload: dict[str, Any]) -> bool:
        """ "Keep my intent and analyze": settle first, and answer 422 if that is refused.

        Before the route, the permission and the job, so a press that then
        cannot start an analysis -- another provider, the budget, one already
        in flight -- has still settled, as the owner ruled for DRC-4682. Over
        an unsaved draft the adoption rides in the same store write
        (`annotations.adopt`), and the adoption later in this press is then
        only checked, never repeated. Every reply after this carries the
        store's token as `settled`.
        """
        application = self.server.application
        through = payload.get("settle_through")
        expected = payload.get("expected_revision")
        # The settlement's own stamp, so the job can tell this press's
        # settlement from one written after it (`_composes_what_was_pressed`).
        now = application.clock()
        self._keep_at = now
        outcome = (
            self._adopt_prompt(harness, sid, payload, settle_through=through, now=now)
            if "adopt" in payload
            else annotation_store.settle(
                application.config,
                application.state,
                harness,
                sid,
                through=through,
                now=now,
                expected_revision=expected,
                diagnostic_sink=application.diagnostic_sink,
            )
            if isinstance(expected, int) and not isinstance(expected, bool)
            else annotation_store.OUTCOME_REFUSED
        )
        self._keep_outcome = outcome
        if outcome in {annotation_store.OUTCOME_STORED, annotation_store.OUTCOME_UNCHANGED}:
            return True
        self._send(
            self._reading_json({"ok": False, "produced": False, "adoption_refused": True}),
            "application/json",
            422,
        )
        return False

    def _reading_json(self, answer: dict[str, Any]) -> bytes:
        """One reading-route reply, with Keep's settlement token when this press carried one."""
        settled = self._keep_outcome
        return json.dumps(
            {**answer, "settled": settled} if settled is not None else answer,
            separators=(",", ":"),
        ).encode()

    def _reading_adoption(
        self,
        harness: str,
        sid: str,
        payload: dict[str, Any],
        route: runtime_reading_route.Route,
    ) -> None:
        if "adopt" in payload and self._keep_outcome is None:
            outcome = self._adopt_prompt(harness, sid, payload)
            if outcome not in {annotation_store.OUTCOME_STORED, annotation_store.OUTCOME_UNCHANGED}:
                self._send(
                    json.dumps({"ok": False, "produced": False, "adoption_refused": True}).encode(),
                    "application/json",
                    422,
                )
                return
        self._send_reading(harness, sid, route, adoption=payload if "adopt" in payload else None)

    def _adopt_prompt(
        self,
        harness: str,
        sid: str,
        payload: dict[str, Any],
        *,
        standalone: bool = False,
        settle_through: Any = None,
        now: float | None = None,
        receipt: dict[str, int] | None = None,
    ) -> str:
        application = self.server.application
        expected = payload.get("expected_revision")
        # Keep names its revision as Looks right does (`annotations.adopt`).
        guarded = standalone or settle_through is not None
        if guarded and (isinstance(expected, bool) or not isinstance(expected, int)):
            return annotation_store.OUTCOME_REFUSED
        # Read the source again rather than accepting client-authored provenance.
        application.state.snapshot.clear()
        _, body = application.collect_json(show_all=False)
        rows = [
            row
            for row in json.loads(body)["sessions"]
            if row.get("harness") == harness and row.get("sid") == sid
        ]
        if len(rows) != 1:
            return annotation_store.OUTCOME_REFUSED
        source = str(payload.get("adopt") or "")
        return annotation_store.adopt(
            application.config,
            application.state,
            rows[0],
            source=source,
            expected_text=payload.get("expected_prompt"),
            expected_at=payload.get("expected_prompt_at"),
            now=application.clock() if now is None else now,
            expected_revision=expected if guarded else None,
            settle_through=settle_through,
            receipt=receipt,
            chosen=(
                self._chosen_prompt(rows[0], payload.get("prompt_fact"))
                if source == runtime_reading.PROMPT_CHOSEN
                else None
            ),
        )

    def _chosen_prompt(
        self, row: dict[str, Any], fact_id: Any
    ) -> annotation_store.PromptChoice | None:
        """The server's own choice for the fact id the page sent, or None (Q7).

        Resolve one of the five menu prompts or an explicitly selected later
        direction from this session's own record. The final adoption checks
        the offered words, source time and revision again before writing.
        """
        if not isinstance(fact_id, str) or not fact_id:
            return None
        choices = annotation_store.prompt_choices(
            row,
            _prompt_facts(self.server.application, row, self._session_facts(row)),
            self.server.application.config.annotation_text_cap_chars,
        )
        choice = next((choice for choice in choices if choice["fact_id"] == fact_id), None)
        if choice is not None:
            return choice
        found = self._later_direction(row, fact_id)
        if found is None:
            return None
        at, words, cut = found
        return annotation_store.prompt_choice(
            fact_id, at, words, self.server.application.config.annotation_text_cap_chars, cut=cut
        )

    def _session_row(self, harness: str, sid: str) -> dict[str, Any] | None:
        """This session's published row, or None. See `_published_row`."""
        return self._published_row(harness, sid)

    def _published_row(self, harness: str, sid: str) -> dict[str, Any] | None:
        """This session's row as the board publishes it, or None.

        The default variant first, which is warm within `collect_memo_sec`, and
        the all-sessions one only when the default lacks the row: a reader can
        act from that view, and the default one leaves an aged session out. No
        clear, so the staleness floor is exactly a GET's (owner, 2026-10-02:
        the clear made every save a full all-sessions collection, about 900 ms
        of it). A row that old is what the page drew from, and what a save
        reads off it does not age: a direction's text and a window start's
        facts are read from the transcript again whatever the row's age, and
        the row supplies only identity, paths and the prompt fields
        `direction_floor` reads. The adoption arm keeps its own clear.
        """
        application = self.server.application
        for show_all in (False, True):
            _, body = application.collect_json(show_all=show_all)
            rows = [
                row
                for row in json.loads(body)["sessions"]
                if row.get("harness") == harness and row.get("sid") == sid
            ]
            if rows:
                return rows[0] if len(rows) == 1 else None
        return None

    def _later_direction(
        self,
        row: dict[str, Any],
        fact_id: str,
        adopt_source: str | None = None,
        refusal: dict[str, str] | None = None,
        lookup: runtime_project_context.DirectionLookup | None = None,
        listed_facts: list[dict[str, Any]] | None = None,
    ) -> tuple[float, str, bool] | None:
        """A later direction's time, whole raw text and whether it was cut, or None.

        Every check is the server's own: the fact must be a person's message
        in THIS session's published record, later than the words it would join
        (`annotations.direction_floor`), with its whole text read again from
        the bounded source (`project_context.direction_text`). A direction
        outside that bound is refused rather than stood in for by its summary
        (`annotations.direction_floor` cites the ruling).
        """
        application = self.server.application
        harness, sid = str(row.get("harness")), str(row.get("sid"))
        entry = annotation_store.find(
            annotation_store.active(application.config, application.state), harness, sid
        )
        floor = annotation_store.direction_floor(entry, row, adopt_source)
        if floor is None:
            return None
        lookup = lookup or runtime_project_context.direction_lookup(
            application.config, application.state, harness, sid, fact_id
        )
        if refusal is not None and lookup.reason:
            refusal["reason"] = lookup.reason
        if not lookup.words.text.strip():
            # A known earlier request is not out of reach, even when this read
            # misses it. Successful native reads already prove identity, author
            # and time; recomposing the project for each Keep source exceeded
            # the control deadline on the real long-session scratch board.
            listed = next(
                (
                    f
                    for f in (
                        listed_facts if listed_facts is not None else self._session_facts(row)
                    )
                    if f.get("fact_id") == fact_id
                ),
                None,
            )
            listed_at = runtime_reading.valid_prompt_time(listed.get("at")) if listed else None
            if (
                refusal is not None
                and listed is not None
                and (listed_at is None or listed_at <= floor)
            ):
                refusal["reason"] = "not_found"
            return None
        fact = lookup.fact
        if not isinstance(fact, dict):
            return None
        marked = copied_corrections.mark({"semantic": {"facts": [fact]}}, [row])
        fact = marked["semantic"]["facts"][0]
        if (
            fact.get("type") != "user_message"
            or fact.get("source_session") != {"harness": harness, "sid": sid}
            or fact.get(runtime_reading.COPIED_FLAG) is True
            or fact.get("at") != lookup.at
        ):
            return None
        at = runtime_reading.valid_prompt_time(fact.get("at"))
        if at is None or at <= floor:
            return None
        return at, lookup.words.text, lookup.words.cut

    def _add_direction(self, harness: str, sid: str, payload: dict[str, Any]) -> str:
        """The `add_direction` arm: a verified later direction saved as an outcome line.

        On `/api/annotate` rather than a route of its own, for the settle
        arm's reason: the same session's annotation and the same reply. The
        fact is re-validated exactly as `POST /api/direction` opened it.
        """
        application = self.server.application
        row = self._session_row(harness, sid)
        adopt = payload.get("adopt")
        fact_id = str(payload.get("add_direction") or "")
        found = (
            self._later_direction(row, fact_id, adopt if isinstance(adopt, str) else None)
            if row is not None and fact_id
            else None
        )
        if row is None or found is None:
            return annotation_store.OUTCOME_REFUSED
        now = application.clock()
        return annotation_store.add_direction(
            application.config,
            application.state,
            row,
            source_id=fact_id,
            text=payload.get("text"),
            entry_at=found[0],
            expected_revision=payload.get("expected_revision"),
            now=now,
            replace=payload.get("replace"),
            adopt=adopt,
            expected_prompt=payload.get("expected_prompt"),
            expected_prompt_at=payload.get("expected_prompt_at"),
            window_start=self._typed_window_start(harness, sid, now),
            diagnostic_sink=application.diagnostic_sink,
            source_facts=_request_sources(application, row, self._session_facts(row)),
        )

    def _direction(self) -> None:
        """Open later directions' whole text for review (DRC-4682).

        Reads and writes nothing but the reply: the page opens the direction
        as a pending outcome line, and only the `add_direction` arm of
        `/api/annotate` saves one. Guarded as the reading route is, by the
        navigation and loopback-resource refusals, because this reply carries
        more of a prompt than any published field: the whole message, redacted
        and bounded, where the record holds its first sentence. Every
        direction it will not open answers one 200 body, never a 404, for
        `_focus`'s ruling.
        """
        application = self.server.application
        config = application.config
        if not config.annotations_enabled:
            self._reject(503)
            return
        if self._is_document_navigation() or not self._loopback_resource_ok():
            self._reject(403)
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = -1
        if not 0 <= length <= config.annotation_body_cap_bytes:
            self._reject(413)
            return
        try:
            payload = json.loads(self._read_body(length) or b"{}")
        except (ValueError, json.JSONDecodeError, RecursionError):
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        harness, sid = payload.get("harness"), payload.get("sid")
        if not all(isinstance(part, str) and part for part in (harness, sid)):
            self._reject(400)
            return
        batch = "fact_ids" in payload
        ids = payload.get("fact_ids") if batch else [payload.get("fact_id")]
        if (
            not isinstance(ids, list)
            or not ids
            or (batch and ("fact_id" in payload or len(ids) > 64))
            or not all(
                isinstance(part, str) and part and (not batch or len(part) <= 256) for part in ids
            )
        ):
            self._reject(400)
            return
        row = self._session_row(str(harness), str(sid))
        lookups = (
            runtime_project_context.direction_lookups(
                config, application.state, str(harness), str(sid), ids
            )
            if batch and row is not None
            else [None] * len(ids)
        )
        listed_facts = (
            self._session_facts(row)
            if batch
            and row is not None
            and any(lookup and not lookup.words.text.strip() for lookup in lookups)
            else None
        )
        answers = [
            self._direction_answer(row, str(harness), fact_id, lookup, listed_facts)
            for fact_id, lookup in zip(ids, lookups, strict=True)
        ]
        answer = {"results": answers} if batch else answers[0]
        self._send(json.dumps(answer, separators=(",", ":")).encode(), "application/json")

    def _direction_answer(
        self,
        row: dict[str, Any] | None,
        harness: str,
        fact_id: str,
        lookup: runtime_project_context.DirectionLookup | None,
        listed_facts: list[dict[str, Any]] | None,
    ) -> dict[str, Any]:
        config = self.server.application.config
        refusal = {"reason": "not_found"}
        found = (
            self._later_direction(
                row, fact_id, refusal=refusal, lookup=lookup, listed_facts=listed_facts
            )
            if row is not None
            else None
        )
        if found is None:
            answer: dict[str, Any] = {
                "ok": False,
                "reason": refusal["reason"],
                "why": _DIRECTION_WHY.get(refusal["reason"], _DIRECTION_WHY["not_found"]),
            }
        else:
            text, clipped, fits = annotation_store.direction_review(
                found[1], config.annotation_text_cap_chars, cut=found[2]
            )
            answer = {
                "ok": True,
                "fact_id": fact_id,
                "text": text,
                "clipped": clipped,
                "fits": fits,
                "goal_choice": annotation_store.prompt_choice(
                    str(fact_id), found[0], found[1], config.annotation_text_cap_chars, cut=found[2]
                )
                if harness in annotation_store.ADOPTION_HARNESSES
                and not records.harness_control(found[1])
                else None,
            }
        return answer

    def _correction(self) -> None:
        """Compose Steer back's correction for one session (DRC-4681).

        Stores nothing of its own. It reads: the reply is what
        `correction.compose` builds from the session's published row, its
        observed record and the later-direction floor, never from anything the
        page sends beyond which session. The collection `_session_row` runs may
        rewrite the semantic history store, as `/api/direction`'s does.
        Guarded as `POST /api/direction` is, because the reply carries the
        reader's whole goal and lines. Every session it will not compose for
        answers one 200 body, for `_focus`'s ruling.
        """
        application = self.server.application
        config = application.config
        if not config.annotations_enabled:
            self._reject(503)
            return
        if self._is_document_navigation() or not self._loopback_resource_ok():
            self._reject(403)
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = -1
        if not 0 <= length <= config.annotation_body_cap_bytes:
            self._reject(413)
            return
        try:
            payload = json.loads(self._read_body(length) or b"{}")
        except (ValueError, json.JSONDecodeError, RecursionError):
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        harness, sid = payload.get("harness"), payload.get("sid")
        if not all(isinstance(part, str) and part for part in (harness, sid)):
            self._reject(400)
            return
        row = self._session_row(str(harness), str(sid)) if harness in correction.HARNESSES else None
        # An unknown session and another harness answer what a session with nothing to steer
        # from does, so a refusal says nothing about which sessions exist.
        answer: dict[str, Any] = {"ok": False, "reason": correction.REASON_NOTHING}
        if row is not None:
            entry = annotation_store.find(
                annotation_store.active(config, application.state), str(harness), str(sid)
            )
            route = runtime_reading_route.resolve(str(harness), config=config)
            context = _session_context(self.server.application, row)
            latest = entry["revisions"][-1] if entry and entry["revisions"] else None
            request_sources = (
                _request_sources(application, row, _facts_of(context), entry)
                if latest and latest["n"] == row.get("annotation_revision")
                else []
            )
            answer = correction.compose(
                row,
                _facts_of(context),
                person_at=_scan_of(context, str(harness), str(sid)).get("last_user_at"),
                floor=annotation_store.direction_floor(entry, row),
                line_requests=runtime_reading.line_request_floors(
                    latest, request_sources, str(harness), str(sid)
                )
                if latest
                else {},
                # The agent's messages carry a line verdict where no check can be sent
                # (owner ruling, 2026-10-03), as the previous page's `nextReadingOutputLimit` says.
                lines_judged=bool(
                    route["provider"]
                    and (
                        route["destination"]
                        or harness in runtime_project_context.AGENT_MESSAGE_HARNESSES
                    )
                ),
            )
        self._send(json.dumps(answer, separators=(",", ":")).encode(), "application/json")

    def _correction_copied(self) -> None:
        """Record that the reader copied this correction for this session (DRC-4678).

        Guarded as `POST /api/direction` and the reading route are: 503 under
        `--no-annotations`, whose flag turns the store off, and refused to a
        document navigation and to a same-site or cross-site fetch, because a
        forged copy would let a page mark the reader's next message as
        Compass's. Every accepted registration answers one body, whether the
        session exists, whether its messages are read and whether the text was
        copied before, so the reply tells a caller nothing it did not send.
        """
        # The copy is the press, so it is timed on arrival: a board collection and
        # a lock wait come after, and a paste inside them would be dated before it.
        now = self.server.application.clock()
        application = self.server.application
        config = application.config
        if not config.annotations_enabled:
            self._reject(503)
            return
        if self._is_document_navigation() or not self._loopback_resource_ok():
            self._reject(403)
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = -1
        if not 0 <= length <= config.annotation_body_cap_bytes:
            self._reject(413)
            return
        try:
            payload = json.loads(self._read_body(length) or b"{}")
        except (ValueError, json.JSONDecodeError, RecursionError):
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        harness, sid, text = payload.get("harness"), payload.get("sid"), payload.get("text")
        if (
            not all(isinstance(part, str) and part for part in (harness, sid))
            or not isinstance(text, str)
            or len(text) > copied_corrections.CORRECTION_CAP_CHARS
            or not copied_corrections.normalise(text)
        ):
            self._reject(400)
            return
        outcome = copied_corrections.OUTCOME_REFUSED
        if harness in copied_corrections.HARNESSES:
            outcome = self._register_copy(str(harness), str(sid), text, now)
        unwritable = outcome == copied_corrections.OUTCOME_UNWRITABLE
        self._send(
            json.dumps({"ok": not unwritable}, separators=(",", ":")).encode(),
            "application/json",
            503 if unwritable else 200,
        )

    def _register_copy(self, harness: str, sid: str, text: str, now: float) -> str:
        """Register a copy for a session the board publishes; returns the store's outcome."""
        application = self.server.application
        # Where the transcript ends is read before the lookup's collection too, for the
        # clock's reason: only a message past it can match.
        position = copied_corrections.transcript_position(
            application.config, application.state, harness, sid
        )
        if not self._session_row(harness, sid):
            return copied_corrections.OUTCOME_REFUSED
        outcome = copied_corrections.register(
            application.config,
            harness,
            sid,
            text,
            now=now,
            position=position,
            diagnostic_sink=application.diagnostic_sink,
        )
        # The lookup's own collection is memoised, and a paste written while it ran is in it
        # unrecognised, so a board read next would show that paste as the reader's words.
        if outcome == copied_corrections.OUTCOME_STORED:
            application.state.snapshot.clear()
        return outcome

    def _reading_permission_reply(
        self,
        answer: reading_policy.Status,
        *,
        off: bool = False,
        route: runtime_reading_route.Route | None = None,
    ) -> None:
        self.server.application.state.snapshot.clear()
        reason = answer["reason"]
        code = (
            200
            if off and reason != "store-unavailable"
            else 429
            if reason == "daily-cap"
            else 503
            if reason in {"store-unavailable", "run-disabled"}
            else 403
        )
        reply: dict[str, Any] = {"ok": code == 200, "produced": False, "reading": answer}
        if route is not None:
            # The press's own route, resolved now, so a page drawn before the
            # destination moved shows the changed line over today's `To:`
            # rather than over the one it drew (regressions minor 2, ui5).
            reply["route"] = route
        self._send(self._reading_json(reply), "application/json", code)

    def _send_reading(
        self,
        harness: str,
        sid: str,
        route: runtime_reading_route.Route,
        *,
        adoption: dict[str, Any] | None = None,
    ) -> None:
        """Produce, store and answer. Split for the complexity cap alone."""
        application = self.server.application
        config = application.config
        state = application.state
        _revision, body = application.collect_json(show_all=False)
        rows = [
            row
            for row in json.loads(body)["sessions"]
            if row.get("harness") == harness and row.get("sid") == sid
        ]
        # From disk under the store's lock, the entry the job is handed: the
        # cache can miss this press's own adoption, when a collection that read
        # the store before it assigned its copy after (the a11y lens's Keep over
        # a draft), and a save another dashboard made since the check.
        entries = annotation_store.fresh(config, state, application.diagnostic_sink)
        entry = annotation_store.find(entries or (), harness, sid)
        if not rows or entry is None:
            self._send(
                self._reading_json(
                    {"ok": True, "produced": False, "reason": "no annotated session by that name"}
                ),
                "application/json",
            )
            return
        if not self._composes_what_was_pressed(entry, adopted=adoption is not None):
            self._revision_changed()
            return
        if adoption is not None and not self._adoption_matches(entry, adoption):
            self._send(
                self._reading_json({"ok": False, "produced": False, "adoption_refused": True}),
                "application/json",
                422,
            )
            return
        if self._press_withheld(rows[0], entry):
            return
        key = f"{harness}:{sid}"
        job = runtime_reading.start_job(
            config, key, provider=route["provider"], label=route["label"], now=application.clock()
        )
        if job is None:
            # One in flight per session, and no retry: a second press starts
            # nothing and is handed the running job to show. A slot the unasked
            # lane holds has no job, and none is invented for it.
            running = runtime_reading.published_jobs(config).get(key)
            self._send(
                self._reading_json(
                    {
                        "ok": False,
                        "produced": False,
                        "reason": "in-flight",
                        **({"job": running} if running else {}),
                    }
                ),
                "application/json",
                409,
            )
            return
        # Taken before the thread starts, which may finish before this reply.
        started = runtime_reading.published_jobs(config)[key]
        row, found = rows[0], entry
        try:
            runtime_reading_jobs.launch(
                application, job, lambda hooks: self._compose_reading(row, found, route, hooks)
            )
        except RuntimeError:
            # No thread to run it on; `launch` has already freed the slot, so
            # the next press can start one. Nothing was spent. A Keep press
            # has settled by now, so its reply says so rather than a bare 503.
            if self._keep_outcome is None:
                self._reject(503)
            else:
                self._send(
                    self._reading_json({"ok": False, "produced": False, "reason": "no-thread"}),
                    "application/json",
                    503,
                )
            return
        self._send(
            self._reading_json({"ok": True, "job": started}),
            "application/json",
            202,
        )

    def _press_withheld(self, row: dict[str, Any], entry: annotation_store.Annotation) -> bool:
        """Answer a press the board already says cannot read, before any job, and say so.

        The same `reading.press_eligibility` the collection publishes as
        `reading_eligibility` and the job's own `eligibility` call reads, so the
        page, this check and the job cannot disagree (DRC-4758 slice A2). 200
        and not 202: nothing started, nothing was spent, and no attempt is
        counted. Recorded nowhere, because the published eligibility already
        says it on every collection. A recorded Allow stands, as it did when
        the job withheld this later.
        """
        application = self.server.application
        answer = runtime_reading.press_eligibility(
            row,
            entry["revisions"],
            now=application.clock(),
            settle_sec=application.config.reading_settle_sec,
        )
        reason = answer["reason"]
        if reason is None:
            return False
        self._send(
            self._reading_json(
                {
                    "ok": False,
                    "produced": False,
                    "reason": "withheld",
                    "withheld": reason,
                    "sentence": answer["sentence"],
                    "until": answer["until"],
                }
            ),
            "application/json",
        )
        return True

    def _adoption_matches(
        self, entry: annotation_store.Annotation, payload: dict[str, Any]
    ) -> bool:
        latest = entry["revisions"][-1] if entry["revisions"] else None
        return bool(
            latest
            and latest.get("goal_source") == payload.get("adopt")
            and latest.get("goal_source_at") == payload.get("expected_prompt_at")
            and latest["goal"]
            == records.safe_text(
                payload.get("expected_prompt"),
                self.server.application.config.annotation_text_cap_chars,
            )
        )

    def _compose_reading(
        self,
        row: dict[str, Any],
        entry: annotation_store.Annotation,
        route: runtime_reading_route.Route,
        hooks: runtime_reading_jobs.Hooks,
    ) -> tuple[runtime_reading.Assessment | None, str, bool]:
        """The model lane, with the observed record it reads.

        The route resolved before consent is the route that runs: one model,
        built here from it, and no second provider if that one is missing at
        launch or fails. A fresh press is the only retry.
        """
        application = self.server.application
        transcript = (
            runtime_observer.resolve_transcript(
                application.config, application.state, str(row.get("harness")), str(row.get("sid"))
            )
            or ""
        )
        press_stamp = runtime_project_context.transcript_stamp(transcript)
        # The window of the revision being read, not the previous reading's: a first press has no
        # stored one, and an edited Goal has moved it.
        revisions = entry["revisions"]
        reach = (
            runtime_project_context.PressWindow(
                runtime_reading.window_start(revisions[-1]), press_stamp
            )
            if revisions and press_stamp is not None
            else None
        )
        context = _session_context(application, row, reach)
        # What the press read back and the project cap kept, where it read back; else the tail's.
        reached = (context.get("sources") or {}).get("message_reach")
        return runtime_reading.produce(
            application.config,
            row,
            entry["revisions"],
            _facts_of(context),
            record_coverage_lookup=lambda: (
                dict(reached)
                if reached
                else runtime_project_context.transcript_tail_coverage(
                    application.config,
                    transcript,
                    expected_stamp=press_stamp,
                )
                if press_stamp is not None
                else {}
            ),
            goal_source_lookup=lambda: runtime_project_context.transcript_user_facts(
                application.config,
                application.state,
                transcript,
                str(row.get("harness")),
                str(row.get("sid")),
                goal_choices=True,
            ),
            person_source_lookup=(
                (
                    lambda wanted: (
                        runtime_project_context.transcript_window_words(
                            application.config,
                            transcript,
                            str(row.get("harness")),
                            str(row.get("sid")),
                            wanted,
                            expected_stamp=press_stamp,
                        )
                        if press_stamp is not None
                        else []
                    )
                )
                if row.get("harness") in {"claude", "codex"}
                else None
            ),
            # The newest recorded final reply, read whole from the source version stamped
            # above, before the context read: a file that moved since is refused there.
            # Only this press carries it; the unasked lane never builds this call.
            final_source_lookup=(
                (
                    lambda wanted: runtime_project_context.transcript_newest_final_words(
                        application.config,
                        transcript,
                        str(row.get("harness")),
                        str(row.get("sid")),
                        wanted,
                        expected_stamp=press_stamp,
                    )
                )
                if press_stamp is not None
                and row.get("harness") in runtime_project_context.AGENT_MESSAGE_HARNESSES
                else None
            ),
            # A record never read withholds in its own sentence, not as an
            # empty one (DRC-4689).
            record_withheld=runtime_reading.record_withheld(
                context, str(row.get("harness")), str(row.get("sid"))
            ),
            # The one caller that reads the outcome lines: the reader pressed
            # for this reading (item 12 of the ruling
            # `reading.MAX_OUTCOME_LINES` cites keeps them from
            # every other).
            read_lines=True,
            # And the one that sends what the agent said: the unasked lane
            # keeps the default and sends none of it (review, 2026-10-03).
            read_agent_words=True,
            # And the one that may read a turn stop, on the harnesses the
            # ruling `reading.TURN_STOP_HARNESSES` cites names; the unasked
            # lane keeps the closed default.
            admit_turn_stop=str(row.get("harness")) in runtime_reading.TURN_STOP_HARNESSES,
            # The job's phases, each told where it really begins (DRC-4686).
            on_phase=hooks.phase,
            **self._reading_arguments(row, entry, route, hooks),
        )

    def _session_facts(self, row: dict[str, Any]) -> list[Any]:
        """The observed record for one session, without refreshing anything."""
        return _facts_of(_session_context(self.server.application, row))

    def _reading_arguments(
        self,
        row: dict[str, Any],
        entry: annotation_store.Annotation,
        route: runtime_reading_route.Route,
        hooks: runtime_reading_jobs.Hooks,
    ) -> dict[str, Any]:
        """Everything `produce` takes beyond the record, from the route that ran."""
        application = self.server.application
        harness, sid = str(row.get("harness")), str(row.get("sid"))
        tool_output = None
        where = route["destination"]
        if harness in runtime_reading_route.TOOL_OUTPUT_HARNESSES and not where:
            # Nothing to grant: the reading runs on the reader's words and its
            # cutoff says the checks were not sent and why (owner, Q5).
            tool_output = runtime_reading.ToolOutput(destination="", label=route["label"])
        elif harness in runtime_reading_route.TOOL_OUTPUT_HARNESSES and (
            reading_policy.tool_output_allowed(
                reading_policy.status(
                    application.config, now=application.clock(), provider=route["provider"]
                ),
                route["provider"],
                where,
            )
        ):
            # Re-read inside the press rather than taken from the payload: only
            # a stored grant for exactly this provider and destination admits
            # the checks, and their output tails are read here, at the press,
            # never from the published record.
            press = runtime_project_context.press_checks(
                application.config, application.state, harness, sid
            )
            tool_output = runtime_reading.ToolOutput(
                destination=where,
                label=route["label"],
                tails=press.tails,
                changed_after=press.changed_after,
                read_incomplete=press.read_incomplete,
                passes_and_writes=press.passes_and_writes,
            )
        elif harness in runtime_reading_route.TOOL_OUTPUT_HARNESSES:
            # Named, and no grant for it when the reading ran: never given, or
            # withdrawn in another tab after the press was admitted. The words
            # are read and the cutoff says the checks were not sent and why.
            tool_output = runtime_reading.ToolOutput(
                destination="", label=route["label"], allowed=False
            )
        return {
            "tool_output": tool_output,
            "now": application.clock(),
            # A discard record has no revisions, which is also what a session
            # nobody typed against has. `produce` is handed revisions and
            # cannot tell them apart, so the caller that holds the entry says
            # which (DRC-4565).
            "discarded": annotation_store.is_discarded(entry),
            # A stamp: what read it and when, from the route that ran. It once
            # carried a policy sentence, rendered where the design says a
            # stamp names the model and the moment. The policy belongs in the
            # route's disclosure above the button, seen BEFORE pressing.
            "stamp_text": (
                f"{route['model']} · read at "
                f"{time.strftime('%H:%M', time.localtime(application.clock()))}"
            ),
            "model": reading_policy.GuardedModel(
                application.config,
                (
                    runtime_reading.ClaudeReadingModel
                    if route["provider"] == runtime_reading_route.CLAUDE
                    else runtime_reading.CodexReadingModel
                )(application.config, on_spawn=hooks.spawned),
                application.clock,
                provider=route["provider"],
                destination=route["words_destination"],
                # The resolver the route came from, asked again at the
                # reservation, so the job checks today's value as the board does.
                resolve_destination=lambda: runtime_reading_route.destination(route["provider"]),
                on_reserved=hooks.reserved,
                before_reserve=hooks.before_reserve,
                cancelled=hooks.cancelled,
                content=_press_content(route["harness"]),
            ),
        }

    def _events(self, harness: str) -> None:
        """A harness's lifecycle events, forwarded by its own hook.

        The harness comes from the route, never from the body: a payload field
        naming its own source would let one adapter's token post as any harness.
        The route alone proves nothing about the caller, so the capability is
        checked as well, which is the difference between this and `/api/notify`.

        Order is deliberate. Unknown route first, so an unsupported harness is a
        404 and not an authentication oracle. Then the capability. Then the rate
        ceiling, which is independent of the token because a looping adapter holds
        a valid one by definition. Then the length, before any read.
        """
        coordinator = self.server.observation
        if coordinator is None or harness not in runtime_events.IDENTITY_NORMALIZERS:
            self._reject(404)
            return
        if not coordinator.authorized(harness, self.headers.get("X-Compass-Capability")):
            self._reject(403)
            return
        if not coordinator.within_budget(harness):
            self._reject(429)
            return
        config = self.server.application.config
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = -1
        if not 0 <= length <= config.event_body_cap_bytes:
            self._reject(413)
            return
        try:
            payload = json.loads(self._read_body(length) or b"{}")
        except (ValueError, json.JSONDecodeError, RecursionError):
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        outcome = coordinator.submit(harness, payload)
        # Always 200, even for a rejected envelope. The hook must not learn to
        # retry, and must never be the reason an agent session stalls; the
        # outcome string is for diagnostics.
        self._send(
            json.dumps({"ok": True, "outcome": outcome}, separators=(",", ":")).encode(),
            "application/json",
        )

    def _focus(self) -> None:
        """Raise the terminal one session is running in. Answers one boolean.

        The check order differs from `/api/events/<harness>` deliberately, and
        the difference is the whole security property. That route 404s an unknown
        harness BEFORE consulting the capability, because a harness name is
        public and an unsupported one is not an authentication oracle. **A
        session id is not public.** So here the capability comes first, then the
        rate ceiling, then the session lookup — getting it backwards would turn
        this route into an oracle for which sessions exist.

        The ceiling is claimed AFTER the body is read rather than before it, and
        that ordering is load-bearing too: `_read_body` is a blocking read with
        no socket timeout, so claiming the one-slot gate first let a peer that
        sent a `Content-Length` and then nothing hold focus shut for as long as
        it kept the socket open. Reading first takes no process-wide state on a
        request that may never finish, and the gate still precedes the raise,
        which is what "a repeated or looped request cannot repeat the raise"
        actually asks for. Nothing about the body distinguishes one session from
        another, so moving it ahead of the ceiling adds no oracle.

        The body names a session and a harness and never a target: the target
        comes from an authenticated event, and nothing in this body reaches an
        argv position. The answer is a single boolean, so an unknown session, a
        session with no terminal, a declined lookup and a failed command are all
        the same answer to a caller.
        """
        application = self.server.application
        config = application.config
        coordinator = self.server.observation
        if coordinator is None or not config.focus_enabled:
            # 503 rather than 404, for `/api/dismiss`'s reason: under `--no-focus`
            # or `--no-events` the route exists and the feature does not, and a
            # 404 would read as a build too old to have it. It leaks nothing
            # about sessions, being a run-wide fact.
            self._reject(503)
            return
        if not coordinator.focus_authorized(self.headers.get("X-Compass-Capability")):
            self._reject(403)
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = -1
        if not 0 <= length <= config.focus_body_cap_bytes:
            self._reject(413)
            return
        try:
            payload = json.loads(self._read_body(length) or b"{}")
        except (ValueError, json.JSONDecodeError, RecursionError):
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        harness, sid = payload.get("harness"), payload.get("sid")
        if not coordinator.claim_focus():
            # The floor and the in-flight gate together: a repeated or looped
            # request cannot repeat the raise.
            self._reject(429)
            return
        try:
            target = (
                coordinator.focus_target(harness, sid)
                if isinstance(harness, str) and isinstance(sid, str)
                else None
            )
            focused = target is not None and coordinator.raise_focus(target)
        finally:
            coordinator.release_focus()
        self._send(
            json.dumps({"focused": focused}, separators=(",", ":")).encode(),
            "application/json",
        )

    def do_POST(self) -> None:
        self._body_consumed = 0
        if not self._local_ok():
            self._reject(403)
            return
        path = urlparse(self.path).path
        # Prefix-matched, so it cannot join the exact-match table below.
        if path.startswith("/api/events/"):
            self._events(path[len("/api/events/") :])
            return
        if path.startswith("/api/interaction/"):
            self._interaction_post(path[len("/api/interaction/") :])
            return
        # A table rather than a ladder of ifs: every entry is one route to one
        # handler, and the ladder had grown to the point where the last branch
        # carried a whole request body inline while the ones above it did not.
        route = {
            "/api/shutdown": self._shutdown,
            "/api/usage": self._usage_receipt,
            "/api/dismiss": self._dismiss,
            "/api/tripwire": self._tripwire,
            "/api/annotate": self._annotate,
            "/api/direction": self._direction,
            "/api/correction": self._correction,
            "/api/correction/copied": self._correction_copied,
            "/api/reading": self._reading,
            "/api/reading/cancel": self._reading_cancel,
            "/api/focus": self._focus,
            "/api/ask": self._ask,
            "/api/ask/withdraw": self._withdraw,
            "/api/answer": self._answer,
            "/api/notify": self._notify,
            "/api/lane": self._lane,
        }.get(path)
        if route is None:
            self._reject(404)
            return
        route()

    def _interaction_post(self, route: str) -> None:
        prototype = self.server.interaction_prototype
        if prototype is None:
            self._reject(404)
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = -1
        if not 0 <= length <= 8_192:
            self._reject(413)
            return
        try:
            body = json.loads(self.rfile.read(length) or b"null")
        except (ValueError, json.JSONDecodeError, RecursionError):
            body = None
        if not isinstance(body, dict):
            self._reject(400)
            return
        handler = {
            "register": self._interaction_register,
            "renew": self._interaction_renew,
            "probe-unregistered": self._interaction_probe,
            "probe-spoofed": self._interaction_probe_spoofed,
            "control": self._interaction_reject_control,
            "input": self._interaction_reject_control,
            "expire": self._interaction_expire,
            "disconnect": self._interaction_disconnect,
            "reconnect": self._interaction_reconnect,
            "reset": self._interaction_reset,
        }.get(route)
        if handler is None:
            self._reject(404)
            return
        result = handler(prototype, body)
        if result is None:
            self._reject(400)
            return
        self._send(json.dumps(result, separators=(",", ":")).encode(), "application/json")

    def _interaction_register(
        self, prototype: InteractionPrototype, body: dict[str, Any]
    ) -> dict[str, Any] | None:
        if set(body) != {"registration_token", "compass_session_id", "origin"}:
            return None
        token, session_id = body.get("registration_token"), body.get("compass_session_id")
        if not isinstance(token, str) or not isinstance(session_id, str):
            return None
        return prototype.register(token, session_id, body.get("origin"), now=time.monotonic())

    def _interaction_renew(
        self, prototype: InteractionPrototype, body: dict[str, Any]
    ) -> dict[str, Any] | None:
        if set(body) != {"origin_id", "lease_token"}:
            return None
        origin_id, lease_token = body.get("origin_id"), body.get("lease_token")
        if not isinstance(origin_id, str) or not isinstance(lease_token, str):
            return None
        return prototype.renew(origin_id, lease_token, now=time.monotonic())

    def _interaction_reject_control(
        self, _prototype: InteractionPrototype, _body: dict[str, Any]
    ) -> dict[str, str]:
        return {"state": "refused", "reason": "read-only-capability"}

    def _interaction_probe(
        self, prototype: InteractionPrototype, body: dict[str, Any]
    ) -> dict[str, Any] | None:
        return prototype.probe_unregistered() if not body else None

    def _interaction_probe_spoofed(
        self, prototype: InteractionPrototype, body: dict[str, Any]
    ) -> dict[str, Any] | None:
        return prototype.probe_spoofed() if not body else None

    def _interaction_expire(
        self, prototype: InteractionPrototype, body: dict[str, Any]
    ) -> dict[str, Any] | None:
        return prototype.expire(self.server.server_port) if not body else None

    def _interaction_disconnect(
        self, prototype: InteractionPrototype, body: dict[str, Any]
    ) -> dict[str, Any] | None:
        return prototype.disconnect(self.server.server_port) if not body else None

    def _interaction_reconnect(
        self, prototype: InteractionPrototype, body: dict[str, Any]
    ) -> dict[str, Any] | None:
        return prototype.reconnect(self.server.server_port) if not body else None

    def _interaction_reset(
        self, prototype: InteractionPrototype, body: dict[str, Any]
    ) -> dict[str, Any] | None:
        return prototype.reset(self.server.server_port) if not body else None

    def _notify(self) -> None:
        """Claude Code's Notification hook: {"session_id": ..., "message": ..., ...}."""
        application = self.server.application
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = -1
        # Checked before the read, so an oversized declared length costs nothing
        # and no path here ever reads an unbounded body.
        if not 0 <= length <= application.config.notification_body_cap_bytes:
            self._reject(413)
            return
        try:
            payload = json.loads(self._read_body(length) or b"{}")
        except (ValueError, json.JSONDecodeError, RecursionError):
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        response = notifications.handle_payload(
            application.config,
            application.state,
            payload,
            now=time.time(),
            popup_notifier=application.popup_notifier,
        )
        # Compact separators: the notify response is a fixed wire format, and the
        # hook and race tests assert the exact bytes. json.dumps' default spaces
        # would break them.
        self._send(json.dumps(response, separators=(",", ":")).encode(), "application/json")

    def _ask_unavailable(self, reason: str, *, body_read: bool) -> None:
        """Refuse an ask route at 503, saying which kind of no this is.

        503 for both reasons, because both are honest "not right now" answers
        rather than anything the caller got wrong. What the machine-readable
        reason adds is whether waiting helps: a `disabled` build will never take
        a question and a `busy` one will as soon as a slot frees. A bare 503 was
        indistinguishable from a wrong port, and the stdio server read it as one:
        it walked on to the next candidate and registered the question on a
        second dashboard that had the lane switched on, defeating `--no-ask`.

        `_reject` cannot carry a body, hence `_send` at 503. The drain `_reject`
        would have done is conditional here: on the refusal that happens before
        the body is read it is still required, because closing a socket over
        unread inbound data makes the OS send RST and the reply already written
        can be discarded. After the body has been read it would be actively
        wrong, since a second read on a keep-alive connection would consume the
        next request's bytes.
        """
        if not body_read:
            self._drain_body()
        self._send(
            json.dumps({"ok": False, "reason": reason}, separators=(",", ":")).encode(),
            "application/json",
            503,
        )

    @staticmethod
    def _ask_options(value: Any, *, cap_chars: int, max_options: int) -> tuple[str, ...] | None:
        """The offered options, bounded in count and length, or None if unusable.

        Past `max_options` the leading options are kept rather than a sample,
        and an option that bounds to empty refuses the whole request rather than
        being dropped. Both follow from the answer being an index: the asking
        peer resolves it against its own copy of the list, so keeping a prefix
        stays aligned with that copy while dropping a member from the middle
        would silently shift every later index onto the wrong option.

        A non-string member is refused rather than coerced. `records.safe_text`
        does `str(value or "")`, so it does not fail on one: `[{"a": 1}]`
        published the label `{'a': 1}`, and falsiness rather than type decided
        the rest, which is why `[1, 2]` was accepted while `[0, 1]` was refused.
        The answer is an index into this tuple, so a stringified option is a
        choice the asking session never offered.
        """
        if not isinstance(value, list):
            return None
        offered = value[:max_options]
        if not all(isinstance(item, str) for item in offered):
            return None
        options = tuple(records.safe_text(item, cap_chars).strip() for item in offered)
        # Two is the floor for a question worth putting on the board: one option
        # is not a choice, and nothing can be rendered from an empty list.
        return None if len(options) < 2 or not all(options) else options

    def _ask(self) -> None:
        """Register a question a session is holding its tool call open for.

        Guarded exactly like `/api/dismiss`: `_local_ok()` has already run, the
        declared length is checked before any read, and a malformed or non-object
        body degrades to `{}`.

        Where it differs is that an unusable body is a 400 rather than a 200
        no-op, and the difference is the point. A dismissal naming nothing has
        nothing to do; a caller here is about to wait for an answer, and has to
        learn now that none is coming rather than after the deadline.

        This route also owns the server half of the ask notification, below the
        reply. The browser half is gated by `native_notify` in the payload, which
        is the same reading this makes — exactly one layer alerts for one
        question.

        This is the only place the question and the options are bounded. `asks`
        imports nothing, so it cannot reach `records.safe_text`, and every field
        read below was written by an agent.
        """
        application = self.server.application
        config = application.config
        if not config.ask_enabled:
            self._ask_unavailable("disabled", body_read=False)
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = -1
        if not 0 <= length <= config.ask_body_cap_bytes:
            self._reject(413)
            return
        try:
            payload = json.loads(self._read_body(length) or b"{}")
        except (ValueError, json.JSONDecodeError, RecursionError):
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        raw_question = payload.get("question")
        # Type-checked before it is bounded, for the reason `_ask_options` gives:
        # `safe_text` would turn a non-string into its Python repr and publish
        # that as the question. Falling through to the empty string keeps one 400
        # path for every unusable body.
        question = (
            records.safe_text(raw_question, config.ask_question_cap_chars).strip()
            if isinstance(raw_question, str)
            else ""
        )
        options = self._ask_options(
            payload.get("options"),
            cap_chars=config.ask_option_cap_chars,
            max_options=config.ask_max_options,
        )
        if not question or options is None:
            self._reject(400)
            return
        label_cap = config.ask_option_cap_chars
        ask = runtime_asks.PendingAsk(
            # harness and session_id share the option cap: they really are short
            # labels of the same order. `project` does not, and gets its own knob
            # below, because it is a filesystem path.
            harness=records.safe_text(payload.get("harness"), label_cap).strip(),
            session_id=records.safe_text(payload.get("session_id"), label_cap).strip(),
            project=self._ask_project(payload.get("project")),
            question=question,
            options=options,
            created=application.clock(),
        )
        if not application.state.asks.register(
            ask,
            limit=config.ask_max_pending,
            deadline=config.ask_deadline_sec,
            retention=config.ask_retention_sec,
        ):
            self._ask_unavailable("busy", body_read=True)
            return
        # The published bodies are dropped rather than waited out, exactly as a
        # dismissal drops them.
        application.state.snapshot.clear()
        # Dropping the body is not a wake path on its own: nothing collects until
        # something asks it to, and a dashboard with no browser tab open asks for
        # nothing. Measured before this call existed: 18.2 to 22.3 s to first
        # render on the default build, where the page's own 20-second fallback
        # poll was what eventually noticed.
        #
        # After `register` has returned, and never inside it: `note_ask` takes
        # `Observation._lock`, and `_due` reads the registry while holding that
        # lock, so this is the only order that stays acyclic. `AskRegistry` and
        # `Observation.note_ask` carry the same note.
        #
        # None under `--no-events`, where there is no coordinator to wake and
        # `lifecycle.run_producer` is collecting on its own timer instead.
        coordinator = self.server.observation
        if coordinator is not None:
            coordinator.note_ask()
        self._send(
            json.dumps({"ok": True, "id": ask.id}, separators=(",", ":")).encode(),
            "application/json",
        )
        # Gated on the same expression `/api/data` publishes as `native_notify`,
        # and not on `notify_mac`'s own platform guard: the page decides whether
        # to raise its own notification by reading that field, so a second,
        # independent reading is a second place the one-layer rule can drift —
        # and it does drift for an injected notifier.
        #
        # After `_send` and not before, unlike `/api/notify`. osascript runs on
        # this handler thread with a 5s timeout, against the stdio client's 3s
        # register POST: a lost reply is not a retry there, it walks to the next
        # candidate port and registers the question on a second dashboard while
        # this one keeps a card nobody can withdraw, because its id was in the
        # reply that never arrived. `_send` writes through an unbuffered wfile, so
        # the bytes are on the socket by the time this runs.
        if application.native_notifier(config.platform_name):
            notifications.maybe_ask_popup(
                config,
                application.state,
                notifications.AskSubject(
                    harness=ask.harness,
                    sid=ask.session_id,
                    label=application.harness_label(ask.harness),
                    question=ask.question,
                    project=ask.project,
                ),
                now=ask.created,
                popup_notifier=application.popup_notifier,
            )

    def _ask_project(self, value: object) -> str:
        """The asking session's directory, bounded but still identifiable.

        `safe_text` truncates from the front, which is wrong for a path: the
        distinctive part is the tail. A 122-character cwd against the old
        120-char label cap published `.../e2e/adop` for a directory named
        `adopt2`, so the card named somewhere that does not exist. An over-long
        path therefore keeps its end and marks the cut.
        """
        config = self.server.application.config
        cap = config.ask_project_cap_chars
        # Stripped at the request body's own cap, not at `cap`: `safe_text`
        # truncates from the front, so pre-trimming to anything near `cap` throws
        # away the very tail this method exists to keep. The body cap already
        # bounds how much can arrive, so this cannot run long.
        project = records.safe_text(value, config.ask_body_cap_bytes).strip()
        if len(project) > cap:
            return "\u2026" + project[-(cap - 1) :]
        return project

    def _withdraw(self) -> None:
        """Take a question off the board on its asking session's behalf.

        The session that asked is the one that gives up: its tool call was
        aborted, or its poll ran out. Without this route the card stayed
        clickable for the rest of the deadline, and the reader's click was
        accepted and thrown away, so a person answered a question nobody was
        listening for and was told nothing about it.

        A 200 for an unknown id, exactly as `/api/answer` gives one: a 404 would
        make this an oracle for which asks exist. The caller reads `withdrawn`.

        Bounded at the answer route's cap rather than the register route's: the
        body carries an id and nothing else.
        """
        application = self.server.application
        config = application.config
        if not config.ask_enabled:
            self._ask_unavailable("disabled", body_read=False)
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = -1
        if not 0 <= length <= config.ask_answer_body_cap_bytes:
            self._reject(413)
            return
        try:
            payload = json.loads(self._read_body(length) or b"{}")
        except (ValueError, json.JSONDecodeError, RecursionError):
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        ask_id = payload.get("id")
        withdrawn = isinstance(ask_id, str) and application.state.asks.withdraw(ask_id)
        if withdrawn:
            # The same reason an answer drops it: a card that has left the
            # registry has to leave the board on the next collection, or it goes
            # on offering a choice nobody can act on.
            application.state.snapshot.clear()
        self._send(
            json.dumps({"ok": True, "withdrawn": withdrawn}, separators=(",", ":")).encode(),
            "application/json",
        )

    def _answer(self) -> None:
        """Record the option the reader chose.

        Guarded exactly like `/api/dismiss`, and a no-op in the same way: an
        unknown id, a non-integer index and an out-of-range one all answer 200
        with `answered: false`. A 404 for an unknown id would turn this route
        into an oracle for which asks exist, so the page reads `answered` rather
        than the status line to decide whether anyone heard.
        """
        application = self.server.application
        config = application.config
        if not config.ask_enabled:
            self._reject(503)
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = -1
        if not 0 <= length <= config.ask_answer_body_cap_bytes:
            self._reject(413)
            return
        try:
            payload = json.loads(self._read_body(length) or b"{}")
        except (ValueError, json.JSONDecodeError, RecursionError):
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        ask_id, index = payload.get("id"), payload.get("index")
        answered = (
            isinstance(ask_id, str)
            and isinstance(index, int)
            # A bool IS an int in Python, so `"index": true` would otherwise
            # answer option 1 for a body that named no option at all.
            and not isinstance(index, bool)
            and application.state.asks.answer(ask_id, index)
        )
        if answered:
            # The card has to leave the board on the next collection, or it goes
            # on offering a choice that has already been made.
            application.state.snapshot.clear()
        self._send(
            json.dumps({"ok": True, "answered": answered}, separators=(",", ":")).encode(),
            "application/json",
        )

    def log_message(self, *args: Any) -> None:
        pass  # keep the terminal quiet
