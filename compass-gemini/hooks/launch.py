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
   It never downloads (`--no-python-downloads`), never reads the project or its config
   (`--no-project --no-config`), never executes a `.venv` found in or above the working
   directory, which is the user's project and not ours (`--system`), and is cut off
   after two seconds, because Gemini gives a hook five. If it finds one,
   the script runs there with the payload, arguments and exit status passed through.
3. Otherwise one sentence goes to stderr. A hook exits nonzero only on `SessionStart`,
   so the notice appears once per session; every later event exits 0 silently. The MCP
   server and `server.py` always exit nonzero. Antigravity's hooks have no session-start
   event, so they print only the `{}` it reads from stdout.

`COMPASS_LAUNCH_ASSUME_PYTHON` (for example `3.9.6`) makes the version check believe
that version. It exists for `test_launch.py` and nothing else documents or reads it.
"""

import os
import sys

TYPE_CHECKING = False  # `typing` costs an import at every hook; the checker reads this anyway
if TYPE_CHECKING:
    import subprocess
    from typing import Any, Callable

FLOOR = (3, 12)
SEAM = "COMPASS_LAUNCH_ASSUME_PYTHON"
UV_TIMEOUT_SECONDS = 2
HOOK_SCRIPTS = ("event_hook.py", "agy_hook.py", "notify_hook.py", "statusline_hook.py")
SESSION_START = "SessionStart"
AGY_HOOK = "agy_hook.py"


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
                "--no-config",
                "--system",
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


def wait_for(child: "subprocess.Popen[bytes]", payload: "bytes | None") -> int:
    if payload is None:
        while True:
            try:
                return child.wait()
            except KeyboardInterrupt:  # noqa: PERF203 - waiting is the point
                # Ctrl-C reaches the whole process group; the child is shutting down on
                # its own. subprocess.call would kill it after 0.25 s, so keep waiting.
                continue
    try:
        child.communicate(payload)
    except OSError:  # the child closed stdin early; its exit status still counts
        child.wait()
    return child.returncode


def forward_signals(children: "list[Any]", early: "list[int]") -> "Callable[[], None]":
    """Pass SIGTERM and SIGHUP to the child; return what puts the old handlers back.

    A shell's `exec` leaves one process, so a signal for it reaches the script. This process
    is a second one, so it passes the signal on and lets the child decide. One that lands
    before the child exists waits in `early` for the caller to deliver.

    Windows has no signal to forward: SIGTERM there is a hard kill of this process, so no
    handler could run, and a console Ctrl-C already reaches the child by itself.
    """
    if os.name != "posix":
        return lambda: None
    import signal

    def forward(number: int, _frame: object) -> None:
        if children:
            children[0].send_signal(number)
        else:
            early.append(number)

    numbers = [getattr(signal, name) for name in ("SIGTERM", "SIGHUP") if hasattr(signal, name)]
    previous = [(number, signal.signal(number, forward)) for number in numbers]

    def restore() -> None:
        for number, handler in previous:
            signal.signal(number, handler)

    return restore


def exit_like(status: int) -> int:
    """If the child died of a signal, die of it too, so the caller sees what `exec` would show."""
    if status < 0 and os.name == "posix":
        import contextlib
        import signal

        # SIGKILL's handler cannot be set; the kill still works
        with contextlib.suppress(OSError, ValueError):
            signal.signal(-status, signal.SIG_DFL)
        os.kill(os.getpid(), -status)
        return 128 - status  # still here: the signal was blocked or ignored
    return status


def run_elsewhere(
    interpreter: str, target: str, args: "list[str]", payload: "bytes | None"
) -> "int | None":
    import subprocess

    children: list[Any] = []
    early: list[int] = []
    restore = forward_signals(children, early)
    try:
        command = [interpreter, target, *args]
        try:
            child = subprocess.Popen(command, stdin=None if payload is None else subprocess.PIPE)
        except OSError:
            return None
        children.append(child)
        for number in early:
            child.send_signal(number)
        status = wait_for(child, payload)
    finally:
        restore()
    return exit_like(status)


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
        if os.path.basename(target) == AGY_HOOK:
            sys.stdout.write("{}\n")  # Antigravity reads stdout JSON; see SECURITY.md
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
    try:
        with open(target, "rb") as handle:
            code = compile(handle.read(), target, "exec")
    except OSError as error:
        if os.path.basename(target) == AGY_HOOK:
            sys.stdout.write("{}\n")
        sys.stderr.write(f"launch.py: can't open {target!r}: {error.strerror}\n")
        return 2
    sys.path.insert(0, os.path.dirname(os.path.abspath(target)))
    sys.argv = [target, *args]
    # A real `__main__` module, as `python target` has: dataclasses, typing.get_type_hints and
    # pickle look the running module up in sys.modules by name, and find launch.py otherwise.
    import types

    main_module = types.ModuleType("__main__")
    main_module.__file__ = os.path.abspath(target)
    sys.modules["__main__"] = main_module
    exec(code, main_module.__dict__)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
