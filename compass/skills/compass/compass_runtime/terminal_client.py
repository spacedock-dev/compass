"""The terminal's one client for the dashboard's loopback API.

Standard library only, with terminal leaves and a lazily loaded monitor holder: `entry.main` runs
this before `cli` is imported, so a short command never pays for the collectors. The reasoning,
and what was rejected, is in
[R-1](docs/design-runtime-architecture.md#r-1-one-responsibility-per-file-and-the-launcher-owns-none).

It holds the request path, discovery, the session rule, the version guard and the wording, for
the operations that call them. `--monitor` holds a lease through `terminal_monitor`; `--drift`
spends on a reading whose rules live in the leaf
`terminal_drift`, which this file hands the four exchanges it needs and imports only on that path,
so no other operation loads it.

`--footer` is the one operation that never reaches the dashboard. It runs on every status line
refresh, so it reads what the dashboard already wrote and the JSON the status line
hands it, and `http.client` is imported only by the functions that do reach the dashboard, which
keeps it out of this command's import set.
"""

from __future__ import annotations

import json
import math
import os
import re
import stat
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, NamedTuple

from compass_runtime import terminal_sessions

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping
    from typing import TextIO

BUNDLED_VERSION_PATH = Path(__file__).with_name("release-version.txt")
PLUGIN_MANIFEST_PATH = Path(__file__).resolve().parents[3] / ".claude-plugin" / "plugin.json"

DEFAULT_PORT = 4553
# The state files are searched newest first and the default port is always among them, so a stale
# file left by a crash costs one refused connection each. Eight is more dashboards than one
# person runs.
MAX_CANDIDATES: Final = 8
HEALTH_TIMEOUT_SEC: Final = 0.3
REQUEST_TIMEOUT_SEC: Final = 5.0
# On 2026-11-07, a cold list of 3,700+ sessions took 4.8 s and the first client read
# hit the five-second limit. Allow collection time while keeping a whole-exchange bound.
LIST_REQUEST_TIMEOUT_SEC: Final = 30.0
HEALTH_CAP_BYTES: Final = 4096
REPLY_CAP_BYTES: Final = 1_048_576
# The board's own read. `/api/data` measured 1,096,870 bytes on a real board on 2026-11-03, so the
# 1 MiB reply cap above refuses an ordinary board. Keep a larger safety bound for board reads
# and the projected session list; even projected rows can exceed a constant cap.
DATA_CAP_BYTES: Final = 16_777_216
# `--drift`'s exchanges. A press collects the board and verifies an adoption before it answers, and
# so does the focused context, so five seconds can expire on a busy board; an expired press reads as
# a lost answer, which is never retried, so this errs long.
DRIFT_REQUEST_TIMEOUT_SEC: Final = 30.0
STDIN_CAP_CHARS: Final = 65_536
# A status line command is run on every refresh with its JSON written at once, so a quarter of a
# second is generous for a producer that is alive and short enough that a pipe held open cannot
# hold the bar.
STDIN_DEADLINE_SEC: Final = 0.25
# Four times the dashboard's 15 s refresh of its line files: one missed refresh and the
# collection that follows it still leave the file fresh. A constant here rather than a
# `config.py` value because this module imports nothing from the runtime.
LINE_STALE_SEC: Final = 60.0
LINE_CAP_BYTES: Final = 8192
# A file dated further ahead than this is a clock that moved or a file nobody wrote.
LINE_FUTURE_SLACK_SEC: Final = 5.0
LABEL_CAP_CHARS: Final = 40
SHAPE_VERSION: Final = 1
FOOTER_DIRECTORY: Final = "footer"
_MS_EPOCH_FLOOR: Final = 1e11  # a seconds value this large is the year 5138; it is milliseconds

# One place each, because the sentences name them and a restart that tells a reader to type a
# command that does not exist is worse than none. `--stop` and `--daemon` are Compass's own
# options (MANUAL.md); Spacedock has no restart command of its own to name instead.
START_COMMAND: Final = "spacedock-compass --daemon"
STOP_COMMAND: Final = "spacedock-compass --stop"

_STATE_NAME = re.compile(r"compass-([1-9][0-9]{0,4})\.json")
_PATH = re.compile(r"/[!-~]*")
_SESSION_FLAG = re.compile(r"([a-z][a-z0-9_-]{0,31}):([!-~]{1,200})")
_SESSION_ID = re.compile(r"[!-~]{1,200}")
CLAUDE_SESSION_ENV: Final = "CLAUDE_CODE_SESSION_ID"
# Another harness's own session id in its shells: Codex's, the one `interaction_prototype`'s
# SESSION_ENVIRONMENT registers a Codex pane by. Started inside a Claude Code session, that harness
# inherits CLAUDE_CODE_SESSION_ID too, which names the outer session and not the one asking, so
# its presence stops the environment from naming a session. A harness with no marker of its own
# cannot be told apart here; SECURITY.md says so.
OTHER_SESSION_ENV: Final = ("CODEX_THREAD_ID",)

# Every sentence the terminal prints about reaching the dashboard. The page derives its own
# wording elsewhere; this is the terminal's single copy, so a result reads the same from every
# command that produces it.
SENTENCES: Final[dict[str, str]] = {
    "monitor_started": "Live monitor started for this session.",
    "monitor_already_running": "Live monitor is already running for this session.",
    "monitor_stopped": "This terminal's Live monitor stopped.",
    "monitor_not_running": "This terminal's Live monitor is not running.",
    "monitor_busy": "Another monitor command is still running.",
    "monitor_failed": "Compass could not start or stop this terminal's Live monitor.",
    "monitor_unreadable": "Compass could not read the board to find this live Claude Code session.",
    "monitor_unavailable": "Compass could not find this live Claude Code session.",
    "monitor_refused": "Compass refused this Live monitor start.",
    "monitor_paused": "Live monitor cannot start while model calls are paused.",
    "monitor_no-observer-model": "Live monitor cannot start under --no-observer-model.",
    "monitor_ended": "Live monitor cannot start because this session has ended.",
    "monitor_missing": "Live monitor is on and makes no check until a goal is saved.",
    "not_running": "Compass is not running. Start it with `{start}`.",
    "starting": "Compass was not running, so this started it as `--daemon` does.",
    "start_failed": "Compass could not start the dashboard. Start it with `{start}`.",
    "start_failed_in_session": (
        "Compass could not start the dashboard. Type `/compass:compass` to start it."
    ),
    "no_session": "Compass cannot tell which session this is. Pass --session claude:SESSION_ID.",
    "no_session_in_session": (
        "The drift action reads Claude Code sessions and this command was given no Claude Code "
        "session id, so nothing was read or spent; a session's page on the board shows its drift."
    ),
    "other_harness": (
        "The drift action reads Claude Code sessions and this command runs inside another tool's "
        "session, so nothing was read or spent; that session's page on the board shows its drift."
    ),
    "bad_session_flag": "The session must look like claude:SESSION_ID, with no spaces.",
    "unreadable_reply": "Compass answered, but its session list could not be read.",
    "caller_unknown": (
        "Compass could not tell which session is asking, so this list may include it."
    ),
    "nothing_waiting": "Nothing is reported as waiting on you.",
    "version_mismatch": (
        "The running dashboard is version {theirs} and this is version {own}, so nothing was sent. "
        "Stop it with `{stop}` and start it again with `{start}`."
    ),
    "version_mismatch_in_session": (
        "The running dashboard is version {theirs} and this is version {own}, so nothing was sent. "
        "Ask `/compass:compass` to stop the dashboard, then type `/compass:compass` to start this "
        "version."
    ),
}


def sentence(key: str, **values: str) -> str:
    """The wording for `key`, with the two commands filled in unless a caller names others."""
    values.setdefault("start", START_COMMAND)
    values.setdefault("stop", STOP_COMMAND)
    return SENTENCES[key].format(**values)


class Operation(NamedTuple):
    """An option the terminal client owns. `cli.build_parser` registers each one from this table."""

    flag: str
    help: str
    # Values the flag may take after it. Empty means a switch; otherwise the value is optional.
    choices: tuple[str, ...] = ()


class Option(NamedTuple):
    """A client operation's option that takes a value, registered beside the flags."""

    flag: str
    metavar: str
    help: str


OPERATIONS = (
    Operation("--pause-model-calls", "pause Compass model calls; Resume stays on the board"),
    Operation(
        "--monitor",
        "hold the Live monitor for this Claude Code session; --off stops this terminal holder",
    ),
    Operation(
        "--project", "read this Claude Code session's project brief without starting Compass"
    ),
    Operation("--version", "print the Compass version and exit"),
    Operation(
        "--footer",
        "print one status line segment (other sessions waiting, the tightest quota window) "
        "from the JSON on stdin and the dashboard's line file, and exit 0; "
        "it reaches no dashboard, so it stands alone or with --session",
    ),
    Operation(
        "--sessions",
        "list the sessions running now and those that finished lately; with `waiting`, only "
        "the ones waiting on you",
        ("waiting",),
    ),
    Operation(
        "--drift",
        "print a session's drift reading against your goal, with --session or "
        "CLAUDE_CODE_SESSION_ID; a stored reading costs nothing, and with none, or with "
        "`again`, it asks the model for one and waits",
        ("again",),
    ),
)
OPTIONS = (
    Option(
        "--session",
        "HARNESS:SESSION_ID",
        "the session --footer, --project or --drift reports for, or --monitor holds; "
        "such as claude:SESSION_ID; "
        "default: the status line's session_id (--footer only), then CLAUDE_CODE_SESSION_ID",
    ),
)


SWITCHES = (Operation("--off", "stop this terminal holder, only with --monitor"),)


def release_version() -> str | None:
    """The Compass version: the stamp a standalone binary carries, else the plugin manifest."""
    try:
        stamped = BUNDLED_VERSION_PATH.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        stamped = ""
    if stamped:
        return stamped
    try:
        manifest = json.loads(PLUGIN_MANIFEST_PATH.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        return None
    version = manifest.get("version") if isinstance(manifest, dict) else None
    return version if isinstance(version, str) and version else None


def print_version() -> int:
    version = release_version()
    if version is None:
        print("Compass: this installation does not record its version", file=sys.stderr)
        return 1
    print(version)
    return 0


def parse_footer_args(argv: list[str]) -> tuple[bool, str | None]:
    """Whether `argv` is exactly a footer request, and the `--session` value it carries.

    `--footer` once, and optionally `--session X` or `--session=X` once, in either order.
    Anything else is not the client's: argparse keeps judging it.
    """
    rest = list(argv)
    if rest.count("--footer") != 1:
        return False, None
    rest.remove("--footer")
    if not rest:
        return True, None
    if len(rest) == 1 and rest[0].startswith("--session="):
        return True, rest[0][len("--session=") :]
    if len(rest) == 2 and rest[0] == "--session":
        return True, rest[1]
    return False, None


def parse_drift_args(argv: list[str]) -> tuple[bool, bool, str | None]:
    """Whether `argv` is exactly a drift request, whether it says `again`, and its `--session`.

    `--drift` or `--drift=again` once, `again` at most once and only right after `--drift`, and
    `--session X` or `--session=X` at most once, anywhere. Anything else is argparse's.
    """
    rest = list(argv)
    again = False
    if rest.count("--drift=again") == 1 and "--drift" not in rest:
        rest.remove("--drift=again")
        again = True
    elif rest.count("--drift") == 1 and "--drift=again" not in rest:
        at = rest.index("--drift")
        again = rest[at + 1 : at + 2] == ["again"]
        del rest[at : at + 2 if again else at + 1]
    else:
        return False, False, None
    if not rest:
        return True, again, None
    if len(rest) == 1 and rest[0].startswith("--session="):
        return True, again, rest[0][len("--session=") :]
    if len(rest) == 2 and rest[0] == "--session" and not rest[1].startswith("--"):
        return True, again, rest[1]
    return False, False, None


def parse_monitor_args(argv: list[str]) -> tuple[bool, bool, str | None]:
    rest = list(argv)
    if rest.count("--monitor") != 1 or rest.count("--off") > 1:
        return False, False, None
    rest.remove("--monitor")
    off = "--off" in rest
    if off:
        rest.remove("--off")
    if not rest:
        return True, off, None
    if len(rest) == 1 and rest[0].startswith("--session="):
        return True, off, rest[0][len("--session=") :]
    if len(rest) == 2 and rest[0] == "--session" and not rest[1].startswith("--"):
        return True, off, rest[1]
    return False, False, None


def run_pause_model_calls(
    *, port: int | None = None, environ: Mapping[str, str] | None = None
) -> int:
    """Send the page's durable pause without starting a dashboard or resolving a session."""
    env = os.environ if environ is None else environ
    dashboard = ensure_dashboard(
        state_home(env), port=port, spend=False, own_version=release_version()
    )
    if isinstance(dashboard, Refusal):
        print(dashboard.message, file=sys.stderr)
        return dashboard.code
    try:
        reply = post(
            dashboard.port, "/api/reading", {"consent": "off", "observer_model": 1, "press": True}
        )
        data = reply.data
        reading = data.get("reading") if isinstance(data, dict) else None
        confirmed = (
            reply.status == 200
            and isinstance(data, dict)
            and data.get("ok") is True
            and isinstance(reading, dict)
            and reading.get("off") is True
        )
    except DashboardUnreachable:
        confirmed = False
    if not confirmed:
        print("Compass could not confirm that model calls are paused. Try again.", file=sys.stderr)
        return 1
    print("Model calls are paused.")
    return 0


def run_monitor(
    *, off: bool = False, session: str | None = None, environ: Mapping[str, str] | None = None
) -> int:
    from compass_runtime import terminal_monitor  # noqa: PLC0415

    env = os.environ if environ is None else environ
    named = resolve_session(session, env, None)
    if isinstance(named, Unresolved):
        print(sentence("no_session"), file=sys.stderr)
        return 1
    if named.harness != "claude":
        print(sentence("monitor_unavailable"), file=sys.stderr)
        return 1
    return terminal_monitor.command(
        named,
        off=off,
        home=state_home(env),
        in_session=named.source == "environment" and not sys.stdout.isatty(),
    )


def claim(argv: list[str]) -> tuple[Operation, str | None] | None:
    """The operation `argv` is, and the value it carries, when `argv` is exactly one operation.

    A lone flag, or a flag with one of its own choices in either spelling. `--footer` is claimed
    here only when alone; `parse_footer_args` owns it with its `--session`. Anything else,
    `--version` beside another option included, is not claimed and goes to the CLI so argparse
    keeps judging combinations and usage errors exactly as it did.
    """
    for operation in OPERATIONS:
        if argv == [operation.flag]:
            return operation, None
        for choice in operation.choices:
            if argv in ([operation.flag, choice], [f"{operation.flag}={choice}"]):
                return operation, choice
    return None


def parse_project_args(argv: list[str]) -> tuple[bool, str | None]:
    """Claim the project read alone or with its explicit caller; leave other flags to argparse."""
    if "--project" not in argv:
        return False, None
    rest = list(argv)
    rest.remove("--project")
    if not rest:
        return True, None
    if len(rest) == 2 and rest[0] == "--session":
        return True, rest[1]
    if len(rest) == 1 and rest[0].startswith("--session="):
        return True, rest[0].split("=", 1)[1]
    return False, None


def handles(argv: list[str]) -> bool:
    return (
        parse_monitor_args(argv)[0]
        or parse_footer_args(argv)[0]
        or parse_drift_args(argv)[0]
        or parse_project_args(argv)[0]
        or claim(argv) is not None
    )


def run(argv: list[str]) -> int:
    monitor, off, named = parse_monitor_args(argv)
    if monitor:
        return run_monitor(off=off, session=named)
    if parse_footer_args(argv)[0]:
        return run_footer(argv, os.environ, sys.stdin, sys.stdout)
    drift, again, session = parse_drift_args(argv)
    if drift:
        return run_drift(again=again, session=session)
    project, session = parse_project_args(argv)
    if project:
        return run_project(session=session)
    claimed = claim(argv)
    if claimed is not None and claimed[0].flag == "--sessions":
        return run_sessions(claimed[1] or True)
    operation = (
        run_pause_model_calls
        if claimed is not None and claimed[0].flag == "--pause-model-calls"
        else print_version
    )
    return operation()


class DashboardUnreachable(OSError):  # noqa: N818
    """Nothing answered, or what answered broke the HTTP exchange."""


class UnreadableSessionsError(ValueError):
    """The dashboard's session list could not be read; this is never an empty list."""


class Dashboard(NamedTuple):
    port: int
    pid: int
    started: float
    version: str | None


class Reply(NamedTuple):
    status: int
    data: Any


class Refusal(NamedTuple):
    """One sentence for the reader and the exit code that goes with it."""

    message: str
    code: int = 1


class Session(NamedTuple):
    harness: str
    sid: str
    source: str


class Unresolved(NamedTuple):
    message: str


def state_home(environ: Mapping[str, str]) -> str:
    override = environ.get("COMPASS_HOME")
    if override and override.strip():
        return override
    return os.path.join(os.path.expanduser("~"), ".compass")


def published_ports(home: str) -> list[int]:
    """Ports named by state files, newest first, from file names and mtimes alone.

    A state file holds the event-ingress tokens, so no code path here opens one: the name carries
    the port and `stat` carries when it was written. Symlinks and directories are skipped because
    neither is something Compass wrote.
    """
    found: list[tuple[float, int]] = []
    try:
        with os.scandir(home) as entries:
            for entry in entries:
                match = _STATE_NAME.fullmatch(entry.name)
                if match is None or int(match.group(1)) > 65535:
                    continue
                try:
                    if entry.is_symlink() or not entry.is_file(follow_symlinks=False):
                        continue
                    found.append((entry.stat(follow_symlinks=False).st_mtime, int(match.group(1))))
                except OSError:
                    continue
    except OSError:
        return []
    found.sort(key=lambda item: (-item[0], item[1]))
    return [port for _, port in found]


def candidate_ports(home: str, port: int | None = None) -> tuple[int, ...]:
    if port is not None:
        return (port,)
    ports = [p for p in published_ports(home) if p != DEFAULT_PORT][: MAX_CANDIDATES - 1]
    return (*ports, DEFAULT_PORT)


def _valid_port(port: object) -> bool:
    return type(port) is int and 1 <= port <= 65535


def probe(port: int, timeout: float = HEALTH_TIMEOUT_SEC) -> Dashboard | None:
    """The dashboard answering `/api/health` on `port`, or None for nothing or something else.

    The acceptance rule is `lifecycle.probe_port`'s, written out again because that module is not
    importable from here. An older dashboard answers without `version`; it is still a dashboard.
    """
    import http.client  # noqa: PLC0415 — only a command that reaches the dashboard pays for it

    from compass_runtime.loopback_transport import exchange  # noqa: PLC0415

    try:
        status, body = exchange("GET", port, "/api/health", timeout=timeout, cap=HEALTH_CAP_BYTES)
        if status != 200 or len(body) > HEALTH_CAP_BYTES:
            return None
        data = json.loads(body)
    except (OSError, http.client.HTTPException, ValueError, RecursionError):
        return None
    if not isinstance(data, dict):
        return None
    pid, reported, started = data.get("pid"), data.get("port"), data.get("started")
    if (
        data.get("ok") is not True
        or type(pid) is not int
        or pid <= 0
        or type(reported) is not int
        or reported != port
        or isinstance(started, bool)
        or not isinstance(started, int | float)
        or not math.isfinite(started)
    ):
        return None
    version = data.get("version")
    return Dashboard(port, pid, float(started), version if isinstance(version, str) else None)


def find_dashboard(
    home: str, *, port: int | None = None, timeout: float = HEALTH_TIMEOUT_SEC
) -> Dashboard | None:
    """The newest-started dashboard among the candidate ports."""
    answers = [d for p in candidate_ports(home, port) if (d := probe(p, timeout)) is not None]
    return max(answers, key=lambda d: d.started, default=None)


def request(
    method: str,
    port: int,
    path: str,
    body: bytes | None = None,
    *,
    headers: Mapping[str, str] | None = None,
    timeout: float = REQUEST_TIMEOUT_SEC,
    cap: int | None = None,
) -> Reply:
    """One loopback exchange. The host is the literal 127.0.0.1 and the port an integer.

    `http.client` reads no proxy variable and follows no redirect, so there is nothing to switch
    off: a 3xx comes back as an ordinary reply with `data` empty and no second request.
    """
    if not _valid_port(port):
        msg = "port must be an integer from 1 to 65535"
        raise ValueError(msg)
    if _PATH.fullmatch(path) is None or path.startswith("//"):
        msg = "path must start with one / and hold no spaces or control characters"
        raise ValueError(msg)
    import http.client  # noqa: PLC0415 — see `probe`

    limit = REPLY_CAP_BYTES if cap is None else cap
    from compass_runtime.loopback_transport import exchange  # noqa: PLC0415

    try:
        status, raw = exchange(
            method, port, path, body, headers=headers, timeout=timeout, cap=limit
        )
    except (OSError, http.client.HTTPException) as error:
        msg = f"no answer from 127.0.0.1:{port}"
        raise DashboardUnreachable(msg) from error
    data: Any = None
    # A refusal's body is read too: `--drift` says why a press was refused from its `reason`.
    if len(raw) <= limit and (200 <= status < 300 or status >= 400):
        try:
            data = json.loads(raw)
        except (ValueError, RecursionError):
            data = None
    return Reply(status, data)


def get(
    port: int, path: str, *, timeout: float = REQUEST_TIMEOUT_SEC, cap: int | None = None
) -> Reply:
    return request("GET", port, path, timeout=timeout, cap=cap)


def post(
    port: int,
    path: str,
    payload: Mapping[str, Any],
    *,
    headers: Mapping[str, str] | None = None,
    timeout: float = REQUEST_TIMEOUT_SEC,
) -> Reply:
    """One JSON POST. `http.client` sends no `Origin` or `Sec-Fetch-*` header, so the dashboard
    sees a local process, which SECURITY.md says its Host, Origin and fetch-metadata checks do not
    stop: loopback is not a per-user boundary."""
    sent = {"Content-Type": "application/json", **(headers or {})}
    return request("POST", port, path, json.dumps(payload).encode(), headers=sent, timeout=timeout)


def version_guard(
    dashboard: Dashboard, own_version: str | None, *, in_session: bool = False
) -> str | None:
    """One sentence when the dashboard is another release than this client, else None.

    A dashboard that reports no version is another release, since the first one to report it is
    this one. Only the release string is compared, so two dev checkouts of one number are not
    told apart.
    """
    if dashboard.version is not None and dashboard.version == own_version:
        return None
    return sentence(
        "version_mismatch_in_session" if in_session else "version_mismatch",
        own=own_version or "unknown",
        theirs=dashboard.version or "unknown",
    )


def start_daemon(port: int, *, timeout: float = 30.0) -> None:
    """Start a dashboard the way `--daemon` does, and wait for the parent to return."""
    import subprocess  # noqa: PLC0415 — a read never starts one, so a read never loads this

    root = Path(__file__).resolve().parents[1]
    if getattr(sys, "frozen", False):
        argv = [sys.executable]
    else:
        argv = [sys.executable, str(root / "launch.py"), str(root / "server.py")]
    argv += ["--daemon", "--port", str(port)]
    try:
        subprocess.run(  # noqa: S603 — our own interpreter and launcher, with an integer port
            argv, stdin=subprocess.DEVNULL, capture_output=True, timeout=timeout, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return


def ensure_dashboard(
    home: str,
    *,
    port: int | None,
    spend: bool,
    own_version: str | None,
    start: Callable[[int], None] | None = None,
    say: Callable[[str], None] | None = None,
    in_session: bool = False,
) -> Dashboard | Refusal:
    """The one rule for a missing dashboard, and for a dashboard of another release.

    A read with none running says so and stops. A spend starts one and says it did. A spend
    against another release stops before it sends anything; a read is still served. `in_session`
    words the refusals for the skill, whose person may have no `spacedock-compass` on PATH.
    """
    found = find_dashboard(home, port=port)
    if found is None:
        if not spend:
            return Refusal(sentence("not_running"))
        (say or _say)(sentence("starting"))
        (start or start_daemon)(DEFAULT_PORT if port is None else port)
        found = find_dashboard(home, port=port, timeout=2.0)
        if found is None:
            return Refusal(sentence("start_failed_in_session" if in_session else "start_failed"))
    if spend and (message := version_guard(found, own_version, in_session=in_session)) is not None:
        return Refusal(message)
    return found


def _say(message: str) -> None:
    print(message, file=sys.stderr)


def read_status_line(
    stream: TextIO | None, *, deadline: float = STDIN_DEADLINE_SEC
) -> dict[str, Any] | None:
    """The one JSON object a status line command is given, or None.

    Bounded in bytes and in time. A producer that writes the object and leaves the pipe open
    answers at once, because the buffer is parsed as it grows; one that writes nothing, or stops
    in the middle, costs `deadline` and answers None. `readline` was rejected: the payload is not
    documented to end in a newline.
    """
    if stream is None:
        return None
    fd: int | None
    try:
        if stream.isatty():
            return None
        fd = stream.fileno()
    except (OSError, ValueError, AttributeError):
        fd = None
    raw: bytes | str | None
    if fd is None:
        raw = _read_whole(stream)
    elif os.name == "nt":
        raw = _read_in_thread(stream, deadline)
    else:
        raw = _read_pipe(fd, deadline)
    return _object(raw)


def _object(raw: bytes | str | None) -> dict[str, Any] | None:
    try:
        data = json.loads(raw) if raw else None
    except (ValueError, RecursionError):
        return None
    return data if isinstance(data, dict) else None


def _read_whole(stream: TextIO) -> str | None:
    """A stream with no descriptor is in memory, so a bounded read cannot hang."""
    try:
        raw = stream.read(STDIN_CAP_CHARS + 1)
    except (OSError, ValueError):
        return None
    return raw if len(raw) <= STDIN_CAP_CHARS else None


def _read_pipe(fd: int, deadline: float) -> bytes | None:
    import select  # noqa: PLC0415 — only a footer call reads a pipe

    end = time.monotonic() + deadline
    buffer = b""
    while True:
        remaining = end - time.monotonic()
        try:
            if remaining <= 0 or not select.select([fd], [], [], remaining)[0]:
                return None
            chunk = os.read(fd, 65_536)
        except (OSError, ValueError):
            return None
        buffer += chunk
        if len(buffer) > STDIN_CAP_CHARS:
            return None
        if not chunk or _complete(buffer):
            return buffer


def _complete(buffer: bytes) -> bool:
    """Whether `buffer` already holds one whole JSON value, so a held-open pipe is not waited on."""
    try:
        json.loads(buffer)
    except (ValueError, RecursionError):
        return False
    return True


def _read_in_thread(stream: TextIO, deadline: float) -> str | None:
    """Windows cannot `select` a pipe, so the read runs in a thread abandoned at the deadline.

    Not exercised by CI, which runs macOS and Linux: it ends at end of input, as a status line
    command's stdin does.
    """
    import threading  # noqa: PLC0415

    box: list[str | None] = []
    worker = threading.Thread(target=lambda: box.append(_read_whole(stream)), daemon=True)
    worker.start()
    worker.join(deadline)
    return box[0] if box else None


def resolve_session(
    flag: str | None,
    environ: Mapping[str, str],
    stdin: TextIO | None,
    *,
    payload: Mapping[str, Any] | None = None,
) -> Session | Unresolved:
    """Which session this command is in: `--session`, else the status line, else the environment.

    The environment names none when another harness's own marker is set (`OTHER_SESSION_ENV`).
    Never the working directory. A session id names a session and proves nothing about who asked,
    so a spend still passes the dashboard's own guards. A `--session` that does not parse is
    refused, not replaced by a looser source.
    """
    if flag is not None:
        match = _SESSION_FLAG.fullmatch(flag)
        if match is None:
            return Unresolved(sentence("bad_session_flag"))
        return Session(match.group(1), match.group(2), "flag")
    # A caller that already read stdin passes what it read, so stdin is never read twice.
    status_line = payload if payload is not None else read_status_line(stdin)
    value = status_line.get("session_id") if status_line is not None else None
    if isinstance(value, str) and _SESSION_ID.fullmatch(value):
        return Session("claude", value, "status line")
    if any(environ.get(name) for name in OTHER_SESSION_ENV):
        return Unresolved(sentence("other_harness"))
    value = environ.get(CLAUDE_SESSION_ENV)
    if value is not None and _SESSION_ID.fullmatch(value):
        return Session("claude", value, "environment")
    return Unresolved(sentence("no_session"))


class Window(NamedTuple):
    """One quota window the status line reported: its label, percent used and reset (epoch)."""

    label: str
    used: float
    resets_at: float | None


class Line(NamedTuple):
    """What the dashboard last wrote for one session: others waiting (None if unmeasured)."""

    waiting: int | None
    blind: tuple[str, ...]
    monitor: bool = False
    level: str | None = None
    last_end: tuple[str, float] | None = None
    model_calls_paused: bool | None = None


# Copies of the producer vocabularies, held equal by tests without importing the runtime here.
FOOTER_LEVELS: Final = {
    "none_or_low": "None or low",
    "medium": "Medium",
    "high": "High",
    "extreme": "Extreme",
    "not_enough": "Not enough recorded yet",
}
# Short forms of the page's `drift/monitor.ts` END_NOTES; the reader's own Off stays silent.
MONITOR_END_NOTES: Final = {
    "ended": "monitor off: session ended",
    "left": "monitor off: check-in expired",
    "paused": "monitor off: model calls paused",
    "unanswered": "monitor off: no answer",
    "declined": "monitor off: as you asked",
    "cap": "monitor off: check limit reached",
    "stopped": "",
}
MONITOR_END_SEC: Final = 300.0


_WINDOWS: Final = (("five_hour", "5h"), ("seven_day", "7d"))


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    try:
        return float(value) if math.isfinite(value) else None
    except OverflowError:
        # A JSON integer past a float's range: `isfinite` raises on it, and the blanket handler
        # in `run_footer` would then hide a valid waiting count along with the window.
        return None


def _reset_epoch(value: object) -> float | None:
    """Epoch seconds, or ISO text, or None. No capture of the real payload exists yet, so both."""
    if isinstance(value, str):
        from datetime import UTC, datetime  # noqa: PLC0415

        try:
            moment = datetime.fromisoformat(value.strip())
        except ValueError:
            return None
        return (moment if moment.tzinfo else moment.replace(tzinfo=UTC)).timestamp()
    seconds = _number(value)
    return seconds if seconds is not None and 0 < seconds < _MS_EPOCH_FLOOR else None


def tightest_window(payload: Mapping[str, Any] | None, now: float) -> Window | None:
    """The window with the higher percent used, among those that can be read and have not reset.

    A percent that is not a number from 0 to 100 withholds its window: zero would be a statement
    about the schema. A window that has already reset describes a finished period, so it is
    dropped rather than shown at its old, alarming figure. A usable percent with no usable reset
    is kept and shown without one.
    """
    limits = payload.get("rate_limits") if payload is not None else None
    if not isinstance(limits, dict):
        return None
    found: list[Window] = []
    for key, label in _WINDOWS:
        window = limits.get(key)
        if not isinstance(window, dict):
            continue
        used = _number(window.get("used_percentage"))
        if used is None or not 0 <= used <= 100:
            continue
        resets_at = _reset_epoch(window.get("resets_at"))
        if resets_at is not None and resets_at <= now:
            continue
        found.append(Window(label, used, resets_at))
    # Higher use first, then the sooner reset (none last), then the five-hour window.
    found.sort(key=lambda w: (-w.used, math.inf if w.resets_at is None else w.resets_at))
    return found[0] if found else None


def _until(seconds: float) -> str:
    minutes = max(1, int(seconds // 60))
    if minutes >= 1440:
        return f"{minutes // 1440}d {minutes % 1440 // 60}h"
    if minutes >= 60:
        return f"{minutes // 60}h {minutes % 60}m"
    return f"{minutes}m"


def format_window(window: Window, now: float) -> str:
    text = f"{window.label} {int(window.used + 0.5)}%"
    if window.resets_at is None:
        return text
    return f"{text} resets in {_until(window.resets_at - now)}"


def line_name(harness: str, sid: str) -> str:
    """The dashboard's name for one session's file, written again because the client imports no
    runtime module. A test holds the two equal.
    """
    import hashlib  # noqa: PLC0415

    return f"{harness}-{hashlib.sha256(sid.encode('utf-8', 'replace')).hexdigest()[:32]}.json"


def _label(value: object) -> str | None:
    ok = isinstance(value, str) and 0 < len(value) <= LABEL_CAP_CHARS
    return (
        value
        if ok and isinstance(value, str) and value.isprintable() and value == value.strip()
        else None
    )


def read_line(home: str, session: Session, now: float) -> Line | None:
    """The dashboard's file for `session`, or None for anything that is not fresh and plain.

    Missing, unreadable, not a regular file, oversized, not JSON, another shape version, older
    than the ceiling or dated in the future all leave the segments out. The file is opened
    without following a link, and the name is a hash, so an outside id reaches no path.
    """
    path = os.path.join(home, FOOTER_DIRECTORY, line_name(session.harness, session.sid))
    try:
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        fd = os.open(path, flags)
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                return None
            raw = os.read(fd, LINE_CAP_BYTES + 1)
        finally:
            os.close(fd)
        data = json.loads(raw) if len(raw) <= LINE_CAP_BYTES else None
    except (OSError, ValueError, RecursionError):
        return None
    if not isinstance(data, dict) or type(data.get("v")) is not int or data["v"] != SHAPE_VERSION:
        return None
    at = _number(data.get("at"))
    if at is None or at > now + LINE_FUTURE_SLACK_SEC or now - at > LINE_STALE_SEC:
        return None
    waiting = data.get("waiting")
    count = waiting if type(waiting) is int and waiting >= 0 else None
    labels = data.get("blind")
    blind = tuple(x for x in (_label(v) for v in labels) if x) if isinstance(labels, list) else ()
    monitor = data.get("monitor") is True
    raw_level = data.get("level")
    level = raw_level if isinstance(raw_level, str) and raw_level in FOOTER_LEVELS else None
    # An unknown token is not the stated absence: suppress only its drift segment.
    monitor = monitor and (raw_level is None or level is not None)
    raw_end = data.get("last_end")
    last_end = None
    if data.get("monitor") is False and isinstance(raw_end, dict):
        reason, ended_at = raw_end.get("reason"), _number(raw_end.get("at"))
        if (
            isinstance(reason, str)
            and reason in MONITOR_END_NOTES
            and ended_at is not None
            and ended_at <= now + LINE_FUTURE_SLACK_SEC
        ):
            last_end = (reason, ended_at)
    paused = data.get("model_calls_paused")
    return Line(count, blind, monitor, level, last_end, paused if type(paused) is bool else None)


def _monitor_parts(line: Line | None, now: float) -> list[str]:
    parts: list[str] = []
    if line is not None:
        if line.monitor is True:
            if line.level is None:
                parts.append("drift: no level yet")
            elif line.level in FOOTER_LEVELS:
                parts.append(f"drift {FOOTER_LEVELS[line.level]}")
        elif line.last_end is not None:
            reason, ended_at = line.last_end
            note = MONITOR_END_NOTES.get(reason)
            if reason == "paused":
                note = "monitor off"
            if note and -LINE_FUTURE_SLACK_SEC <= now - ended_at < MONITOR_END_SEC:
                parts.append(note)
    return parts


def compose_footer(payload: Mapping[str, Any] | None, line: Line | None, now: float) -> str:
    """The one line: monitor, waiting, who cannot report a wait, then the tightest quota window.

    An unmeasured or zero count prints nothing, and a steady board prints nothing at all.
    """
    parts: list[str] = []
    if line is not None and line.model_calls_paused is True:
        parts.append("model calls paused")
    parts.extend(_monitor_parts(line, now))
    if line is not None and line.waiting:
        parts.append(f"{line.waiting} waiting")
    if line is not None and line.blind:
        parts.append(f"waits not reported for {', '.join(line.blind)}")
    window = tightest_window(payload, now)
    if window is not None:
        parts.append(format_window(window, now))
    return " · ".join(parts)


def run_footer(
    argv: list[str],
    environ: Mapping[str, str],
    stdin: TextIO | None,
    stdout: TextIO,
    *,
    now: float | None = None,
) -> int:
    """Print the status line segment. Always 0, and silent when it cannot tell.

    A status line discards stderr and shows a nonzero exit as nothing useful, so every failure
    here is an empty line. It sends no request: there is nothing in this path that could.
    """
    try:
        moment = time.time() if now is None else now
        flag = parse_footer_args(argv)[1]
        payload = read_status_line(stdin)
        session = resolve_session(flag, environ, None, payload=payload or {})
        if isinstance(session, Session):
            line = read_line(state_home(environ), session, moment)
            text = compose_footer(payload, line, moment)
            if text:
                stdout.write(text + "\n")
    except Exception:  # noqa: BLE001 — nothing may reach a status bar but the line
        return 0
    return 0


def _emit(lines: list[str], stream: TextIO) -> None:
    text = "\n".join(lines) + "\n"
    encoding = getattr(stream, "encoding", None) or "utf-8"
    # A pipe in a non-UTF-8 locale would raise on goal text the board shows without trouble.
    stream.write(text.encode(encoding, "replace").decode(encoding, "replace"))


def read_sessions(port: int, *, timeout: float = LIST_REQUEST_TIMEOUT_SEC) -> dict[str, Any]:
    """Read list rows, or the full board when an older daemon lacks the list route."""
    deadline = time.monotonic() + timeout
    try:
        reply = get(port, "/api/sessions", cap=DATA_CAP_BYTES, timeout=timeout)
        # Updating the plugin leaves an older daemon running. Only a missing route earns the
        # legacy read; hiding any other failure would turn a broken list into a second answer.
        if reply.status == 404:
            left = max(0.0, deadline - time.monotonic())
            reply = get(port, "/api/data", timeout=left, cap=DATA_CAP_BYTES)
    except DashboardUnreachable as exc:
        raise UnreadableSessionsError from exc
    payload = reply.data
    if (
        reply.status != 200
        or not isinstance(payload, dict)
        or not isinstance(payload.get("sessions"), list)
    ):
        raise UnreadableSessionsError
    for field, required in (
        ("sessions", ("harness", "sid", "project")),
        ("harnesses", ("key",)),
        ("asks", ("id", "harness", "session_id", "project", "question")),
    ):
        if field not in payload:
            continue
        rows = payload[field]
        if not isinstance(rows, list) or any(
            not isinstance(row, dict) or any(not isinstance(row.get(key), str) for key in required)
            for row in rows
        ):
            raise UnreadableSessionsError
    return payload


def run_project(
    *,
    session: str | None = None,
    port: int | None = None,
    environ: Mapping[str, str] | None = None,
) -> int:
    """Read the caller, lean membership and project context; no launch or model press."""
    from urllib.parse import urlencode  # noqa: PLC0415

    from compass_runtime import terminal_project  # noqa: PLC0415

    env = os.environ if environ is None else environ
    named = resolve_session(session, env, None)
    if isinstance(named, Unresolved) or named.harness != "claude":
        print(
            named.message
            if isinstance(named, Unresolved)
            else "--project needs a Claude Code caller.",
            file=sys.stderr,
        )
        return 1
    found = ensure_dashboard(state_home(env), port=port, spend=False, own_version=None)
    if isinstance(found, Refusal):
        print(found.message, file=sys.stderr)
        return found.code
    # Keep the cold collection's longer allowance without lengthening the focused reads.
    deadline = time.monotonic() + LIST_REQUEST_TIMEOUT_SEC + 2 * REQUEST_TIMEOUT_SEC

    def remaining(ceiling: float = REQUEST_TIMEOUT_SEC) -> float:
        seconds = deadline - time.monotonic()
        if seconds <= 0:
            raise DashboardUnreachable
        return min(ceiling, seconds)

    try:
        reply = get(
            found.port,
            "/api/session?" + urlencode({"harness": named.harness, "sid": named.sid}),
            cap=REPLY_CAP_BYTES,
            timeout=remaining(),
        )
        own = reply.data.get("session") if isinstance(reply.data, dict) else None
        if (
            reply.status != 200
            or not isinstance(own, dict)
            or own.get("harness") != named.harness
            or not isinstance(own.get("sid"), str)
            or not isinstance(own.get("project"), str)
        ):
            raise UnreadableSessionsError  # noqa: TRY301 - shared unreadable-response handling
        label = own["project"]
        if not label.strip():
            print("This session has no project label; no project sessions are listed.")
            return 0
        payload = read_sessions(found.port, timeout=remaining(LIST_REQUEST_TIMEOUT_SEC))
        caller = (own["harness"], own["sid"])
        matching = [
            row
            for row in payload["sessions"]
            if row["harness"] == named.harness and terminal_sessions.names(row, named.sid)
        ]
        if len(matching) != 1 or matching[0]["project"] != label:
            print(
                "This session is outside the current board or its project changed; read again.",
                file=sys.stderr,
            )
            return 1
        project = terminal_project.project_key(payload, label)
        reply = get(
            found.port,
            "/api/project-context?" + urlencode({"project": project}),
            cap=DATA_CAP_BYTES,
            timeout=remaining(),
        )
        if (
            reply.status != 200
            or not isinstance(reply.data, dict)
            or not isinstance(reply.data.get("semantic"), dict)
            or reply.data.get("project") != project
            or reply.data.get("focus") is not None
        ):
            raise UnreadableSessionsError  # noqa: TRY301 - shared unreadable-response handling
        brief = terminal_project.derive(payload, reply.data, label=label)
        lines = terminal_project.render(brief, caller=caller)
    except (
        DashboardUnreachable,
        UnreadableSessionsError,
        ValueError,
        TypeError,
        KeyError,
        OverflowError,
    ):
        print(sentence("unreadable_reply"), file=sys.stderr)
        return 1
    _emit(lines, sys.stdout)
    return 0


def run_sessions(
    mode: str | bool | None = None,
    *,
    port: int | None = None,
    environ: Mapping[str, str] | None = None,
) -> int:
    """`--sessions`, and `--sessions waiting` for the second one: read the board, print it.

    Read only. With no dashboard it says so and stops; it never starts one. The caller is left
    out of the waiting list, since a session that asks what waits on you is not what waits. When
    the caller cannot be identified nothing can be left out, and a line above the rows says so.
    """
    env = os.environ if environ is None else environ
    found = ensure_dashboard(state_home(env), port=port, spend=False, own_version=None)
    if isinstance(found, Refusal):
        print(found.message, file=sys.stderr)
        return found.code
    try:
        payload = read_sessions(found.port)
    except UnreadableSessionsError:
        print(sentence("unreadable_reply"), file=sys.stderr)
        return 1
    try:
        if mode == "waiting":
            caller = resolve_session(None, env, None)
            lines = terminal_sessions.render_waiting(
                payload,
                port=found.port,
                exclude=caller.sid if isinstance(caller, Session) else None,
                nothing=sentence("nothing_waiting"),
                caveat=None if isinstance(caller, Session) else sentence("caller_unknown"),
            )
        else:
            lines = terminal_sessions.render_sessions(payload)
    except Exception:  # noqa: BLE001 - a payload is untrusted; whatever it holds, say one sentence
        print(sentence("unreadable_reply"), file=sys.stderr)
        return 1
    _emit(lines, sys.stdout)
    return 0


def _is_terminal(stream: object) -> bool:
    try:
        return bool(stream.isatty())  # type: ignore[attr-defined]
    except (AttributeError, OSError, ValueError):
        return False


def _budget(deadline: float | None, ceiling: float) -> float:
    """`ceiling`, cut to end a second before `deadline`; never below a tenth of a second."""
    if deadline is None:
        return ceiling
    return max(0.1, min(ceiling, deadline - time.time() - 1.0))


class LoopbackBoard:
    """The dashboard as `terminal_drift` reaches it: four exchanges, each over `request`.

    A reply that never came is `terminal_drift.Lost`, so the drift rules never see a socket error.
    With a `deadline` (`time.time` terms) no exchange outlasts it, so an in-session run still has
    time to say a reading keeps running.
    """

    def __init__(self, port: int, deadline: float | None = None) -> None:
        self.port = port
        self.deadline = deadline

    def timeout(self) -> float:
        return _budget(self.deadline, DRIFT_REQUEST_TIMEOUT_SEC)

    def _read(self, path: str) -> Any:
        from compass_runtime.terminal_drift import Lost  # noqa: PLC0415 — only a drift reaches this

        try:
            reply = get(self.port, path, timeout=self.timeout(), cap=DATA_CAP_BYTES)
        except DashboardUnreachable as error:
            raise Lost(path) from error
        return reply.data if reply.status == 200 else None

    def data(self) -> Any:
        return self._read("/api/data")

    def context(self, project: str, session: str) -> Any:
        from urllib.parse import quote  # noqa: PLC0415 — only a drift reaches this

        query = f"project={quote(project, safe='')}&session={quote(session, safe='')}"
        return self._read(f"/api/project-context?{query}")

    def post(self, path: str, body: Mapping[str, Any]) -> tuple[int, Any]:
        from compass_runtime.terminal_drift import Lost  # noqa: PLC0415 — only a drift reaches this

        try:
            reply = post(self.port, path, body, timeout=self.timeout())
        except DashboardUnreachable as error:
            raise Lost(path) from error
        return reply.status, reply.data


def run_drift(
    *,
    again: bool = False,
    session: str | None = None,
    port: int | None = None,
    environ: Mapping[str, str] | None = None,
) -> int:
    """`--drift` and `--drift again`: name the session, find the dashboard, hand the rest over.

    The session is `--session`, else `CLAUDE_CODE_SESSION_ID`; stdin is never read, since it is not
    a status line here. Both refusals come before any dashboard is reached. A Claude Code session
    may spend, so a missing dashboard is started and another release refused; any other harness is
    only sent to its page, which needs a running board and starts none.

    A person at a shell is `--session` with standard output a terminal. An agent's shell tool, and
    Claude Code's `!` mode, read the output through a pipe, so a named session alone would print
    the correction into the context of the agent it is addressed to
    ([DEC-25](docs/design-reading-a-session.md#dec-25-a-correction-stays-yours-to-copy)).
    """
    began = time.time()  # the in-session budget counts from here, a dashboard start included
    from compass_runtime import terminal_drift  # noqa: PLC0415 — only a drift loads the drift rules

    env = os.environ if environ is None else environ
    tty = _is_terminal(sys.stdout)
    named = resolve_session(session, env, None, payload={})
    if isinstance(named, Unresolved):
        message = named.message
        if not tty and message == sentence("no_session"):
            # The skill never adds `--session`, so the flag is no step for its agent to take.
            message = sentence("no_session_in_session")
        print(message, file=sys.stderr)
        return 1
    # The skill's own run, as `SKILL.md` writes it: named by the environment, read through a pipe.
    in_session = named.source == "environment" and not tty
    at_shell = named.source == "flag" and tty
    deadline = None if at_shell else began + terminal_drift.IN_SESSION_WAIT_SEC
    said: list[str] = []
    found = ensure_dashboard(
        state_home(env),
        port=port,
        spend=named.harness == "claude",
        own_version=release_version(),
        start=lambda chosen: start_daemon(chosen, timeout=_budget(deadline, 30.0)),
        # Inside a session the skill shows standard output on success and standard error on a
        # refusal, so the line is handed to the drift rules to say on whichever answers.
        say=said.append if in_session else None,
        in_session=in_session,
    )
    if isinstance(found, Refusal):
        print(found.message, file=sys.stderr)
        return found.code
    return terminal_drift.run(
        named.harness,
        named.sid,
        again=again,
        at_shell=at_shell,
        in_session=in_session,
        board=LoopbackBoard(found.port, deadline),
        port=found.port,
        out=sys.stdout,
        err=sys.stderr,
        began=began,
        note=said[0] if said else "",
    )
