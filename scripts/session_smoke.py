#!/usr/bin/env python3
"""Type a Compass skill action into a real headless Claude Code session and print what happened.

Starts a review dashboard from a tree on a spare port, creates a headless Claude Code session in a
scratch project with a real first prompt, then types each requested `/compass:compass <action>`
into it and prints the permission denials, the tool commands and the tool results. The board, the
session and its hooks share a scratch Compass home. Stops the board it started, and kills each
command's process group, on every exit path it can catch.

    python3 scripts/session_smoke.py --tree . sessions "sessions waiting"

A defect only a real session shows passed about 9,000 tests and 19 review agents on 2026-11-06,
because every fixture agreed with itself; this recipe found both in minutes. The burndown
delivery stage says when to run it.
"""

from __future__ import annotations

import argparse
import contextlib
import dataclasses
import http.client
import importlib
import json
import os
import re
import shlex
import signal
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import IO, TYPE_CHECKING, Any, NoReturn

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence
    from types import FrameType

OWNER_PORT = 4553
DEFAULT_PORT = 4795
DEFAULT_TASK = "Write a three-line poem about a lighthouse keeper."
# The argument lists after `server.py` that read and never press a reading. Anything else counts as
# spending until it is listed here, so a new action fails closed rather than spending by default.
FREE_ARGUMENTS = frozenset({("--sessions",), ("--sessions", "waiting"), ("--monitor", "--off")})
_TABLE_ROW = re.compile(r"\|\s*`([^`]+)`\s*\|\s*`([^`]+)`\s*\|")
SKILL_DIR = Path("compass/skills/compass")


@dataclasses.dataclass(frozen=True)
class Completed:
    returncode: int
    stdout: str
    stderr: str


@dataclasses.dataclass(frozen=True)
class Deps:
    run: Callable[[Sequence[str], Path | None, float, Mapping[str, str]], Completed]
    probe: Callable[[int], bool]
    newest: Callable[[Path, str], int | None]
    warm: Callable[[int, float], bool]
    sleep: Callable[[float], None]
    out: IO[str]
    err: IO[str]


class SmokeError(Exception):
    """A step failed; the message says which, and the board is still stopped."""


def parse_actions(skill_text: str) -> dict[str, str]:
    """The action table under `## Terminal actions` in the shipped skill body: action to command.

    Empty when the heading is missing, so every action is refused rather than any table row
    elsewhere in the body being read as one.
    """
    if "## Terminal actions" not in skill_text:
        return {}
    section = skill_text.split("## Terminal actions", 1)[1].split("\n## ", 1)[0]
    return {m.group(1): m.group(2) for m in _TABLE_ROW.finditer(section)}


def spends(command: str) -> bool:
    words = shlex.split(command)
    server = next((i for i, word in enumerate(words) if word.endswith("server.py")), None)
    return server is None or tuple(words[server + 1 :]) not in FREE_ARGUMENTS


def task_refusal(task: str) -> str | None:
    """Why the first prompt cannot be sent, or None. It is typed as the person's own prompt.

    A skill command there would skip the action admission: typed first, `drift` passes Compass's
    own typed-press check, and a bare `/compass:compass` opens a dashboard on the owner's port.
    """
    if task.lstrip().startswith("/") or "compass" in task.casefold():
        return "--task must be an ordinary first prompt, not a slash command or one naming Compass"
    return None


def admission(actions: Sequence[str], table: dict[str, str], *, allow_spend: bool) -> list[str]:
    refusals = []
    for action in actions:
        if action not in table:
            # The skill falls through to `## Start` for a word it does not list, which opens a
            # dashboard, and it opens it on the owner's port.
            refusals.append(f"`{action}` is not an action the skill's table lists")
        elif spends(table[action]) and not allow_spend:
            # Plain `drift` presses too: a session this helper just created has no stored reading.
            refusals.append(f"`{action}` can press a paid reading; pass --allow-spend to spend it")
    return refusals


def _kill_group(pid: int) -> None:
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(pid, signal.SIGKILL)


def child_env(home: str) -> dict[str, str]:
    env = dict(os.environ)
    # Set inside a Claude Code session; a nested `claude` reads it as a refusal to start.
    env.pop("CLAUDECODE", None)
    # One scratch home for the board, the session's hooks and its commands. With the real one, the
    # hooks post this session to the owner's board on 4553, and every other session's terminal
    # client asks the spare board, because it is the newest-started one there.
    env["COMPASS_HOME"] = home
    return env


def run_command(
    argv: Sequence[str], cwd: Path | None, timeout: float, env: Mapping[str, str]
) -> Completed:
    """Run one command in its own process group, and kill the group however the command ends.

    Standard input is closed because a headless harness waits on an open one (codex measurably
    does). Output goes to files rather than pipes and the wait is on the process, because a child
    left behind holding a pipe would hold the read open, and the group is killed after a clean exit
    too, because a spawned session's hooks and servers have outlived it here before.
    """
    with tempfile.TemporaryFile("w+") as stdout, tempfile.TemporaryFile("w+") as stderr:
        process = subprocess.Popen(  # noqa: S603 - argv built by this module, no shell
            list(argv),
            cwd=cwd,
            env=dict(env),
            stdin=subprocess.DEVNULL,
            stdout=stdout,
            stderr=stderr,
            text=True,
            start_new_session=os.name != "nt",
        )
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            msg = f"{argv[0]} ran past {timeout:g} s"
            raise TimeoutError(msg) from None
        finally:
            if os.name != "nt":
                _kill_group(process.pid)
            if process.poll() is None:
                process.kill()
                process.wait()
        stdout.seek(0)
        stderr.seek(0)
        return Completed(process.returncode, stdout.read(), stderr.read())


def probe_board(port: int) -> bool:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=0.5)
    try:
        connection.request("GET", "/api/health")
        response = connection.getresponse()
        data = json.loads(response.read(4096)) if response.status == 200 else None
    except (OSError, http.client.HTTPException, ValueError):
        return False
    finally:
        connection.close()
    return isinstance(data, dict) and data.get("ok") is True and data.get("port") == port


def warm_board(port: int, timeout: float) -> bool:
    """Read `/api/data` once, so the board's first collection is done before a session asks."""
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    try:
        connection.request("GET", "/api/data")
        response = connection.getresponse()
        response.read()
    except (OSError, http.client.HTTPException):
        return False
    finally:
        connection.close()
    return response.status == 200


def newest_board(tree: Path, home: str) -> int | None:
    """The port the tree's own terminal client would ask from `home`: the newest-started board."""
    sys.path.insert(0, str(tree / SKILL_DIR))
    try:
        client: Any = importlib.import_module("compass_runtime.terminal_client")
    finally:
        sys.path.pop(0)
    found = client.find_dashboard(client.state_home({"COMPASS_HOME": home}))
    return None if found is None else int(found.port)


def real_deps() -> Deps:
    return Deps(run_command, probe_board, newest_board, warm_board, _sleep, sys.stdout, sys.stderr)


def _sleep(seconds: float) -> None:
    import time  # noqa: PLC0415 - kept out of the injected surface

    time.sleep(seconds)


def _claude(args: argparse.Namespace, prompt: str, *rest: str) -> list[str]:
    return [
        args.claude,
        "-p",
        prompt,
        "--plugin-dir",
        str(args.tree / "compass"),
        "--setting-sources",
        "local",
        "--model",
        args.model,
        *rest,
    ]


def _text(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(str(part.get("text", "")) for part in content if isinstance(part, dict))
    return json.dumps(content)


def _tool_lines(event: dict[str, Any]) -> list[str]:
    """The tool calls and results one stream-json event carries, one printable entry each."""
    message = event.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    lines = []
    for part in content if isinstance(content, list) else []:
        if not isinstance(part, dict):
            continue
        if part.get("type") == "tool_use":
            tool_input = part.get("input")
            command = tool_input.get("command") if isinstance(tool_input, dict) else None
            lines.append(f"tool {part.get('name')}: {command or json.dumps(tool_input)}")
        elif part.get("type") == "tool_result":
            state = "error" if part.get("is_error") else "ok"
            lines.append(f"result ({state}):\n{_text(part.get('content'))}")
    return lines


def _events(stdout: str) -> list[dict[str, Any]]:
    events = []
    for line in stdout.splitlines():
        with contextlib.suppress(ValueError):
            event = json.loads(line)
            if isinstance(event, dict):
                events.append(event)
    return events


def report_action(action: str, done: Completed, out: IO[str]) -> bool:
    """Print one action's tool calls, results and denials. True when it ran with none denied."""
    out.write(f"\n== /compass:compass {action}\nexit: {done.returncode}\n")
    events = _events(done.stdout)
    for event in events:
        for line in _tool_lines(event):
            out.write(f"{line}\n")
    result = next((e for e in reversed(events) if e.get("type") == "result"), {})
    denials = [d for d in result.get("permission_denials") or [] if isinstance(d, dict)]
    out.write(f"permission_denials: {len(denials) or 'none'}\n")
    for denial in denials:
        tool_input = denial.get("tool_input")
        command = tool_input.get("command") if isinstance(tool_input, dict) else tool_input
        out.write(f"denied {denial.get('tool_name')}: {command}\n")
    if "result" in result:
        out.write(f"reply:\n{result['result']}\n")
    if done.returncode != 0:
        out.write(f"stderr:\n{done.stderr}\n")
    return done.returncode == 0 and not denials


def _session(args: argparse.Namespace, project: Path, env: dict[str, str], deps: Deps) -> str:
    first = _claude(args, args.task, "--output-format", "json")
    done = deps.run(first, project, args.timeout, env)
    try:
        session_id = json.loads(done.stdout).get("session_id") if done.returncode == 0 else None
    except (ValueError, AttributeError):
        session_id = None
    if not isinstance(session_id, str) or not session_id:
        msg = f"the first prompt made no session (exit {done.returncode}): {done.stderr.strip()}"
        raise SmokeError(msg)
    return session_id


def _board(args: argparse.Namespace, *flags: str) -> list[str]:
    skill = args.tree / SKILL_DIR
    return [sys.executable, str(skill / "launch.py"), str(skill / "server.py"), *flags]


def _start_board(args: argparse.Namespace, env: dict[str, str], deps: Deps) -> None:
    command = _board(args, "--daemon", "--port", str(args.port))
    done = deps.run(command, args.tree / SKILL_DIR, args.board_timeout, env)
    if done.returncode != 0:
        msg = f"the board did not start on {args.port}: {done.stderr.strip() or done.stdout}"
        raise SmokeError(msg)


def _await_board(args: argparse.Namespace, deps: Deps) -> None:
    for _ in range(int(args.board_timeout * 4)):
        if deps.probe(args.port):
            return
        deps.sleep(0.25)
    msg = f"the board on {args.port} never answered /api/health"
    raise SmokeError(msg)


def _check_newest(args: argparse.Namespace, home: str, deps: Deps) -> None:
    # The skill's commands ask the newest-started board, and the default port's board is always a
    # candidate, so a board started there since the last check would answer instead.
    newest = deps.newest(args.tree, home)
    if newest != args.port:
        msg = f"the terminal client would ask the board on {newest}, not the one on {args.port}"
        raise SmokeError(msg)


def _stop_board(args: argparse.Namespace, env: dict[str, str], deps: Deps) -> bool:
    command = _board(args, "--stop", "--port", str(args.port))
    try:
        done = deps.run(command, args.tree / SKILL_DIR, args.board_timeout, env)
    except (TimeoutError, OSError) as error:
        manual = shlex.join(command)
        deps.err.write(f"failed to stop the board on {args.port} ({error}); run: {manual}\n")
        return False
    deps.out.write(f"\nboard on {args.port} stopped (exit {done.returncode})\n")
    return done.returncode == 0


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("actions", nargs="+", metavar="ACTION", help='e.g. sessions "drift"')
    parser.add_argument("--tree", type=Path, default=Path(), help="repository tree to test")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="spare board port")
    parser.add_argument("--task", default=DEFAULT_TASK, help="the session's real first prompt")
    parser.add_argument("--model", default="sonnet")
    parser.add_argument("--claude", default="claude", help="the claude executable")
    parser.add_argument("--timeout", type=float, default=300.0, help="seconds per claude call")
    parser.add_argument("--board-timeout", type=float, default=60.0)
    parser.add_argument(
        "--allow-spend", action="store_true", help="permit actions that can press a paid reading"
    )
    args = parser.parse_args(argv)
    args.tree = args.tree.resolve()
    return args


def main(argv: Sequence[str], deps: Deps | None = None) -> int:
    deps = deps or real_deps()
    args = parse_args(argv)
    if args.port == OWNER_PORT or not 1 <= args.port <= 65535:
        deps.err.write(f"refused: port {args.port}; {OWNER_PORT} is the owner's dashboard\n")
        return 2
    skill_md = args.tree / SKILL_DIR / "SKILL.md"
    try:
        table = parse_actions(skill_md.read_text(encoding="utf-8"))
    except OSError as error:
        deps.err.write(f"refused: cannot read {skill_md}: {error}\n")
        return 2
    refusals = admission(args.actions, table, allow_spend=args.allow_spend)
    if (refusal := task_refusal(args.task)) is not None:
        refusals.append(refusal)
    if deps.probe(args.port):
        refusals.append(f"something already answers on {args.port}; pick another --port")
    for refusal in refusals:
        deps.err.write(f"refused: {refusal}\n")
    if refusals:
        return 2

    with tempfile.TemporaryDirectory(
        prefix="compass-smoke-home-", ignore_cleanup_errors=True
    ) as home:
        return _run(args, home, deps)


def _run(args: argparse.Namespace, home: str, deps: Deps) -> int:
    env = child_env(home)
    clean = True
    started = False
    session_id: str | None = None
    monitor_attempted = False
    try:
        _start_board(args, env, deps)
        # Only after the daemon said it started: a failed start may mean a sibling's board holds
        # the port, and `--stop` stops whatever Compass answers there.
        started = True
        _await_board(args, deps)
        # Measured: a cold board's first collection took 5.1 s, past the terminal client's 5 s
        # read limit, so the first `sessions` printed "could not be read"; later reads took 0.8 s.
        if not deps.warm(args.port, args.board_timeout):
            deps.err.write(f"note: the board on {args.port} did not answer /api/data yet\n")
        with tempfile.TemporaryDirectory(prefix="compass-smoke-") as scratch:
            project = Path(scratch)
            _check_newest(args, home, deps)
            session_id = _session(args, project, env, deps)
            deps.out.write(f"board: 127.0.0.1:{args.port}\nsession: {session_id}\n")
            for action in args.actions:
                _check_newest(args, home, deps)
                command = _claude(
                    args,
                    f"/compass:compass {action}",
                    "--resume",
                    session_id,
                    "--output-format",
                    "stream-json",
                    "--verbose",
                )
                monitor_attempted = monitor_attempted or action == "monitor on"
                done = deps.run(command, project, args.timeout, env)
                ran = report_action(action, done, deps.out)
                clean = clean and ran
    except (SmokeError, TimeoutError, OSError) as error:
        deps.err.write(f"failed: {error}\n")
        clean = False
    finally:
        if monitor_attempted and session_id is not None:
            command = _board(args, "--monitor", "--off", "--session", "claude:" + session_id)
            try:
                done = deps.run(command, args.tree / SKILL_DIR, args.board_timeout, env)
                if done.returncode:
                    deps.err.write("failed to stop the detached monitor: " + done.stderr + "\n")
                    clean = False
            except (TimeoutError, OSError) as error:
                deps.err.write(f"failed to stop the detached monitor: {error}\n")
                clean = False
        if started and not _stop_board(args, env, deps):
            clean = False
    return 0 if clean else 1


def _terminate(signum: int, frame: FrameType | None) -> NoReturn:
    del frame
    raise SystemExit(128 + signum)


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, _terminate)
    if os.name != "nt":
        signal.signal(signal.SIGHUP, _terminate)
    sys.exit(main(sys.argv[1:]))
