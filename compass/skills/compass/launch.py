#!/usr/bin/env python3
"""Start a Compass script, or say in one sentence why this Python cannot.

Every hook, the MCP server and the documented `server.py` start run
`python3 launch.py <script> <args...>`. The rest of Compass needs Python 3.12, and an
older `python3` meets that as a traceback inside a hook the person never asked to read.

This file must parse and run on Python 3.6 and newer, so it uses no f-strings with `=`,
no walrus, no `match`, no `from __future__` import, and annotations only as quoted strings
(`"list[str]"` is not valid at definition time on 3.6). Ruff holds it to
that through `per-file-target-version`, and `test_launch.py` parses it as 3.6 and, when
a system `python3` older than 3.12 exists, runs it there.

At or above the floor the script runs in this process, compiled and executed directly. The
imports below the floor sit inside the functions that need them, because `subprocess`, `shutil`
and `json` cost about ten milliseconds per hook that nothing at or above the floor uses. Below it:

1. A hook's payload is read from stdin, because the event decides whether anyone is told.
2. `uv`, if installed, is asked for a Python 3.12 or newer that is already on the machine.
   It never downloads (`--no-python-downloads`), never reads the project (`--no-project`)
   and is cut off after two seconds, because Gemini gives a hook five. If it finds one,
   the script runs there with the payload, arguments and exit status passed through.
3. Otherwise one sentence goes to stderr. A hook exits nonzero only on `SessionStart`,
   so the notice appears once per session; every later event exits 0 silently. The MCP
   server and `server.py` always exit nonzero. Antigravity's hooks have no session-start
   event, so they stay silent.

`COMPASS_LAUNCH_ASSUME_PYTHON` (for example `3.9.6`) makes the version check believe
that version. It exists for `test_launch.py` and nothing else documents or reads it.
"""

import os
import sys

FLOOR = (3, 12)
SEAM = "COMPASS_LAUNCH_ASSUME_PYTHON"
UV_TIMEOUT_SECONDS = 2
HOOK_SCRIPTS = ("event_hook.py", "agy_hook.py", "notify_hook.py", "statusline_hook.py")
SESSION_START = "SessionStart"


def running_version() -> "tuple[tuple[int, ...], str]":
    assumed = os.environ.get(SEAM)
    if assumed:
        parts = [int(part) for part in assumed.split(".") if part.isdigit()]
        return tuple(parts), assumed
    major, minor, micro = sys.version_info[:3]
    return (major, minor, micro), f"{major}.{minor}.{micro}"


def sentence(version_text: str) -> str:
    floor = f"{FLOOR[0]}.{FLOOR[1]}"
    return (
        f"Compass needs Python {floor} or newer; python3 here is {version_text} "
        f"({sys.executable}). Install Python {floor} or newer, "
        f"or run `uv python install {floor}`."
    )


def find_new_python() -> "str | None":
    import shutil
    import subprocess

    uv = shutil.which("uv")
    if not uv:
        return None
    try:
        done = subprocess.run(
            [
                uv,
                "python",
                "find",
                f">={FLOOR[0]}.{FLOOR[1]}",
                "--no-python-downloads",
                "--no-project",
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=UV_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if done.returncode != 0:
        return None
    lines = done.stdout.decode("utf-8", "replace").strip().splitlines()
    found = lines[-1].strip() if lines else ""
    return found if found and os.path.isfile(found) else None


def starts_a_session(payload: bytes) -> bool:
    import json

    try:
        event = json.loads(payload.decode("utf-8")).get("hook_event_name")
    except (ValueError, AttributeError):
        return False
    return event == SESSION_START


def run_elsewhere(
    interpreter: str, target: str, args: "list[str]", payload: "bytes | None"
) -> "int | None":
    import subprocess

    command = [interpreter, target, *args]
    try:
        if payload is None:
            return subprocess.call(command)
        child = subprocess.Popen(command, stdin=subprocess.PIPE)
    except OSError:
        return None
    try:
        child.communicate(payload)
    except OSError:  # the child closed stdin early; its exit status still counts
        child.wait()
    return child.returncode


def below_floor(target: str, args: "list[str]", version_text: str) -> int:
    is_hook = os.path.basename(target) in HOOK_SCRIPTS
    payload: bytes | None = None
    if is_hook:
        try:
            payload = sys.stdin.buffer.read()
        except (OSError, ValueError, AttributeError):
            payload = b""
    interpreter = find_new_python()
    if interpreter:
        status = run_elsewhere(interpreter, target, args, payload)
        if status is not None:
            return status
    if is_hook and not (
        os.path.basename(target) == "event_hook.py" and starts_a_session(payload or b"")
    ):
        return 0
    sys.stderr.write(sentence(version_text) + "\n")
    return 1


def main(argv: "list[str]") -> int:
    if len(argv) < 2:
        sys.stderr.write("usage: launch.py <script> [args...]\n")
        return 2
    target, args = argv[1], argv[2:]
    version, version_text = running_version()
    if version < FLOOR:
        return below_floor(target, args, version_text)
    sys.path.insert(0, os.path.dirname(os.path.abspath(target)))
    sys.argv = [target, *args]
    with open(target, "rb") as handle:
        code = compile(handle.read(), target, "exec")
    exec(code, {"__name__": "__main__", "__file__": target})
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
