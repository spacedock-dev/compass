#!/usr/bin/env python3
"""Trace an Intent and drift journey on a running build, and prove the trace loses nothing.

    observe_journey.py control [--out DIR] [--count N]
    observe_journey.py run --mode MODE [--out DIR] [--port P] [--home DIR] [--seconds S]
        [--transcript FILE] [--clipboard] [-- FLAGS]
    observe_journey.py report TRACE --mode MODE [--reach-host HOST]

`control` runs a synthetic workload under the observer: a known number of short program
launches, sub-second TCP connections to a local listener, name lookups and HTTP requests, one
after another and then all at once, from Python and from every Node or Bun runtime on PATH. It
counts what happened independently (each launched program appends a line to a marker file, the
listener counts what it accepted) and exits non-zero unless the trace holds exactly the expected
events and at least every accepted connection.

`run` starts a Compass server from this checkout under the observer, on a spare loopback port
with a scratch `COMPASS_HOME`, and records until Ctrl-C, `--seconds`, the server's own exit, or the
first model launch past the run's Claude call budget, which the hook refuses before it starts. It
then stops the server's process group and writes `report.json` and `report.md` (owner-readable,
with arguments and paths) and `report-shapes.md` (no argument, path or user name) beside the
trace, attributed to the tables in SECURITY.md's "What launches and what sends". `report` redoes
that for a trace already recorded.

`owned_observer.py` is the recorder. docs/design-owned-process-observer.md owns what it can and
cannot see, and how to drive each journey run. Nothing here is shipped.
"""

from __future__ import annotations

import argparse
import collections
import contextlib
import dataclasses
import hashlib
import http.server
import json
import os
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import TYPE_CHECKING, Any

import owned_observer

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Sequence

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "compass" / "skills" / "compass" / "server.py"
SECURITY = ROOT / "SECURITY.md"
OBSERVER = Path(owned_observer.__file__).resolve()

Event = dict[str, Any]
Key = tuple[str, str, str]

# --- the control run ---------------------------------------------------------------------------

# Each launched program appends its tag to the marker file, so the marker is a count of
# programs that actually ran, made without the trace.
_PY_APPEND = "import sys; open(sys.argv[1], 'a').write(sys.argv[2] + '\\n')"

# An ES module with named imports of the builtins, the form a bundled CLI uses: Node binds
# those when first imported, so this is the case the preload has to reach, not `require`.
_JS_WORKLOAD = r"""
import { execFile, spawn, spawnSync } from 'node:child_process';
import { lookup } from 'node:dns';
import { get } from 'node:http';
import { connect } from 'node:net';

const [port, marker, count] = process.argv.slice(2);
const runtime = process.versions.bun ? 'bun' : 'node';
const url = `http://127.0.0.1:${port}/`;
const append = (tag) => ['-c', `echo ${tag} >> "$0"`, marker];

const connectOnce = () =>
  new Promise((resolve, reject) => {
    const socket = connect({ host: '127.0.0.1', port: Number(port) }, () => {
      socket.end();
      resolve();
    });
    socket.on('error', reject);
  });
const getOnce = () =>
  new Promise((resolve, reject) => {
    get(url, (response) => {
      response.resume();
      response.on('end', resolve);
    }).on('error', reject);
  });
const lookupOnce = () =>
  new Promise((resolve, reject) => lookup('localhost', (e) => (e ? reject(e) : resolve())));
const execFileOnce = (tag) =>
  new Promise((resolve, reject) =>
    execFile('/bin/sh', append(tag), (error) => (error ? reject(error) : resolve())),
  );
const spawnOnce = (tag) =>
  new Promise((resolve, reject) => {
    const child = spawn('/bin/sh', append(tag));
    child.on('error', reject);
    child.on('close', resolve);
  });
const many = (make) => Promise.all(Array.from({ length: Number(count) }, make));

for (let i = 0; i < Number(count); i += 1) {
  await connectOnce();
  await getOnce();
  await (await fetch(url)).text();
  await lookupOnce();
  spawnSync('/bin/sh', append(`${runtime}-spawnSync`));
  await execFileOnce(`${runtime}-execFile`);
}
// The same calls at once: every connect and every spawn in flight together.
await many(() => connectOnce());
await many(() => spawnOnce(`${runtime}-spawn`));
"""


class _Listener(http.server.ThreadingHTTPServer):
    """A loopback HTTP server that counts every connection it accepts, request or not."""

    daemon_threads = True
    # macOS resets a connect that finds the listen queue full, and the default of 5 filled on
    # one run in eight under back-to-back raw connects.
    request_queue_size = 128

    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), _Handler)
        self.accepted = 0
        self._lock = threading.Lock()

    def verify_request(self, request: Any, client_address: Any) -> bool:  # noqa: ARG002
        with self._lock:
            self.accepted += 1
        return True


class _Handler(http.server.BaseHTTPRequestHandler):
    # HTTP/1.0 closes after each answer, so no client can carry two requests on one connection.
    protocol_version = "HTTP/1.0"

    def do_GET(self) -> None:
        body = b"ok"
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002, ARG002 - the base's names
        return


def runtimes_on_path() -> tuple[str, ...]:
    """The JavaScript runtimes the control can exercise here."""
    return tuple(name for name in ("node", "bun") if shutil.which(name))


def expected_events(count: int, runtimes: Sequence[str]) -> collections.Counter[Key]:
    """What the workload must leave in the trace, by (source, kind, operation), and nothing else."""
    n = count
    expected: collections.Counter[Key] = collections.Counter(
        {
            ("python", "start", "process"): 1,
            # Sequential and threaded Popen launches, and one per runtime child.
            ("python", "launch", "subprocess.Popen"): 2 * n + len(runtimes),
            ("python", "spawned", "subprocess.Popen"): 2 * n + len(runtimes),
            ("python", "exit", "subprocess.Popen"): 2 * n + len(runtimes),
            ("python", "launch", "os.posix_spawn"): n,
            # Raw connects, threaded ones, and the one each urlopen makes underneath.
            ("python", "connect", "socket.connect"): 3 * n,
            ("python", "resolve", "socket.getaddrinfo"): 2 * n,
            ("python", "request", "urllib.Request"): n,
            ("python", "request", "http.client.connect"): n,
        }
    )
    for runtime in runtimes:
        expected.update(
            {
                (runtime, "start", "process"): 1,
                (runtime, "exit", "process"): 1,
                (runtime, "request", "http.get"): n,
                (runtime, "request", "fetch"): n,
                (runtime, "resolve", "dns.lookup"): n,
                (runtime, "launch", "child_process.spawnSync"): n,
                (runtime, "launch", "child_process.execFile"): n,
                (runtime, "launch", "child_process.spawn"): n,
                # Node connects net, http and fetch through one socket method. Bun's fetch is
                # native and never reaches it (measured on Bun 1.4.4); its http does. The last
                # n are the concurrent connects.
                (runtime, "connect", "socket.connect"): 4 * n if runtime == "node" else 3 * n,
            }
        )
    return expected


# Bun requests that open their own connection without passing through `net.Socket`.
BUN_NATIVE = frozenset({"fetch", "WebSocket"})


def connections(events: Iterable[Event]) -> int:
    """TCP connections the trace witnessed: socket connects, plus Bun's native `fetch`."""
    total = 0
    for event in events:
        socket_level = event["kind"] == "connect" and event.get("family") == "inet"
        if socket_level or (event["src"] == "bun" and event["op"] in BUN_NATIVE):
            total += 1
    return total


def read_trace(path: Path) -> list[Event]:
    """Every event in a trace file, in the order written."""
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _workload(port: int, marker: str, count: int, js_path: str, runtimes: Sequence[str]) -> None:
    """The control's own process, run under `owned_observer.py exec`."""
    for _ in range(count):
        subprocess.run([sys.executable, "-c", _PY_APPEND, marker, "python-popen"], check=True)  # noqa: S603
    for _ in range(count):
        pid = os.posix_spawn(
            sys.executable, [sys.executable, "-c", _PY_APPEND, marker, "python-spawn"], os.environ
        )
        os.waitpid(pid, 0)
    for _ in range(count):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client:
            client.connect(("127.0.0.1", port))
    for _ in range(count):
        socket.getaddrinfo("localhost", port)
    for _ in range(count):
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=10) as response:
            response.read()

    def connect_and_launch() -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client:
            client.connect(("127.0.0.1", port))
        subprocess.run([sys.executable, "-c", _PY_APPEND, marker, "python-popen"], check=True)  # noqa: S603

    threads = [threading.Thread(target=connect_and_launch) for _ in range(count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    for runtime in runtimes:
        binary = shutil.which(runtime) or runtime
        subprocess.run([binary, js_path, str(port), marker, str(count)], check=True)  # noqa: S603


@dataclasses.dataclass
class ControlResult:
    """Expected against observed, and the independent counts behind both."""

    runtimes: tuple[str, ...]
    expected: dict[str, int]
    observed: dict[str, int]
    launches_ran: dict[str, int]
    launches_observed: dict[str, int]
    accepted: int
    connections_observed: int
    seconds: float
    trace: str

    @property
    def lost(self) -> bool:
        """True when a count disagrees, or a connection was accepted that the trace never saw.

        A connect line is an attempt, written before the call runs, so a refused or reset
        connect is still a line. The trace may therefore hold more connects than the listener
        accepted, and only fewer means an event was lost.
        """
        return (
            self.expected != self.observed
            or self.launches_ran != self.launches_observed
            or self.connections_observed < self.accepted
        )


def _key(key: Key) -> str:
    return " ".join(key)


def control_run(
    out: Path, *, count: int = 10, runtimes: Sequence[str] | None = None
) -> ControlResult:
    """Run the workload under the observer and compare the trace with what happened."""
    chosen = tuple(runtimes_on_path() if runtimes is None else runtimes)
    out.mkdir(parents=True, exist_ok=True)
    trace = out / "control-trace.jsonl"
    marker = out / "control-marker.txt"
    js_path = out / "control-workload.mjs"
    for path in (trace, marker):
        path.unlink(missing_ok=True)
    js_path.write_text(_JS_WORKLOAD)
    listener = _Listener()
    thread = threading.Thread(target=listener.serve_forever, daemon=True)
    thread.start()
    started = time.monotonic()
    try:
        env = owned_observer.observed_environment(os.environ, str(trace))
        command = [sys.executable, str(OBSERVER), "exec", "--", __file__, "_workload"]
        command += [str(listener.server_address[1]), str(marker), str(count), str(js_path), *chosen]
        subprocess.run(command, env=env, check=True, timeout=600)  # noqa: S603
        seconds = time.monotonic() - started
        events = read_trace(trace)
        witnessed = connections(events)
        # The listener accepts on its own thread; give it a moment to catch up before comparing.
        deadline = time.monotonic() + 5
        while listener.accepted < witnessed and time.monotonic() < deadline:
            time.sleep(0.05)
    finally:
        listener.shutdown()
        listener.server_close()
    observed = collections.Counter((event["src"], event["kind"], event["op"]) for event in events)
    ran = (
        collections.Counter(line for line in marker.read_text().split() if line)
        if marker.exists()
        else {}
    )
    launch_tags = {
        ("python", "subprocess.Popen"): "python-popen",
        ("python", "os.posix_spawn"): "python-spawn",
    }
    for runtime in chosen:
        launch_tags[(runtime, "child_process.spawnSync")] = f"{runtime}-spawnSync"
        launch_tags[(runtime, "child_process.execFile")] = f"{runtime}-execFile"
        launch_tags[(runtime, "child_process.spawn")] = f"{runtime}-spawn"
    launches_observed: collections.Counter[str] = collections.Counter()
    for event in events:
        tag = launch_tags.get((event["src"], event["op"]))
        if event["kind"] == "launch" and tag and event.get("program") not in chosen:
            launches_observed[tag] += 1
    return ControlResult(
        runtimes=chosen,
        expected={
            _key(key): value for key, value in sorted(expected_events(count, chosen).items())
        },
        observed={_key(key): value for key, value in sorted(observed.items())},
        launches_ran=dict(sorted(ran.items())),
        launches_observed=dict(sorted(launches_observed.items())),
        accepted=listener.accepted,
        connections_observed=witnessed,
        seconds=round(seconds, 3),
        trace=str(trace),
    )


# --- the audit table ---------------------------------------------------------------------------

_TABLE_HEADINGS = (
    "### Outbound requests and program launches",
    "### What can reach into a session",
)


def table_rows(security: Path = SECURITY) -> list[str]:
    """The first cell of every row of SECURITY.md's two launch-and-send tables."""
    rows: list[str] = []
    inside = False
    for line in security.read_text().splitlines():
        if line.startswith("### "):
            inside = line.strip() in _TABLE_HEADINGS
            continue
        if inside and line.startswith("| ") and not line.startswith(("| Path |", "|---")):
            rows.append(line.split("|")[1].strip())
    return rows


ROW_QUOTA = "Vendor quota poll, with the credential read before it"
ROW_REACH = "Reach nudge"
ROW_PRESS = "A press for a reading, an unasked check"
ROW_FIND_GOAL = "A press on Find goal"
ROW_SUMMARY = "A session summary, on open of a finished session or on a press"
ROW_MONITOR = (
    "A Live monitor check, about once a minute "
    "while you view a Claude Code session with the switch on"
)
ROW_CI = "A press for a reading that reads a pull request's CI checks"
ROW_GIT = "The git probe, and the committed-file read of a project's check scripts"
ROW_SPACEDOCK = "The Spacedock workflow discovery"
ROW_FOCUS = "The focus command"
ROW_NOTIFY = "A native notification"
ROW_TERMINAL = "The optional read-only terminal"
ROW_PS = "The process-group check around a supervised child"
ROW_DAEMON = "The daemon"
ROW_WRITE = "A write into a session, its transcript store or its working directory"
# Each row a trace event can be attributed to. A test holds every name to SECURITY.md.
ROWS_USED = (
    ROW_QUOTA, ROW_REACH, ROW_PRESS, ROW_FIND_GOAL, ROW_SUMMARY, ROW_MONITOR, ROW_CI, ROW_GIT,
    ROW_SPACEDOCK, ROW_FOCUS, ROW_NOTIFY, ROW_TERMINAL, ROW_PS, ROW_DAEMON, ROW_WRITE,
)  # fmt: skip

QUOTA_HOSTS = frozenset({"api.anthropic.com", "api2.cursor.sh"})
MODEL_PROGRAMS = owned_observer.MODEL_PROGRAMS
# Programs Compass starts for itself, by row. `security` is the keychain read before the quota
# poll; `ps` reads process groups while a supervised child is reaped. The focus command and the
# read-only terminal both run `tmux` and are told apart by its subcommand.
PROGRAM_ROWS = {
    "git": ROW_GIT,
    "gh": ROW_CI,
    "glab": ROW_CI,
    "spacedock": ROW_SPACEDOCK,
    "osascript": ROW_NOTIFY,
    "ps": ROW_PS,
    "security": ROW_QUOTA,
}
CALLER_ROWS = {
    "reading": ROW_PRESS,
    "find-goal": ROW_FIND_GOAL,
    "summary": ROW_SUMMARY,
    "monitor": ROW_MONITOR,
}
digest = owned_observer.digest


def _runtime() -> None:
    runtime = str(SERVER.parent)
    if runtime not in sys.path:
        sys.path.insert(0, runtime)


def prompts() -> dict[str, str]:
    """The system prompts of this checkout's Claude callers, by caller."""
    _runtime()
    from compass_runtime import live_monitor, observer, session_summary  # noqa: PLC0415

    return {
        "reading": observer.CLAUDE_READING_SYSTEM_PROMPT,
        "summary": session_summary.SYSTEM_PROMPT,
        "monitor": live_monitor.MONITOR_SYSTEM_PROMPT,
    }


@dataclasses.dataclass(frozen=True)
class Mode:
    """One journey run: its flags, what must not appear in it, and its Claude call budget."""

    flags: tuple[str, ...]
    model_launches: str  # "any", "monitor" (the Live monitor's checks only) or "none"
    budget: int
    summaries_off: bool
    seconds: float | None
    steps: str


# A summary is one call per 16 KiB window of the session plus a closing call
# (`session_summary.py`), and each run starts from a fresh store, so a finished session opened
# with summaries on is summarized again. Every budget below assumes the default run's session fits
# one window; the hook refuses the call past the budget, so a longer session is refused, not paid.
MODES: dict[str, Mode] = {
    "no-model": Mode(
        ("--no-observer-model",),
        "none",
        0,
        False,
        None,
        "Rehearse every step here first. Open a finished Claude Code session, press Analyze, "
        "Find goal and the Live monitor switch; all are refused.",
    ),
    "paused": Mode(
        (),
        "none",
        0,
        False,
        None,
        "Press Pause model calls before opening any session. Then open a finished Claude Code "
        "session and press Analyze, Find goal and the Live monitor switch; all are refused.",
    ),
    "default": Mode(
        (),
        "any",
        3,
        False,
        None,
        "Open a finished Claude Code session short enough for one summary window, with a pull "
        "request so gh runs (summary: 2 calls). Press Analyze once (1 call). Copy the correction.",
    ),
    "monitor-only": Mode(
        (),
        "monitor",
        3,
        True,
        150.0,
        "Summaries off. Open a session that is live now, switch on the Live monitor, keep the "
        "tab visible and press nothing else. The run ends after 150 seconds.",
    ),
    # `--allow-tool-output` is accepted and does nothing for one release (SECURITY.md, "The launch
    # grant for tool output"), so its reading call must match the default run's.
    "launch-granted": Mode(
        ("--allow-tool-output",),
        "any",
        1,
        True,
        None,
        "Summaries off. Open a finished Claude Code session and press Analyze once.",
    ),
}
# Flags that would take the server out of the runner's process group, so the runner could
# neither stop it nor see that its trace was still growing.
REFUSED_FLAGS = frozenset({"--daemon"})


def _after(argv: Sequence[str], flag: str) -> str:
    for index, arg in enumerate(argv[:-1]):
        if arg == flag:
            return str(argv[index + 1])
    prefix = f"{flag}="
    return next((str(arg)[len(prefix) :] for arg in argv if str(arg).startswith(prefix)), "")


def _caller(event: Event, digests: dict[str, str], route: str) -> str:
    """Which Claude caller made a model launch, from its own arguments and the press before it.

    The system prompt's digest names a reading, a summary or a Live monitor check. Analyze, an
    unasked check and Find goal share the reading envelope, so the POST answered last before the
    launch tells Find goal from the rest.
    """
    argv = [str(arg) for arg in event.get("argv", ())]
    found = _after(argv, "--system-prompt")
    caller = next((name for key, name in digests.items() if f"sha256:{key}" in found), "")
    if not caller:
        caller = "monitor" if "haiku" in _after(argv, "--model").lower() else "reading"
    if caller == "reading" and route == "/api/goal/find":
        return "find-goal"
    return caller


def _launch_row(
    event: Event, mode: Mode, digests: dict[str, str], route: str
) -> tuple[str | None, str | None, str]:
    """(row, departure, caller) for a Python-side launch."""
    program = str(event.get("program", ""))
    if program in MODEL_PROGRAMS:
        caller = _caller(event, digests, route)
        row = CALLER_ROWS[caller]
        if mode.model_launches == "none" or (
            mode.model_launches == "monitor" and caller != "monitor"
        ):
            return row, f"{program} ({caller}) started in a run that allows no such call", caller
        return row, None, caller
    if program == "tmux":
        argv = event.get("argv", ())
        return (ROW_TERMINAL if "attach-session" in argv else ROW_FOCUS), None, ""
    return PROGRAM_ROWS.get(program), None, ""


def _endpoint(event: Event) -> str:
    if event.get("family") == "unix":
        return "unix socket"
    return f"{event.get('host', '')}:{event.get('port', '')}"


def _attribute(  # noqa: PLR0911 - one answer per kind of line
    event: Event, tree_row: dict[int, str], reach_host: str | None
) -> tuple[str | None, str | None]:
    """(row, departure) for an event that is not a Python-side launch."""
    kind, src = event["kind"], event["src"]
    if src != "python":
        if event["pid"] not in tree_row:
            return None, None
        return ("" if kind in {"start", "exit"} else tree_row[event["pid"]]), None
    if kind == "refused":
        why = f"{event.get('program')} refused: past this run's budget of {event.get('budget')}"
        return ROW_PRESS, why
    if kind == "fork":
        return ROW_DAEMON, None
    if kind in {"connect", "request", "resolve", "send"}:
        if event.get("family") == "unix":
            return ROW_WRITE, "a Unix-domain socket connection, the path a hand-off would take"
        host = str(event.get("host", ""))
        if host in QUOTA_HOSTS:
            return ROW_QUOTA, None
        # A loopback connection, or any host but the configured reach endpoint, is left for a
        # person to read: the host alone cannot say which row it belongs to.
        return (ROW_REACH if reach_host and host == reach_host else None), None
    if kind in {"start", "spawned", "exit", "serve"}:
        return "", None
    return None, None


def _shape(event: Event) -> str:
    label = event.get("program") if event["kind"] in {"launch", "refused"} else _endpoint(event)
    return f"{event['src']} {event['kind']} {event['op']} {label}"


def report(  # noqa: C901, PLR0912, PLR0915 - one pass, one branch per kind of line
    events: Sequence[Event], mode_name: str, *, reach_host: str | None = None
) -> dict[str, Any]:
    """Launches, connections and timings of one run, attributed to the audit table's rows."""
    mode = MODES[mode_name]
    rows = set(table_rows())
    digests = {digest(text): name for name, text in prompts().items()}
    exits = {e["child"]: e for e in events if e["kind"] == "exit" and "child" in e}
    seen_inside = {e["pid"] for e in events if e["kind"] == "start" and e["src"] != "python"}
    decided: dict[int, tuple[str | None, str | None]] = {}
    callers: dict[int, str] = {}
    launches: list[dict[str, Any]] = []
    # A Popen's launch and its `spawned` line are written by one thread, in that order, so the
    # thread pairs them even when two threads start the same program at once.
    pending: dict[object, dict[str, Any]] = {}
    tree_row: dict[int, str] = {}
    route = ""
    for index, event in enumerate(events):
        if event["kind"] == "serve":
            route = str(event.get("route", ""))
        elif event["kind"] == "launch" and event["src"] == "python":
            row, departure, caller = _launch_row(event, mode, digests, route)
            decided[index] = (row, departure)
            callers[index] = caller
            launch = {"t": event["t"], "src": "python", "program": event.get("program")}
            launch |= {"caller": caller, "row": row, "argv": event.get("argv", [])}
            launches.append(launch)
            if event["op"] == "subprocess.Popen":
                pending[(event["pid"], event.get("tid"))] = launch
        elif event["kind"] == "launch":
            launches.append({"t": event["t"], "src": event["src"], "program": event.get("program")})
        elif event["kind"] == "spawned":
            paired = pending.pop((event["pid"], event.get("tid")), None)
            if paired is not None:
                child, end = event["child"], exits.get(event["child"])
                paired["child"] = child
                paired["seconds"] = round(end["t"] - event["t"], 3) if end else None
                paired["seen_inside"] = child in seen_inside
                if paired["program"] in MODEL_PROGRAMS and paired["row"]:
                    tree_row[child] = paired["row"]
        elif event["kind"] == "start" and event["ppid"] in tree_row:
            tree_row[event["pid"]] = tree_row[event["ppid"]]
    by_row: dict[str, collections.Counter[str]] = collections.defaultdict(collections.Counter)
    departures: list[dict[str, Any]] = []
    unlisted: list[Event] = []
    for index, event in enumerate(events):
        if index in decided:
            row, departure = decided[index]
        elif event["kind"] == "launch":
            row, departure = (tree_row.get(event["pid"]), None)
        else:
            row, departure = _attribute(event, tree_row, reach_host)
        if departure:
            departures.append({"row": row, "why": departure, "event": event})
        if row == "":
            continue
        if row is None or row not in rows:
            unlisted.append(event)
            continue
        label = event.get("program") if event["kind"] == "launch" else _endpoint(event)
        if callers.get(index):
            label = f"{label} ({callers[index]})"
        by_row[row][f"{event['src']} {event['kind']} {label}"] += 1
    connections_seen = collections.Counter(
        f"{e['src']} {_endpoint(e)}" for e in events if e["kind"] in {"connect", "request"}
    )
    model_launches = [
        x for x in launches if x["src"] == "python" and x["program"] in MODEL_PROGRAMS
    ]
    return {
        "mode": mode_name,
        "flags": list(mode.flags),
        "budget": mode.budget,
        "model_launches": len(model_launches),
        "events": len(events),
        "seconds": round(events[-1]["t"] - events[0]["t"], 3) if events else 0,
        "launches": launches,
        "opaque_launches": sorted(
            {
                str(launch["program"])
                for launch in launches
                if launch.get("child") and not launch.get("seen_inside")
            }
        ),
        "connections": dict(sorted(connections_seen.items())),
        "by_row": {row: dict(sorted(counter.items())) for row, counter in sorted(by_row.items())},
        "rows_without_events": sorted(rows - set(by_row)),
        "departures": departures,
        "unlisted": unlisted,
        "unlisted_shapes": dict(sorted(collections.Counter(map(_shape, unlisted)).items())),
    }


def _after_the_run(result: dict[str, Any], *, paths: bool) -> list[str]:
    if "transcripts" not in result:
        return []
    lines = ["", "## After the run", ""]
    for item in result["transcripts"]:
        name = f"`{item['path']}`" if paths else "A session transcript"
        lines.append(
            f"- {name}: earlier bytes preserved {item['prefix_preserved']}, "
            f"{item['appended_lines']} lines appended"
        )
    alive = result.get("alive_after_stop", [])
    lines.append(f"- Children still running after the stop: {len(alive) if not paths else alive}")
    if "clipboard_changed" in result:
        changed = result["clipboard_changed"]
        size = f", {result['clipboard_bytes']} bytes" if changed else ""
        lines.append(f"- Clipboard changed during the run: {changed}{size}")
    return lines


def render(result: dict[str, Any]) -> str:
    """The full report as Markdown, for the operator: it carries arguments and paths."""
    lines = [f"# Journey trace: {result['mode']}", ""]
    lines.append(f"Flags: `{' '.join(result['flags']) or '(none)'}`. Events: {result['events']}.")
    lines.append(f"Model launches: {result['model_launches']} of a budget of {result['budget']}.")
    lines.append(f"Span: {result['seconds']} s. Departures: {len(result['departures'])}.")
    lines.append(f"Unlisted: {len(result['unlisted'])}.")
    lines += ["", "## Launches", ""]
    lines += [
        "| t | from | program | caller | seconds | seen inside |",
        "|---|---|---|---|---|---|",
    ]
    lines += [
        f"| {launch['t']:.3f} | {launch['src']} | {launch['program']} | "
        f"{launch.get('caller', '')} | {launch.get('seconds', '')} | "
        f"{launch.get('seen_inside', '')} |"
        for launch in result["launches"]
    ]
    lines += ["", "## Connections and requests", "", "| from and endpoint | count |", "|---|---|"]
    lines += [f"| {name} | {count} |" for name, count in result["connections"].items()]
    lines += ["", "## By table row", ""]
    for row, counter in result["by_row"].items():
        lines.append(
            f"- {row}: " + ", ".join(f"{name} x{count}" for name, count in counter.items())
        )
    lines += ["", "## Departures", ""]
    lines += [f"- {item['row']}: {item['why']}" for item in result["departures"]] or ["None."]
    lines += ["", "## Not in the table", ""]
    lines += [f"- `{json.dumps(event)}`" for event in result["unlisted"]] or ["None."]
    return "\n".join([*lines, *_after_the_run(result, paths=True)]) + "\n"


def render_shapes(result: dict[str, Any]) -> str:
    """The report as shapes only, for an issue or SECURITY.md: no argument, path or user name."""
    lines = [f"# Journey trace shapes: {result['mode']}", ""]
    lines.append(f"Flags: `{' '.join(result['flags']) or '(none)'}`. Events: {result['events']}.")
    lines.append(f"Model launches: {result['model_launches']} of a budget of {result['budget']}.")
    lines.append(f"Departures: {len(result['departures'])}. Unlisted: {len(result['unlisted'])}.")
    lines += ["", "## By table row", ""]
    for row, counter in result["by_row"].items():
        lines.append(
            f"- {row}: " + ", ".join(f"{name} x{count}" for name, count in counter.items())
        )
    lines += ["", "## Seen only from outside", ""]
    lines.append(", ".join(result["opaque_launches"]) or "None.")
    lines += ["", "## Departures", ""]
    lines += [f"- {item['row']}: {item['why']}" for item in result["departures"]] or ["None."]
    lines += ["", "## Not in the table", ""]
    lines += [f"- {shape} x{count}" for shape, count in result["unlisted_shapes"].items()] or [
        "None."
    ]
    return "\n".join([*lines, *_after_the_run(result, paths=False)]) + "\n"


# --- the journey run ---------------------------------------------------------------------------


def spare_port() -> int:
    """A loopback port nothing holds right now."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def journey_command(port: int, mode: str, extra: Sequence[str]) -> list[str]:
    """The observed server's argv: the observer's `exec`, then server.py and the run's flags."""
    refused = sorted({arg.split("=", 1)[0] for arg in extra} & REFUSED_FLAGS)
    if refused:
        message = f"refused: {', '.join(refused)} would take the server out of the run's reach"
        raise ValueError(message)
    flags = [*MODES[mode].flags, *extra]
    return [sys.executable, str(OBSERVER), "exec", "--", str(SERVER), "--port", str(port), *flags]


def journey_environment(
    trace: Path, compass_home: Path, home: str | None, *, budget: int | None = None
) -> dict[str, str]:
    """The observed server's environment: the trace on, a scratch store, the chosen HOME."""
    env = owned_observer.observed_environment(os.environ, str(trace))
    env["COMPASS_HOME"] = str(compass_home)
    if budget is not None:
        env[owned_observer.ENV_BUDGET] = str(budget)
    if home:
        env["HOME"] = home
    return env


def _summary_config(compass_home: Path, home: str | None) -> tuple[Any, Any]:
    _runtime()
    from compass_runtime import config as runtime_config  # noqa: PLC0415
    from compass_runtime import reading_policy  # noqa: PLC0415

    environ = dict(os.environ)
    environ |= {"COMPASS_HOME": str(compass_home), "HOME": home or os.path.expanduser("~")}
    config = runtime_config.build_runtime_config(
        environ=environ, platform_name=sys.platform, os_name=os.name, launcher_path=SERVER
    )
    return config, reading_policy


def summaries_off(compass_home: Path, home: str | None) -> bool:
    """Whether the store at `compass_home` holds Turn off summaries."""
    config, policy = _summary_config(compass_home, home)
    return bool(policy.summary_status(config, now=time.time()).get("off"))


def seed_summaries_off(compass_home: Path, home: str | None) -> bool:
    """Store Turn off summaries in a run's fresh store before its server starts; read it back."""
    compass_home.mkdir(parents=True, exist_ok=True)
    config, policy = _summary_config(compass_home, home)
    policy.set_summary_consent(config, False, now=time.time())
    return summaries_off(compass_home, home)


def clipboard_begin(copy: Callable[[str], object]) -> str:
    """Put a sentinel on the clipboard, so what was there before the run is never read back."""
    sentinel = f"compass-observer-{secrets.token_hex(8)}"
    copy(sentinel)
    return sentinel


def clipboard_end(paste: Callable[[], str], sentinel: str, out: Path) -> dict[str, Any]:
    """Keep the clipboard, owner-readable only, when the run changed it; nothing otherwise."""
    text = paste()
    if text == sentinel:
        return {"clipboard_changed": False}
    _write_private(out / "clipboard.txt", text)
    return {"clipboard_changed": True, "clipboard_bytes": len(text.encode())}


def _pbcopy(text: str) -> None:
    subprocess.run(["/usr/bin/pbcopy"], input=text, text=True, check=True)


def _pbpaste() -> str:
    result = subprocess.run(["/usr/bin/pbpaste"], capture_output=True, text=True, check=True)
    return result.stdout


def snapshot(path: Path) -> bytes:
    """A transcript's bytes before the run, held in memory and never written out."""
    return path.read_bytes() if path.exists() else b""


def transcript_change(path: Path, before: bytes) -> dict[str, Any]:
    """Whether the run left a transcript's earlier bytes as they were, without its words.

    A harness appends to its transcript, so a session that kept working during the run grows.
    A write by Compass would show as earlier bytes changed. Only sizes, digests and a line count
    are recorded, so the result can be attached without the session's content.
    """
    after = snapshot(path)
    return {
        "path": str(path),
        "before": {"bytes": len(before), "sha256": hashlib.sha256(before).hexdigest()},
        "after": {"bytes": len(after), "sha256": hashlib.sha256(after).hexdigest()},
        "prefix_preserved": after.startswith(before),
        "appended_lines": after[len(before) :].count(b"\n") if after.startswith(before) else None,
    }


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _reach_host(flags: Sequence[str]) -> str | None:
    url = _after(flags, "--reach-url") or os.environ.get("COMPASS_REACH_URL", "")
    return urllib.parse.urlsplit(url).hostname if url else None


def _refused(trace: Path, offset: int) -> tuple[bool, int]:
    """Whether a `refused` line was written after `offset`, and the new offset."""
    if not trace.exists():
        return False, offset
    with trace.open("rb") as handle:
        handle.seek(offset)
        chunk = handle.read()
    complete = chunk[: chunk.rfind(b"\n") + 1]
    return b'"kind": "refused"' in complete, offset + len(complete)


def _wait(process: subprocess.Popen[bytes], trace: Path, seconds: float | None) -> str:
    """Wait for the server's exit, the deadline, Ctrl-C, or the first refused model launch."""
    deadline = None if seconds is None else time.monotonic() + seconds
    offset = 0
    try:
        while process.poll() is None:
            refused, offset = _refused(trace, offset)
            if refused:
                return "budget"
            if deadline is not None and time.monotonic() >= deadline:
                return "deadline"
            time.sleep(0.5)
    except KeyboardInterrupt:
        return "interrupted"
    return "exited"


def _stop(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    with contextlib.suppress(ProcessLookupError):
        os.killpg(process.pid, signal.SIGTERM)
    try:
        process.wait(timeout=15)
    except subprocess.TimeoutExpired:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
        process.wait()


def run_journey(args: argparse.Namespace) -> int:
    """Start the observed server, wait, stop it, and write the report."""
    mode = MODES[args.mode]
    out = Path(args.out or tempfile.mkdtemp(prefix=f"journey-{args.mode}-")).resolve()
    out.mkdir(parents=True, exist_ok=True)
    trace = out / "trace.jsonl"
    trace.unlink(missing_ok=True)
    port = args.port or spare_port()
    command = journey_command(port, args.mode, args.flags)
    compass_home = out / "compass-home"
    if mode.summaries_off and not seed_summaries_off(compass_home, args.home):
        print("refused: Turn off summaries could not be stored before the run", file=sys.stderr)
        return 2
    env = journey_environment(trace, compass_home, args.home, budget=mode.budget)
    transcripts = {
        Path(path).expanduser(): snapshot(Path(path).expanduser()) for path in args.transcript
    }
    sentinel = clipboard_begin(_pbcopy) if args.clipboard else ""
    print(f"mode {args.mode}: {mode.steps}")
    print(f"Claude call budget: {mode.budget}. Summaries off: {mode.summaries_off}.")
    print(f"open http://127.0.0.1:{port}/ ; trace {trace}", flush=True)
    process = subprocess.Popen(command, env=env, start_new_session=True)  # noqa: S603
    try:
        ended = _wait(process, trace, args.seconds or mode.seconds)
    finally:
        _stop(process)
    if ended == "budget":
        print("stopped: a model launch past the budget was refused")
    names = [flag.split("=", 1)[0] for flag in [*mode.flags, *args.flags] if flag.startswith("-")]
    extra: dict[str, Any] = {
        "flags": names,
        "ended": ended,
        "transcripts": [transcript_change(path, before) for path, before in transcripts.items()],
        # Children Compass started in their own session outlive the group signal. Listed, not
        # killed: a pid read from the trace may already belong to another program.
        "alive_after_stop": sorted(
            event["child"]
            for event in read_trace(trace)
            if event["kind"] == "spawned" and _alive(event["child"])
        ),
    }
    if args.clipboard:
        extra |= clipboard_end(_pbpaste, sentinel, out)
    return write_report(trace, args.mode, extra, reach_host=_reach_host(args.flags))


def _write_private(path: Path, text: str) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as handle:
        handle.write(text)


def write_report(
    trace: Path, mode: str, extra: dict[str, Any] | None = None, *, reach_host: str | None = None
) -> int:
    """Write the full report and its shapes beside the trace. Non-zero when the run departed."""
    result = report(read_trace(trace), mode, reach_host=reach_host) | (extra or {})
    # The full report carries arguments and paths, so it is owner-readable like the trace.
    _write_private(trace.parent / "report.json", json.dumps(result, indent=2, default=str) + "\n")
    _write_private(trace.parent / "report.md", render(result))
    (trace.parent / "report-shapes.md").write_text(render_shapes(result))
    print(render_shapes(result))
    return 1 if result["departures"] else 0


def main(argv: Sequence[str] | None = None) -> int:
    """Command-line entry point."""
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments[:1] == ["_workload"]:
        port, marker, count, js_path, *runtimes = arguments[1:]
        _workload(int(port), marker, int(count), js_path, runtimes)
        return 0
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0] if __doc__ else None)
    commands = parser.add_subparsers(dest="command", required=True)
    control = commands.add_parser("control", help="prove the observer loses no events")
    control.add_argument("--out", type=Path, default=None)
    control.add_argument("--count", type=int, default=20)
    run = commands.add_parser("run", help="trace one journey run on a running build")
    run.add_argument("--mode", choices=sorted(MODES), required=True)
    run.add_argument("--out", default=None)
    run.add_argument("--port", type=int, default=0)
    run.add_argument("--home", default=None, help="HOME for the server (default: yours)")
    run.add_argument("--seconds", type=float, default=None)
    run.add_argument("--transcript", action="append", default=[], help="a session file to check")
    run.add_argument(
        "--clipboard", action="store_true", help="save what the run copied, if anything"
    )
    run.add_argument("flags", nargs="*", help="extra server flags, after --")
    again = commands.add_parser("report", help="report a recorded trace")
    again.add_argument("trace", type=Path)
    again.add_argument("--mode", choices=sorted(MODES), required=True)
    again.add_argument("--reach-host", default=None)
    args = parser.parse_args(arguments)
    if args.command == "control":
        out = args.out or Path(tempfile.mkdtemp(prefix="observer-control-"))
        result = control_run(out, count=args.count)
        print(json.dumps(dataclasses.asdict(result), indent=2))
        (out / "control.json").write_text(json.dumps(dataclasses.asdict(result), indent=2) + "\n")
        print("LOST EVENTS" if result.lost else "no event lost")
        return 1 if result.lost else 0
    if args.command == "run":
        try:
            journey_command(0, args.mode, args.flags)
        except ValueError as refusal:
            parser.error(str(refusal))
        return run_journey(args)
    return write_report(args.trace, args.mode, reach_host=args.reach_host)


if __name__ == "__main__":
    sys.exit(main())
