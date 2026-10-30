#!/usr/bin/env python3
"""Record what one owned process tree launches and connects to, from inside it. Not shipped.

    COMPASS_OBSERVE_LOG=trace.jsonl owned_observer.py exec -- server.py --port 4599

`exec` installs a Python audit hook in this interpreter and then runs the named script as
`__main__`, so the hook sits inside the Compass server for its whole life. Every program the
server starts inherits `NODE_OPTIONS` and `BUN_OPTIONS` naming `owned_observer_preload.js`,
which records the same events from inside each Node or Bun child and passes itself on to theirs.
Both write one JSON line per event, synchronously, to the one log, before the call they record
runs, so an event a sampler would miss between two ticks is still a line.

Nothing here is reachable from the shipped plugin. The server only carries the hook when it is
started through `exec` with `COMPASS_OBSERVE_LOG` set: `exec` refuses without the variable,
and `server.py` started the ordinary way never reads it. What the trace sees, what it cannot
see and why it is confined to the owned ancestry are in
docs/design-owned-process-observer.md.
"""

from __future__ import annotations

import json
import os
import runpy
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

ENV_LOG = "COMPASS_OBSERVE_LOG"
PRELOAD = Path(__file__).resolve().with_name("owned_observer_preload.js")
# An argument longer than this, or holding a newline, is recorded as its length only: a model
# call's system prompt is an argument, and its words do not belong in a trace.
MAX_ARG = 64

_state: dict[str, Any] = {}
_local = threading.local()


def redact(value: object) -> str:
    """An argument as it may appear in the trace."""
    text = os.fsdecode(value) if isinstance(value, (bytes, os.PathLike)) else str(value)
    return f"<{len(text)} chars>" if len(text) > MAX_ARG or "\n" in text else text


def _argv(args: object) -> list[str]:
    if isinstance(args, (str, bytes, os.PathLike)):
        return [redact(args)]
    if isinstance(args, (list, tuple)):
        return [redact(arg) for arg in args]
    return []


def _program(path: object) -> str:
    if path is None:
        return ""
    return os.path.basename(
        os.fsdecode(path) if isinstance(path, (bytes, os.PathLike)) else str(path)
    )


def _carries_hook(env: object) -> bool:
    """Whether a child started with `env` inherits the preload: None means this process's own."""
    if env is None:
        return True
    for key in (ENV_LOG, os.fsencode(ENV_LOG)):
        try:
            if env[key]:  # type: ignore[index]
                return True
        except (KeyError, TypeError):
            continue
    return False


def emit(kind: str, op: str, **fields: object) -> None:
    """Append one event line. Never raises into the code being watched."""
    fd = _state.get("fd")
    if fd is None:
        return
    record = {
        "t": time.time(),
        "src": "python",
        "pid": os.getpid(),
        "ppid": os.getppid(),
        "tid": threading.get_ident(),
    }
    record.update(kind=kind, op=op, **fields)
    line = (json.dumps(record, default=str) + "\n").encode()
    lock: threading.Lock = _state["lock"]
    try:
        with lock:
            os.write(fd, line)
    except OSError:
        pass


def _address(address: object) -> dict[str, object]:
    if isinstance(address, tuple) and len(address) >= 2:
        return {"family": "inet", "host": str(address[0]), "port": int(address[1])}
    if isinstance(address, (str, bytes)):
        return {"family": "unix", "path": redact(address)}
    return {"family": "other", "address": redact(address)}


def _launch(op: str, path: object, args: object, env: object) -> None:
    argv = _argv(args)
    emit(
        "launch",
        op,
        program=_program(path) or (argv[0] if argv else ""),
        argv=argv,
        hooked=_carries_hook(env),
    )


def _hook(event: str, args: tuple[Any, ...]) -> None:  # noqa: C901, PLR0912 - one branch per audited event
    if getattr(_local, "busy", False):
        return
    _local.busy = True
    try:
        if event == "subprocess.Popen":
            executable, argv, _cwd, env = args
            _launch(
                event,
                executable or (argv[0] if isinstance(argv, (list, tuple)) and argv else argv),
                argv,
                env,
            )
        elif event in {"os.posix_spawn", "os.exec"}:
            if not getattr(_local, "in_popen", False):
                _launch(event, args[0], args[1], args[2])
        elif event == "os.spawn":
            _launch(event, args[1], args[2], args[3])
        elif event == "os.system":
            _launch(event, "sh", ["sh", "-c", args[0]], None)
        elif event == "os.fork":
            emit("fork", event)
        elif event == "socket.connect":
            emit("connect", event, **_address(args[1]))
        elif event == "socket.sendto":
            emit("send", event, **_address(args[1]))
        elif event == "socket.getaddrinfo":
            emit("resolve", event, host=str(args[0]), port=args[1])
        elif event in {"socket.gethostbyname", "socket.gethostbyname_ex", "socket.gethostbyaddr"}:
            emit("resolve", event, host=str(args[0]))
        elif event == "http.client.connect":
            emit("request", event, host=str(args[1]), port=args[2])
        elif event == "urllib.Request":
            from urllib.parse import urlsplit  # noqa: PLC0415 - only when a request is made

            url = urlsplit(str(args[0]))
            default = 443 if url.scheme == "https" else 80
            emit(
                "request",
                event,
                scheme=url.scheme,
                host=url.hostname or "",
                port=url.port or default,
            )
    except Exception:  # noqa: BLE001, S110 - the trace never changes what the server does
        pass
    finally:
        _local.busy = False


def _wrap_popen() -> None:
    """Record each started child's pid, and its exit, so a launch has a duration."""
    popen = subprocess.Popen
    original_init: Callable[..., None] = popen.__init__
    original_exit: Callable[..., Any] | None = getattr(popen, "_handle_exitstatus", None)

    def init(self: subprocess.Popen[Any], *args: Any, **kwargs: Any) -> None:
        _local.in_popen = True
        try:
            original_init(self, *args, **kwargs)
        finally:
            _local.in_popen = False
        args_: Any = self.args
        first = args_ if isinstance(args_, (str, bytes, os.PathLike)) else args_[0]
        emit("spawned", "subprocess.Popen", child=self.pid, program=_program(first))

    def handle_exit(self: subprocess.Popen[Any], *args: Any, **kwargs: Any) -> Any:
        assert original_exit is not None  # noqa: S101 - only installed when present
        result = original_exit(self, *args, **kwargs)
        if self.returncode is not None and not getattr(self, "_observed_exit", False):
            self._observed_exit = True  # type: ignore[attr-defined]
            emit("exit", "subprocess.Popen", child=self.pid, code=self.returncode)
        return result

    popen.__init__ = init  # type: ignore[method-assign]
    if original_exit is not None:
        popen._handle_exitstatus = handle_exit  # type: ignore[attr-defined]  # noqa: SLF001


def install(log_path: str) -> None:
    """Start recording this interpreter's launches and connections to `log_path`. Irreversible."""
    if _state:
        return
    _state["fd"] = os.open(log_path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    _state["lock"] = threading.Lock()
    _wrap_popen()
    sys.addaudithook(_hook)
    emit("start", "process", program=_program(sys.executable))


def install_from_environment(environ: Mapping[str, str]) -> bool:
    """Install only when the environment names a log. False, and nothing installed, otherwise."""
    log_path = environ.get(ENV_LOG, "")
    if not log_path:
        return False
    install(log_path)
    return True


def observed_environment(environ: Mapping[str, str], log_path: str) -> dict[str, str]:
    """`environ` with the trace switched on for this process and every Node or Bun descendant."""
    env = dict(environ)
    env[ENV_LOG] = log_path
    env["NODE_OPTIONS"] = f"{env.get('NODE_OPTIONS', '')} --require={PRELOAD}".strip()
    # Measured on Claude Code 2.1.314, a Bun 1.4.4 executable: it ignores NODE_OPTIONS and loads
    # a preload named here, so without this line the reading model's own calls are invisible.
    env["BUN_OPTIONS"] = f"{env.get('BUN_OPTIONS', '')} --preload={PRELOAD}".strip()
    return env


def main(argv: Sequence[str] | None = None) -> int:
    """`exec -- SCRIPT [ARGS...]`: run SCRIPT as `__main__` under the hook."""
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) < 3 or args[0] != "exec" or args[1] != "--":
        print("usage: owned_observer.py exec -- SCRIPT [ARGS...]", file=sys.stderr)
        return 2
    if not install_from_environment(os.environ):
        print(f"refused: {ENV_LOG} is not set, so nothing would be recorded", file=sys.stderr)
        return 2
    script = os.path.abspath(args[2])
    sys.argv = [script, *args[3:]]
    # As `python3 SCRIPT` would: its own directory first on the path, not this one's.
    sys.path[0] = os.path.dirname(script)
    runpy.run_path(script, run_name="__main__")
    return 0


if __name__ == "__main__":
    sys.exit(main())
