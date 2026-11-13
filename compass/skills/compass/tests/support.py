"""Shared test runtime.

The seam the suite patches: one shared ``RuntimeState``, and one mutable
store-override mapping that ``runtime()`` folds into a freshly built config.
Redirecting a store is ``mock.patch.dict(STORE_OVERRIDES, {...})``.
"""

from __future__ import annotations

import atexit
import contextlib
import dataclasses
import functools
import importlib
import importlib.util
import io
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import MappingProxyType, SimpleNamespace
from typing import Any
from unittest import mock

from compass_runtime import (
    aggregate,
    claude_settings,
    cli,
    diagnostics,
    http_api,
    notifications,
    terminal_client,
    update_check,
)
from compass_runtime.collectors import claude as claude_collector
from compass_runtime.config import COMPASS_HOME_ENV, RuntimeConfig, build_runtime_config
from compass_runtime.state import RuntimeState, build_runtime_state

from .fixtures import STORE_CONSTANTS

SERVER_PATH = Path(__file__).resolve().parents[1] / "server.py"
sys.path.insert(0, str(SERVER_PATH.parent))
frontend_page = importlib.import_module("compass_runtime.web.page")
PAGE_BYTES = frontend_page.load_frontend_page()

# `cli.main` injects this run's focus capability into the served document between
# `load_frontend_page()` and the server construction, so the bytes a running
# server hands out are the verified page plus one meta element. Stripping it here
# keeps the assertions that care about page IDENTITY comparing against
# `frontend_page.load_frontend_page()`, which is the integrity-checked document, and it
# fails rather than passing vacuously if the injection ever ships a token outside its
# own grammar.
FOCUS_META_RE = re.compile(rb'<meta name="compass-focus" content="[0-9a-fA-F]{1,128}">')


def without_focus_meta(page: bytes) -> bytes:
    """The served page with the injected focus capability removed."""
    return FOCUS_META_RE.sub(b"", page, count=1)


HOOK_PATH = SERVER_PATH.parent / "notify_hook.py"
HOOK_SPEC = importlib.util.spec_from_file_location("compass_notify_hook", HOOK_PATH)
assert HOOK_SPEC is not None
assert HOOK_SPEC.loader is not None
dashboard_hook = importlib.util.module_from_spec(HOOK_SPEC)
sys.modules[HOOK_SPEC.name] = dashboard_hook
HOOK_SPEC.loader.exec_module(dashboard_hook)

# The state home every test gets unless it patches COMPASS_HOME for itself.
# Unset, config.py falls back to the developer's real ~/.compass, and since
# DRC-4039 that means every collection reads their real dismissal store — the
# suite's verdict then depends on what they happen to have dismissed. Seeded into
# the process environment rather than injected inside runtime() so config.py
# still sees the honest variable in both directions: an explicit patch overwrites
# it, and an environ built with the key removed still has it removed, which is
# how the unset-fallback case stays testable. Assigned rather than defaulted: an
# exported COMPASS_HOME is the same leak as no COMPASS_HOME, and letting one
# through would make the suite's result depend on the developer's shell.
#
# One directory per process, not per test: runtime() is also called from classes
# with no shared setUp of their own, so a per-test directory could not reach them
# all. Nothing the suite writes here is read back by a later test — every test
# that exercises the dismissal store points state_home at its own directory.
_STATE_HOME = tempfile.TemporaryDirectory(prefix="compass-test-home-")
STATE_HOME = _STATE_HOME.name
atexit.register(_STATE_HOME.cleanup)
os.environ[COMPASS_HOME_ENV] = STATE_HOME

# The same leak one level up. COMPASS_HOME redirects only the dashboard's own
# state; every harness store root is resolved from the user's home instead
# (config.py:403 reads USERPROFILE on Windows and HOME everywhere else), so any
# test that collects without patching a store reads the developer's real
# ~/.claude, ~/.codex, ~/.cursor and the rest. Measured here: 24,981 files under
# ~/.claude/projects alone, and redirecting HOME took test_quota from 4.63s to
# 1.69s, test_lifecycle from 8.04s to 4.97s and test_http_api from 11.34s to
# 8.96s. Speed is the smaller half — otherwise the suite's verdict depends on
# what the developer's own agents happened to be writing while it ran.
#
# A second directory rather than STATE_HOME, because the two answer different
# questions: a test that points COMPASS_HOME at a directory of its own must
# still see an empty harness home, not the state it just redirected. USERPROFILE
# is seeded too — unset on this platform, but config.py prefers it on Windows,
# and the suite runs natively there in platform-tests.
_USER_HOME = tempfile.TemporaryDirectory(prefix="compass-test-user-")
USER_HOME = _USER_HOME.name
atexit.register(_USER_HOME.cleanup)
os.environ["HOME"] = USER_HOME
os.environ["USERPROFILE"] = USER_HOME

# And the model lanes' settings check reads the same machine. A developer's own Claude Code
# config folder, Codex home, telemetry switches or managed policy would otherwise decide
# whether every lane test refuses: measured, a `CLAUDE_CONFIG_DIR` whose remote cache held one
# `permissions` key turned 63 tests in test_observer and test_reading red. A test that wants
# one of these sets it for itself, and one that passes `root` reads its own managed files.
for _name in [
    name
    for name in os.environ
    if name
    in {
        "CLAUDE_CONFIG_DIR",
        "CODEX_HOME",
        "CLAUDE_CODE_ENABLE_TELEMETRY",
        "ENABLE_BETA_TRACING_DETAILED",
        "BETA_TRACING_ENDPOINT",
    }
    or name.startswith("OTEL_")
]:
    del os.environ[_name]
_MANAGED_ROOT = tempfile.TemporaryDirectory(prefix="compass-test-managed-")
atexit.register(_MANAGED_ROOT.cleanup)
claude_settings.MANAGED_ROOT = Path(_MANAGED_ROOT.name)

# Store key -> path. Patch with mock.patch.dict; runtime() folds it into config.
STORE_OVERRIDES: dict[str, Any] = {}  # str, or a tuple/list of candidates
# RuntimeConfig field -> value, applied by runtime() after the build: how a test
# lowers a threshold or a cap.
CONFIG_OVERRIDES: dict[str, Any] = {}


def server_command(*arguments: str, launcher: Path = SERVER_PATH) -> list[str]:
    """Launch a real server without a release request or update-check state files."""
    return [sys.executable, str(launcher), "--no-update-check", *arguments]


REAL_FETCH_RELEASE = update_check.fetch_release


def forbid_live_update_checks() -> None:
    """Refuse unmocked update requests, even from tests without RuntimeTestCase.

    Transport tests call REAL_FETCH_RELEASE only inside their fake-transport
    patches. Other tests must disable the worker or supply a fake fetch.
    """

    def refuse(config: RuntimeConfig) -> str:
        del config
        raise AssertionError("test attempted a live update check; disable it or fake the transport")

    update_check.fetch_release = refuse


# Constant name as the harness-contract fixtures spell it -> store key.
STORE_KEYS: dict[str, str] = {
    "PROJECTS_DIR": "claude.projects",
    "TASKS_DIR": "claude.tasks",
    "TEAMS_DIR": "claude.teams",
    "CODEX_SESSIONS_DIR": "codex.sessions",
    "PI_SESSIONS_DIR": "pi.sessions",
    "GEMINI_TMP": "gemini.tmp",
    "ANTIGRAVITY_CLI_DIR": "antigravity.root",
    "COPILOT_DIR": "copilot.root",
    "OPENCODE_DATA": "opencode.data",
    "CURSOR_CHATS": "cursor.chats",
    "GOOSE_DB": "goose.db",
    "FACTORY_PROJECTS": "droid.projects",
}
assert set(STORE_KEYS) == set(STORE_CONSTANTS), "store name map drifted from the fixtures"

SERVER_STARTED = 1_700_000_000.0
_STATE: RuntimeState | None = None


def store_patch(**by_constant: str) -> Any:
    """Redirect stores by their fixture constant name, as a context manager.

    ``store_patch(PROJECTS_DIR=path)`` drops into existing ``with`` tuples.
    """
    return mock.patch.dict(
        STORE_OVERRIDES, {STORE_KEYS[name]: value for name, value in by_constant.items()}
    )


def config_patch(**fields: Any) -> Any:
    """Override RuntimeConfig fields for the shared runtime, as a context manager."""
    return mock.patch.dict(CONFIG_OVERRIDES, fields)


def state_of() -> RuntimeState:
    """The shared runtime's state."""
    return runtime()[1]


def runtime() -> tuple[RuntimeConfig, RuntimeState]:
    """The shared test runtime: a fresh config, and the one state per test.

    The config is rebuilt on every call so a store override or a COMPASS_HOME
    patch applied after setUp is still seen. The state is not, because tests seed
    hook and cache entries and then expect a collection to observe them.
    """
    global _STATE  # noqa: PLW0603 — one shared state per test process
    single = {k: v for k, v in STORE_OVERRIDES.items() if isinstance(v, str)}
    multi = {k: tuple(v) for k, v in STORE_OVERRIDES.items() if not isinstance(v, str)}
    config = build_runtime_config(
        environ=os.environ,
        platform_name=sys.platform,
        os_name=os_name(),
        launcher_path=SERVER_PATH,
        store_root_overrides=single,
        update_check_disabled=True,
    )
    if multi:
        # build_runtime_config takes one root per key; a test pinning several
        # candidates replaces the resolved tuple outright.
        roots = dict(config.store_roots)
        roots.update(multi)
        config = dataclasses.replace(config, store_roots=MappingProxyType(roots))
    if CONFIG_OVERRIDES:
        config = dataclasses.replace(config, **CONFIG_OVERRIDES)
    if _STATE is None:
        _STATE = build_runtime_state(config, started=SERVER_STARTED)
    _STATE.config = config
    return config, _STATE


def os_name() -> str:
    """``os.name``, read through a function so a test can patch the module."""
    return os.name


def reset_runtime() -> RuntimeState:
    """Drop the shared state so the next runtime() call builds a clean one."""
    global _STATE  # noqa: PLW0603 — one shared state per test process
    _STATE = None
    return runtime()[1]


def cfg() -> RuntimeConfig:
    """The shared runtime's config.

    Lifecycle helpers read the state home, timeouts and os_name off a config
    instead of the ambient environment, so a test that patches COMPASS_HOME has
    to call this INSIDE the patch to get a config that sees it.
    """
    return runtime()[0]


def make_config(**changes: Any) -> RuntimeConfig:
    changes.setdefault("update_check_disabled", True)
    # A root-level path that exists nowhere. It used to be `/home/compass-test`,
    # and on macOS `/home` is an autofs automount, so every store lookup under
    # it was a round trip to the automount daemon: 12.96ms against 0.00ms for a
    # path outside it, about 28s of a 131s suite, measured 2026-09-23.
    config = build_runtime_config(
        environ={"HOME": "/nonexistent-compass-test"},
        platform_name="linux",
        os_name="posix",
        launcher_path=SERVER_PATH,
    )
    return dataclasses.replace(config, **changes)


def make_runtime(
    *,
    started: float = 1_700_000_000.0,
    **changes: Any,
) -> tuple[RuntimeConfig, RuntimeState]:
    config = make_config(**changes)
    return config, build_runtime_state(config, started=started)


def build_app(window_hours: float = 24) -> aggregate.Application:
    """An application over the shared runtime, built the way the CLI builds one."""
    config, state = runtime()
    if window_hours != config.window_hours:
        config = dataclasses.replace(config, window_hours=window_hours)
    return cli.build_application(config, state, clock=time.time)


def collect(window_hours: float = 24, show_all: bool = False) -> dict[str, Any]:
    """One full collection over the shared runtime."""
    return build_app(window_hours).collect(show_all=show_all)


def collect_json(window_hours: float = 24, show_all: bool = False) -> bytes:
    """The published JSON body for one collection over the shared runtime."""
    _revision, body = build_app(window_hours).collect_json(show_all=show_all)
    return body


def diagnose(window_hours: float = 24) -> dict[str, Any]:
    """The diagnostics report for the shared runtime."""
    return diagnostics.diagnose(build_app(window_hours))


def collect_claude(
    now: float,
    window_hours: float,
    show_all: bool,
) -> list[dict[str, Any]]:
    """Run the Claude collector over the shared runtime.

    It raises no popup: since DRC-4192 the popup decision belongs to
    `Application`, which is the only layer that sees a row's final state. Tests
    about popups build an application (see `ApplicationPopupTest`).
    """
    config, state = runtime()
    return claude_collector.collect(config, state, now, window_hours, show_all)


def make_server(
    *,
    port: int = 0,
    host: str = "127.0.0.1",
    application: Any = None,
    page_bytes: bytes | None = None,
    window_hours: float = 24,
    observation: Any = None,
) -> Any:
    """A CompassHTTPServer over the shared runtime, with CLI-equivalent defaults.

    ``observation`` defaults to None, which is what `--no-events` produces and
    what every test that only needs a page and an application wants.
    """
    return http_api.CompassHTTPServer(
        (host, port),
        application if application is not None else build_app(window_hours),
        PAGE_BYTES if page_bytes is None else page_bytes,
        observation,
    )


def notify_handler(payload: dict[str, Any], *, application: Any = None) -> Any:
    """A bare request handler wired to an application, for POST-ordering tests.

    Those tests drive ``do_POST`` directly rather than over a socket, because
    they need to suspend it mid-flight and land a second request inside the
    window. The handler reads its application off the server instance, so it gets
    a stand-in carrying exactly that and nothing else.
    """
    handler: Any = http_api._RequestHandler.__new__(http_api._RequestHandler)
    body = json.dumps(payload).encode()
    handler.headers = {"Content-Length": str(len(body))}
    handler.path = "/api/notify"
    handler.rfile = io.BytesIO(body)
    handler.server = SimpleNamespace(
        application=application if application is not None else build_app()
    )
    handler._local_ok = lambda **_kw: True
    handler._send = lambda *_a, **_k: None
    return handler


SERVE_POLL_INTERVAL = 0.005
"""How often a test server checks whether it has been asked to shut down.

`socketserver` defaults to 0.5s, and `shutdown()` blocks until the accept loop
next wakes and notices — so every server a test stands up and tears down costs
up to half a second of pure waiting. The suite stands up roughly a hundred of
them, which measured as 28s of the 44s that `test_http_api` spent, all of it
idle. The interval buys responsiveness with wakeups on an otherwise idle
selector, which is the right trade in a test and the wrong one in the daemon
the CLI runs; the shipped serve path keeps the stock interval.
"""


def poll_fast(httpd: Any) -> Any:
    """A `serve_forever` callable that notices `shutdown()` promptly.

    Use as a thread target in place of the bound `httpd.serve_forever`.
    """
    return functools.partial(httpd.serve_forever, SERVE_POLL_INTERVAL)


@contextlib.contextmanager
def saturated_server() -> Any:
    """A dashboard at its connection cap: one slot, held by a client that sends nothing.

    Yields the server and a callable that lets the held connection go, which returns the slot.
    """
    bounded = type("Bounded", (http_api.CompassHTTPServer,), {"CONNECTION_LIMIT": 1})
    httpd = bounded(("127.0.0.1", 0), build_app(), PAGE_BYTES)
    thread = threading.Thread(target=poll_fast(httpd), daemon=True)
    thread.start()
    held = socket.create_connection(("127.0.0.1", httpd.server_port), timeout=5.0)
    try:
        yield httpd, held.close
    finally:
        held.close()
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=2)


def serve_until_closed(httpd: Any) -> threading.Thread:
    """Serve on a thread that closes the listening socket when the loop exits.

    Mirrors what the serve path does in its ``try/finally``. Serving without the
    close leaves the port bound after the accept loop has gone — a state the CLI
    never produces, and one that makes anything waiting for the port to come free
    (``--stop``, and therefore any restart) wait for nothing.
    """

    def serve() -> None:
        try:
            httpd.serve_forever(SERVE_POLL_INTERVAL)
        finally:
            httpd.server_close()

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    return thread


def clear_state(state: RuntimeState) -> None:
    """Empty every cache, hook and memo on one state."""
    with state.hook_lock:
        state.hook_notifications.clear()
        state.last_popup.clear()
        state.last_popup_message.clear()
        state.last_session_state.clear()
        state.hook_generation.clear()
    with state.cache_lock:
        state.store_errors.clear()
        state.metadata_cache.clear()
        state.claude_title_cache.clear()
        state.claude_user_event_cache.clear()
        state.cwd_cache.clear()
        state.agent_class_cache.clear()
        state.conversation_cache.clear()
        state.spacedock_role_cache.clear()
        state.spacedock_boot_cache.clear()
        state.spacedock_workflow_cache.clear()
        state.spacedock_entity_cache.clear()
        state.cursor_metadata_cache.clear()
    with state.scanner_lock:
        state.pi_scan.clear()
        state.turn_scan.clear()
    with state.collect_memo_lock:
        state.snapshot.clear()
    with state.usage_fetch_lock:
        state.usage_fetch_cache.clear()
        state.usage_fetch_inflight.clear()


# Every platform name whose backend this suite has to refuse. Wider than the
# one the runner happens to be on, so the refusal does not quietly become a
# no-op the day someone runs the suite elsewhere.
NOTIFIER_PLATFORMS = ("darwin", "linux", "win32")

# The argv of every notification this process refused to deliver, newest last.
REFUSED_NOTIFICATIONS: list[list[str]] = []

_REAL_POPEN_INIT = subprocess.Popen.__init__
_NOTIFICATION_REFUSER: list[Any] = []


def notifier_binaries() -> frozenset[str]:
    """Every backend name ``native_notifier`` can return, over any platform.

    Derived rather than listed so the day a Linux or Windows backend lands
    (``docs/plans/native-notifications.md``) the refusal widens with it, instead
    of leaving a contributor's own desk exposed until someone remembers to edit
    a tuple here.
    """
    named = (notifications.native_notifier(name) for name in NOTIFIER_PLATFORMS)
    return frozenset(name for name in named if name)


def notification_argv(args: Any) -> list[str]:
    """One spawn's argv as strings, however ``subprocess`` was handed it."""
    raw = list(args) if isinstance(args, (list, tuple)) else [args]
    return [part.decode(errors="replace") if isinstance(part, bytes) else str(part) for part in raw]


def is_native_notification(args: Any) -> bool:
    """Whether this argv could put a notification on the host's own desktop."""
    parts = notification_argv(args)
    if not parts:
        return False
    # Basename rather than the absolute path `notifications.py` hardcodes: an
    # equality against that one constant holds only while the constant does,
    # matches nothing a future backend composes, and misses a string argv
    # entirely.
    if Path(parts[0]).name in notifier_binaries():
        return True
    return any("display notification" in part for part in parts)


def _never_starts_dashboard(arguments: list[str]) -> bool:
    read_only = {
        "--version",
        "--help",
        "-h",
        "--status",
        "--stop",
        "--diagnose",
        "--internal",
        "--forget",
        "--footer",
        "--sessions",
        "--project",
        "--pause-model-calls",
        "--summaries",
        "--monitor-sidecar",
    }
    monitor, off, _session = terminal_client.parse_monitor_args(arguments)
    if monitor and off:
        return True
    # Goal reads may select a port but never launch. Goal writes must still
    # carry the opt-out through their automatic dashboard startup.
    rest = list(arguments)
    for index, arg in enumerate(rest):
        if arg == "--port":
            del rest[index : index + 2]
            break
        if arg.startswith("--port="):
            del rest[index]
            break
    goal = terminal_client.parse_goal_args(rest)
    if goal is not None:
        return not goal.writes
    # A drift request is dispatched before recovery flags such as --status.
    # Those flags must not let a request that can launch evade the opt-out.
    startup = {"--drift", "--monitor", "--summary", "--goal"}
    if any(arg.split("=", 1)[0] in startup for arg in arguments):
        return False
    return any(arg.split("=", 1)[0] in read_only for arg in arguments)


def _refusing_popen_init(instance: Any, args: Any, *rest: Any, **kwargs: Any) -> None:
    if is_native_notification(args):
        argv = notification_argv(args)
        REFUSED_NOTIFICATIONS.append(argv)
        raise AssertionError(
            f"this test tried to notify the machine it is running on: {argv}. "
            "Derive the test class from support.RuntimeTestCase, or patch "
            "compass_runtime.notifications.notify_mac inside the test."
        )
    # Fresh interpreters do not inherit the in-process fetch refusal. Cover new
    # direct/launch.py starts here too, even if they omit server_command().
    parts = notification_argv(args)
    for index, token in enumerate(parts[1:3], start=1):
        script = Path(token)
        if not script.is_absolute():
            script = Path(kwargs.get("cwd") or Path.cwd()) / script
        if (
            script.name == "server.py"
            and (script.parent / "compass_runtime" / "entry.py").is_file()
            and "--no-update-check" not in parts
            and not _never_starts_dashboard(parts[index + 1 :])
        ):
            args = [*parts, "--no-update-check"]
            break
    _REAL_POPEN_INIT(instance, args, *rest, **kwargs)


def short_circuit_native_notifications(case: unittest.TestCase) -> None:
    """Let a test run the notifier's composition but not its process.

    For the `InstalledContractCharacterizationTest` classes, which assert the
    route shape of a successful `/api/notify` and so have to reach the code that
    composes an argv, unlike every other test — which patches `notify_mac` and
    never gets that far.

    This is a convenience, not the guard: `forbid_native_notifications` is what
    makes a leak impossible. Three copies of it were inlined in three modules,
    each matching `argv[0]` against one absolute path, and each would have gone
    on matching nothing at all on the day a non-darwin backend landed.
    """
    original_run = subprocess.run

    def run_without_native_delivery(*args: Any, **kwargs: Any) -> Any:
        command = args[0] if args else kwargs.get("args")
        if is_native_notification(command):
            return subprocess.CompletedProcess(notification_argv(command), 0)
        return original_run(*args, **kwargs)

    patcher = mock.patch.object(subprocess, "run", side_effect=run_without_native_delivery)
    patcher.start()
    case.addCleanup(patcher.stop)


def forbid_native_notifications() -> bool:
    """Refuse every native-notification spawn for the life of this process.

    Returns whether this call was the one that installed it.

    The only thing that enforces `RuntimeTestCase`'s ban: a unit run fired three
    audible banners about sessions that never existed (DRC-4431) while that ban
    sat in a docstring and 141 classes derived from a bare `unittest.TestCase`.

    At the spawn, not at `notifications.notify_mac`, even though notify_mac is
    the one seam above the platform branch: three
    `InstalledContractCharacterizationTest` classes enter notify_mac on purpose
    and short-circuit only the process, so refusing on entry would fail them for
    exercising the code they exist to exercise.

    `AssertionError` and not `OSError`, because notify_mac catches OSError and
    logs a diagnostic — an OSError refusal is silent and the leaking test still
    passes green.

    Not the environment switch #289 used for Apple Events: `notifications.py`
    reads no environment at all, and an opt-out read there would move a test
    concern into shipped runtime code, where a mis-set variable silences a real
    user's notifications instead.
    """
    if _NOTIFICATION_REFUSER:
        return False
    patcher = mock.patch.object(subprocess.Popen, "__init__", _refusing_popen_init)
    patcher.start()
    _NOTIFICATION_REFUSER.append(patcher)
    return True


class RuntimeTestCase(unittest.TestCase):
    """A clean shared runtime, and no test may fire a real popup."""

    def setUp(self) -> None:
        STORE_OVERRIDES.clear()
        CONFIG_OVERRIDES.clear()
        clear_state(reset_runtime())
        # No test may fire a real macOS popup ("[sample] permission" spam
        # during dev runs). Tests asserting popups use their own nested patch.
        # `forbid_native_notifications` is what makes this a rule rather than
        # an intention.
        notify_patcher = mock.patch.object(notifications, "notify_mac")
        notify_patcher.start()
        self.addCleanup(notify_patcher.stop)
        self.addCleanup(STORE_OVERRIDES.clear)
        self.addCleanup(CONFIG_OVERRIDES.clear)


class PiScanTestCase(unittest.TestCase):
    def setUp(self) -> None:
        _, state = runtime()
        with state.scanner_lock:
            state.pi_scan.clear()


class HarnessContractTestCase(unittest.TestCase):
    NOW = 1_700_000_000.0
    SID = "abcdef12-3456-7890-abcd-ef1234567890"
    TITLE = "Investigate the failing build"

    def setUp(self) -> None:
        # collect() updates transition/cooldown state. Without clearing it here,
        # a shuffled run can inherit a prior test's last_session_state and
        # suppress or invent the transition this contract is meant to observe.
        STORE_OVERRIDES.clear()
        CONFIG_OVERRIDES.clear()
        clear_state(reset_runtime())
        self.addCleanup(STORE_OVERRIDES.clear)
        self.addCleanup(CONFIG_OVERRIDES.clear)

    def collect(self, build: Any, *, when: float, subdir: str = "store") -> dict[str, Any]:
        """Build one harness's store in isolation and run a full collection."""
        with tempfile.TemporaryDirectory() as tmp:
            empty = Path(tmp) / "empty"
            empty.mkdir()
            # Point every store at an empty directory first, so a harness
            # installed on the developer's machine cannot leak into the result.
            patches: dict[str, str] = {name: str(empty / name) for name in STORE_CONSTANTS}
            patches.update(build(Path(tmp) / subdir, when, self.SID, self.TITLE))
            with contextlib.ExitStack() as stack:
                stack.enter_context(store_patch(**patches))
                stack.enter_context(mock.patch.object(notifications, "notify_mac"))
                stack.enter_context(mock.patch.object(time, "time", lambda: self.NOW))
                collected: dict[str, Any] = collect(24, show_all=True)
                return collected

    def sessions_for(self, data: dict[str, Any], key: str) -> list[dict[str, Any]]:
        return [session for session in data["sessions"] if session["harness"] == key]


# The registry as the runtime declares it, for tests that only read keys/labels.
# Named distinctly from fixtures.HARNESSES, which is (key, builder) pairs.
REGISTRY = aggregate.default_harnesses()


def process_alive(pid: int) -> bool:
    """Whether a process is still running, a zombie counted as gone.

    For the supervised-runner tests, which kill a CLI's whole tree and then
    ask whether a grandchild survived. A killed grandchild is reparented and
    reaped by init, and until then `kill(pid, 0)` still finds it, so `ps`
    tells a zombie from a survivor.
    """
    if sys.platform == "win32":
        import ctypes  # noqa: PLC0415 (Windows only)

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        handle = kernel32.OpenProcess(0x1000, False, pid)  # QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
            return bool(code.value == 259)  # STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    ps = shutil.which("ps") or "/bin/ps"
    state = subprocess.run(
        [ps, "-o", "stat=", "-p", str(pid)], capture_output=True, text=True, check=False
    ).stdout.strip()
    return bool(state) and not state.startswith("Z")
