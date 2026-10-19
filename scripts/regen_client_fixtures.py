#!/usr/bin/env python3
"""Regenerate the typed client's shared contract fixtures from the live server.

Every file under `frontend/test/fixtures/client-contract/` is a request sent over loopback
to a real `CompassHTTPServer` and the response it answered, recorded with the clock, the
build and the sessions pinned so the bytes are the same on every run. The TypeScript client
tests read those bytes; `tests/test_frontend_client_fixtures.py` regenerates them here and
requires equality, so a backend change fails Python before it can fail a client.

Nothing is written by hand. The only inputs are synthetic session rows, a fixed clock and a
scratch state directory; models, quota fetches, notifications and focus raises are off, and
the run refuses to spawn a subprocess at all. A state the real server cannot reach without a
model or a native action is listed in `UNREACHABLE` with the reason instead of invented.

    python3 scripts/regen_client_fixtures.py          # rewrite the committed files
    python3 scripts/regen_client_fixtures.py --check  # exit 1 if any file is stale

It also writes `frontend/test/fixtures/vocabulary.json`: the words, keys and rules the Python
producers and their React twins each spell, read from the Python modules at generation time. A
Python constant that changes without regeneration fails `--check`; a React constant that no longer
equals the fixture fails `frontend/src/api/vocabulary.test.ts`. The file sits beside the
client-contract directory, not in it, because that directory is recorded request and response
scenarios and the manifest and the client tests require every file in it to be one.
"""

from __future__ import annotations

import argparse
import contextlib
import dataclasses
import datetime
import hashlib
import http.client
import json
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any
from unittest import mock

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

REPO = Path(__file__).resolve().parents[1]
SKILL = REPO / "compass" / "skills" / "compass"
FIXTURES = REPO / "frontend" / "test" / "fixtures" / "client-contract"
VOCABULARY = FIXTURES.parent / "vocabulary.json"
sys.path.insert(0, str(SKILL))
from compass_runtime import aggregate as runtime_aggregate  # noqa: E402 - skill runtime path
from compass_runtime import annotations as annotation_store  # noqa: E402 - skill runtime path
from compass_runtime import levels as runtime_levels  # noqa: E402 - skill runtime path
from compass_runtime import notifications as runtime_notifications  # noqa: E402 - runtime path
from compass_runtime import observation as observation_module  # noqa: E402 - skill runtime path
from compass_runtime import reading as runtime_reading  # noqa: E402 - skill runtime path
from compass_runtime import reading_jobs as runtime_reading_jobs  # noqa: E402 - skill runtime path
from compass_runtime import reading_route as runtime_reading_route  # noqa: E402 - runtime path
from compass_runtime import records as runtime_records  # noqa: E402 - skill runtime path
from compass_runtime import tripwires as runtime_tripwires  # noqa: E402 - runtime path
from compass_runtime.aggregate import Application, HarnessSpec  # noqa: E402 - skill runtime path
from compass_runtime.config import build_runtime_config  # noqa: E402 - skill runtime path
from compass_runtime.http_api import CompassHTTPServer  # noqa: E402 - skill runtime path
from compass_runtime.sessions import base_session  # noqa: E402 - skill runtime path
from compass_runtime.state import build_runtime_state  # noqa: E402 - skill runtime path

FORMAT = 1
NOW = 1_900_000_000.0
STARTED = 1_900_000_000.0
RESTARTED = 1_900_000_500.0
PAGE_A = b"<!doctype html><title>compass client fixture build A</title>"
PAGE_B = b"<!doctype html><title>compass client fixture build B</title>"

# Placeholders the request templates carry where the real value is chosen per run: the
# listening port is ephemeral and the focus capability is a per-process secret.
ORIGIN = "{origin}"
CAPABILITY = "{capability}"

# The response headers a client can read and that do not vary per run or per Python build.
KEPT_HEADERS = (
    "Cache-Control",
    "Content-Length",
    "Content-Security-Policy",
    "Content-Type",
    "X-Accel-Buffering",
    "X-Compass-Revision",
)

# What the generation run refused to do. The verifying test requires all zeros, so a
# fixture can never have been produced by spending a model or touching the desktop.
GUARD_COUNTS = {"model_launches": 0, "native_notifications": 0, "subprocess_spawns": 0}

# Routes and states a client must still handle that the real server cannot produce here
# without a model call or a native action, with the reason. The manifest carries this
# table so a consumer sees what is absent and why, rather than finding a silent gap.
UNREACHABLE: dict[str, str] = {
    "reading-started": (
        "POST /api/reading answering 202 with a job starts a model reading; the guard "
        "forbids launching one, so no job or publication shape is captured"
    ),
    "reading-cancel-accepted": "needs a running reading job, which needs a model launch",
    "context-refresh-granted": (
        "GET /api/project-context?refresh=1&observer_model=1 with a model enabled "
        "spends a model call; only the model-disabled answer is captured"
    ),
    "data-usage-consented": (
        "GET /api/data?usage=1 starts a quota fetch against a vendor credential"
    ),
    "data-malformed-fields": (
        "the application always publishes the full row schema, so a missing or malformed "
        "field cannot come from the real server; clients derive those cases by mutating "
        "the captured healthy body"
    ),
    "data-missing-revision-header": (
        "a 200 from /api/data always carries X-Compass-Revision; the header is absent "
        "only on the refusals captured as data-forbidden-*, and clients strip it from "
        "data-healthy for the proxy case"
    ),
    "answer-confirmed": "needs a registered ask, which an agent's own ingress token creates",
    "focus-real-raise": "a real terminal raise is a native action; only an inert runner is used",
    "health": "the body carries the process id, which differs on every run",
    "interaction": "the terminal prototype is not started by the board server in these runs",
}


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def synthetic_row(
    harness: str,
    sid: str,
    project: str,
    *,
    title: str,
    state: str = "idle",
    age: float = 30.0,
    project_key: str | None = None,
    **fields: Any,
) -> dict[str, Any]:
    row = base_session(harness, sid, project)
    row.update(
        project_key=project_key or f"key-{_digest(harness + project)}",
        project_name=project,
        title=title,
        first_prompt=f"Synthetic task for {title}.",
        last_prompt="Keep going with the synthetic task.",
        prompt_at=NOW - age - 20,
        first_prompt_at=NOW - age - 600,
        last_activity=NOW - age,
        own_activity=NOW - age,
        started_at=NOW - 900,
        model="synthetic-model",
        active=state == "working",
        state=state,
        state_detail="running a synthetic tool" if state == "working" else "awaiting your message",
    )
    row.update(fields)
    return row


def healthy_rows() -> dict[str, list[dict[str, Any]]]:
    return {
        "claude": [
            synthetic_row(
                "claude", "a1b2c3d4", "alpha-app", title="Wire the parser", state="working"
            ),
            synthetic_row("claude", "e5f6a7b8", "alpha-app", title="Review the diff", age=240.0),
        ],
        "codex": [
            synthetic_row(
                "codex",
                "019c0000-1111-7222-8333-444455556666",
                "beta-api",
                title="Document the endpoint",
                age=90.0,
            ),
        ],
    }


def collision_rows() -> dict[str, list[dict[str, Any]]]:
    # One sid under two harnesses, and one project label shared by two distinct keys: the two
    # ways an identity built from the display half alone would merge unrelated work.
    return {
        "claude": [
            synthetic_row(
                "claude",
                "0123abcd",
                "shared",
                title="Claude side of the shared sid",
                project_key="key-shared-one",
            ),
            synthetic_row(
                "claude",
                "feedbeef",
                "shared",
                title="Same label, other repository",
                project_key="key-shared-two",
            ),
        ],
        "codex": [
            synthetic_row(
                "codex",
                "0123abcd",
                "shared",
                title="Codex side of the shared sid",
                project_key="key-shared-one",
            ),
        ],
    }


class Scratch:
    """One generation run's directory, removed on exit."""

    def __init__(self) -> None:
        self._dir = tempfile.TemporaryDirectory(prefix="compass-client-fixtures-")
        self.root = Path(self._dir.name).resolve()
        self._count = 0

    def subdir(self, name: str) -> Path:
        self._count += 1
        path = self.root / f"{self._count:02d}-{name}"
        path.mkdir()
        return path

    def close(self) -> None:
        self._dir.cleanup()


class Rig:
    """A real application and server, with synthetic rows and everything else inert."""

    def __init__(
        self,
        scratch: Scratch,
        name: str,
        *,
        rows: dict[str, list[dict[str, Any]]] | None = None,
        started: float = STARTED,
        page: bytes = PAGE_A,
        unavailable: tuple[str, ...] = (),
        with_focus: bool = False,
        blocked_state: bool = False,
        **config_changes: Any,
    ) -> None:
        self.dir = scratch.subdir(name)
        self.focus_now = NOW
        self.now = NOW
        if blocked_state:
            # A regular file where the state directory belongs, so no store can be created or
            # locked under it on any platform without relying on permission bits.
            (self.dir / "state").write_bytes(b"not a directory")
        self.rows = healthy_rows() if rows is None else rows
        self.unavailable = set(unavailable)
        self.diagnostics: list[str] = []
        flags: dict[str, Any] = {
            "spacedock_enabled": False,
            "tripwires_enabled": False,
            "usage_fetch_enabled": False,
            "model_calls_disabled": True,
            "git_probe_enabled": False,
            "focus_enabled": with_focus,
            "irreversible_enabled": False,
            "ask_enabled": False,
            "reach_enabled": False,
            "quiet_hours_enabled": False,
            "history_enabled": False,
        }
        config = build_runtime_config(
            environ={
                "HOME": str(self.dir),
                "USERPROFILE": str(self.dir),
                "COMPASS_HOME": str(self.dir / "state"),
            },
            # Terminals are only recorded for focus on macOS, so that one rig claims it; the
            # label is a config input and nothing in it touches the host.
            platform_name="darwin" if with_focus else "linux",
            os_name="posix",
            launcher_path=SKILL / "server.py",
            port=4581,
            store_root_overrides={"claude.projects": str(self.dir / "projects")},
            **flags,
        )
        self.config = dataclasses.replace(config, **config_changes)
        self.state = build_runtime_state(self.config, started=started)
        specs = tuple(
            HarnessSpec(key, label, lambda *_: True, self._collector(key))
            for key, label in (("claude", "Claude Code"), ("codex", "Codex"))
        )
        self.application = Application(
            self.config,
            self.state,
            specs,
            native_notifier=self._native,
            popup_notifier=self._popup,
            diagnostic_sink=self.diagnostics.append,
            clock=lambda: self.now,
            frontend_page_bytes=page,
        )
        self.observation: Any = None
        self.focus_runner = SimpleNamespace(calls=[])
        if with_focus:
            self._attach_focus()
        self.server = CompassHTTPServer(("127.0.0.1", 0), self.application, page, self.observation)
        self.port = self.server.server_port
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self) -> None:
        with contextlib.suppress(Exception):
            self.server.serve_forever(0.01)

    def _native(self, _platform: str) -> str:
        # A capability probe the payload publishes, not a notification.
        return "disabled"

    def _popup(self, _title: str, _message: str) -> None:
        GUARD_COUNTS["native_notifications"] += 1

    def _collector(self, key: str) -> Callable[..., list[dict[str, Any]]]:
        def collect(*_: Any) -> list[dict[str, Any]]:
            if key in self.unavailable:
                msg = "synthetic store unavailable"
                raise OSError(msg)
            return [dict(row) for row in self.rows.get(key, [])]

        return collect

    def _attach_focus(self) -> None:
        self.observation = observation_module.Observation(
            self.application, clock=lambda: self.focus_now, diagnostic_sink=lambda _line: None
        )
        server_pid = "84321"
        self.observation.submit(
            "claude",
            {
                "v": 1,
                "event": "session_started",
                "session_id": "a1b2c3d4-0000-4000-8000-000000000000",
                "tmux_socket": "default",
                "tmux_pane": "%3",
                "tmux_server": server_pid,
            },
        )

        def runner(argv: Any, **_kwargs: Any) -> Any:
            # An inert tmux: answers the two lookups the raise performs and the switch itself,
            # so no process is spawned and nothing on the host moves.
            self.focus_runner.calls.append(tuple(argv))
            if "display-message" in argv:
                return SimpleNamespace(
                    returncode=0, stdout=f"{server_pid} work\n".encode(), stderr=b""
                )
            if "list-clients" in argv:
                return SimpleNamespace(returncode=0, stdout=b"/dev/ttys007\n", stderr=b"")
            return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")

        self.observation._focus_runner = runner  # noqa: SLF001 - the one inert-runner seam

    @property
    def capability(self) -> str:
        return str(self.observation.focus_capability())

    def write_transcript(self, sid: str, entries: list[dict[str, Any]]) -> None:
        """A Claude Code transcript where the resolver globs for one."""
        folder = self.dir / "projects" / "-work-alpha-app"
        folder.mkdir(parents=True, exist_ok=True)
        lines = "\n".join(json.dumps(entry) for entry in entries)
        (folder / f"{sid}-full.jsonl").write_text(lines + "\n", encoding="utf-8")

    def republish(self) -> None:
        """Drop the published bodies so the next read collects the current rows."""
        self.application.snapshot.clear()

    def close(self) -> None:
        with contextlib.suppress(Exception):
            self.state.streams.close_all()
        self.server.shutdown()
        self.server.server_close()
        self._thread.join(timeout=5)

    def fill(self, text: str) -> str:
        return text.replace(ORIGIN, f"http://127.0.0.1:{self.port}").replace(
            CAPABILITY, self.capability if self.observation else ""
        )

    def send(self, request: dict[str, Any]) -> dict[str, Any]:
        """Send one templated request; return the response the real server wrote."""
        headers = {key: self.fill(value) for key, value in request.get("headers", {}).items()}
        if "body" in request and request["body"] is not None:
            payload = json.dumps(request["body"], separators=(",", ":")).encode()
        elif "body_text" in request:
            payload = str(request["body_text"]).encode()
        elif "body_padding_bytes" in request:
            payload = b" " * int(request["body_padding_bytes"])
        else:
            payload = None
        if payload is not None:
            headers.setdefault("Content-Type", "application/json")
        target = request["path"] + (f"?{request['query']}" if request.get("query") else "")
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            connection.request(request["method"], target, body=payload, headers=headers)
            response = connection.getresponse()
            body = response.read()
            return _response_record(response.status, response.getheaders(), body)
        finally:
            connection.close()


def _response_record(status: int, headers: list[tuple[str, str]], body: bytes) -> dict[str, Any]:
    kept = {name: value for name, value in headers if name in KEPT_HEADERS}
    record: dict[str, Any] = {"status": status, "headers": dict(sorted(kept.items()))}
    content_type = kept.get("Content-Type", "")
    text = body.decode("utf-8")
    if content_type.startswith("application/json"):
        record["body"] = json.loads(text)
    elif content_type.startswith("text/html"):
        # An error page is the standard library's, and its wording and markup change between
        # Python releases (413 reads "Request Entity Too Large" through 3.12 and "Content Too
        # Large" from 3.13; 3.14 adds a <style> block), so the exact text would make these
        # files depend on the interpreter. What a client can rely on is that the body is HTML
        # naming the status, so that is what is recorded and checked here.
        if f"<p>Error code: {status}</p>" not in text or "<h1>Error response</h1>" not in text:
            msg = f"unexpected error page for {status}: {text[:80]!r}"
            raise ValueError(msg)
        record["headers"].pop("Content-Length", None)
        record["error_page"] = {
            "contains": [f"Error code: {status}", "Error response"],
            "kind": "python-http-server",
        }
    else:
        record["text"] = text
    return record


def get(path: str, query: str = "", **headers: str) -> dict[str, Any]:
    return {"method": "GET", "path": path, "query": query, "headers": dict(headers), "body": None}


def post(path: str, body: Any = None, **headers: str) -> dict[str, Any]:
    return {
        "method": "POST",
        "path": path,
        "query": "",
        "headers": {"Origin": ORIGIN, **headers},
        "body": body,
    }


class Recorder:
    def __init__(self) -> None:
        self.scenarios: dict[str, dict[str, Any]] = {}

    def add(
        self,
        name: str,
        request: dict[str, Any],
        response: dict[str, Any],
        notes: str,
    ) -> None:
        if name in self.scenarios:
            msg = f"duplicate scenario {name}"
            raise ValueError(msg)
        self.scenarios[name] = {
            "format": FORMAT,
            "name": name,
            "request": request,
            "response": response,
            "notes": notes,
        }

    def capture(self, rig: Rig, name: str, request: dict[str, Any], notes: str) -> dict[str, Any]:
        response = rig.send(request)
        self.add(name, request, response, notes)
        return response


# ---- streams ---------------------------------------------------------------------------


def _read_more(
    sock: socket.socket, received: str, stop: Callable[[str], bool], deadline: float
) -> str:
    """Append what the stream sends until `stop(text)`, the peer closes, or the deadline."""
    while not stop(received) and time.monotonic() < deadline:
        chunk = sock.recv(4096)
        if not chunk:
            break
        received += chunk.decode("utf-8")
    return received


def _read_stream(
    rig: Rig,
    request: dict[str, Any],
    *,
    stop: Callable[[str], bool],
    frames: int,
    during: Callable[[], None] | None = None,
    timeout: float = 10.0,
) -> dict[str, Any]:
    """Open `/api/stream`, read frames until `stop(text)`, then drop the connection.

    A raw socket, because `http.client` closes a response it cannot frame by length. The head
    is parsed here so the status and headers are the server's own; the body is the event-stream
    text an EventSource would parse.
    """
    headers = {key: rig.fill(value) for key, value in request.get("headers", {}).items()}
    lines = [f"GET {request['path']} HTTP/1.1", f"Host: 127.0.0.1:{rig.port}", "Connection: close"]
    lines.extend(f"{name}: {value}" for name, value in headers.items())
    with socket.create_connection(("127.0.0.1", rig.port), timeout=timeout) as sock:
        sock.sendall(("\r\n".join(lines) + "\r\n\r\n").encode())
        raw = b""
        deadline = time.monotonic() + timeout
        head, separator, body = b"", b"", b""
        while not separator and time.monotonic() < deadline:
            chunk = sock.recv(4096)
            if not chunk:
                break
            raw += chunk
            head, separator, body = raw.partition(b"\r\n\r\n")
        status_line, *header_lines = head.decode("iso-8859-1").split("\r\n")
        status = int(status_line.split(" ")[1])
        pairs = [
            (name, value) for name, _, value in (line.partition(": ") for line in header_lines)
        ]
        if status != 200:
            # An error page is framed by Content-Length, so read it out whole.
            while time.monotonic() < deadline:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                body += chunk
            return _response_record(status, pairs, body)
        received = body.decode("utf-8")
        if during is not None:
            # The server picks the connect-time revision on its own thread after the head is
            # sent, so a write made before that frame is read can become that frame and leave
            # nothing to wait for. Publish only once the connect-time frame has arrived.
            received = _read_more(sock, received, lambda text: "\n\n" in text, deadline)
            during()
        received = _read_more(sock, received, stop, deadline)
    record = _response_record(status, pairs, b"")
    # Cut to the frames the scenario is about. A reader that stalls past the heartbeat is
    # sent extra keepalive comments, and those are timing, not contract.
    record["text"] = "".join(f"{frame}\n\n" for frame in received.split("\n\n")[:frames])
    return record


def stream_heartbeat(recorder: Recorder, scratch: Scratch) -> None:
    """Its own function so a test can slow the reader for this scenario alone."""
    initial = get("/api/stream", **{"Sec-Fetch-Site": "same-origin"})
    rig = Rig(scratch, "stream-heartbeat", stream_heartbeat_sec=0.2)
    try:
        recorder.add(
            "stream-heartbeat",
            initial,
            _read_stream(rig, initial, stop=lambda text: "keepalive" in text, frames=1),
            "Before anything is published the stream carries only the comment heartbeat, "
            "which an EventSource never delivers as an event.",
        )
    finally:
        rig.close()


def stream_scenarios(recorder: Recorder, scratch: Scratch) -> None:
    initial = get("/api/stream", **{"Sec-Fetch-Site": "same-origin"})
    rig = Rig(scratch, "stream-initial")
    try:
        rig.send(get("/api/data"))
        recorder.add(
            "stream-initial-revision",
            initial,
            _read_stream(rig, initial, stop=lambda text: text.endswith("\n\n"), frames=1),
            "A client that connects after the board has published sees the current revision "
            "at once; id and data are the same <started>.<counter> string.",
        )
    finally:
        rig.close()

    stream_heartbeat(recorder, scratch)

    rig = Rig(scratch, "stream-change")
    try:
        # Published once so the change below is revision 2, not the first publication.
        rig.send(get("/api/data"))

        def change() -> None:
            rig.send(post("/api/lane", {"supported": True, "permission": "granted"}))
            rig.send(get("/api/data"))

        recorder.add(
            "stream-revision-after-change",
            initial,
            _read_stream(
                rig,
                initial,
                stop=lambda text: text.count("event: revision") >= 2,
                frames=2,
                during=change,
            ),
            "The connect-time frame for revision 1, then revision 2 after an invalidating "
            "write and the read that republishes.",
        )
    finally:
        rig.close()

    rig = Rig(scratch, "stream-restarted", started=RESTARTED, page=PAGE_B)
    try:
        rig.send(get("/api/data"))
        recorder.add(
            "stream-restarted-build",
            initial,
            _read_stream(rig, initial, stop=lambda text: text.endswith("\n\n"), frames=1),
            "The same route from a server that restarted: the start stamp half of the "
            "revision differs, which a client must read as newer whatever the counter says.",
        )
    finally:
        rig.close()

    stream_refusals(recorder, scratch)


def stream_refusals(recorder: Recorder, scratch: Scratch) -> None:
    refusals = {
        "stream-forbidden-frame": (
            "A frame navigation is refused so a framing page cannot hold a socket.",
            {
                "Sec-Fetch-Site": "same-site",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Dest": "iframe",
            },
        ),
        "stream-forbidden-cross-site": (
            "A cross-site fetch of the stream is refused; the navigation exception does not apply.",
            {"Sec-Fetch-Site": "cross-site", "Sec-Fetch-Mode": "cors", "Sec-Fetch-Dest": "empty"},
        ),
    }
    rig = Rig(scratch, "stream-refusals")
    try:
        for name, (notes, headers) in refusals.items():
            recorder.capture(rig, name, get("/api/stream", **headers), notes)
    finally:
        rig.close()

    rig = Rig(scratch, "stream-budget", stream_max_clients=1)
    try:
        held = http.client.HTTPConnection("127.0.0.1", rig.port, timeout=10)
        try:
            held.request("GET", "/api/stream")
            held.getresponse()
            recorder.capture(
                rig,
                "stream-budget-exhausted",
                get("/api/stream"),
                "With the one stream slot taken the next client is refused 503, never queued.",
            )
        finally:
            held.close()
    finally:
        rig.close()


# ---- scenario sections ------------------------------------------------------------------


def data_scenarios(recorder: Recorder, scratch: Scratch) -> None:
    rig = Rig(scratch, "data")
    try:
        recorder.capture(
            rig,
            "data-healthy",
            get("/api/data"),
            "Two harnesses, three synthetic sessions, both stores readable.",
        )
        recorder.capture(
            rig,
            "data-show-all",
            get("/api/data", "all=1"),
            "all=1 is the only query value that widens the window; the variant keeps its own "
            "revision.",
        )
        recorder.capture(
            rig,
            "data-forbidden-cross-site",
            get(
                "/api/data",
                **{
                    "Sec-Fetch-Site": "cross-site",
                    "Sec-Fetch-Mode": "cors",
                    "Sec-Fetch-Dest": "empty",
                },
            ),
            "A refusal is an HTML error page with no X-Compass-Revision and no JSON body.",
        )
        recorder.capture(
            rig,
            "data-forbidden-host",
            get("/api/data", Host="evil.example"),
            "A Host that is not a loopback literal is refused before anything is read.",
        )
        recorder.capture(
            rig,
            "api-not-found",
            get("/api/not-a-route"),
            "An unknown API path answers 404 as HTML.",
        )
    finally:
        rig.close()

    rig = Rig(scratch, "data-empty", rows={"claude": [], "codex": []})
    try:
        recorder.capture(
            rig,
            "data-empty",
            get("/api/data"),
            "Both stores read cleanly and hold no sessions: empty, and no harness error.",
        )
    finally:
        rig.close()

    rig = Rig(
        scratch, "data-unavailable", rows={"claude": [], "codex": []}, unavailable=("claude",)
    )
    try:
        recorder.capture(
            rig,
            "data-unavailable",
            get("/api/data"),
            "The Claude store cannot be read: no rows, and the harness carries an error. "
            "Source availability stays distinct from an empty store.",
        )
    finally:
        rig.close()

    rig = Rig(scratch, "data-collisions", rows=collision_rows())
    try:
        recorder.capture(
            rig,
            "data-identity-collisions",
            get("/api/data"),
            "The same sid under claude and codex, and one project label under two project keys.",
        )
    finally:
        rig.close()

    rig = Rig(scratch, "data-restarted", started=RESTARTED, page=PAGE_B)
    try:
        recorder.capture(
            rig,
            "data-restarted-build",
            get("/api/data"),
            "The same board from a restarted server: a new start stamp in the revision header "
            "and a different build id, with the counter back at 1.",
        )
    finally:
        rig.close()


SESSION = {"harness": "claude", "sid": "a1b2c3d4"}
HOST_PORT_MISMATCH = "http://127.0.0.1:1"


def context_scenarios(recorder: Recorder, scratch: Scratch) -> None:
    rig = Rig(scratch, "context")
    try:
        key = healthy_rows()["claude"][0]["project_key"]
        recorder.capture(
            rig,
            "context-project",
            get("/api/project-context", "project=alpha-app"),
            "Project scope: no session, so no session levels; a model-disabled run says so in "
            "observer_model.enabled.",
        )
        recorder.capture(
            rig,
            "context-project-key",
            get("/api/project-context", f"project={key}"),
            "The stable project key is accepted where the display label is; two projects may "
            "share a label.",
        )
        recorder.capture(
            rig,
            "context-focused-session",
            get("/api/project-context", "project=alpha-app&session=claude:a1b2c3d4"),
            "Focused scope: the exact harness:sid pair, split at the first colon.",
        )
        recorder.capture(
            rig,
            "context-refresh-model-disabled",
            get(
                "/api/project-context",
                "project=alpha-app&session=claude:a1b2c3d4&refresh=1&observer_model=1",
            ),
            "An explicit summary request on a run with model calls off: answered 200 from "
            "local sources with no model called, and observer_model.enabled false.",
        )
        recorder.capture(
            rig,
            "context-missing-project",
            get("/api/project-context", ""),
            "No project scope is a 400, never an empty context.",
        )
        recorder.capture(
            rig,
            "context-overlong-project",
            get("/api/project-context", "project=" + "p" * 513),
            "A project past the 512-character identity cap is refused.",
        )
        recorder.capture(
            rig,
            "context-malformed-session",
            get("/api/project-context", "project=alpha-app&session=claude"),
            "A session without the harness:sid separator is refused rather than guessed.",
        )
        recorder.capture(
            rig,
            "context-refresh-without-session",
            get("/api/project-context", "project=alpha-app&refresh=1"),
            "refresh=1 needs an exact focused session.",
        )
        recorder.capture(
            rig,
            "context-forbidden-host",
            get("/api/project-context", "project=alpha-app", Host="evil.example"),
            "The strict origin check applies; the navigation exception is not inherited.",
        )
    finally:
        rig.close()


def annotation_scenarios(recorder: Recorder, scratch: Scratch) -> None:
    rig = Rig(scratch, "annotations")
    try:
        recorder.capture(
            rig,
            "annotations-empty",
            get("/api/annotations"),
            "An empty store reads as an empty list.",
        )
        goal = {**SESSION, "goal": "Ship the parser", "lines": ["Tests pass"]}
        recorder.capture(
            rig,
            "annotate-stored",
            post("/api/annotate", goal),
            "First save: stored, revision 1, persisted true.",
        )
        recorder.capture(
            rig,
            "annotate-unchanged",
            post("/api/annotate", goal),
            "The same words again: unchanged, still persisted, no new revision.",
        )
        recorder.capture(
            rig,
            "annotate-stale-lines",
            post("/api/annotate", {**SESSION, "goal": "Ship the parser", "lines": ["Docs build"]}),
            "Replacing a stored outcome list without naming the revision it was drafted "
            "against is refused, so a stale tab cannot overwrite a newer one.",
        )
        recorder.capture(
            rig,
            "annotate-current-revision",
            post(
                "/api/annotate",
                {
                    **SESSION,
                    "goal": "Ship the parser",
                    "lines": ["Docs build"],
                    "expected_revision": 1,
                },
            ),
            "The same replacement naming the stored revision is stored as revision 2.",
        )
        recorder.capture(
            rig,
            "annotations-populated",
            get("/api/annotations"),
            "One annotated session with two revisions and the published binding and "
            "departure fields.",
        )
        recorder.capture(
            rig,
            "annotate-refused",
            post("/api/annotate", {**SESSION, "sid": "00000000", "adopt": "last"}),
            "Adopting a prompt for a session the board does not publish is refused, with "
            "persisted false.",
        )
        recorder.capture(
            rig,
            "annotate-too-large",
            {**post("/api/annotate"), "body": None, "body_padding_bytes": 12_289},
            "A body over the 12288-byte annotation cap is refused 413 before it is read.",
        )
        recorder.capture(
            rig,
            "annotate-malformed-identity",
            post("/api/annotate", {"harness": ["claude"], "sid": "a1b2c3d4", "goal": "x"}),
            "A harness that is not a string is a 400, never stored under its repr.",
        )
        recorder.capture(
            rig,
            "annotate-forbidden-origin",
            {**post("/api/annotate", goal), "headers": {"Origin": HOST_PORT_MISMATCH}},
            "An Origin on another local port is not the same origin.",
        )
        recorder.capture(
            rig,
            "annotations-forbidden-host",
            get("/api/annotations", Host="evil.example"),
            "The annotation log is strict-origin.",
        )
    finally:
        rig.close()

    rig = Rig(scratch, "annotate-untrusted")
    try:
        path = Path(annotation_store.store_path(rig.config))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"this is not json")
        recorder.capture(
            rig,
            "annotate-untrusted",
            post("/api/annotate", {**SESSION, "goal": "Ship the parser"}),
            "The store file exists and cannot be read whole, so nothing is written over it.",
        )
    finally:
        rig.close()

    rig = Rig(scratch, "annotate-unreadable")
    try:
        path = Path(annotation_store.store_path(rig.config))
        path.parent.mkdir(parents=True, exist_ok=True)
        held = {
            "harness": "claude",
            "sid": "a1b2c3d4",
            "revisions": [{"shape": "from a later build"}],
        }
        path.write_text(json.dumps({"entries": [held]}), encoding="utf-8")
        recorder.capture(
            rig,
            "annotate-unreadable",
            post("/api/annotate", {**SESSION, "goal": "Ship the parser"}),
            "This session's own entry was written by a build that reads more than this one; "
            "it is kept raw and not written over.",
        )
    finally:
        rig.close()

    rig = Rig(scratch, "annotate-unwritable", blocked_state=True)
    try:
        recorder.capture(
            rig,
            "annotate-unwritable",
            post("/api/annotate", {**SESSION, "goal": "Ship the parser"}),
            "The state home cannot hold the store or its lock: kept for this run only, "
            "persisted false.",
        )
    finally:
        rig.close()

    rig = Rig(scratch, "annotations-disabled", annotations_enabled=False)
    try:
        recorder.capture(
            rig,
            "annotations-disabled",
            get("/api/annotations"),
            "Run with annotations off: the route exists and the store does not, so 503.",
        )
        recorder.capture(
            rig,
            "annotate-disabled",
            post("/api/annotate", {**SESSION, "goal": "Ship the parser"}),
            "The same switch refuses the save with 503.",
        )
    finally:
        rig.close()


def action_scenarios(recorder: Recorder, scratch: Scratch) -> None:
    rig = Rig(scratch, "actions")
    try:
        recorder.capture(
            rig,
            "lane-reported",
            post("/api/lane", {"supported": True, "permission": "granted"}),
            "A tab reporting a working notification lane.",
        )
        recorder.capture(
            rig,
            "lane-names-session",
            post("/api/lane", {"supported": True, "permission": "granted", "sid": "a1b2c3d4"}),
            "A body naming a session is refused rather than sanitized.",
        )
        recorder.capture(
            rig,
            "lane-malformed",
            post("/api/lane", [1]),
            "A body that is not an object is a 400.",
        )
        recorder.capture(
            rig,
            "dismiss-persisted",
            post("/api/dismiss", SESSION),
            "Marking one exact session handled; persisted says whether it survives a restart.",
        )
        recorder.capture(
            rig,
            "cleared-after-dismiss",
            get("/api/cleared"),
            "The handled sessions, identified by harness and sid only.",
        )
        recorder.capture(
            rig,
            "notify-accepted",
            post("/api/notify", {"session_id": "a1b2c3d4", "message": "needs input"}),
            "The hook route answers 200 with a suppression reason rather than raising a "
            "native notification (the session was just dismissed).",
        )
        recorder.capture(
            rig,
            "notify-too-large",
            {**post("/api/notify"), "body": None, "body_padding_bytes": 70_000},
            "An oversized hook body is refused 413.",
        )
        recorder.capture(
            rig,
            "tripwire-disabled",
            post("/api/tripwire", {}),
            "Tripwires off for this run: the route exists and the feature does not, so 503.",
        )
        recorder.capture(
            rig,
            "answer-disabled",
            post("/api/answer", {"id": "no-such-ask", "index": 0}),
            "Question answering off for this run: 503, with no hint about which asks exist.",
        )
        recorder.capture(
            rig,
            "focus-disabled",
            post("/api/focus", SESSION, **{"X-Compass-Capability": CAPABILITY}),
            "Focus off for this run (the default): 503, whatever the capability.",
        )
    finally:
        rig.close()

    rig = Rig(scratch, "dismiss-disabled", dismissals_enabled=False)
    try:
        recorder.capture(
            rig,
            "dismiss-disabled",
            post("/api/dismiss", SESSION),
            "Dismissals off: 503.",
        )
    finally:
        rig.close()

    rig = Rig(scratch, "answer", ask_enabled=True)
    try:
        recorder.capture(
            rig,
            "answer-unknown-ask",
            post("/api/answer", {"id": "no-such-ask", "index": 0}),
            "An id that names no ask answers the same as any other refusal.",
        )
    finally:
        rig.close()


def copy_and_direction_scenarios(recorder: Recorder, scratch: Scratch) -> None:
    rig = Rig(scratch, "correction")
    try:
        recorder.capture(
            rig,
            "direction-not-found",
            post("/api/direction", {**SESSION, "fact_id": "fact-1"}),
            "A direction the session record cannot open answers one 200 body, never a 404.",
        )
        recorder.capture(
            rig,
            "direction-malformed",
            post("/api/direction", {"harness": "claude"}),
            "Missing identity fields are a 400.",
        )
        recorder.capture(
            rig,
            "direction-forbidden-origin",
            {
                **post("/api/direction", {**SESSION, "fact_id": "fact-1"}),
                "headers": {"Origin": HOST_PORT_MISMATCH},
            },
            "A wrong-port Origin is refused before the body is read.",
        )
        recorder.capture(
            rig,
            "correction-nothing-to-steer",
            post("/api/correction", SESSION),
            "A session with nothing to steer from answers one 200 body, which is also what an "
            "unknown session answers.",
        )
        recorder.capture(
            rig,
            "correction-copied-accepted",
            post("/api/correction/copied", {**SESSION, "text": "Please keep the diff small."}),
            "Registering a copy answers one body whatever the session is.",
        )
        recorder.capture(
            rig,
            "correction-copied-malformed",
            post("/api/correction/copied", {"harness": "claude"}),
            "A copy with no sid or text is a 400.",
        )
    finally:
        rig.close()


def reading_scenarios(recorder: Recorder, scratch: Scratch) -> None:
    press = {**SESSION, "observer_model": 1, "press": True}
    rig = Rig(scratch, "reading-disabled")
    try:
        recorder.capture(
            rig,
            "reading-model-disabled",
            post("/api/reading", press),
            "A run with model calls off refuses every reading with 503 before anything else.",
        )
        recorder.capture(
            rig,
            "reading-cancel-model-disabled",
            post("/api/reading/cancel", {**press, "job": "j1"}),
            "Cancel shares the admission and refuses the same way.",
        )
    finally:
        rig.close()

    # Both providers look usable and name a fixed destination, so the route a press resolves
    # does not depend on which CLIs or settings the machine regenerating this happens to have.
    # Only inputs to the route's own code are fixed; no reply is written here.
    patches = contextlib.ExitStack()
    patches.enter_context(mock.patch.object(shutil, "which", lambda name: f"/synthetic/{name}"))
    real_destination = runtime_reading_route.destination
    empty_root = scratch.subdir("no-settings")
    patches.enter_context(
        mock.patch.object(
            runtime_reading_route,
            "destination",
            # The route's own resolution, against no environment variables and no settings files,
            # which is the shipped default and so names the vendor.
            lambda provider, **_: real_destination(
                # An account is named explicitly: with none, the route asks the POSIX password file,
                # which Windows lacks, and then names no destination there at all.
                provider,
                environ={"HOME": "/synthetic/home", "USER": "fixture"},
                root=empty_root,
                system="Linux",
            ),
        )
    )
    rig = Rig(scratch, "reading", model_calls_disabled=False)
    try:
        model = runtime_reading_route.resolve("claude", config=rig.config)["model"]
        same_site = {"Sec-Fetch-Site": "same-site"}
        recorder.capture(
            rig,
            "reading-malformed-press",
            post("/api/reading", {**SESSION, "press": True}),
            "A press that does not carry observer_model=1 is a 400.",
        )
        recorder.capture(
            rig,
            "reading-too-large",
            {**post("/api/reading"), "body": None, "body_padding_bytes": 12_289},
            "A body over the annotation cap is refused 413.",
        )
        recorder.capture(
            rig,
            "reading-forbidden-origin",
            {**post("/api/reading", press), "headers": {"Origin": HOST_PORT_MISMATCH}},
            "A wrong-port Origin never reaches the reading gate.",
        )
        recorder.capture(
            rig,
            "reading-forbidden-same-site",
            post("/api/reading", press, **same_site),
            "A same-site fetch from another local port is refused: a reading spends the "
            "reader's own capacity.",
        )
        recorder.capture(
            rig,
            "reading-provider-changed",
            post("/api/reading", {**press, "provider": "codex"}),
            "The page named a provider that is not the one this press would reach: 409, with "
            "nothing consented or spent.",
        )
        recorder.capture(
            rig,
            "reading-revision-changed",
            post("/api/reading", {**press, "expected_revision": 5}),
            "A press drawn against a revision that is not the stored one: 409.",
        )
        recorder.capture(
            rig,
            "reading-adoption-refused",
            post("/api/reading", {**press, "settle_through": 1.0}),
            "Keep without the revision it settles: refused 422 before any route or model.",
        )
        recorder.capture(
            rig,
            "reading-stale-model",
            post("/api/reading", {**press, "provider": "claude", "model": "stale-model"}),
            "The Claude model the page drew is not the one the route selects: 409, nothing "
            "recorded and nothing spent.",
        )
        recorder.capture(
            rig,
            "reading-page-outdated",
            post("/api/reading", {**press, "provider": "claude", "model": model, "allow": True}),
            "An Allow from a page that predates words_destination is refused 400 and records "
            "no consent.",
        )
        recorder.capture(
            rig,
            "reading-destination-changed",
            post(
                "/api/reading",
                {
                    **press,
                    "provider": "claude",
                    "model": model,
                    "allow": True,
                    "words_destination": "Somewhere else",
                },
            ),
            "An Allow given for a destination other than today's is refused 409, and records "
            "no consent.",
        )
        # A fresh store no longer refuses a press (DEC-28), so the refusal recorded is a
        # stored Turn off readings, the one answer that still stops a reader-started call.
        rig.send(post("/api/reading", {**press, "consent": "off"}))
        off = recorder.capture(
            rig,
            "reading-off",
            post("/api/reading", {**press, "provider": "claude", "model": model}),
            "With readings turned off, a resolved route answers 403 readings-off and names its "
            "route; nothing is read.",
        )
        route = off["body"].get("route", {})
        recorder.capture(
            rig,
            "reading-unknown-session",
            post(
                "/api/reading",
                {
                    **press,
                    "sid": "00000000",
                    "provider": route.get("provider"),
                    "model": route.get("model"),
                    "allow": True,
                    "words_destination": route.get("words_destination"),
                    "tool_output": route.get("destination"),
                },
            ),
            "With the route's own disclosure echoed back, a session that is not published "
            "answers 200 produced:false, never a 404 that would reveal which sids exist.",
        )
        recorder.capture(
            rig,
            "reading-cancel-not-running",
            post("/api/reading/cancel", {**press, "job": "j1"}),
            "No running job by that id: 409 not-running, the same answer for an unknown session.",
        )
        recorder.capture(
            rig,
            "reading-cancel-malformed",
            post("/api/reading/cancel", press),
            "A cancel without a job id is a 400.",
        )
    finally:
        rig.close()
        patches.close()


class FrozenTime:
    """The `time` module with `time()` pinned, patched into one module's namespace only."""

    @staticmethod
    def time() -> float:
        return NOW

    def __getattr__(self, name: str) -> Any:
        return getattr(time, name)


FIRST_PROMPT = "Add retry with backoff to the webhook handler."
LATER_PROMPT = "Keep the diff small and leave the tests alone."


def _transcript_entry(kind: str, text: str, at: float, index: int) -> dict[str, Any]:
    stamp = datetime.datetime.fromtimestamp(at, datetime.UTC).isoformat().replace("+00:00", "Z")
    return {
        "type": kind,
        "uuid": f"u{index}",
        "parentUuid": f"u{index - 1}" if index else None,
        "isSidechain": False,
        "cwd": "/work/alpha-app",
        "sessionId": "a1b2c3d4-0000-4000-8000-000000000000",
        "timestamp": stamp,
        "message": {"role": kind, "content": [{"type": "text", "text": text}]},
    }


def adoption_scenarios(recorder: Recorder, scratch: Scratch) -> None:
    first_at, later_at = NOW - 3600, NOW - 1800
    row = synthetic_row(
        "claude",
        "a1b2c3d4",
        "alpha-app",
        title="Retry work",
        state="working",
        age=5.0,
        first_prompt=FIRST_PROMPT,
        first_prompt_at=first_at,
        last_prompt=LATER_PROMPT,
        prompt_at=later_at,
    )
    rig = Rig(scratch, "adoption", rows={"claude": [row], "codex": []})
    try:
        rig.write_transcript(
            "a1b2c3d4",
            [
                _transcript_entry("user", FIRST_PROMPT, first_at, 0),
                _transcript_entry("assistant", "Done.", first_at + 60, 1),
                _transcript_entry("user", LATER_PROMPT, later_at, 2),
            ],
        )
        scope = "project=alpha-app&session=claude:a1b2c3d4"
        context = recorder.capture(
            rig,
            "context-focused-facts",
            get("/api/project-context", scope),
            "A focused session whose transcript the server reads: the observed record carries "
            "one fact per person message, each with a stable fact_id.",
        )
        recorder.capture(
            rig,
            "context-focused-prompts",
            get("/api/project-context", scope + "&prompts=1"),
            "prompts=1 adds the menu of prompts this session can adopt as its goal.",
        )
        for name, query, note in (
            (
                "record-newest-to-start",
                scope + "&limit=50",
                "The newest message facts reach the start of this short synthetic record.",
            ),
            (
                "record-stale",
                scope + "&before=invalid",
                "An unauthenticated cursor returns stale without a boundary claim.",
            ),
            (
                "record-unavailable",
                "project=alpha-app&session=claude:unknown",
                "An unknown source establishes no record start.",
            ),
            (
                "record-malformed-session",
                "project=alpha-app&session=claude",
                "The exact identity guard refuses a missing sid.",
            ),
        ):
            recorder.capture(rig, name, get("/api/session-record", query), note)
        facts = context["body"]["semantic"]["facts"]
        later = next(
            fact for fact in facts if fact.get("type") == "user_message" and fact["at"] > first_at
        )
        recorder.capture(
            rig,
            "annotate-adopted",
            post(
                "/api/annotate",
                {
                    **SESSION,
                    "adopt": "first-prompt",
                    "expected_prompt": FIRST_PROMPT,
                    "expected_prompt_at": first_at,
                    "expected_revision": 0,
                },
            ),
            "Adopting the first prompt as the goal: stored, and saved_revision names the "
            "revision this adoption wrote.",
        )
        original_config = rig.application.config
        rig.application.config = dataclasses.replace(original_config, direction_scan_max_bytes=16)
        recorder.capture(
            rig,
            "direction-out-of-reach",
            post("/api/direction", {**SESSION, "fact_id": later["fact_id"]}),
            "A known direction beyond the search allowance is distinct from a missing record, "
            "still HTTP 200.",
        )
        rig.application.config = original_config
        recorder.capture(
            rig,
            "direction-opened",
            post("/api/direction", {**SESSION, "fact_id": later["fact_id"]}),
            "A later direction read back whole for review.",
        )
        recorder.capture(
            rig,
            "direction-batch-mixed",
            post(
                "/api/direction",
                {**SESSION, "fact_ids": ["fact:missing", later["fact_id"], later["fact_id"]]},
            ),
            "One batch returns the single-id answer shapes, including repeated ids, "
            "in request order.",
        )
        recorder.capture(
            rig,
            "direction-batch-invalid",
            post("/api/direction", {**SESSION, "fact_ids": ["x"] * 65}),
            "More than 64 ids is refused before scanning.",
        )
        recorder.capture(
            rig,
            "annotate-direction-added",
            post(
                "/api/annotate",
                {
                    **SESSION,
                    "add_direction": later["fact_id"],
                    "text": LATER_PROMPT,
                    "expected_revision": 1,
                },
            ),
            "The reviewed direction saved as an outcome line, revision 2.",
        )
        recorder.capture(
            rig,
            "annotate-direction-refused",
            post(
                "/api/annotate",
                {
                    **SESSION,
                    "add_direction": "fact:0000000000000000",
                    "text": "x",
                    "expected_revision": 2,
                },
            ),
            "A fact the session record does not hold is refused, persisted false.",
        )
        with mock.patch.object(annotation_store, "time", FrozenTime()):
            recorder.capture(
                rig,
                "annotate-cleared",
                post("/api/annotate", {**SESSION, "clear": True}),
                "Clearing withdraws every revision and stamps the discard. The server stamps it "
                "from the wall clock, so this module's clock is pinned for the one request.",
            )
    finally:
        rig.close()


def tripwire_scenarios(recorder: Recorder, scratch: Scratch) -> None:
    key = "0" * 63 + "1"
    request = {"id": key, "stage": "review", "action": "remove", "expected_revision": ""}
    rig = Rig(scratch, "tripwire", tripwires_enabled=True)
    try:
        recorder.capture(
            rig,
            "tripwire-invalid",
            post("/api/tripwire", {}),
            "A body that is not exactly id, stage, action and expected_revision is a 400 with "
            "the reason in JSON.",
        )
        recorder.capture(
            rig,
            "tripwire-stale-revision",
            post("/api/tripwire", {**request, "expected_revision": "a" * 32}),
            "A condition that changed since the page read it is a 409; nothing is saved.",
        )
        recorder.capture(
            rig,
            "tripwire-removed",
            post("/api/tripwire", request),
            "A writable store accepts the change: 200 with the resulting rule (none, after a "
            "removal).",
        )
    finally:
        rig.close()

    # A state home that cannot hold the store fails in a different place on each platform
    # (unreadable first on one, unwritable first on another), so each state is made at the one
    # function the route calls for it, and the route's own answer to it is what is recorded.
    rig = Rig(scratch, "tripwire-blocked", tripwires_enabled=True)
    try:
        with mock.patch.object(runtime_tripwires, "load", lambda *_args, **_kwargs: None):
            recorder.capture(
                rig,
                "tripwire-unreadable",
                post("/api/tripwire", request),
                "A store that cannot be read: 503, nothing saved, and the sentence says no stage "
                "condition is being checked.",
            )
        with mock.patch.object(runtime_tripwires, "save", lambda *_args, **_kwargs: False):
            recorder.capture(
                rig,
                "tripwire-unwritable",
                post("/api/tripwire", request),
                "A store that refuses the write: 503, nothing saved.",
            )
    finally:
        rig.close()


def focus_scenarios(recorder: Recorder, scratch: Scratch) -> None:
    rig = Rig(scratch, "focus", with_focus=True)
    capability = {"X-Compass-Capability": CAPABILITY}
    try:
        recorder.capture(
            rig,
            "focus-focused",
            post("/api/focus", SESSION, **capability),
            "An observed terminal and an inert runner: the answer is one boolean, true. It "
            "says the command exited zero, not that a window came forward.",
        )
        recorder.capture(
            rig,
            "focus-throttled",
            post("/api/focus", SESSION, **capability),
            "A second press inside the floor is 429 and raises nothing.",
        )
        rig.focus_now += 60
        recorder.capture(
            rig,
            "focus-declined",
            post("/api/focus", {**SESSION, "sid": "00000000"}, **capability),
            "A session this run never observed a terminal for answers focused:false, the same "
            "answer as a failed raise.",
        )
        recorder.capture(
            rig,
            "focus-forbidden-capability",
            post("/api/focus", SESSION, **{"X-Compass-Capability": "stale-capability"}),
            "A capability from a previous run is 403: reload for a new page.",
        )
        recorder.capture(
            rig,
            "focus-missing-capability",
            post("/api/focus", SESSION),
            "No capability header is 403 as well.",
        )
        recorder.capture(
            rig,
            "focus-too-large",
            {**post("/api/focus", **capability), "body": None, "body_padding_bytes": 1_025},
            "A body over the 1024-byte focus cap is refused 413.",
        )
    finally:
        rig.close()


def unsupported_record_scenario(recorder: Recorder, scratch: Scratch) -> None:
    rig = Rig(
        scratch,
        "record-unsupported",
        rows={
            "claude": [synthetic_row("pi", "s1", "alpha-app", title="Synthetic unsupported record")]
        },
    )
    try:
        recorder.capture(
            rig,
            "record-unsupported",
            get("/api/session-record", "project=alpha-app&session=pi:s1"),
            "An unsupported harness is not an empty record and establishes no start.",
        )
    finally:
        rig.close()


SCENARIO_SECTIONS: tuple[Callable[[Recorder, Scratch], None], ...] = (
    data_scenarios,
    stream_scenarios,
    context_scenarios,
    unsupported_record_scenario,
    annotation_scenarios,
    action_scenarios,
    copy_and_direction_scenarios,
    reading_scenarios,
    adoption_scenarios,
    tripwire_scenarios,
    focus_scenarios,
)


@contextlib.contextmanager
def guarded() -> Iterator[None]:
    """Refuse every model launch and every subprocess for the length of a run."""

    def refuse_launch(*_args: Any, **_kwargs: Any) -> None:
        GUARD_COUNTS["model_launches"] += 1
        msg = "a fixture run tried to launch a model reading"
        raise AssertionError(msg)

    def refuse_spawn(*_args: Any, **_kwargs: Any) -> None:
        GUARD_COUNTS["subprocess_spawns"] += 1
        msg = "a fixture run tried to spawn a subprocess"
        raise AssertionError(msg)

    for key in GUARD_COUNTS:
        GUARD_COUNTS[key] = 0
    with (
        mock.patch.object(runtime_reading_jobs, "launch", refuse_launch),
        mock.patch.object(subprocess.Popen, "__init__", refuse_spawn),
        mock.patch.object(shutil, "which", lambda _name: None),
    ):
        yield


def canonical(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")


def manifest_of(scenarios: dict[str, dict[str, Any]], files: dict[str, bytes]) -> dict[str, Any]:
    rows = [
        {
            "name": name,
            "method": scenario["request"]["method"],
            "route": scenario["request"]["path"],
            "status": scenario["response"]["status"],
            "sha256": hashlib.sha256(files[f"{name}.json"]).hexdigest(),
        }
        for name, scenario in sorted(scenarios.items())
    ]
    return {
        "format": FORMAT,
        "placeholders": {
            ORIGIN: "http://127.0.0.1:<the listening port>; the port is ephemeral per run",
            CAPABILITY: "the focus capability the page was served with; a per-process secret",
        },
        "normalised": {
            "headers": "Date, Server and Connection are dropped; Content-Length is dropped "
            "from error pages",
            "error_page": "stdlib error pages are recorded by status, not by text, because "
            "their wording differs between Python releases",
            "reading_route": "the CLI lookup is pinned to a present binary, which is a machine "
            "fact; the destination is the route's own resolution against an empty environment "
            "and no settings files, which is the shipped default and names the vendor",
            "json_body": "bodies are re-serialised with sorted keys; the wire order is not kept",
        },
        "scenarios": rows,
        "unreachable": dict(sorted(UNREACHABLE.items())),
    }


def generate() -> dict[str, bytes]:
    """Every fixture file, by file name, regenerated from the live server."""
    recorder = Recorder()
    scratch = Scratch()
    try:
        with guarded():
            for section in SCENARIO_SECTIONS:
                section(recorder, scratch)
    finally:
        scratch.close()
    files = {f"{name}.json": canonical(scenario) for name, scenario in recorder.scenarios.items()}
    files["index.json"] = canonical(manifest_of(recorder.scenarios, files))
    return dict(sorted(files.items()))


def _code_point_ranges(pattern: Any) -> list[list[int]]:
    """The BMP code points a compiled pattern matches as one character, as [first, last] runs."""
    runs: list[list[int]] = []
    for point in range(0x10000):
        if not pattern.fullmatch(chr(point)):
            continue
        if runs and runs[-1][1] == point - 1:
            runs[-1][1] = point
        else:
            runs.append([point, point])
    return runs


def vocabulary() -> dict[str, Any]:
    """What the Python producers and their React twins must each spell the same way.

    Every entry is read from the Python module that owns it, so a change there moves this file and
    `--check` says so. The React side is held to it by `frontend/src/api/vocabulary.test.ts`, which
    imports the React constants where they live and compares them, so a change on either side fails
    until the other follows. These replaced the Python tests that compared the retired page's
    source text with the same constants.
    """
    reading = runtime_reading
    # The registry labels a harness; a titled alert and a popup body are composed in two layers.
    labels = ("Claude Code", "")
    wait_bodies = [
        {"project": "alpha/app", "state_detail": detail} for detail in ("", "Run the migration?")
    ]
    ask_details = [
        {"question": question, "project": project}
        for question, project in (
            ("Which branch?", "alpha/app"),
            ("Which branch?", ""),
        )
    ]
    return {
        "format": FORMAT,
        "assessmentKeys": list(reading.ASSESSMENT_KEYS),
        "criterionKeys": list(reading.CRITERION_KEYS),
        "whyTokens": [token for token in reading.WHY_TOKENS if token != reading.WHY_STANDS],
        "whyStands": reading.WHY_STANDS,
        "workEvidenceByHarness": {
            harness: sorted(types) for harness, types in reading.WORK_EVIDENCE_BY_HARNESS.items()
        },
        "checkResultWords": dict(reading.CHECK_RESULT_WORDS),
        "checkNotRecorded": reading.CHECK_NOT_RECORDED,
        "checkEarlierFailed": reading.CHECK_EARLIER_FAILED,
        "checkBeforeLastChange": reading.CHECK_BEFORE_LAST_CHANGE,
        "results": list(reading.RESULTS),
        "promptSources": list(reading.PROMPT_SOURCES),
        "promptChosen": reading.PROMPT_CHOSEN,
        "maxOutcomeLines": reading.MAX_OUTCOME_LINES,
        "turnStopHarnesses": list(reading.TURN_STOP_HARNESSES),
        "levelReasons": list(runtime_levels.REASONS),
        "annotationFields": sorted(annotation_store.published(None)),
        "unsafeChars": {
            "pattern": runtime_records._UNSAFE_CHARS.pattern,  # noqa: SLF001 - the rule is the contract
            "codePoints": _code_point_ranges(runtime_records._UNSAFE_CHARS),  # noqa: SLF001
        },
        "titles": {
            "waiting": {label: runtime_notifications.waiting_title(label) for label in labels},
            "asking": {label: runtime_notifications.asking_title(label) for label in labels},
        },
        "waitBodies": [
            {**case, "body": runtime_aggregate._wait_popup_body(case)}  # noqa: SLF001
            for case in wait_bodies
        ],
        "askDetails": [
            {**case, "detail": runtime_notifications.ask_popup_detail(**case)}
            for case in ask_details
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--check", action="store_true", help="exit 1 if a committed file is stale")
    args = parser.parse_args()
    files = generate()
    present = {path.name: path.read_bytes() for path in FIXTURES.glob("*.json")}
    words = canonical(vocabulary())
    if args.check:
        stale = sorted(
            {name for name in files if present.get(name) != files[name]}
            | (present.keys() - files.keys())
        )
        if not VOCABULARY.is_file() or VOCABULARY.read_bytes() != words:
            stale.append(str(VOCABULARY.relative_to(REPO)))
        for name in stale:
            print(f"stale: {name}", file=sys.stderr)
        return 1 if stale else 0
    VOCABULARY.write_bytes(words)
    FIXTURES.mkdir(parents=True, exist_ok=True)
    for name in present.keys() - files.keys():
        (FIXTURES / name).unlink()
    for name, body in files.items():
        (FIXTURES / name).write_bytes(body)
    print(f"wrote {len(files)} files to {FIXTURES.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
