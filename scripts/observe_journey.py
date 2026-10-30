#!/usr/bin/env python3
"""Trace an Intent and drift journey on a running build, and prove the trace loses nothing.

    observe_journey.py control [--out DIR] [--count N]
    observe_journey.py run --mode MODE [--out DIR] [--port P] [--home DIR] [--seconds S] [-- FLAGS]
    observe_journey.py report TRACE --mode MODE

`control` runs a synthetic workload under the observer: a known number of short program
launches, sub-second TCP connections to a local listener, name lookups and HTTP requests, from
Python and from every Node or Bun runtime on PATH. It counts what happened independently (each
launched program appends a line to a marker file, the listener counts what it accepted) and
exits non-zero unless the trace holds exactly the expected events.

`run` starts a Compass server from this checkout under the observer, on a spare loopback port
with a scratch `COMPASS_HOME`, and records until Ctrl-C, `--seconds` or the server's own exit.
It then stops the server's process group, writes `report.json` and `report.md` beside the trace,
and diffs the trace against the tables in SECURITY.md's "What launches and what sends". `report`
redoes that for a trace already recorded.

`owned_observer.py` is the recorder. docs/design-owned-process-observer.md owns what it can and
cannot see, and how to drive each of the five journey runs. Nothing here is shipped.
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
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path
from typing import TYPE_CHECKING, Any

import owned_observer

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

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
import { execFile, spawnSync } from 'node:child_process';
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

for (let i = 0; i < Number(count); i += 1) {
  await connectOnce();
  await getOnce();
  await (await fetch(url)).text();
  await lookupOnce();
  spawnSync('/bin/sh', append(`${runtime}-spawnSync`));
  await execFileOnce(`${runtime}-execFile`);
}
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
            ("python", "launch", "subprocess.Popen"): n + len(runtimes),
            ("python", "spawned", "subprocess.Popen"): n + len(runtimes),
            ("python", "exit", "subprocess.Popen"): n + len(runtimes),
            ("python", "launch", "os.posix_spawn"): n,
            # One raw connect each, and the one each urlopen makes underneath.
            ("python", "connect", "socket.connect"): 2 * n,
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
                # Node connects net, http and fetch through one socket method. Bun's fetch is
                # native and never reaches it (measured on Bun 1.4.4); its http does.
                (runtime, "connect", "socket.connect"): 3 * n if runtime == "node" else 2 * n,
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
        """True when any count disagrees."""
        return (
            self.expected != self.observed
            or self.launches_ran != self.launches_observed
            or self.accepted != self.connections_observed
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
ROW_PRESS = "A press for a reading, an unasked check"
ROW_MONITOR = (
    "A Live monitor check, about once a minute "
    "while you view a Claude Code session with the switch on"
)
ROW_CI = "A press for a reading that reads a pull request's CI checks"
ROW_GIT = "The git probe, and the committed-file read of a project's check scripts"
ROW_SPACEDOCK = "The Spacedock workflow discovery"
ROW_NOTIFY = "A native notification"
ROW_TERMINAL = "The optional read-only terminal"
ROW_DAEMON = "The daemon"
ROW_WRITE = "A write into a session, its transcript store or its working directory"
# Each row a trace event can be attributed to. A test holds every name to SECURITY.md.
ROWS_USED = (
    ROW_QUOTA, ROW_PRESS, ROW_MONITOR, ROW_CI, ROW_GIT,
    ROW_SPACEDOCK, ROW_NOTIFY, ROW_TERMINAL, ROW_DAEMON, ROW_WRITE,
)  # fmt: skip

QUOTA_HOSTS = frozenset({"api.anthropic.com", "api2.cursor.sh"})
MODEL_PROGRAMS = frozenset({"claude", "codex"})


@dataclasses.dataclass(frozen=True)
class Mode:
    """One of the issue's five runs: the flags it starts with and what must not appear in it."""

    flags: tuple[str, ...]
    model_launches: str  # "any", "monitor" (Haiku only) or "none"
    steps: str


# Opening a finished session starts its summary with no prior question (SECURITY.md, opening
# section), so every run that must start no model opens a session only after the refusal holds.
MODES: dict[str, Mode] = {
    "default": Mode(
        (),
        "any",
        "Open a finished Claude Code session (its summary runs), press Analyze once, "
        "copy the correction.",
    ),
    "monitor-only": Mode(
        (),
        "monitor",
        "Open a live Claude Code session (a live one gets no summary), switch on the Live "
        "monitor, keep the tab visible about three minutes, press nothing else.",
    ),
    "no-model": Mode(
        ("--no-observer-model",),
        "none",
        "Open a finished Claude Code session and press Analyze; the summary and the press "
        "are both refused.",
    ),
    "declined": Mode(
        (),
        "none",
        "Before opening any session press Pause model calls, then open a finished Claude "
        "Code session and press Analyze; both are refused.",
    ),
    # `--allow-tool-output` is accepted and does nothing for one release (SECURITY.md, "The launch
    # grant for tool output"), so this run must match the default one.
    "launch-granted": Mode(
        ("--allow-tool-output",), "any", "As the default run, started with the launch grant."
    ),
}


def _is_monitor(event: Event) -> bool:
    return any("haiku" in str(arg).lower() for arg in event.get("argv", ()))


def _descendants(events: Sequence[Event], roots: set[int]) -> set[int]:
    """Pids started under `roots`, as far as the preloads' start events can see."""
    found = set(roots)
    changed = True
    while changed:
        changed = False
        for event in events:
            if event["kind"] == "start" and event["ppid"] in found and event["pid"] not in found:
                found.add(event["pid"])
                changed = True
    return found


def _endpoint(event: Event) -> str:
    if event.get("family") == "unix":
        return f"unix:{event.get('path', '')}"
    return f"{event.get('host', '')}:{event.get('port', '')}"


def _attribute(event: Event, mode: Mode, model_tree: set[int]) -> tuple[str | None, str | None]:  # noqa: C901, PLR0911 - one answer per row
    """(row, departure) for one event: which table row covers it, and what the mode forbids."""
    kind, src = event["kind"], event["src"]
    if src != "python":
        if event["pid"] not in model_tree:
            return None, None
        if kind in {"start", "exit"}:
            return "", None
        return (ROW_MONITOR if mode.model_launches == "monitor" else ROW_PRESS), None
    if kind == "launch":
        program = event.get("program", "")
        if program in MODEL_PROGRAMS:
            monitor = _is_monitor(event)
            row = ROW_MONITOR if monitor else ROW_PRESS
            if mode.model_launches == "none" or (mode.model_launches == "monitor" and not monitor):
                return (
                    row,
                    f"{program} started in a run that allows {mode.model_launches} model launches",
                )
            return row, None
        rows = {"git": ROW_GIT, "gh": ROW_CI, "glab": ROW_CI, "spacedock": ROW_SPACEDOCK}
        rows |= {"osascript": ROW_NOTIFY, "tmux": ROW_TERMINAL}
        return rows.get(program), None
    if kind == "fork":
        return ROW_DAEMON, None
    if kind in {"connect", "request", "resolve", "send"}:
        if event.get("family") == "unix":
            return ROW_WRITE, "a Unix-domain socket connection, the path a hand-off would take"
        host = str(event.get("host", ""))
        # Anything else, loopback and a configured reach endpoint included, is left for a person
        # to read: the host alone cannot say which row a connection belongs to.
        return (ROW_QUOTA if host in QUOTA_HOSTS else None), None
    if kind in {"start", "spawned", "exit"}:
        return "", None
    return None, None


def report(events: Sequence[Event], mode_name: str) -> dict[str, Any]:
    """Launches, connections and timings of one run, attributed to the audit table's rows."""
    mode = MODES[mode_name]
    server = next((e["pid"] for e in events if e["src"] == "python" and e["kind"] == "start"), None)
    spawned = {e["child"]: e for e in events if e["kind"] == "spawned"}
    exits = {e["child"]: e for e in events if e["kind"] == "exit" and "child" in e}
    seen_inside = {e["pid"] for e in events if e["kind"] == "start" and e["src"] != "python"}
    model_pids = {pid for pid, e in spawned.items() if e.get("program") in MODEL_PROGRAMS}
    model_tree = _descendants(events, model_pids)
    rows = set(table_rows())
    by_row: dict[str, collections.Counter[str]] = collections.defaultdict(collections.Counter)
    departures: list[dict[str, Any]] = []
    unlisted: list[Event] = []
    launches: list[dict[str, Any]] = []
    # A Popen's launch and its `spawned` line are written by one thread, in that order, so the
    # thread pairs them even when two threads start the same program at once.
    pending: dict[object, dict[str, Any]] = {}
    for event in events:
        row, departure = _attribute(event, mode, model_tree)
        if event["kind"] == "launch":
            launch = {
                "t": event["t"],
                "src": event["src"],
                "pid": event["pid"],
                "program": event.get("program"),
            }
            launch["argv"] = event.get("argv", [])
            launches.append(launch)
            if event["op"] == "subprocess.Popen":
                pending[(event["pid"], event.get("tid"))] = launch
        elif event["kind"] == "spawned":
            paired = pending.pop((event["pid"], event.get("tid")), None)
            if paired is not None:
                child, end = event["child"], exits.get(event["child"])
                paired["child"] = child
                paired["seconds"] = round(end["t"] - event["t"], 3) if end else None
                paired["seen_inside"] = child in seen_inside
        if departure:
            departures.append({"row": row, "why": departure, "event": event})
        if row == "":
            continue
        if row is None or row not in rows:
            unlisted.append(event)
            continue
        label = event.get("program") if event["kind"] == "launch" else _endpoint(event)
        by_row[row][f"{event['src']} {event['kind']} {label}"] += 1
    connections_seen = collections.Counter(
        f"{e['src']} {_endpoint(e)}" for e in events if e["kind"] in {"connect", "request"}
    )
    return {
        "mode": mode_name,
        "flags": list(mode.flags),
        "server_pid": server,
        "events": len(events),
        "seconds": round(events[-1]["t"] - events[0]["t"], 3) if events else 0,
        "launches": launches,
        "opaque_launches": sorted(
            {
                launch["program"]
                for launch in launches
                if launch.get("child") and not launch.get("seen_inside")
            }
        ),
        "connections": dict(sorted(connections_seen.items())),
        "by_row": {row: dict(sorted(counter.items())) for row, counter in sorted(by_row.items())},
        "rows_without_events": sorted(rows - set(by_row)),
        "departures": departures,
        "unlisted": unlisted,
        "model_tree": sorted(model_tree),
    }


def render(result: dict[str, Any]) -> str:
    """The report as Markdown, for attaching beside the trace."""
    lines = [f"# Journey trace: {result['mode']}", ""]
    lines.append(f"Flags: `{' '.join(result['flags']) or '(none)'}`. Events: {result['events']}.")
    lines.append(f"Span: {result['seconds']} s. Departures: {len(result['departures'])}.")
    lines.append(f"Unlisted: {len(result['unlisted'])}.")
    lines += [
        "",
        "## Launches",
        "",
        "| t | from | program | seconds | seen inside |",
        "|---|---|---|---|---|",
    ]
    lines += [
        f"| {launch['t']:.3f} | {launch['src']} | {launch['program']} | "
        f"{launch.get('seconds', '')} | {launch.get('seen_inside', '')} |"
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
    if "transcripts" in result:
        lines += ["", "## After the run", ""]
        lines += [
            f"- `{item['path']}`: earlier bytes preserved {item['prefix_preserved']}, "
            f"{item['appended_lines']} lines appended"
            for item in result["transcripts"]
        ]
        lines.append(
            f"- Children still running after the stop: {result['alive_after_stop'] or 'none'}"
        )
        if "clipboard_bytes" in result:
            lines.append(
                f"- Clipboard read back: {result['clipboard_bytes']} bytes, in clipboard.txt"
            )
    return "\n".join(lines) + "\n"


# --- the journey run ---------------------------------------------------------------------------


def spare_port() -> int:
    """A loopback port nothing holds right now."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def journey_command(port: int, mode: str, extra: Sequence[str]) -> list[str]:
    """The observed server's argv: the observer's `exec`, then server.py and the run's flags."""
    flags = [*MODES[mode].flags, *extra]
    return [sys.executable, str(OBSERVER), "exec", "--", str(SERVER), "--port", str(port), *flags]


def journey_environment(trace: Path, compass_home: Path, home: str | None) -> dict[str, str]:
    """The observed server's environment: the trace on, a scratch store, the chosen HOME."""
    env = owned_observer.observed_environment(os.environ, str(trace))
    env["COMPASS_HOME"] = str(compass_home)
    if home:
        env["HOME"] = home
    return env


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


def run_journey(args: argparse.Namespace) -> int:
    """Start the observed server, wait, stop it, and write the report."""
    out = Path(args.out or tempfile.mkdtemp(prefix=f"journey-{args.mode}-")).resolve()
    out.mkdir(parents=True, exist_ok=True)
    trace = out / "trace.jsonl"
    trace.unlink(missing_ok=True)
    port = args.port or spare_port()
    command = journey_command(port, args.mode, args.flags)
    env = journey_environment(trace, out / "compass-home", args.home)
    transcripts = {
        Path(path).expanduser(): snapshot(Path(path).expanduser()) for path in args.transcript
    }
    print(f"mode {args.mode}: {MODES[args.mode].steps}")
    print(f"open http://127.0.0.1:{port}/ ; trace {trace}", flush=True)
    process = subprocess.Popen(command, env=env, start_new_session=True)  # noqa: S603
    try:
        process.wait(timeout=args.seconds)
    except subprocess.TimeoutExpired:
        pass
    except KeyboardInterrupt:
        print("stopping")
    finally:
        if process.poll() is None:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(process.pid, signal.SIGKILL)
                process.wait()
    extra: dict[str, Any] = {
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
        pbpaste = shutil.which("pbpaste")
        text = ""
        if pbpaste:
            text = subprocess.run([pbpaste], capture_output=True, text=True, check=False).stdout  # noqa: S603
        (out / "clipboard.txt").write_text(text)
        extra["clipboard_bytes"] = len(text.encode())
    return write_report(trace, args.mode, extra)


def write_report(trace: Path, mode: str, extra: dict[str, Any] | None = None) -> int:
    """Write report.json and report.md beside the trace. Non-zero when the run departed."""
    result = report(read_trace(trace), mode) | (extra or {})
    (trace.parent / "report.json").write_text(json.dumps(result, indent=2, default=str) + "\n")
    (trace.parent / "report.md").write_text(render(result))
    print(render(result))
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
    run.add_argument("--clipboard", action="store_true", help="save the clipboard after the run")
    run.add_argument("flags", nargs="*", help="extra server flags, after --")
    again = commands.add_parser("report", help="report a recorded trace")
    again.add_argument("trace", type=Path)
    again.add_argument("--mode", choices=sorted(MODES), required=True)
    args = parser.parse_args(arguments)
    if args.command == "control":
        out = args.out or Path(tempfile.mkdtemp(prefix="observer-control-"))
        result = control_run(out, count=args.count)
        print(json.dumps(dataclasses.asdict(result), indent=2))
        (out / "control.json").write_text(json.dumps(dataclasses.asdict(result), indent=2) + "\n")
        print("LOST EVENTS" if result.lost else "no event lost")
        return 1 if result.lost else 0
    if args.command == "run":
        return run_journey(args)
    return write_report(args.trace, args.mode)


if __name__ == "__main__":
    sys.exit(main())
