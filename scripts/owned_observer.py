#!/usr/bin/env python3
"""Record what one owned process tree launches and connects to, from inside it. Not shipped.

    COMPASS_OBSERVE_LOG=/abs/trace.jsonl owned_observer.py exec -- server.py --port 4599

`exec` installs a Python audit hook in this interpreter and then runs the named script as
`__main__`, so the hook sits inside the Compass server for its whole life. It also puts
`owned_observer_preload.js` on this process's `NODE_OPTIONS` and `BUN_OPTIONS`, so every Node or
Bun program the server starts records the same events from inside and passes the preload on to
its own children. Both write one JSON line per event, synchronously, to the one log, before the
call they record runs, so an event a sampler would miss between two ticks is still a line.

`COMPASS_OBSERVE_MODEL_BUDGET`, when set, is the number of `claude` or `codex` launches the
server may make. The hook refuses each launch past it with `PermissionError` before the program
starts, and records a `refused` line.

Nothing here is reachable from the shipped plugin. The server only carries the hook when it is
started through `exec` with an absolute `COMPASS_OBSERVE_LOG`: `exec` refuses otherwise, and
`server.py` started the ordinary way never reads it. What the trace sees, what it cannot see and
why it is confined to the owned ancestry are in docs/design-owned-process-observer.md.
"""

from __future__ import annotations

import hashlib
import http.server
import json
import os
import re
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
ENV_BUDGET = "COMPASS_OBSERVE_MODEL_BUDGET"
PRELOAD = Path(__file__).resolve().with_name("owned_observer_preload.js")
MODEL_PROGRAMS = frozenset({"claude", "codex"})
MAX_ARG = 64
# Flags whose value is kept: each is a switch Compass passes with a value from its own code (a
# model id, an effort, a fixed mode), never one a person or a session wrote. Every other value is
# recorded as its length, so a short token after `--token` stays out of the trace.
VALUE_FLAGS = frozenset(
    {
        "--model",
        "--effort",
        "--output-format",
        "--permission-mode",
        "--permission-prompts",
        "--tools",
        "--sandbox",
        "--config",
    }
)
# A system prompt is a constant in Compass's code. Its digest says which caller made a model
# call (a reading, a summary, a Live monitor check) without carrying its words.
DIGEST_FLAGS = frozenset({"--system-prompt"})
# Positional words of the commands Compass itself starts. A value equal to one of these is a word
# of a fixed command, so keeping it discloses nothing; anything else is recorded as its length.
WORDS = frozenset(
    {
        "exec",
        "-",
        "rev-parse",
        "rev-list",
        "ls-tree",
        "cat-file",
        "config",
        "merge-base",
        "status",
        "HEAD",
        "remote.origin.url",
        "pr",
        "checks",
        "run",
        "view",
        "api",
        "mr",
        "ci",
        "display-message",
        "list-clients",
        "switch-client",
        "attach-session",
        "find-generic-password",
    }
)
_FLAG = re.compile(r"--?[A-Za-z0-9][A-Za-z0-9-]{0,39}\Z")

_state: dict[str, Any] = {}
_local = threading.local()


def digest(value: str) -> str:
    """The first twelve hex digits of a value's SHA-256, as the trace records a system prompt."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def _text(value: object) -> str:
    return os.fsdecode(value) if isinstance(value, (bytes, os.PathLike)) else str(value)


def _length(text: str) -> str:
    return f"<{len(text)} chars>"


def redact(value: object) -> str:
    """A value as its length: what the trace keeps of anything it was not told is safe."""
    return _length(_text(value))


def _kept(flag: str, value: str) -> str:
    if flag in DIGEST_FLAGS:
        return f"<{len(value)} chars sha256:{digest(value)}>"
    if flag in VALUE_FLAGS and len(value) <= MAX_ARG and "\n" not in value:
        return value
    return _length(value)


def redact_argv(args: object) -> list[str]:
    """An argument vector as the trace records it: the program's name, flag names, safe values."""
    if isinstance(args, (str, bytes, os.PathLike)):
        return [os.path.basename(_text(args))]
    if not isinstance(args, (list, tuple)) or not args:
        return []
    texts = [_text(arg) for arg in args]
    kept = [os.path.basename(texts[0])]
    previous = ""
    for text in texts[1:]:
        if previous:
            kept.append(_kept(previous, text))
            previous = ""
        elif "=" in text and _FLAG.match(text.split("=", 1)[0]):
            flag, value = text.split("=", 1)
            kept.append(f"{flag}={_kept(flag, value)}")
        elif _FLAG.match(text):
            kept.append(text)
            previous = text if text in VALUE_FLAGS | DIGEST_FLAGS else ""
        else:
            kept.append(text if text in WORDS else _length(text))
    return kept


def _program(path: object) -> str:
    return "" if path is None else os.path.basename(_text(path))


def _get(env: Any, key: str) -> str:
    for candidate in (key, os.fsencode(key)):
        try:
            value = env[candidate]
        except (KeyError, TypeError):
            continue
        return _text(value)
    return ""


def carries_hook(env: object) -> bool:
    """Whether a child started with `env` loads the preload. None means this process's own."""
    source: Any = os.environ if env is None else env
    preload = str(PRELOAD)
    return bool(_get(source, ENV_LOG)) and (
        preload in _get(source, "NODE_OPTIONS") or preload in _get(source, "BUN_OPTIONS")
    )


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


def _admit(op: str, program: str) -> None:
    """Raise, before the program starts, when it is a model launch past the budget."""
    budget = _state.get("budget")
    if budget is None or program not in MODEL_PROGRAMS:
        return
    with _state["lock"]:
        _state["model_launches"] += 1
        over = _state["model_launches"] > budget
    if over:
        emit("refused", op, program=program, budget=budget)
        message = f"owned observer: {program} refused, past this run's budget of {budget}"
        raise PermissionError(message)


def _launch(op: str, path: object, args: object, env: object) -> None:
    argv = redact_argv(args)
    program = _program(path) or (argv[0] if argv else "")
    _admit(op, program)
    emit("launch", op, program=program, argv=argv, hooked=carries_hook(env))


def _record(event: str, args: tuple[Any, ...]) -> None:  # noqa: C901 - one branch per audited event
    if event == "subprocess.Popen":
        executable, argv, _cwd, env = args
        first = argv[0] if isinstance(argv, (list, tuple)) and argv else argv
        _launch(event, executable or first, argv, env)
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
        emit("request", event, scheme=url.scheme, host=url.hostname or "", port=url.port or default)


def _hook(event: str, args: tuple[Any, ...]) -> None:
    if getattr(_local, "busy", False):
        return
    _local.busy = True
    try:
        _record(event, args)
    except PermissionError:
        # The budget's refusal is the one thing the hook lets through to the caller.
        raise
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


_SEGMENT = re.compile(r"[a-z][a-z-]{0,23}\Z")


def _route(path: str) -> str:
    """A request path as the trace keeps it: fixed route words, anything else as its length."""
    parts = path.split("?", 1)[0].split("/")
    return "/".join(part if not part or _SEGMENT.match(part) else _length(part) for part in parts)


def _wrap_http() -> None:
    """Record each POST the server answers: the reader's presses that start model calls."""
    handler = http.server.BaseHTTPRequestHandler
    original: Callable[..., bool] = handler.parse_request

    def parse_request(self: http.server.BaseHTTPRequestHandler) -> bool:
        parsed = original(self)
        if parsed and getattr(self, "command", "") == "POST":
            emit("serve", "http", method="POST", route=_route(str(getattr(self, "path", ""))))
        return parsed

    handler.parse_request = parse_request  # type: ignore[method-assign]


def install(log_path: str, budget: int | None = None) -> None:
    """Start recording this interpreter's launches and connections to `log_path`. Irreversible."""
    if _state:
        return
    if not os.path.isabs(log_path):
        message = f"{ENV_LOG} must be an absolute path"
        raise ValueError(message)
    _state["fd"] = os.open(log_path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    _state["lock"] = threading.Lock()
    _state["budget"] = budget
    _state["model_launches"] = 0
    _wrap_popen()
    _wrap_http()
    sys.addaudithook(_hook)
    emit("start", "process", program=_program(sys.executable), budget=budget)


def install_from_environment(environ: Mapping[str, str]) -> bool:
    """Install only when the environment names an absolute log. False, and nothing, otherwise."""
    log_path = environ.get(ENV_LOG, "")
    if not log_path or not os.path.isabs(log_path):
        return False
    budget = environ.get(ENV_BUDGET, "")
    install(log_path, int(budget) if budget.isdigit() else None)
    return True


def observed_environment(environ: Mapping[str, str], log_path: str) -> dict[str, str]:
    """`environ` with the trace on for this process and every Node or Bun descendant.

    The log is resolved to an absolute path here, once, so a child in another directory writes
    to the same file. The preload is added only where it is not already named.
    """
    env = dict(environ)
    env[ENV_LOG] = os.path.abspath(log_path)
    require, preload = f"--require={PRELOAD}", f"--preload={PRELOAD}"
    if require not in env.get("NODE_OPTIONS", ""):
        env["NODE_OPTIONS"] = f"{env.get('NODE_OPTIONS', '')} {require}".strip()
    # Measured on Claude Code 2.1.314, a Bun 1.4.4 executable: it ignores NODE_OPTIONS and loads
    # a preload named here, so without this line the reading model's own calls are invisible.
    if preload not in env.get("BUN_OPTIONS", ""):
        env["BUN_OPTIONS"] = f"{env.get('BUN_OPTIONS', '')} {preload}".strip()
    return env


def main(argv: Sequence[str] | None = None) -> int:
    """`exec -- SCRIPT [ARGS...]`: run SCRIPT as `__main__` under the hook."""
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) < 3 or args[0] != "exec" or args[1] != "--":
        print("usage: owned_observer.py exec -- SCRIPT [ARGS...]", file=sys.stderr)
        return 2
    log_path = os.environ.get(ENV_LOG, "")
    if not log_path or not os.path.isabs(log_path):
        print(f"refused: {ENV_LOG} must name an absolute path", file=sys.stderr)
        return 2
    os.environ.update(observed_environment(os.environ, log_path))
    install_from_environment(os.environ)
    script = os.path.abspath(args[2])
    sys.argv = [script, *args[3:]]
    # As `python3 SCRIPT` would: its own directory first on the path, not this one's.
    sys.path[0] = os.path.dirname(script)
    runpy.run_path(script, run_name="__main__")
    return 0


if __name__ == "__main__":
    sys.exit(main())
