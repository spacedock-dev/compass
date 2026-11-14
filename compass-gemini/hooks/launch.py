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
2. `uv`, if installed on a rooted PATH element, is asked for a Python 3.12 or newer that is
   already on the machine, searching only those elements. It never downloads
   (`--no-python-downloads`), never reads the project or its config
   (`--no-project --no-config`), never executes a `.venv` found in or above the working
   directory, which is the user's project and not ours (`--system`), and is cut off
   after two seconds, because Gemini gives a hook five. If it finds one,
   the script runs there with the payload, arguments and exit status passed through.
3. Otherwise one sentence goes to stderr. A hook exits nonzero only on `SessionStart`,
   so the notice appears once per session; every later event exits 0 silently. The MCP
   server and `server.py` always exit nonzero. Antigravity's hooks have no session-start
   event, so they print only the `{}` it reads from stdout.

A hook whose script cannot be opened exits 0 having printed only what its harness reads as
nothing (`{}` for Antigravity's hook, an empty line for its status line), at any version. Claude
Code, Codex, Gemini CLI and Droid read a hook's exit 2 as a decision to block the prompt or tool
call, and a plugin upgraded or removed mid-session leaves them running hooks whose files are gone.

`COMPASS_LAUNCH_ASSUME_PYTHON` (for example `3.9`, a major and a minor and nothing else) makes the
version check believe that version; any other value is ignored. It exists for `test_launch.py`
and nothing else documents or reads it.
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
# What each hook prints when it has nothing to say. Antigravity reads its hook's stdout as JSON,
# and a status-line command that prints nothing blanks the status bar. The others print nothing on
# every ordinary event, and Codex's empty output was measured as an abstain
# (`docs/captures/codex/permission-abstain-0.149.0-macos.jsonl`).
EMPTY_OUTPUT = {AGY_HOOK: "{}\n", "statusline_hook.py": "\n"}
# Every hook reads at most 1 MiB of its payload, so one byte more says the payload is longer than
# any hook would act on, and the launcher need hold no more than that below the floor.
PAYLOAD_CAP = (1 << 20) + 1


def assumed_version(value: str) -> "tuple[int, int] | None":
    """Major and minor, ASCII digits only, without importing `re` at every hook.

    `str.isdigit` is not that test: it accepts a superscript two, which `int` then refuses.
    """
    parts = value.split(".")
    if len(parts) != 2 or not all(part and all(c in "0123456789" for c in part) for part in parts):
        return None
    return int(parts[0]), int(parts[1])


def running_version() -> "tuple[tuple[int, ...], str]":
    assumed = assumed_version(os.environ.get(SEAM) or "")
    if assumed is not None:
        return assumed, "{}.{}".format(*assumed)
    major, minor, micro = sys.version_info[:3]
    return (major, minor, micro), f"{major}.{minor}.{micro}"


def sentence(version_text: str) -> str:
    floor = f"{FLOOR[0]}.{FLOOR[1]}"
    return (
        f"Compass needs Python {floor} or newer; python3 here is {version_text} "
        f"({sys.executable}). Install Python {floor} or newer, "
        f"or run `uv python install {floor}`."
    )


# `compass_runtime.rooted_path`'s rule, restated: this file must parse on 3.6 and runs before the
# version check, so it cannot import that package. `test_launch.LauncherRootedRuleTest` holds the
# two to the same answers.
def rooted(part: str) -> bool:
    if not os.path.isabs(part):
        return False
    # A driveless root resolves against the current drive, part of the working directory.
    return os.name != "nt" or bool(os.path.splitdrive(part)[0])


def search_path(path: str) -> str:
    return os.pathsep.join(part for part in path.split(os.pathsep) if rooted(part))


def find_new_python() -> "str | None":
    """A Python at or above the floor that uv already has, found only on rooted PATH elements.

    A hook's working directory is inside the watched repository, so a relative, empty or `.`
    PATH element would let it supply `uv`, or the interpreter `uv python find` reports.
    """
    import shutil
    import subprocess

    path = os.environ.get("PATH")
    search = search_path(os.defpath if path is None else path)
    uv = shutil.which("uv", path=search) if search else None
    # Windows `which` searches the current directory first before 3.12 whatever PATH it is
    # handed, and answers `.\uv.exe` from there; the answer is held to the rule too.
    if not uv or not rooted(uv):
        return None
    env = dict(os.environ)
    env["PATH"] = search
    env["NoDefaultCurrentDirectoryInExePath"] = "1"
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
            env=env,
            timeout=UV_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if done.returncode != 0:
        return None
    lines = done.stdout.decode("utf-8", "replace").strip().splitlines()
    found = lines[-1].strip() if lines else ""
    return found if found and rooted(found) and os.path.isfile(found) else None


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


def abstain(target: str) -> int:
    """A hook's no-op: what its harness reads as nothing, and exit 0."""
    sys.stdout.write(EMPTY_OUTPUT.get(os.path.basename(target), ""))
    return 0


def below_floor(target: str, args: "list[str]", version_text: str) -> int:
    is_hook = os.path.basename(target) in HOOK_SCRIPTS
    payload: bytes | None = None
    if is_hook:
        if not (os.path.isfile(target) and os.access(target, os.R_OK)):
            return abstain(target)
        try:
            payload = sys.stdin.buffer.read(PAYLOAD_CAP)
        except (OSError, ValueError, AttributeError):
            payload = b""
        if len(payload) >= PAYLOAD_CAP:
            return abstain(target)
    interpreter = find_new_python()
    if interpreter:
        status = run_elsewhere(interpreter, target, args, payload)
        if status is not None:
            return status
    if is_hook and not (
        os.path.basename(target) == "event_hook.py" and starts_a_session(payload or b"")
    ):
        return abstain(target)  # Antigravity reads stdout JSON; see SECURITY.md
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
        if os.path.basename(target) in HOOK_SCRIPTS:
            return abstain(target)
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
