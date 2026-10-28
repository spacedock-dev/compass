#!/usr/bin/env python3
"""Forward one command-hook lifecycle event to a running Compass.

Serves every harness whose hooks are *hook-shaped*: a fresh process per event,
one JSON payload on stdin, a `hook_event_name` naming what happened. Claude Code,
Codex and Gemini CLI all are, and Codex's `hooks.json` turned out to accept the
same schema as Claude's `settings.json` hooks, PascalCase event names included.
Gemini's event names differ but its payload does not. Antigravity is not: its
status line pushes a state snapshot rather than an event, so it has its own
adapter in `statusline_hook.py`.

This file ships three times. Gemini CLI loads extension hooks only from
`<extension>/hooks/hooks.json` and Claude Code claims that same path in a plugin
root, so Gemini gets its own extension root at `compass-gemini/`. Droid searches
`hooks/hooks.json` first and would run Claude's file if pointed at the shared root,
so Droid gets its own extension root at `compass-droid/`. Each carries
a byte-identical copy of this script and of `notify_hook.py` beside its hooks
file. `scripts/validate_plugins.py` fails the build if the copies drift.

Separate from `notify_hook.py` on purpose. That script forwards a needs-input
notification to `/api/notify`, which is unauthenticated and sets one harness's
side state; this one posts general lifecycle events to `/api/events/<harness>`,
which requires this run's capability because a forged `session_ended` could
suppress a permission alert and a looped `turn_started` could mask a blocked
session. Different power, different door. The transport guards are shared, so a
proxy or redirect fix lands in one place.

Usage, with the harness first and an optional port second:

    python3 <skill-dir>/event_hook.py claude       # macOS, Linux, WSL, Git Bash
    python  <skill-dir>\\event_hook.py codex 9999  # Windows, non-default port

The harness is an argument rather than sniffed from the payload. Two harnesses
send the same field names, so a payload cannot say which one it came from, and
guessing would post one harness's events to the other's route.

## What it sends, and what it refuses to send

Only the twelve allowlisted envelope fields, built field by field from the native
payload. The prompt, the tool name, the tool input and output, and every other
native field are dropped here rather than at the server, so they are never put
on a socket at all.

Three of the twelve are terminal identity, and they ride `SessionStart` alone. A
hook can see what the dashboard never can: `events.ALLOWED_FIELDS` carries no pid,
tty or terminal identity and no collector reads one, but a hook is a child of the
harness and its environment says which tmux pane it is in. What is read is the
tmux socket NAME and `TMUX_PANE`, from the environment, and nothing else. No
ancestry walk, no controlling terminal, no `ps`: those belong to the Apple Event
case `SECURITY.md` does not name yet, and `docs/captures/README.md` measured
`hook_ms` at 200.8 to 524.8 ms dominated by exactly those calls.

`Notification` is deliberately **not** mapped. A generic or actionable Claude
notification stays standing hook state under today's precedence via
`notify_hook.py`, because Claude Code can emit an input-waiting notification for
a session that then carries on running. Promoting it to an authoritative
permission overlay would make that transient state hard to clear.
`PermissionRequest` is different: it is explicit, so it maps to
`input_requested` and is cleared only by positive evidence.

`PreCompact` is not mapped either. Suppressing collection during a rewrite window
needs a server-side rewrite-in-progress state that does not exist yet; without it
the honest thing is to reconcile after the fact, which is what `PostCompact`
does.

Always exits 0. A hook that fails must never disturb the agent it reports on, and
"the dashboard is not running" is an ordinary state rather than an error.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import sys
import threading
import time
from datetime import UTC, datetime
from typing import Any

# A sentinel for "read it from this process", so a caller may pass an explicit
# None meaning "there is no uid" without that being read as "go and look".
_UNSET = object()

# The envelope version this adapter writes. An adapter lives in user-owned
# configuration and is not upgraded when Compass is, so a server may see this
# value long after the server itself moved on; it answers `event-incompatible`
# rather than ignoring the event.
ENVELOPE_VERSION = 1

DEFAULT_PORT = 4553
MAX_PAYLOAD_BYTES = 1 << 20

# Native hook name to the normalized vocabulary, per harness. A name absent from
# a harness's table is not forwarded: the table is the whole of what this adapter
# claims to understand for that harness, and the server would refuse an unknown
# name anyway.
CLAUDE_EVENTS = {
    "SessionStart": "session_started",
    "SessionEnd": "session_ended",
    "UserPromptSubmit": "turn_started",
    "Stop": "turn_stopped",
    "PermissionRequest": "input_requested",
    "PostToolUse": "store_changed",
    "SubagentStart": "subagent_started",
    "SubagentStop": "subagent_stopped",
    "TaskCompleted": "tasks_changed",
    "PostCompact": "reconcile_required",
}

# Codex. Measured from a real `codex exec` turn rather than read off a page: the
# five names below all fired, once each, in the order
# UserPromptSubmit -> PreToolUse -> PostToolUse -> Stop with SessionStart outside
# the turn. `PreToolUse` is deliberately absent even though it fires: it means a
# tool is about to run, which `PostToolUse` reports better once the store has
# actually changed, and forwarding both would double every tool call for no gain.
#
# The subagent pair is measured too, from a second capture that did spawn one:
# see `docs/captures/codex/subagents-0.146.0-macos.jsonl`. The question that
# decided the mapping was whose id `session_id` carries, and it is the parent's.
# Measured, not read: it equalled the `UserPromptSubmit` session id of the same
# turn, while `agent_id` was a different 36-character UUID which appears in the
# child's own rollout filename, and the child's rollout records that same parent
# id as `parent_thread_id`. So the envelope maps straight through and the existing
# `agent_id` to `subagent_id` rename is all that was needed. One subagent produced
# exactly one start and one stop.
#
# `PermissionRequest` is mapped, and it took three readings to get there. It was
# "unmeasured", then "measured, and deliberately declined", and both of those
# conflated two questions this entry finally separates: whether to REPORT a gate,
# and whether to ANSWER one.
#
# Measured on 0.149.0, driven interactively
# (`docs/captures/codex/permission-hook-interactive-0.149.0-macos.jsonl`): it
# fires with a real approval prompt standing open, its payload carries
# `session_id`, and Codex blocks the tool call on the hook -- honoured at 25
# seconds on allow and 70 on deny rather than timing out. The earlier negative
# was narrower than it read: `codex exec` pins `approval_policy` to `never`, so
# under `exec` nothing ever asks. That is a property of the mode, not the event.
# (`approval_policy = "untrusted"`, which that run passed, is now a hard error.)
#
# **Reporting is separable from answering, and this file can only report.** Alone
# among Codex's hooks this one gets to decide, and Codex validates what comes
# back: `hookSpecificOutput` requires `hookEventName`, `decision.behavior` is
# exactly `allow` or `deny`, and three reserved fields fail closed. But `main()`
# writes nothing to stdout on any of its five exit paths, and empty output is
# read as an abstain -- so declining is not a choice this script makes correctly,
# it is the only thing it can do.
#
# That last step was a documentation read until it was measured, which mattered
# because every earlier arm returned NON-empty output and Codex fails closed on a
# malformed one: if zero bytes had parsed as invalid rather than as no-opinion,
# registering this event would have denied every escalated tool call for every
# install. Measured on 0.149.0, interactively: the hook fired, printed nothing,
# exited 0, the prompt reached the person, and the approved command ran
# (`docs/captures/codex/permission-abstain-0.149.0-macos.jsonl`). Tests pin the
# empty stdout on the four early exits and on the far side of a real forward,
# and they are mutation-checked -- the first version of that test patched
# `sys.stdin` with a `StringIO`, which has no `.buffer`, so all four arms
# measured the no-stdin path and a mutant printing a `deny` sailed through.
#
# Two channels the argument does NOT cover, recorded rather than argued away.
# A failure before `main()` runs -- no interpreter, an unreadable file, an
# interrupt -- exits non-zero, and whether Codex reads a non-zero exit from this
# event as a block is unmeasured. And no `timeout` is set on the bundled entry,
# deliberately: the interactive capture could not exclude a fail-closed timeout,
# so naming a short one risks converting a slow disk into a refused tool call,
# which is worse than the stall it would bound. Both are in the capture's
# `_unrun` records.
#
# Note the asymmetry with Antigravity, which is exactly inverted and is why
# `agy_hook.py` cannot borrow this reasoning: there an empty object is a DENY, so
# the harmless-looking output gates the call. Here empty output is the safe one.
#
# Answering a gate is still a product decision (DEC-2 / B4) and nothing here
# advances it. What this ships is a red row, on the harness where a gate was the
# one thing the board could not see.
CODEX_EVENTS = {
    "SessionStart": "session_started",
    "UserPromptSubmit": "turn_started",
    "Stop": "turn_stopped",
    "PermissionRequest": "input_requested",
    "PostToolUse": "store_changed",
    "PostCompact": "reconcile_required",
    "SubagentStart": "subagent_started",
    "SubagentStop": "subagent_stopped",
}

# Gemini CLI. Measured from four real 0.53.1 sessions driven against a local
# stand-in for the API, so no credential was involved: see
# `docs/captures/gemini/hooks-0.53.1-macos.jsonl`. Gemini's vocabulary is its own
# -- `BeforeAgent` and `AfterAgent` rather than `UserPromptSubmit` and `Stop` --
# but its payload is the same snake_case shape, down to `session_id`,
# `transcript_path` and `cwd`, which is why this adapter needs no per-harness
# field mapping. `gemini hooks migrate` exists to port Claude Code hooks across,
# so the resemblance is deliberate rather than coincidence.
#
# `BeforeAgent` and `AfterAgent` fired exactly once per turn, in that order.
# `BeforeTool` is deliberately absent for the same reason `PreToolUse` is for
# Codex: `AfterTool` reports the same tool call once the store has actually
# changed.
#
# `Notification` is absent, and it is the one Gemini event worth wanting:
# it is documented as carrying `notification_type: "ToolPermission"`, which would
# be a first-class permission signal. It could not be captured, because
# non-interactive Gemini withholds every tool that needs approval -- the offered
# set was glob, grep_search, list_directory, read_file, google_web_search,
# invoke_agent, update_topic and enter_plan_mode, with no shell or write tool --
# so no approval prompt can arise. Unmeasured semantics do not ship here.
#
# `BeforeModel`, `BeforeToolSelection` and `AfterModel` are absent because they
# fire per model round-trip rather than per turn, and `AfterModel` is documented
# as firing per streamed chunk. `PreCompress` is absent for the reason
# `PreCompact` is for Claude, and because it was measured firing once per model
# round-trip, which makes it a poor session signal in any case.
GEMINI_EVENTS = {
    "SessionStart": "session_started",
    "SessionEnd": "session_ended",
    "BeforeAgent": "turn_started",
    "AfterAgent": "turn_stopped",
    "AfterTool": "store_changed",
}

# Droid. Measured from two non-interactive exec sessions on Droid 0.202.0: see
# `docs/captures/droid/notification-0.202.0-macos.jsonl`. Droid accepts
# `.factory-plugin` or `.claude-plugin` manifest directories and executes hooks
# configured under its hooks file. Only SessionStart and SessionEnd were measured;
# Notification was never captured and interactive launches did not pass login, so
# no permission/gate events are mapped.
DROID_EVENTS = {
    "SessionStart": "session_started",
    "SessionEnd": "session_ended",
}

EVENTS_BY_HARNESS = {
    "claude": CLAUDE_EVENTS,
    "codex": CODEX_EVENTS,
    "gemini": GEMINI_EVENTS,
    "droid": DROID_EVENTS,
}

# The two terminal-identity fields, and the grammars that decide whether either
# is sent at all. They are the same patterns `compass_runtime/focus.py` applies
# again at the raise; duplicated rather than imported because this file ships
# into a user's harness configuration with no runtime package beside it, and a
# hook that cannot import is a hook that does not run.
#
# The socket is a NAME and never a path, because the raise passes it as `-L`. A
# session on a custom `-S /path` socket therefore yields no target, which is an
# honest decline rather than a command that cannot work.
TMUX_PANE_PATTERN = r"^%[0-9]{1,9}$"
TMUX_SOCKET_PATTERN = r"^[A-Za-z0-9_][A-Za-z0-9._-]{0,63}$"
# The tmux server's pid, `$TMUX`'s second field. Sent because a pane id is an
# ordinal on ONE server: kill the server, start another on the same socket name,
# and `%3` is somebody else's pane. The raise asks the server for `#{pid}` and
# declines a target the answer does not match, so this field is what stops a
# stale target from naming an unrelated pane.
TMUX_SERVER_PATTERN = r"^[0-9]{1,10}$"

# The event this identity rides, and the only one. A pane does not change inside
# a session, and posting it on every hook would put it on the socket hundreds of
# times per session for no reading the first one did not already give.
IDENTITY_EVENT = "session_started"


def tmux_identity(environ: Any, uid: int | None) -> dict[str, str]:
    """The tmux socket name, pane and server pid for this hook's process, or {}.

    `TMUX` is `<socket path>,<server pid>,<session id>`, and all three readings
    come out of it and `TMUX_PANE`. The basename is taken only when its directory
    is the DEFAULT tmux socket directory for this uid (`$TMUX_TMPDIR/tmux-<uid>`,
    falling back to `/tmp`), because a name passed as `-L` resolves against that
    directory *for a process that shares this one's `TMUX_TMPDIR`* — which the
    dashboard daemon need not, since it may have been launched from a differently
    configured tmux or from none. So the directory check is a bound on what may
    be named and never a promise about where the name will resolve later; the
    server pid is what makes a name resolving elsewhere a decline rather than a
    raise on an unrelated server's pane.

    Reads three environment variables and makes no other call of any kind. There
    is no ancestry walk and no controlling-terminal read here, and their absence
    is asserted rather than assumed: DRC-4382 measured that for a session with no
    controlling terminal at all, both obvious readings report a terminal, and it
    is somebody else's.
    """
    if uid is None:
        return {}
    raw = environ.get("TMUX")
    pane = environ.get("TMUX_PANE")
    if (
        not isinstance(raw, str)
        or not isinstance(pane, str)
        or re.match(TMUX_PANE_PATTERN, pane) is None
    ):
        return {}
    fields = raw.split(",")
    if len(fields) < 2 or re.match(TMUX_SERVER_PATTERN, fields[1]) is None:
        return {}
    path, server = fields[0], fields[1]
    name = os.path.basename(path)
    if re.match(TMUX_SOCKET_PATTERN, name) is None:
        return {}
    # The default tmux socket directory, which is the only one a `-L` name can
    # resolve against. Not a temporary file this process creates or trusts: it is
    # the path tmux itself already bound its socket in, and the comparison below
    # is what decides whether the name may be used at all.
    tmpdir = environ.get("TMUX_TMPDIR") or "/tmp"  # noqa: S108
    expected = os.path.join(tmpdir, "tmux-{}".format(uid))  # noqa: UP032
    # realpath on both sides: macOS resolves /tmp to /private/tmp, so the honest
    # comparison is between resolved directories rather than between the strings
    # tmux and the environment happened to spell.
    if os.path.realpath(os.path.dirname(path)) != os.path.realpath(expected):
        return {}
    return {"tmux_socket": name, "tmux_pane": pane, "tmux_server": server}


def process_uid() -> int | None:
    """This process's uid, or None where the platform has none (Windows)."""
    getuid = getattr(os, "getuid", None)
    return None if getuid is None else getuid()


def _shared() -> Any:
    """The transport guards from `notify_hook`, which ships beside this file.

    Imported rather than copied so the loopback check, the proxy suppression and
    the redirect refusal have one implementation. Returns None if it cannot be
    reached, and the caller then does nothing at all.
    """
    with contextlib.suppress(Exception):
        here = os.path.dirname(os.path.abspath(__file__))
        if here not in sys.path:
            sys.path.insert(0, here)
        import notify_hook  # noqa: PLC0415 — resolved relative to this file at runtime

        return notify_hook
    return None


def default_home() -> str:
    return os.path.join(os.path.expanduser("~"), ".compass")


def state_home() -> str:
    env = os.environ
    override = env.get("COMPASS_HOME")
    return override if override and override.strip() else default_home()


def state_file(port: int) -> str:
    """Where the serving process published this run's capability."""
    return os.path.join(state_home(), f"compass-{port}.json")


def capability(port: int, harness: str, *, irreversible: bool = False) -> str | None:
    """This run's token for `harness`, or None if there is nothing to read.

    None is an ordinary answer: no dashboard running, an older dashboard that
    publishes no capabilities, or one started with --no-events. In every case
    this adapter simply does not post, which costs the agent one file read.
    """
    try:
        with open(state_file(port), "rb") as handle:
            data = json.loads(handle.read(65_536) or b"null")
    except (OSError, ValueError, RecursionError):
        return None
    if not isinstance(data, dict):
        return None
    if irreversible and data.get("irreversible_enabled") is not True:
        return None
    tokens = data.get("capabilities")
    if not isinstance(tokens, dict):
        return None
    token = tokens.get(harness)
    return token if isinstance(token, str) and token else None


PLAIN_CHARS = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_./:@%+=,-")
COMMAND_LIMIT = 4096
MATCH_WAIT_SEC = 0.005


def _plain(token: str) -> bool:
    return bool(token) and all(char in PLAIN_CHARS for char in token)


def _sql_shape(command: str) -> str | None:
    quote = "'" if "'" in command else '"'
    parts = command.split(quote)
    if len(parts) != 3 or parts[2].strip():
        return None
    client = parts[0].split()
    admitted = client in (["psql", "-c"], ["mysql", "-e"]) or (
        len(client) == 2
        and client[0] == "sqlite3"
        and _plain(client[1])
        and not client[1].startswith("-")
    )
    if not admitted:
        return None
    sql = parts[1].strip().removesuffix(";").split()
    if len(sql) == 5 and [word.upper() for word in sql[2:4]] == ["IF", "EXISTS"]:
        sql = sql[:2] + sql[4:]
    if len(sql) != 3 or [word.upper() for word in sql[:2]] != ["DROP", "TABLE"]:
        return None
    identifiers = sql[2].split(".")
    if all(word.isascii() and word.isidentifier() for word in identifiers):
        return "sql_drop_table"
    return None


def _recursive_shape(tokens: list[str]) -> str | None:
    flags = {"-r", "-R", "-rf", "-fr", "-Rf", "-fR"}
    if len(tokens) < 3 or tokens[1] not in flags:
        return None
    paths = tokens[2:]
    if paths and paths[0] == "-f":
        paths = paths[1:]
    if paths and paths[0] == "--":
        paths = paths[1:]
    if not paths or any(path.startswith("-") or ".." in path.split("/") for path in paths):
        return None
    prefixes = ("/tmp/", "/private/tmp/", "/var/tmp/")  # noqa: S108 — lexical exclusions only
    if any(not path.startswith(prefixes) for path in paths):
        return "recursive_delete"
    return None


def _plain_shape(tokens: list[str]) -> str | None:
    if tokens[:2] == ["git", "push"]:
        flags = {"--force", "-f", "--force-with-lease"}
        args = tokens[2:]
        if any(arg in flags for arg in args) and all(
            not arg.startswith("-") or arg in flags for arg in args
        ):
            return "git_force_push"
    if (
        tokens[:3] == ["git", "reset", "--hard"]
        and len(tokens) in (3, 4)
        and (len(tokens) == 3 or not tokens[3].startswith("-"))
    ):
        return "git_hard_reset"
    if tokens[0] == "rm":
        return _recursive_shape(tokens)
    return None


def command_shape(command: str) -> str | None:
    """The lexical table in SECURITY.md; no shell interpretation is performed."""
    if (
        len(command) > COMMAND_LIMIT
        or any(char in command for char in "\\$`&|<>!#")
        or any(char.isspace() and char not in " \t" for char in command)
    ):
        return None
    tokens = command.split()
    if not tokens or len(tokens) > 64:
        return None
    command = command.strip()
    if tokens[0] == "rtk":
        command = command[3:].lstrip()
        if command.startswith(("proxy ", "proxy\t")):
            command = command[5:].lstrip()
        elif command.startswith(("bypass ", "bypass\t")):
            command = command[6:].lstrip()
        tokens = command.split()
    if "'" in command or '"' in command:
        return _sql_shape(command)
    if not tokens or not all(_plain(token) for token in tokens):
        return None
    return _plain_shape(tokens)


def irreversible_report(payload: dict[str, Any], harness: str) -> dict[str, Any] | None:
    """Reduce one measured after-tool payload, discarding any late result.

    The daemon thread is intentional: an executor joins at interpreter exit.
    A 5 ms join is best effort, not a hard deadline for scheduling or native work;
    the fixed worker contains no I/O, regex or configurable callback.
    """
    if (
        harness not in {"claude", "codex"}
        or payload.get("hook_event_name") != "PostToolUse"
        or payload.get("tool_name") != "Bash"
    ):
        return None
    tool_input = payload.get("tool_input")
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    sid = payload.get("session_id")
    if (
        not isinstance(command, str)
        or len(command) > COMMAND_LIMIT
        or not isinstance(sid, str)
        or not sid.strip()
        or len(sid) > 200
    ):
        return None
    result: list[str | None] = []

    def match() -> None:
        with contextlib.suppress(Exception):
            result.append(command_shape(command))

    started = time.monotonic()
    worker = threading.Thread(target=match, daemon=True)
    worker.start()
    worker.join(MATCH_WAIT_SEC)
    if (
        worker.is_alive()
        or time.monotonic() - started > MATCH_WAIT_SEC
        or not result
        or result[0] is None
    ):
        return None
    return {
        "v": ENVELOPE_VERSION,
        "event": "command_shape_reported",
        "session_id": sid.strip(),
        "timestamp": datetime.now(UTC).isoformat(),
        "pattern_id": result[0],
        "tool_name": "Bash",
    }


def envelope(
    payload: dict[str, Any],
    harness: str = "claude",
    *,
    environ: Any = None,
    uid: Any = _UNSET,
) -> dict[str, Any] | None:
    """Build the allowlisted envelope, or None if this hook is not forwarded.

    Built field by field from an allowlist rather than by deleting known-bad keys
    from a copy. A native payload that grows a field would otherwise start
    carrying it, and the field most likely to be added to an agent hook is the
    one carrying the user's text. Codex's payloads carry `prompt`, `tool_input`,
    `tool_response` and `last_assistant_message`, all of which this drops.
    """
    names = EVENTS_BY_HARNESS.get(harness)
    if names is None:
        return None
    native = payload.get("hook_event_name")
    name = names.get(native) if isinstance(native, str) else None
    if name is None:
        return None
    session_id = payload.get("session_id")
    if not isinstance(session_id, str) or not session_id.strip():
        return None
    event: dict[str, Any] = {
        "v": ENVELOPE_VERSION,
        "event": name,
        "session_id": session_id.strip(),
    }
    for source, field in (
        ("cwd", "cwd"),
        ("transcript_path", "transcript_path"),
        ("agent_id", "subagent_id"),
    ):
        value = payload.get(source)
        if isinstance(value, str) and value.strip():
            event[field] = value.strip()
    if name == IDENTITY_EVENT:
        event.update(
            tmux_identity(
                os.environ if environ is None else environ,
                process_uid() if uid is _UNSET else uid,
            )
        )
    return event


def read_event(raw: bytes, harness: str = "claude") -> dict[str, Any] | None:
    """Parse stdin into an envelope, or None if there is nothing to forward."""
    try:
        payload = json.loads(raw or b"{}")
    except (ValueError, RecursionError):
        # RecursionError as well as ValueError: deeply nested JSON blows the
        # decoder's stack, and an escaping exception is the one thing this script
        # promises never to do.
        return None
    if not isinstance(payload, dict):
        return None
    return envelope(payload, harness)


def main(argv: list[str]) -> int:
    # An unknown harness needs no check here: `envelope` has no table for it and
    # returns None, so the guard below already covers it. A second check would be
    # a branch no test could distinguish from its absence.
    harness = argv[1] if len(argv) > 1 else "claude"
    port = DEFAULT_PORT
    if len(argv) > 2:
        with contextlib.suppress(ValueError):
            port = int(argv[2])
    try:
        raw = sys.stdin.buffer.read(MAX_PAYLOAD_BYTES)
    except (OSError, ValueError, AttributeError):
        return 0  # no stdin: run interactively, or a harness that closes it
    # Checked in order, cheapest first: parse before reading a file, and read the
    # file before importing anything. Doing nothing is the common case, because
    # most sessions run with no dashboard listening at all.
    event = read_event(raw, harness)
    if event is None:
        return 0
    token = capability(port, harness)
    if token is None:
        return 0
    shared = _shared()
    if shared is None:
        return 0
    # Last-resort guard, as in notify_hook: forward() handles every failure it
    # expects, and this catches the ones it does not, because a raising hook
    # surfaces as an error inside the very session it is reporting on.
    with contextlib.suppress(Exception):
        shared.forward(
            f"http://127.0.0.1:{port}/api/events/{harness}",
            json.dumps(event, separators=(",", ":")).encode(),
            headers={"X-Compass-Capability": token},
        )
    with contextlib.suppress(Exception):
        report_token = capability(port, harness, irreversible=True)
        if report_token is not None:
            report = irreversible_report(json.loads(raw), harness)
            if report is not None:
                shared.forward(
                    f"http://127.0.0.1:{port}/api/events/{harness}",
                    json.dumps(report, separators=(",", ":")).encode(),
                    headers={"X-Compass-Capability": report_token},
                )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
