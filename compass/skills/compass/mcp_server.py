#!/usr/bin/env python3
"""Let an agent ask the operator a question and wait for the answer.

A stdio MCP server exposing one tool, ``ask_operator(question, options)``. The
question is registered with the running Compass dashboard over loopback, the
reader clicks an option there, and the chosen option is returned to the agent.
The harness holds the tool call open for the whole wait, which is measured on
Claude Code 2.1.239 and codex-cli 0.146.1 (see
``docs/captures/{claude,codex}/mcp-ask-gate-*.jsonl``).

## The promise

**Exactly one valid JSON-RPC object per request, on every path.** This is a
stronger promise than the lifecycle forwarders beside this file make, and the
reason is that a caller is waiting: `notify_hook.py` can post nothing and exit 0
because nothing is blocked on it, whereas an agent parked in a `tools/call` is
blocked until this process answers. So there is no silent path here. Every
failure, including no dashboard running, a refused connection, a 503, a
cancellation and an unhandled exception in the worker, resolves to an ordinary
tool result that declines. Never a JSON-RPC error for a call, never a non-zero
exit, and nothing but JSON-RPC frames on stdout. Diagnostics go to stderr.

That promise is kept even for a request the client has cancelled. MCP says a
receiver SHOULD NOT answer a cancelled request, and this server answers anyway:
a late frame on a dead id is discarded by every client, while a missing one can
hang a client that cancelled on its own timeout, and "one object per request" is
the invariant that makes this stdout auditable at all.

## The security property

The dashboard records the options at registration and answers with an **index**.
This process returns ``options[index]`` from the list it registered, never from
anything the dashboard echoes back, and range-checks the index against its own
list. A forged or confused answer can therefore only pick the wrong one of the
options the agent itself offered, and can never introduce text into an agent's
context. `docs/design-ask-lane.md` records why an index rather than a string.

The list it registered is also the list the operator saw. Its own copy is cut
by ``records.cut_text``, the function the dashboard cuts the card with, run on
the very strings it sends; the dashboard's register reply echoes the card's text,
and a question whose card differs is withdrawn before anyone can click it. So the
string handed back is character for character the label on the card that was
clicked: nobody can approve text that was never shown.

## Why three threads

A reader thread owns stdin, the dispatch loop routes frames, and each
`tools/call` runs on its own worker with a lock keeping every emitted frame
atomic. One sequential loop could not service a `notifications/cancelled` or a
`ping` while a call was outstanding, and would serialize two asks in one turn
into a double wait. The reader is separate from the loop so the loop can wake on
a timeout and notice a stdout that has gone away, which it could not do while
parked in an uninterruptible ``readline``.

Usage, with an optional port to prefer over what the state files publish:

    python3 <skill-dir>/mcp_server.py            # discover the dashboard
    python3 <skill-dir>/mcp_server.py 9999       # prefer port 9999
"""

from __future__ import annotations

import contextlib
import dataclasses
import glob
import http.client
import json
import os
import queue
import re
import sys
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:
    from collections.abc import Sequence

# An installed plugin's skill directory is not on sys.path, so the transport
# guards below have to be made importable before they can be imported. Same
# shape as `agy_hook._shared`, hoisted to module scope because this server
# depends on them for every request rather than occasionally.
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

# Imported rather than copied. `notify_hook` owns the loopback parse and the
# redirect refusal for every edge script here, and SECURITY.md's claim that they
# have one implementation is worth more than avoiding one private name: a second
# copy of a security guard is exactly what that claim exists to prevent.
# `notify_hook.forward` itself is unusable here because it returns a bool and
# this server needs the response status and body.
import notify_hook  # noqa: E402 — needs the sys.path insert above

# The dashboard's own redaction and cut, imported for the reason `notify_hook`
# is: a second copy is a second answer to what the card says.
from compass_runtime import records  # noqa: E402 — needs the sys.path insert above

SERVER_NAME: Final = "compass"
# Not the plugin version. That lives in five manifest fields owned by the
# release workflow, and a sixth copy here would drift silently while no client
# acts on the value.
SERVER_VERSION: Final = "0"
TOOL_NAME: Final = "ask_operator"

# Echoed back to the client whenever it announces one: Claude Code 2.1.239 sends
# 2025-11-25 and codex-cli 0.146.1 sends 2025-06-18, both measured. This is only
# the answer for a client that announces nothing.
PROTOCOL_FALLBACK: Final = "2025-06-18"

DEFAULT_PORT: Final = 4553
MAX_CANDIDATE_PORTS: Final = 4
STATE_READ_CAP_BYTES: Final = 65_536
RESPONSE_CAP_BYTES: Final = 65_536
MAX_FRAME_BYTES: Final = 1 << 20

# Mirror the dashboard's `ask_*` caps in config.py. The dashboard cuts the card's
# text from what this process sends uncut; this process cuts its own copy the
# same way, to answer with the label that was clicked.
QUESTION_CAP_CHARS: Final = 2_000
OPTION_CAP_CHARS: Final = 240
MAX_OPTIONS: Final = 8
MIN_OPTIONS: Final = 2
# Mirrors `ask_body_cap_bytes`; config.py carries the arithmetic. The one bound
# on what is sent, and refused past rather than cut. The dashboard also makes
# text safe at this many characters before it cuts, so this process uses the
# same figure for its copy to match.
BODY_CAP_BYTES: Final = 32_768

REGISTER_TIMEOUT_SEC: Final = 3.0
# A withdrawal runs before the caller's reply is written, and one of its two
# triggers is the client having gone away, where the dispatch loop is already
# joining workers with `WORKER_JOIN_SEC`. So it is bounded well under that: the
# board being tidy is never worth delaying the answer somebody is parked on.
WITHDRAW_TIMEOUT_SEC: Final = 1.0
# Must exceed the dashboard's `ask_poll_timeout_sec` (10.0), which is how long
# one long poll deliberately holds. A socket timeout under it would abort every
# poll and read as a dead dashboard.
POLL_TIMEOUT_SEC: Final = 30.0
# A 204 that returns immediately means the long poll did not hold, which an
# older dashboard or one mid-shutdown can do. Without a floor that is a spin
# loop on loopback.
POLL_FLOOR_SEC: Final = 0.25
# Twice the dashboard's `ask_deadline_sec` (300.0). The dashboard's own expiry
# is what normally ends a wait; this is the backstop for one that keeps
# answering 204 forever.
OVERALL_DEADLINE_SEC: Final = 600.0

# The status `_open` reports for the dashboard's connection-cap refusal: a 503 carrying
# Retry-After, written before the request is read. Outside the HTTP range on purpose, so it is
# never mistaken for the poll route's own 503, which says the ask lane is off.
BUSY: Final = 0
LOOP_TICK_SEC: Final = 0.5
WORKER_JOIN_SEC: Final = 2.0

PARSE_ERROR: Final = -32700
INVALID_REQUEST: Final = -32600

# Not one of the dashboard's states: the state this process gives an ask whose
# poll came back 404, so the difference between "already off the board" and "we
# stopped waiting" survives as far as the withdrawal decision.
GONE: Final = "gone"

# `secrets.token_urlsafe`'s alphabet. The id is interpolated into a URL path,
# and not trusting what the dashboard echoes back is this lane's whole posture.
ASK_ID_RE: Final = re.compile(r"[A-Za-z0-9_-]{1,64}\Z")

# AI_AGENT is `<client>_<version>_<role>`, measured as `claude-code_2-1-239_agent`
# on Claude Code 2.1.239. Only the client half names a harness and only Claude's
# spelling is measured, so anything else is reported as unknown rather than
# guessed into a registry key that the dashboard would then fail to match.
HARNESS_BY_AGENT: Final[dict[str, str]] = {"claude-code": "claude"}
UNKNOWN_HARNESS: Final = "unknown"

TOOL_DESCRIPTION: Final = (
    "Ask the human operator to choose between options, and wait for their answer. "
    "The question appears on their local Compass dashboard and this call blocks "
    "until they click one, so use it for a decision you genuinely cannot make "
    "alone, not for confirmation. Returns the chosen option verbatim, or says that "
    "nothing was chosen if nobody answered."
)

TOOL: Final[dict[str, Any]] = {
    "name": TOOL_NAME,
    "title": "Ask the operator",
    "description": TOOL_DESCRIPTION,
    "inputSchema": {
        "type": "object",
        "properties": {
            "question": {
                "type": "string",
                "description": "The decision to put to the operator, in one sentence.",
                "maxLength": QUESTION_CAP_CHARS,
            },
            "options": {
                "type": "array",
                "description": "The choices to offer, each a short label the operator can click.",
                "items": {"type": "string", "maxLength": OPTION_CAP_CHARS},
                "minItems": MIN_OPTIONS,
                "maxItems": MAX_OPTIONS,
            },
        },
        "required": ["question", "options"],
        "additionalProperties": False,
    },
}

# One sentence per cause, because the agent puts this text in its context and may
# repeat it to the user. "No dashboard is running here" used to answer every
# non-200, which is false whenever the dashboard answered: it says the operator
# cannot be reached at all, when in fact the lane is switched off or full and the
# next attempt may well land.
DECLINE_UNREACHABLE: Final = (
    "No operator was reached: no Compass dashboard is running here, so the question was "
    "never shown and nothing was chosen. Proceed on your own judgement and say which "
    "option you took and why."
)
DECLINE_DISABLED: Final = (
    "No operator was reached: the Compass dashboard is running with its ask lane switched "
    "off, so the question was never shown and nothing was chosen. Another question will be "
    "refused the same way until it is switched back on. Proceed on your own judgement and "
    "say which option you took and why."
)
DECLINE_BUSY: Final = (
    "No operator was reached: the Compass dashboard is running, but too many questions are "
    "already waiting on the operator, so this one was not shown and nothing was chosen. "
    "Proceed on your own judgement and say which option you took and why."
)
DECLINE_REFUSED: Final = (
    "No operator was reached: the Compass dashboard is running but refused the question, so "
    "it was never shown and nothing was chosen. Proceed on your own judgement and say which "
    "option you took and why."
)
# Which part of the register body put it over the cap, so the agent is told
# what to shorten. A modest question beside eight long options once heard that a
# shorter question could be asked, which would have been refused again.
_TOO_LARGE_HEAD: Final = (
    "No operator was reached: {part} over the {cap:,}-byte limit on one question, "
)
_TOO_LARGE_SHOWN: Final = "so nothing was shown and nothing was chosen. "
_TOO_LARGE_TAIL: Final = (
    "Otherwise proceed on your own judgement and say which option you took and why."
)
DECLINE_TOO_LARGE_QUESTION: Final = (
    _TOO_LARGE_HEAD.format(part="the question alone is", cap=BODY_CAP_BYTES)
    + _TOO_LARGE_SHOWN
    + f"A card shows {QUESTION_CAP_CHARS:,} characters of a question, so a shorter question "
    "can be asked again. " + _TOO_LARGE_TAIL
)
DECLINE_TOO_LARGE_OPTIONS: Final = (
    _TOO_LARGE_HEAD.format(part="the options alone are", cap=BODY_CAP_BYTES)
    + _TOO_LARGE_SHOWN
    + f"A card shows {OPTION_CAP_CHARS} characters of an option, so the question can be asked "
    "again with shorter options. " + _TOO_LARGE_TAIL
)
DECLINE_TOO_LARGE: Final = (
    _TOO_LARGE_HEAD.format(part="the question and the options together are", cap=BODY_CAP_BYTES)
    + _TOO_LARGE_SHOWN
    + f"A card shows {QUESTION_CAP_CHARS:,} characters of a question and {OPTION_CAP_CHARS} of "
    "an option, so a shorter question or shorter options can be asked again. " + _TOO_LARGE_TAIL
)
DECLINE_TOO_LARGE_ATTRIBUTION: Final = (
    _TOO_LARGE_HEAD.format(
        part="this session's own attribution, its project path and session id, is",
        cap=BODY_CAP_BYTES,
    )
    + _TOO_LARGE_SHOWN
    + "No shorter question would fit. Proceed on your own judgement and say which option "
    "you took and why."
)
# The reasons the register route publishes. An unknown one falls back to the
# generic refusal rather than to unreachable, so a newer dashboard inventing a
# reason cannot make this process claim nothing is running.
DECLINE_BY_REASON: Final[dict[str, str]] = {
    "disabled": DECLINE_DISABLED,
    "busy": DECLINE_BUSY,
}
DECLINE_UNANSWERED: Final = (
    "No option was chosen: the question was shown but nobody answered it. Proceed on your "
    "own judgement and say which option you took and why."
)
DECLINE_INTERNAL: Final = (
    "No option was chosen: the question could not be delivered. Proceed on your own "
    "judgement and say which option you took and why."
)
# A dashboard that registered the question but sent back no card text predates
# the echo `_register` checks, and is still running after the plugin was updated.
# Worded as `terminal_drift.CLIENT_OUTDATED_IN_SESSION` is, without its harness's
# command: this process cannot tell Codex from an unmeasured harness.
DECLINE_OUTDATED: Final = (
    "No operator was reached: the Compass dashboard running here is older than this "
    "plugin, so the question was taken back before anyone could answer it and nothing was "
    "chosen. Tell the person to restart it: ask Compass to stop the dashboard, then start "
    "Compass again to run this version. Proceed on your own judgement and say which option "
    "you took and why."
)


def log(message: str) -> None:
    """Diagnostics, on stderr. stdout is the protocol and carries nothing else."""
    with contextlib.suppress(OSError, ValueError):
        print(f"compass mcp: {message}", file=sys.stderr, flush=True)


def default_home() -> str:
    return os.path.join(os.path.expanduser("~"), ".compass")


def state_home() -> str:
    env = os.environ
    override = env.get("COMPASS_HOME")
    return override if override and override.strip() else default_home()


def _published_ports() -> list[int]:
    """Ports from the state files, most recently started first."""
    found: list[tuple[float, int]] = []
    paths = glob.glob(os.path.join(state_home(), "compass-*.json"))
    for path in paths:
        try:
            with open(path, "rb") as handle:
                raw = handle.read(STATE_READ_CAP_BYTES + 1)
            if len(raw) > STATE_READ_CAP_BYTES:
                continue
            data = json.loads(raw or b"null")
        except (OSError, ValueError, RecursionError):
            continue
        if not isinstance(data, dict):
            continue
        port = data.get("port")
        started = data.get("started")
        if isinstance(port, int) and not isinstance(port, bool) and 1 <= port <= 65535:
            found.append((float(started) if isinstance(started, (int, float)) else 0.0, port))
    found.sort(reverse=True)
    return [port for _started, port in found]


def candidate_ports(args: Sequence[str] = ()) -> tuple[int, ...]:
    """Ports to try for a running dashboard, in order.

    Read from the state files rather than assumed, because a dashboard started
    with ``--port`` publishes only its own file and an MCP server declared in a
    plugin manifest has no user-edited port to inherit the way the lifecycle
    hooks in ``settings.json`` do. The default is appended even so: COMPASS_HOME
    is not necessarily exported to this process when the dashboard has one, and a
    refused connection on a closed port costs one syscall.
    """
    ordered: list[int] = []
    for arg in args:
        with contextlib.suppress(ValueError):
            ordered.append(int(arg))
    ordered.extend(_published_ports())
    ordered.append(DEFAULT_PORT)
    seen: list[int] = []
    for port in ordered:
        if 1 <= port <= 65535 and port not in seen:
            seen.append(port)
    return tuple(seen[:MAX_CANDIDATE_PORTS])


def attribution() -> dict[str, str]:
    """What this process can honestly say about the session that called it.

    Measured present for a stdio MCP server on Claude Code 2.1.239 in a fresh
    interactive session: CLAUDE_CODE_SESSION_ID, CLAUDE_PROJECT_DIR and AI_AGENT.
    Codex's equivalents are unmeasured, so a key is omitted rather than invented:
    a fabricated session id would attach the ask to the wrong row.
    """
    out: dict[str, str] = {}
    agent = (os.environ.get("AI_AGENT") or "").strip()
    out["harness"] = HARNESS_BY_AGENT.get(agent.split("_", 1)[0], UNKNOWN_HARNESS)
    session_id = (os.environ.get("CLAUDE_CODE_SESSION_ID") or "").strip()
    if session_id:
        out["session_id"] = session_id
    project = (os.environ.get("CLAUDE_PROJECT_DIR") or "").strip()
    if not project:
        with contextlib.suppress(OSError):
            project = os.getcwd()
    if project:
        out["project"] = project
    return out


def _open(request: urllib.request.Request, timeout: float) -> tuple[int, bytes] | None:
    """(status, body), or None when the request could not be made at all.

    ProxyHandler({}) disables proxying entirely, mirroring `notify_hook.forward`.
    Without it the default opener honours http_proxy/HTTP_PROXY, which is routine
    in corporate environments, and a POST to 127.0.0.1 carrying an agent's
    question is handed to the proxy instead. `_NoRedirects` refuses to follow a
    307, which preserves method and body and would otherwise bounce that payload
    off the machine.
    """
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        notify_hook._NoRedirects,  # noqa: SLF001 — see the import comment: one implementation
    )
    try:
        with opener.open(request, timeout=timeout) as response:
            return int(response.status), response.read(RESPONSE_CAP_BYTES)
    except urllib.error.HTTPError as exc:
        # A 4xx or 5xx is an answer here, not a failure: the poll route uses 404
        # for an ask that is gone and 503 for the feature being off, and urllib
        # raises on both. Caught before URLError, which it subclasses.
        body = b""
        with contextlib.suppress(OSError, ValueError, http.client.HTTPException):
            body = exc.read(RESPONSE_CAP_BYTES)
        if exc.code == 503 and exc.headers.get("Retry-After") is not None:
            return BUSY, body
        return int(exc.code), body
    except (urllib.error.URLError, OSError, ValueError, http.client.HTTPException):
        return None


def _request(url: str, *, data: bytes | None, timeout: float) -> tuple[int, bytes] | None:
    if not notify_hook.is_loopback_url(url):
        # This process carries an agent's question and its session id. It must
        # not become a way to ship those somewhere else because a port argument
        # or a state file was edited.
        return None
    request = urllib.request.Request(  # noqa: S310 — scheme and host checked above
        url,
        data=data,
        headers={"Content-Type": "application/json"} if data is not None else {},
        method="POST" if data is not None else "GET",
    )
    return _open(request, timeout)


def _json_object(raw: bytes) -> dict[str, Any]:
    try:
        data = json.loads(raw or b"null")
    except (ValueError, RecursionError):
        return {}
    return data if isinstance(data, dict) else {}


@dataclasses.dataclass(frozen=True)
class _Ask:
    """One validated call: what is sent, and what the card will show.

    `sent_question` and `sent_options` go in the register body exactly as the
    agent wrote them. `question` and `options` are `records.cut_text` of those
    same strings, which is what the dashboard publishes and what an answer
    resolves against.
    """

    sent_question: str
    sent_options: tuple[str, ...]
    question: str
    options: tuple[str, ...]


def _arguments(raw: Any) -> _Ask | str:
    """The validated call, or a sentence saying what is wrong.

    Nothing is cut before it is sent: the dashboard is the one place the card's
    text is made, redacting the whole of each string before cutting it, and it
    measures the question's length from what it received. The card's text is
    computed here only as this process's copy, with the dashboard's own function
    on the same strings, and `_register` refuses a card whose text differs. The
    one bound on what is sent is the register body cap, refused past with a
    sentence rather than cut, because a cut here is a cut before redaction. Bounding
    after registration instead is what let the card show 120 characters while
    the answer resolved against the untruncated tuple, so a reader could approve
    a string they were never shown, and two options differing only past the cap
    rendered as the same button. Consent has to be to the thing that happens, so
    the answer resolves against the text the card showed.
    """
    if not isinstance(raw, dict):
        return "ask_operator needs an arguments object with `question` and `options`."
    question = raw.get("question")
    sent_question = question if isinstance(question, str) else ""
    shown = records.cut_text(sent_question, QUESTION_CAP_CHARS, BODY_CAP_BYTES)[0]
    if not shown:
        return "ask_operator needs a non-empty `question` string."
    raw_options = raw.get("options")
    if not isinstance(raw_options, list):
        return f"ask_operator needs an `options` array of {MIN_OPTIONS} to {MAX_OPTIONS} strings."
    sent_options = tuple(item for item in raw_options if isinstance(item, str) and item.strip())
    options = tuple(
        records.cut_text(item, OPTION_CAP_CHARS, BODY_CAP_BYTES)[0] for item in sent_options
    )
    if (
        len(options) != len(raw_options)
        or not MIN_OPTIONS <= len(options) <= MAX_OPTIONS
        or not all(options)
    ):
        # Length-checked rather than truncated. A model told it may offer eight
        # options and offering twelve would otherwise be answered from a set it
        # never saw chosen from.
        return f"ask_operator needs {MIN_OPTIONS} to {MAX_OPTIONS} non-empty option strings."
    if len(set(options)) != len(options):
        # Two options the cut made identical would be two buttons a reader cannot
        # tell apart, and an answer the agent cannot tell apart either.
        return (
            "ask_operator needs options that differ within their first "
            f"{OPTION_CAP_CHARS} characters."
        )
    return _Ask(
        sent_question=sent_question,
        sent_options=sent_options,
        question=shown,
        options=options,
    )


def _encoded_size(payload: dict[str, Any]) -> int:
    """`payload`'s size as `_register` sends it."""
    return len(json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode())


def _too_large(payload: dict[str, Any]) -> str:
    """The refusal for a register body past the cap, naming the part to shorten.

    Each part is measured beside the rest of the body with the other emptied, so
    "alone" means that part cannot fit however short the other is.
    """
    if _encoded_size({**payload, "question": "", "options": []}) > BODY_CAP_BYTES:
        return DECLINE_TOO_LARGE_ATTRIBUTION
    question_over = _encoded_size({**payload, "options": []}) > BODY_CAP_BYTES
    options_over = _encoded_size({**payload, "question": ""}) > BODY_CAP_BYTES
    if question_over and not options_over:
        return DECLINE_TOO_LARGE_QUESTION
    if options_over and not question_over:
        return DECLINE_TOO_LARGE_OPTIONS
    return DECLINE_TOO_LARGE


def _call_key(request_id: Any) -> str:
    """A dict key for a JSON-RPC id, without assuming it is hashable."""
    try:
        return json.dumps(request_id, sort_keys=True, default=str)
    except (TypeError, ValueError, RecursionError):
        return repr(request_id)


def _params(message: dict[str, Any]) -> dict[str, Any]:
    """A message's params, tolerating the key being absent.

    Measured: Claude Code 2.1.239 sends `tools/list` with no params key and
    codex-cli 0.146.1 sends one. Nothing in this server reads params for that
    method, and this is why both frames are answered identically.
    """
    params = message.get("params")
    return params if isinstance(params, dict) else {}


def _result(request_id: Any, text: str, *, is_error: bool = False) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "result": {"content": [{"type": "text", "text": text}], "isError": is_error},
    }


def _error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


@dataclasses.dataclass(frozen=True, slots=True)
class _Frame:
    """One line off stdin.

    ``oversized`` is carried rather than dropped: a caller may be waiting on the
    request inside the line and is owed a reply either way.
    """

    data: bytes
    oversized: bool = False


class _Writer:
    """Serialized access to stdout.

    A worker's tool result must never interleave with the dispatch loop's reply
    to a ping that arrived while the call was held. ``closed`` rises when the
    stream has gone away, which is the loop's cue to stop.
    """

    def __init__(self, stream: Any) -> None:
        self._stream = stream
        self._lock = threading.Lock()
        self.closed = threading.Event()

    def send(self, message: dict[str, Any]) -> None:
        line = json.dumps(message, separators=(",", ":")).encode() + b"\n"
        with self._lock:
            try:
                self._stream.write(line)
                self._stream.flush()
            except (OSError, ValueError):
                # The client is gone. Raising here would traceback out of a
                # worker and break the one-object-per-request promise for
                # everything still in flight.
                self.closed.set()


class AskServer:
    """The stdio JSON-RPC loop and the ask_operator call flow."""

    def __init__(self, *, stdin: Any, stdout: Any, ports: Sequence[int]) -> None:
        self._stdin = stdin
        self._writer = _Writer(stdout)
        self._ports = tuple(ports)
        self._frames: queue.Queue[_Frame | None] = queue.Queue()
        self._aborts: dict[str, threading.Event] = {}
        self._aborts_lock = threading.Lock()
        self._workers: list[threading.Thread] = []

    # --- the loop -------------------------------------------------------

    def run(self) -> int:
        reader = threading.Thread(target=self._read, name="compass-mcp-stdin", daemon=True)
        reader.start()
        while not self._writer.closed.is_set():
            try:
                frame = self._frames.get(timeout=LOOP_TICK_SEC)
            except queue.Empty:
                continue
            if frame is None:
                break
            self._dispatch(frame)
        # stdin closed or stdout died: the client is gone, so every poll still
        # running is waiting for an answer nobody will read.
        self._abort_all()
        for worker in self._workers:
            worker.join(timeout=WORKER_JOIN_SEC)
        return 0

    def _read(self) -> None:
        """Own stdin, and hand whole lines to the loop."""
        while True:
            try:
                line = self._stdin.readline(MAX_FRAME_BYTES + 1)
            except (OSError, ValueError):
                break
            if not line:
                break
            if not line.endswith(b"\n") and len(line) > MAX_FRAME_BYTES:
                self._drain()
                self._frames.put(_Frame(b"", oversized=True))
                continue
            self._frames.put(_Frame(line))
        self._frames.put(None)

    def _drain(self) -> None:
        """Discard the rest of an oversized line so the next read starts on a frame."""
        while True:
            try:
                chunk = self._stdin.readline(MAX_FRAME_BYTES)
            except (OSError, ValueError):
                return
            if not chunk or chunk.endswith(b"\n"):
                return

    def _dispatch(self, frame: _Frame) -> None:
        if frame.oversized:
            self._writer.send(_error(None, PARSE_ERROR, "frame exceeds the size limit"))
            return
        text = frame.data.strip()
        if not text:
            # A bare newline is not a request, so it is owed no reply.
            return
        try:
            message = json.loads(text)
        except (ValueError, RecursionError):
            # RecursionError, not just ValueError: deeply nested JSON blows the
            # decoder's stack rather than raising ValueError, and that would
            # escape as a traceback with nothing on stdout.
            self._writer.send(_error(None, PARSE_ERROR, "malformed JSON"))
            return
        if not isinstance(message, dict):
            self._writer.send(_error(None, INVALID_REQUEST, "not a JSON-RPC object"))
            return
        request_id = message.get("id")
        method = message.get("method")
        if not isinstance(method, str):
            if request_id is not None:
                self._writer.send(_error(request_id, INVALID_REQUEST, "no method"))
            return
        if request_id is None:
            self._notification(method, message)
            return
        self._handle(request_id, method, message)

    def _notification(self, method: str, message: dict[str, Any]) -> None:
        if method == "notifications/cancelled":
            self._cancel(_params(message).get("requestId"))
        # Every other notification, `notifications/initialized` included, is
        # acknowledged by silence: it has no id and JSON-RPC forbids a reply.

    def _handle(self, request_id: Any, method: str, message: dict[str, Any]) -> None:
        if method == "initialize":
            announced = _params(message).get("protocolVersion")
            protocol = announced if isinstance(announced, str) and announced else PROTOCOL_FALLBACK
            self._writer.send(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "protocolVersion": protocol,
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
                    },
                }
            )
        elif method == "tools/list":
            self._writer.send({"jsonrpc": "2.0", "id": request_id, "result": {"tools": [TOOL]}})
        elif method == "tools/call":
            self._start_call(request_id, message)
        else:
            # Includes `ping`. An empty result is a valid answer to any request
            # this server does not implement, and answering is what keeps the
            # one-object-per-request promise literal.
            self._writer.send({"jsonrpc": "2.0", "id": request_id, "result": {}})

    def _cancel(self, request_id: Any) -> None:
        with self._aborts_lock:
            targets = (
                list(self._aborts.values())
                if request_id is None
                else [self._aborts[key] for key in [_call_key(request_id)] if key in self._aborts]
            )
        for abort in targets:
            abort.set()

    def _abort_all(self) -> None:
        self._cancel(None)

    # --- the call -------------------------------------------------------

    def _start_call(self, request_id: Any, message: dict[str, Any]) -> None:
        params = _params(message)
        if params.get("name") != TOOL_NAME:
            self._writer.send(_result(request_id, "Unknown tool.", is_error=True))
            return
        abort = threading.Event()
        with self._aborts_lock:
            self._aborts[_call_key(request_id)] = abort
        # Pruned here rather than never: a long session makes many calls, and the
        # list exists only to bound shutdown. Touched from the dispatch loop
        # thread alone, so it needs no lock.
        self._workers = [worker for worker in self._workers if worker.is_alive()]
        worker = threading.Thread(
            target=self._run_call,
            args=(request_id, params.get("arguments"), abort),
            name="compass-mcp-ask",
            daemon=True,
        )
        self._workers.append(worker)
        worker.start()

    def _run_call(self, request_id: Any, arguments: Any, abort: threading.Event) -> None:
        text, is_error = DECLINE_INTERNAL, False
        try:
            text, is_error = self._ask(arguments, abort)
        except Exception:  # noqa: BLE001 — a raising worker would hang the caller forever
            log(f"ask_operator failed:\n{traceback.format_exc()}")
        with self._aborts_lock:
            self._aborts.pop(_call_key(request_id), None)
        self._writer.send(_result(request_id, text, is_error=is_error))

    def _ask(self, arguments: Any, abort: threading.Event) -> tuple[str, bool]:
        validated = _arguments(arguments)
        if isinstance(validated, str):
            return validated, True
        registration = self._register(validated)
        if isinstance(registration, str):
            return registration, False
        base, ask_id = registration
        outcome = self._poll(base, ask_id, abort)
        if outcome is None:
            # Nothing resolved this: the call was cancelled, the wait ran out, or
            # the dashboard stopped answering. The card is still on the board and
            # still clickable with nobody listening, so take it back.
            self._withdraw(base, ask_id)
            return DECLINE_UNANSWERED, False
        state, index = outcome
        # The whole security property of this feature. The answer names a
        # position in this process's own copy of the list, cut exactly as the
        # card was; it never carries text, and an index the dashboard should not
        # have sent resolves to a decline rather than to somebody else's string.
        if state != "answered" or index is None or not 0 <= index < len(validated.options):
            return DECLINE_UNANSWERED, False
        return validated.options[index], False

    def _register(self, ask: _Ask) -> tuple[str, str] | str:
        """(base url, ask id), or the sentence to hand the agent instead.

        The candidate list is walked only past a **connection-level** failure. Any
        HTTP response means a dashboard is listening on that port, and walking
        past one that refused registered the question on a different dashboard,
        where a different reader answered it: measured with `--no-ask` on the
        preferred port, which is the switch cli.py calls the rollback switch. So a
        refusal ends the walk and its reason becomes the answer.

        A 200 whose echoed question and options are not this process's own copy
        is withdrawn: the card would show one thing and the answer return
        another, which is the consent failure `_arguments` exists to prevent. A
        reply that echoes neither came from a dashboard older than the echo, and
        is withdrawn too, with a sentence asking for that dashboard's restart.
        """
        payload: dict[str, Any] = {
            "question": ask.sent_question,
            "options": list(ask.sent_options),
            **attribution(),
        }
        # ensure_ascii=False so the gate here measures the axis the dashboard
        # measures: it checks Content-Length against its own byte cap, and
        # escaping to \uXXXX turns one character of a non-Latin script into six
        # bytes, which refused a question inside every documented character cap.
        body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode()
        if len(body) > BODY_CAP_BYTES:
            log(f"payload of {len(body)} bytes is over the {BODY_CAP_BYTES} byte cap")
            return _too_large(payload)
        for port in self._ports:
            base = f"http://127.0.0.1:{port}"
            answer = _request(f"{base}/api/ask", data=body, timeout=REGISTER_TIMEOUT_SEC)
            if answer is None:
                # A timeout rather than a refusal may mean the POST landed and
                # only the reply was lost, leaving a card that cannot be
                # withdrawn because the id was in that reply. The dashboard's own
                # deadline is what retires it; there is nothing to do here.
                continue
            status, raw = answer
            data = _json_object(raw)
            if status != 200:
                reason = data.get("reason")
                log(f"register on {port} returned {status} ({reason})")
                # Looked up only when it is a string: a reason of any other shape
                # is an unhashable key away from a traceback in a worker.
                if isinstance(reason, str):
                    return DECLINE_BY_REASON.get(reason, DECLINE_REFUSED)
                return DECLINE_REFUSED
            ask_id = data.get("id")
            decline = DECLINE_INTERNAL
            if (
                not isinstance(ask_id, str)
                or data.get("ok") is not True
                or not ASK_ID_RE.match(ask_id)
            ):
                log(f"register on {port} returned an unusable id")
            elif "question" not in data and "options" not in data:
                # An older dashboard: it shows text this process cannot confirm.
                log(f"register on {port} echoed no card text; that dashboard is older")
                decline = DECLINE_OUTDATED
            elif data.get("question") != ask.question or data.get("options") != list(ask.options):
                log(f"register on {port} shows a question unlike the one asked")
            else:
                return base, ask_id
            # A 200 means that dashboard took the question, so a card nothing can
            # poll, or one whose answer would not be the label clicked, is on
            # somebody's board. The id goes in a body rather than a path, which is
            # why one this process refuses to interpolate into a URL can still be
            # withdrawn.
            if isinstance(ask_id, str):
                self._withdraw(base, ask_id)
            return decline
        return DECLINE_UNREACHABLE

    def _withdraw(self, base: str, ask_id: str) -> None:
        """Take an abandoned question off the board. Best effort, and silent.

        Whether this lands changes nothing the agent is told: the agent's answer
        is about whether an option was chosen, and a card left on the board is the
        operator's problem, not part of that. So every failure here is a log line.
        """
        body = json.dumps({"id": ask_id}, separators=(",", ":")).encode()
        answer = _request(f"{base}/api/ask/withdraw", data=body, timeout=WITHDRAW_TIMEOUT_SEC)
        if answer is None or answer[0] != 200:
            log(f"withdrawing {ask_id} did not land: {answer[0] if answer else 'no response'}")

    def _poll(
        self, base: str, ask_id: str, abort: threading.Event
    ) -> tuple[str, int | None] | None:
        """The ask's outcome, or None if nothing resolved it before we stopped.

        None is the caller's cue to withdraw, so `GONE` is a state rather than a
        None: a question already off the board needs no taking back.

        A bounded long poll rather than one held request: each GET returns within
        the dashboard's own poll timeout, which is what keeps a cancellation, a
        dashboard restart and a dead peer ordinary instead of three things to
        engineer. See docs/design-ask-lane.md.
        """
        deadline = time.monotonic() + OVERALL_DEADLINE_SEC
        url = f"{base}/api/ask/{urllib.parse.quote(ask_id, safe='')}"
        while not abort.is_set():
            if time.monotonic() >= deadline:
                return None
            started = time.monotonic()
            answer = _request(url, data=None, timeout=POLL_TIMEOUT_SEC)
            if answer is None:
                return None  # the dashboard went away mid-wait
            status, raw = answer
            if status == 404:
                # An outcome rather than a failure to get one: the question has
                # already left the dashboard, so it is not withdrawn afterwards.
                return GONE, None
            if status == 200:
                body = _json_object(raw)
                state = body.get("state")
                if state in {"answered", "declined", "expired"}:
                    index = body.get("index")
                    # `not isinstance(index, bool)` is load-bearing, not tidy-up
                    # noise: True is an int in Python, so a boolean here would
                    # index options[1] and choose for the operator.
                    usable = isinstance(index, int) and not isinstance(index, bool)
                    return str(state), index if usable else None
                # A 200 naming a state this version does not know is not a
                # resolution, so it is waited out rather than read as one.
            elif status not in (204, BUSY):
                # BUSY is a dashboard at its connection cap, which refused before reading the
                # poll: the question is still on the board, so it is waited out like a 204.
                # The route's own 503 (the ask lane is off) is not; the card is gone.
                return None
            self._floor(started, abort)
        return None

    @staticmethod
    def _floor(started: float, abort: threading.Event) -> None:
        """Keep a poll that returned early from becoming a spin loop.

        Waited on the abort event rather than slept, so a cancellation arriving
        inside the floor still lands promptly.
        """
        elapsed = time.monotonic() - started
        if elapsed < POLL_FLOOR_SEC:
            abort.wait(POLL_FLOOR_SEC - elapsed)


def main(argv: list[str]) -> int:
    server = AskServer(
        stdin=sys.stdin.buffer,
        stdout=sys.stdout.buffer,
        ports=candidate_ports(argv[1:]),
    )
    try:
        return server.run()
    except Exception:  # noqa: BLE001 — the promise includes never exiting non-zero
        log(f"server loop failed:\n{traceback.format_exc()}")
        return 0


def _leave(status: int) -> None:
    """Exit without running interpreter finalization.

    On every exit that is not stdin reaching EOF, the reader thread is a daemon
    parked in a blocking `readline`, so it still holds the buffered reader's lock
    when CPython finalizes. Finalization aborts there (`_enter_buffered_busy`) and
    the process dies with SIGABRT and a fatal error dump instead of `status`. A
    stdout that has gone away is the other half: the final flush raises
    BrokenPipeError, prints "Exception ignored" and turns the exit code into 120.

    Both are artefacts of tearing down a process that has already written every
    frame it owes, since `_Writer` flushes each one as it goes. So the flush here
    is best effort and finalization is skipped entirely.
    """
    for stream in (sys.stdout, sys.stderr):
        with contextlib.suppress(OSError, ValueError):
            stream.flush()
    # os._exit rather than sys.exit: skipping finalization is the whole point.
    os._exit(status)


if __name__ == "__main__":
    _leave(main(sys.argv))
