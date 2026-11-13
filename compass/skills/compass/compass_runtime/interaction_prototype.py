"""Disposable tmux-origin registration for the shaping checkpoint.

This module is enabled only by the shaping CLI flag. It starts one isolated
tmux server and a skill-shaped client inside its pane. The client discovers and
registers its exact origin. The browser can request a server-resolved capture,
but this module exposes no keyboard-input operation.
"""

from __future__ import annotations

import argparse
import contextlib
import dataclasses
import http.client
import json
import os
import secrets
import select
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
from collections import deque
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, Protocol

if TYPE_CHECKING:
    from collections.abc import Callable

LEASE_SEC: Final = 15.0
REGISTER_TIMEOUT_SEC: Final = 2.0
MAX_CAPTURE_CHARS: Final = 12_000
MAX_STREAM_FRAMES: Final = 512
MAX_STREAM_BYTES: Final = 65_536
MAX_REGISTRATION_BYTES: Final = 16_384
# Between two tries at a dashboard at its connection cap, as `loopback_transport` waits.
BUSY_PAUSE_SEC: Final = 0.05
SESSION_ENVIRONMENT: Final = {
    "codex": "CODEX_THREAD_ID",
    "claude": "CLAUDE_CODE_SESSION_ID",
}
ORIGIN_FIELDS: Final = (
    "server_socket",
    "server_pid",
    "session_id",
    "session_name",
    "window_id",
    "window_index",
    "window_name",
    "pane_id",
    "pane_index",
    "pane_tty",
    "pane_cols",
    "pane_rows",
)
# A live bootstrap measured `window_name` changing from `spacedock` to `[tmux]`
# under tmux automatic rename while the IDs and TTY stayed fixed. Names and
# indexes remain display metadata; this tuple alone decides attachment identity.
STABLE_ORIGIN_FIELDS: Final = (
    "server_socket",
    "server_pid",
    "session_id",
    "window_id",
    "pane_id",
    "pane_tty",
)


@dataclasses.dataclass(frozen=True)
class TmuxOrigin:
    """The exact tmux coordinates discovered by a process in one pane."""

    server_socket: str
    server_pid: str
    session_id: str
    session_name: str
    window_id: str
    window_index: str
    window_name: str
    pane_id: str
    pane_index: str
    pane_tty: str
    pane_cols: str
    pane_rows: str

    @classmethod
    def from_dict(cls, value: object) -> TmuxOrigin | None:
        """Parse the closed origin shape without accepting extra coordinates."""
        if not isinstance(value, dict) or set(value) != set(ORIGIN_FIELDS):
            return None
        if not all(isinstance(value[field], str) for field in ORIGIN_FIELDS):
            return None
        fields = {field: value[field] for field in ORIGIN_FIELDS}
        if not all(fields.values()):
            return None
        if not all(
            fields[field].isdigit() and int(fields[field]) > 0
            for field in ("pane_cols", "pane_rows")
        ):
            return None
        return cls(**fields)

    def as_dict(self) -> dict[str, str]:
        """Return the closed JSON representation used by the client."""
        return dataclasses.asdict(self)

    def same_identity(self, other: TmuxOrigin) -> bool:
        """Compare server generation and stable tmux IDs, not mutable labels."""
        return all(getattr(self, field) == getattr(other, field) for field in STABLE_ORIGIN_FIELDS)


@dataclasses.dataclass(frozen=True)
class OriginLease:
    """One process-bound registration and its renewable consent deadline."""

    origin_id: str
    lease_token: str
    compass_session_id: str
    origin: TmuxOrigin
    expires_at: float
    renewal_count: int


class OriginUnavailableError(RuntimeError):
    """Report that the disposable tmux substrate cannot provide a capture."""


class OriginAdapter(Protocol):
    """Boundary between registry policy and the disposable tmux substrate."""

    def prepare(self) -> TmuxOrigin:
        """Create an inert disposable pane and return its inspected origin."""

    def start_client(
        self,
        port: int,
        registration_token: str,
        compass_session_id: str,
        lease_sec: float,
        origin: TmuxOrigin,
    ) -> None:
        """Run the skill-shaped registration client inside the prepared pane."""

    def bind_origin(self, origin: TmuxOrigin) -> None:
        """Bind exact coordinates supplied by an explicitly authorized session."""

    def start_read_only_stream(
        self,
        origin: TmuxOrigin,
        on_output: Callable[[str, str], None],
        on_disconnect: Callable[[], None],
    ) -> None:
        """Attach one server-owned read-only control-mode client."""

    def stop_read_only_stream(self) -> None:
        """Disconnect the control-mode client without changing the target pane."""

    def inspect(self, origin: TmuxOrigin) -> TmuxOrigin:
        """Inspect the pane currently addressed by the registered origin."""

    def capture(self, origin: TmuxOrigin) -> str:
        """Capture text from one exact pane without sending input."""

    def connected(self, origin: TmuxOrigin) -> bool:
        """Return whether the exact pane still exists."""

    def stop(self) -> None:
        """Stop only the disposable substrate created by this adapter."""


class DashboardBusyError(Exception):
    """Every try within the budget met the dashboard's connection-cap refusal."""


def request(
    port: int,
    method: str,
    path: str,
    body: dict[str, Any] | None = None,
    *,
    timeout: float = 2.0,
) -> tuple[int, dict[str, Any]]:
    """Make one bounded loopback request from the disposable client.

    A dashboard at its connection cap answers with an empty 503 carrying Retry-After before it
    reads the request, which read as an answer said "refused" with no reason. That refusal is
    tried again within `timeout`, and DashboardBusyError says every try met it, or that a try
    after one failed outright. This is `loopback_transport.exchange`'s busy rule, kept here
    because this file also runs as a script in the pane, where `compass_runtime` is not
    importable.
    """
    raw = None if body is None else json.dumps(body, separators=(",", ":")).encode()
    headers = {"Content-Type": "application/json"} if raw is not None else {}
    deadline = time.monotonic() + timeout
    refused = False
    while True:
        try:
            status, retry_after, answer = _request_once(
                port, method, path, raw, headers, max(deadline - time.monotonic(), 0.001)
            )
        except (OSError, http.client.HTTPException) as error:
            if refused:
                raise DashboardBusyError(port) from error
            raise
        if status != 503 or retry_after is None:
            value = json.loads(answer or b"{}")
            return status, value if isinstance(value, dict) else {}
        refused = True
        if deadline - time.monotonic() <= BUSY_PAUSE_SEC:
            raise DashboardBusyError(port)
        time.sleep(BUSY_PAUSE_SEC)


def _request_once(
    port: int,
    method: str,
    path: str,
    raw: bytes | None,
    headers: dict[str, str],
    timeout: float,
) -> tuple[int, str | None, bytes]:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    try:
        connection.request(method, path, body=raw, headers=headers)
        response = connection.getresponse()
        return response.status, response.getheader("Retry-After"), response.read()
    finally:
        connection.close()


def _control_mode_output(raw_line: bytes) -> tuple[str, str] | None:
    marker = b"%output "
    start = raw_line.find(marker)
    if start < 0:
        return None
    fields = raw_line[start:].split(b" ", 2)
    if len(fields) != 3:
        return None
    pane_id = fields[1].decode("ascii", "replace")
    return pane_id, _decode_tmux_output(fields[2])


def _decode_tmux_output(value: bytes) -> str:
    """Decode the octal escapes tmux control mode uses in `%output` lines."""
    decoded = bytearray()
    index = 0
    while index < len(value):
        if value[index] == 92 and index + 3 < len(value):  # backslash
            digits = value[index + 1 : index + 4]
            if all(48 <= digit <= 55 for digit in digits):
                decoded.append(int(digits, 8))
                index += 4
                continue
        decoded.append(value[index])
        index += 1
    return decoded.decode("utf-8", "replace")


class TmuxAdapter:
    """Own one isolated tmux server and its skill-shaped client process."""

    _FORMAT: Final = (
        "#{pid}\t#{session_id}\t#{session_name}\t#{window_id}\t#{window_index}\t"
        "#{window_name}\t#{pane_id}\t#{pane_index}\t#{pane_tty}\t#{pane_width}\t#{pane_height}"
    )

    def __init__(self, executable: str | None = None, *, owns_server: bool = True) -> None:
        self._executable = executable or shutil.which("tmux") or "tmux"
        self._owns_server = owns_server
        self._root: Path | None = None
        self._socket = ""
        self._origin: TmuxOrigin | None = None
        self._client_config: Path | None = None
        self._stream_process: subprocess.Popen[bytes] | None = None
        self._stream_fd: int | None = None
        self._stream_thread: threading.Thread | None = None
        self._stream_stop = threading.Event()

    def prepare(self) -> TmuxOrigin:
        """Create a private server whose sole pane initially runs a shell."""
        if not self._owns_server:
            raise OriginUnavailableError("external tmux adapters do not create a server")
        if shutil.which(self._executable) is None and not Path(self._executable).is_file():
            raise OriginUnavailableError("tmux executable not found")
        self._root = Path(tempfile.mkdtemp(prefix="compass-origin-"))
        self._socket = str(self._root / "tmux.sock")
        self._client_config = self._root / "client.json"
        session_name = f"compass-origin-{secrets.token_hex(4)}"
        command = shlex.join(
            [
                sys.executable,
                str(Path(__file__).resolve()),
                "--tmux-wait-client",
                "--config",
                str(self._client_config),
            ]
        )
        self._run(
            "new-session",
            "-d",
            "-s",
            session_name,
            "-n",
            "registered-origin",
            command,
        )
        pane_id = self._run("display-message", "-p", "-t", session_name, "#{pane_id}").strip()
        self._origin = self._inspect(pane_id)
        return self._origin

    def start_client(
        self,
        port: int,
        registration_token: str,
        compass_session_id: str,
        lease_sec: float,
        origin: TmuxOrigin,
    ) -> None:
        """Release the waiting pane client after the server has an allowlist."""
        if origin != self._origin:
            raise OriginUnavailableError("prepared tmux origin changed before client start")
        config_path = self._client_config
        if config_path is None:
            raise OriginUnavailableError("tmux client configuration path is missing")
        temporary = config_path.with_name(f".{config_path.name}.{secrets.token_hex(4)}.tmp")
        try:
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "port": port,
                        "registration_token": registration_token,
                        "compass_session_id": compass_session_id,
                        "lease_sec": lease_sec,
                        "require_session_environment": False,
                    },
                    handle,
                    separators=(",", ":"),
                )
            os.replace(temporary, config_path)
        finally:
            with contextlib.suppress(OSError):
                temporary.unlink()

    def bind_origin(self, origin: TmuxOrigin) -> None:
        """Adopt one external origin, or verify the disposable origin already prepared."""
        if self._owns_server:
            if self._origin is None or not origin.same_identity(self._origin):
                raise OriginUnavailableError("prepared tmux origin changed before registration")
            return
        if self._origin is not None and not origin.same_identity(self._origin):
            raise OriginUnavailableError("external tmux origin is already bound")
        self._socket = origin.server_socket
        self._origin = origin

    def start_read_only_stream(
        self,
        origin: TmuxOrigin,
        on_output: Callable[[str, str], None],
        on_disconnect: Callable[[], None],
    ) -> None:
        """Attach `tmux -CC -r` through a PTY and expose output callbacks only."""
        if self.inspect(origin) != origin:
            raise OriginUnavailableError("cannot stream a changed tmux origin")
        openpty = getattr(os, "openpty", None)
        if openpty is None:
            raise OriginUnavailableError("tmux control mode requires a POSIX pseudo-terminal")
        self.stop_read_only_stream()
        master_fd, slave_fd = openpty()
        try:
            process = subprocess.Popen(  # noqa: S603 - fixed executable and argument vector
                [
                    self._executable,
                    "-f",
                    "/dev/null",
                    "-S",
                    self._socket,
                    "-CC",
                    "attach-session",
                    "-r",
                    "-t",
                    origin.session_id,
                ],
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                close_fds=True,
            )
        except OSError as exc:
            os.close(master_fd)
            raise OriginUnavailableError("cannot start tmux control-mode client") from exc
        finally:
            os.close(slave_fd)
        self._stream_process = process
        self._stream_fd = master_fd
        self._stream_stop = threading.Event()
        self._stream_thread = threading.Thread(
            target=self._read_control_mode,
            args=(master_fd, on_output, on_disconnect),
            daemon=True,
        )
        self._stream_thread.start()

    def stop_read_only_stream(self) -> None:
        """Stop only the read-only control client, preserving the tmux target."""
        self._stream_stop.set()
        thread = self._stream_thread
        self._stream_thread = None
        if thread is not None and thread is not threading.current_thread():
            thread.join(0.25)
        master_fd = self._stream_fd
        self._stream_fd = None
        if master_fd is not None:
            with contextlib.suppress(OSError):
                os.close(master_fd)
        process = self._stream_process
        self._stream_process = None
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=0.25)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=0.25)

    def inspect(self, origin: TmuxOrigin) -> TmuxOrigin:
        """Re-read every registered coordinate from the recorded server socket."""
        if origin.server_socket != self._socket:
            raise OriginUnavailableError("tmux server socket is outside the disposable server")
        return self._inspect(origin.pane_id)

    def capture(self, origin: TmuxOrigin) -> str:
        """Return bounded pane text after re-validating the registered identity."""
        if not self.inspect(origin).same_identity(origin):
            message = "registered tmux origin no longer identifies the same pane"
            raise OriginUnavailableError(message)
        output = self._run("capture-pane", "-p", "-S", "-100", "-t", origin.pane_id)
        return output[-MAX_CAPTURE_CHARS:].rstrip()

    def connected(self, origin: TmuxOrigin) -> bool:
        """Check exact-origin continuity without mutating the tmux server."""
        try:
            return self.inspect(origin).same_identity(origin)
        except OriginUnavailableError:
            return False

    def stop(self) -> None:
        """Kill only this adapter's private server and remove its private socket directory."""
        self.stop_read_only_stream()
        if self._owns_server and self._socket:
            with contextlib.suppress(OriginUnavailableError):
                self._run("kill-server")
        root = self._root
        self._root = None
        self._socket = ""
        self._origin = None
        self._client_config = None
        if root is not None and root.name.startswith("compass-origin-"):
            shutil.rmtree(root, ignore_errors=True)

    def _inspect(self, pane_id: str) -> TmuxOrigin:
        values = self._run("display-message", "-p", "-t", pane_id, self._FORMAT).strip().split("\t")
        if len(values) != len(ORIGIN_FIELDS) - 1:
            raise OriginUnavailableError("tmux returned an incomplete origin")
        return TmuxOrigin(self._socket, *values)

    def _run(self, *arguments: str) -> str:
        try:
            completed = subprocess.run(  # noqa: S603 - fixed executable and argument vector
                [self._executable, "-f", "/dev/null", "-S", self._socket, *arguments],
                check=True,
                capture_output=True,
                text=True,
                timeout=2.0,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise OriginUnavailableError(f"tmux operation failed: {type(exc).__name__}") from exc
        return completed.stdout

    def _read_control_mode(
        self,
        master_fd: int,
        on_output: Callable[[str, str], None],
        on_disconnect: Callable[[], None],
    ) -> None:
        pending = b""
        try:
            while not self._stream_stop.is_set():
                readable, _, _ = select.select([master_fd], [], [], 0.1)
                if not readable:
                    continue
                chunk = os.read(master_fd, 65_536)
                if not chunk:
                    break
                pending += chunk
                while b"\n" in pending:
                    raw_line, pending = pending.split(b"\n", 1)
                    if len(raw_line) > MAX_STREAM_BYTES:
                        return
                    parsed = _control_mode_output(raw_line.rstrip(b"\r"))
                    if parsed is not None:
                        on_output(*parsed)
                if len(pending) > MAX_STREAM_BYTES:
                    return
        except OSError:
            pass
        finally:
            on_disconnect()


class InteractionPrototype:
    """A process-bound origin registry with read-only tmux attachment."""

    def __init__(
        self,
        adapter: OriginAdapter | None = None,
        *,
        lease_sec: float = LEASE_SEC,
        collected_session_id: str | None = None,
        session_exists: Callable[[str], bool] | None = None,
        registration_file: Path | None = None,
    ) -> None:
        self._condition = threading.Condition()
        self._external_session_id = collected_session_id
        self._session_exists = session_exists or (lambda _session_id: True)
        self._registration_file = registration_file
        self._adapter = adapter or TmuxAdapter(owns_server=collected_session_id is None)
        self._lease_sec = lease_sec
        self._registration_token = secrets.token_urlsafe(24)
        self._server_generation = ""
        self._expected_session_id = collected_session_id or ""
        self._expected_origin: TmuxOrigin | None = None
        self._lease: OriginLease | None = None
        self._generation = 0
        self._capture_sequence = 0
        self._stream_text = ""
        self._stream_frames: deque[tuple[int, str, int, int]] = deque(maxlen=MAX_STREAM_FRAMES)
        self._stream_connected = False
        self._registration_consumed = False
        self._renewals_enabled = True
        self._started = False
        self._start_error = ""

    def register(
        self,
        registration_token: str,
        compass_session_id: str,
        origin_value: object,
        *,
        now: float,
    ) -> dict[str, Any]:
        """Bind a client token to the one process-inspected disposable pane."""
        origin = TmuxOrigin.from_dict(origin_value)
        with self._condition:
            refusal = self._registration_refusal(
                registration_token,
                compass_session_id,
                origin,
            )
            if refusal is not None:
                return refusal
            if origin is None:
                message = "registration guard accepted a missing origin"
                raise RuntimeError(message)
            if not self._session_exists(compass_session_id):
                return {"state": "refused", "reason": "session-uncollected"}
            try:
                self._adapter.bind_origin(origin)
                inspected = self._adapter.inspect(origin)
            except OriginUnavailableError:
                return {"state": "refused", "reason": "origin-disconnected"}
            if not inspected.same_identity(origin):
                return {"state": "refused", "reason": "origin-mismatch"}
            self._expected_origin = inspected
            if self._external_session_id is not None:
                try:
                    self._adapter.start_read_only_stream(
                        inspected,
                        self._on_stream_output,
                        self._on_stream_disconnect,
                    )
                except OriginUnavailableError:
                    return {"state": "refused", "reason": "origin-disconnected"}
                self._stream_connected = True
            lease = OriginLease(
                origin_id=secrets.token_urlsafe(16),
                lease_token=secrets.token_urlsafe(24),
                compass_session_id=compass_session_id,
                origin=inspected,
                expires_at=now + self._lease_sec,
                renewal_count=0,
            )
            self._lease = lease
            self._registration_consumed = True
            self._condition.notify_all()
            return {
                "state": "registered",
                "origin_id": lease.origin_id,
                "lease_token": lease.lease_token,
                "lease_sec": self._lease_sec,
            }

    def _registration_refusal(
        self,
        registration_token: str,
        compass_session_id: str,
        origin: TmuxOrigin | None,
    ) -> dict[str, str] | None:
        reason = ""
        origin_mismatch = origin is None or (
            self._expected_origin is not None and not origin.same_identity(self._expected_origin)
        )
        if not secrets.compare_digest(registration_token, self._registration_token):
            reason = "invalid-registration-token"
        elif compass_session_id != self._expected_session_id:
            reason = "session-mismatch"
        elif origin_mismatch:
            reason = "origin-mismatch"
        elif self._registration_consumed:
            reason = "registration-token-consumed"
        return {"state": "refused", "reason": reason} if reason else None

    def renew(
        self,
        origin_id: str,
        lease_token: str,
        *,
        now: float,
    ) -> dict[str, Any]:
        """Renew consent only while the exact registered pane remains connected."""
        with self._condition:
            lease = self._lease
            if lease is None or not secrets.compare_digest(lease.origin_id, origin_id):
                return {"state": "refused", "reason": "unregistered-origin"}
            if not secrets.compare_digest(lease.lease_token, lease_token):
                return {"state": "refused", "reason": "invalid-lease-token"}
            if not self._renewals_enabled or now >= lease.expires_at:
                return {"state": "refused", "reason": "stale-registration"}
            try:
                inspected = self._adapter.inspect(lease.origin)
            except OriginUnavailableError:
                return {"state": "refused", "reason": "origin-disconnected"}
            if not inspected.same_identity(lease.origin):
                return {"state": "refused", "reason": "origin-disconnected"}
            self._lease = dataclasses.replace(
                lease,
                origin=inspected,
                expires_at=now + self._lease_sec,
                renewal_count=lease.renewal_count + 1,
            )
            self._expected_origin = inspected
            self._condition.notify_all()
            return {
                "state": "renewed",
                "lease_sec": self._lease_sec,
                "renewal_count": self._lease.renewal_count,
            }

    def state(self, port: int) -> dict[str, Any]:
        """Return the active origin without exposing either capability token."""
        self._ensure_started(port)
        with self._condition:
            if self._lease is None and not self._start_error and self._external_session_id is None:
                self._condition.wait(REGISTER_TIMEOUT_SEC)
            lease = self._lease
            if lease is None:
                return {
                    "origin_state": "unregistered",
                    "reason": self._start_error
                    or (
                        "awaiting-session-registration"
                        if self._external_session_id is not None
                        else "registration-timeout"
                    ),
                    "terminal_power": "none",
                    "compass_session_id": self._expected_session_id or None,
                    "session_ownership": (
                        "explicit-collected-session-registration"
                        if self._external_session_id is not None
                        else "not-bound-to-collected-session"
                    ),
                }
            now = time.monotonic()
            stale = not self._renewals_enabled or now >= lease.expires_at
            connected = self._adapter.connected(lease.origin)
            return {
                "origin_state": "stale" if stale else "registered",
                "reason": "lease-expired" if stale else "process-bound-registration",
                "generation": self._generation,
                "lease_remaining_sec": max(0, round(lease.expires_at - now, 1)),
                "renewal_count": lease.renewal_count,
                "connected": connected,
                "stream_connected": self._stream_connected,
                "origin": lease.origin.as_dict(),
                "compass_session_id": lease.compass_session_id,
                "ownership": (
                    "one-use-session-bootstrap"
                    if self._external_session_id is not None
                    else "disposable-process-token"
                ),
                "session_ownership": (
                    "explicit-collected-session-registration"
                    if self._external_session_id is not None
                    else "not-bound-to-collected-session"
                ),
                "terminal_power": "read-only-control-stream",
                "keyboard_input": "not-exposed",
                "bridge": "tmux-control-mode-read-only",
                "backend_attachment": "tmux-CC-read-only-PTY",
                "browser_transport": "output-only-WebSocket",
                "terminal_attachment": True,
                "browser_pty": False,
            }

    def view(self, port: int) -> dict[str, Any]:
        """Capture the registered pane through a server-owned resolution step."""
        self._ensure_started(port)
        with self._condition:
            lease, refusal = self._resolve_registered(time.monotonic())
        if lease is None:
            return refusal or {"state": "refused", "reason": "unregistered-origin"}
        try:
            inspected = self._adapter.inspect(lease.origin)
        except OriginUnavailableError:
            return {"state": "unknown", "reason": "origin-disconnected"}
        if not inspected.same_identity(lease.origin):
            return {"state": "unknown", "reason": "origin-changed"}
        lease = self._refresh_origin_metadata(lease, inspected)
        with self._condition:
            if not self._stream_connected:
                return {"state": "unknown", "reason": "control-mode-disconnected"}
            captured = self._stream_text
            capture_sequence = self._capture_sequence
        if not captured:
            try:
                captured = self._adapter.capture(lease.origin)
            except OriginUnavailableError:
                return {"state": "unknown", "reason": "origin-disconnected"}
        return {
            "state": "viewed",
            "reason": "server-resolved-read-only-control-stream",
            "text": captured,
            "origin_id_hint": lease.origin_id[:8],
            "capture_sequence": capture_sequence,
            "bridge": "tmux-control-mode-read-only",
            "backend_attachment": "tmux-CC-read-only-PTY",
            "browser_transport": "output-only-WebSocket",
            "terminal_attachment": True,
            "browser_pty": False,
            "keyboard_input": "not-exposed",
        }

    def wait_stream(self, port: int, after_sequence: int, timeout: float) -> dict[str, Any]:
        """Wait briefly for exact-pane output and return one read-only stream frame."""
        self._ensure_started(port)
        deadline = time.monotonic() + timeout
        with self._condition:
            while self._capture_sequence <= after_sequence and self._stream_connected:
                lease, refusal = self._resolve_registered(time.monotonic())
                if lease is None:
                    return refusal or {"state": "refused", "reason": "unregistered-origin"}
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self._condition.wait(remaining)
            lease, refusal = self._resolve_registered(time.monotonic())
            if lease is None:
                return refusal or {"state": "refused", "reason": "unregistered-origin"}
            if not self._stream_connected:
                return {"state": "unknown", "reason": "control-mode-disconnected"}
            sequence = self._capture_sequence
            reset = after_sequence <= 0
            frames = tuple(self._stream_frames)
            if frames and after_sequence < frames[0][0] - 1:
                reset = True
            if reset:
                data = self._stream_text
                cols = int(frames[-1][2]) if frames else int(lease.origin.pane_cols)
                rows = int(frames[-1][3]) if frames else int(lease.origin.pane_rows)
                chunks = [
                    {
                        "sequence": sequence,
                        "data": data,
                        "cols": cols,
                        "rows": rows,
                    }
                ]
            else:
                selected = [frame for frame in frames if frame[0] > after_sequence]
                data = "".join(frame[1] for frame in selected)
                chunks = [
                    {
                        "sequence": frame_sequence,
                        "data": text,
                        "cols": cols,
                        "rows": rows,
                    }
                    for frame_sequence, text, cols, rows in selected
                ]
                cols = int(selected[-1][2]) if selected else int(lease.origin.pane_cols)
                rows = int(selected[-1][3]) if selected else int(lease.origin.pane_rows)
            return {
                "state": "streamed",
                "sequence": sequence,
                "reset": reset,
                "data": data,
                "cols": cols,
                "rows": rows,
                "chunks": chunks,
                "origin_id_hint": lease.origin_id[:8],
            }

    def probe_unregistered(self) -> dict[str, str]:
        """Exercise resolver refusal without letting the browser name a target."""
        return {"state": "refused", "reason": "unregistered-origin"}

    def probe_spoofed(self) -> dict[str, Any]:
        """Exercise exact-origin refusal with a server-owned altered pane claim."""
        with self._condition:
            origin = self._expected_origin
        if origin is None:
            return {"state": "refused", "reason": "unregistered-origin"}
        spoofed = dataclasses.replace(origin, pane_id="%server-owned-spoof")
        return self.register(
            self._registration_token,
            self._expected_session_id,
            spoofed.as_dict(),
            now=time.monotonic(),
        )

    def resolve_session(self, port: int, compass_session_id: str) -> dict[str, Any]:
        """Resolve one collected identity to its exact live origin without granting power."""
        self._ensure_started(port)
        with self._condition:
            lease, refusal = self._resolve_registered(time.monotonic())
        if lease is None:
            return refusal or {"state": "refused", "reason": "unregistered-origin"}
        if compass_session_id != lease.compass_session_id:
            return {"state": "refused", "reason": "session-mismatch"}
        try:
            inspected = self._adapter.inspect(lease.origin)
        except OriginUnavailableError:
            return {"state": "unknown", "reason": "origin-disconnected"}
        if not inspected.same_identity(lease.origin):
            return {"state": "unknown", "reason": "origin-changed"}
        lease = self._refresh_origin_metadata(lease, inspected)
        return {
            "state": "registered",
            "reason": "exact-collected-session-origin",
            "compass_session_id": lease.compass_session_id,
            "origin_id_hint": lease.origin_id[:8],
            "origin": lease.origin.as_dict(),
            "lease_remaining_sec": max(0, round(lease.expires_at - time.monotonic(), 1)),
            "terminal_power": "read-only-control-stream",
            "keyboard_input": "not-exposed",
            "stream_connected": self._stream_connected,
        }

    def expire(self, port: int) -> dict[str, Any]:
        """Revoke consent and reject later client renewals without killing tmux."""
        self._ensure_started(port)
        with self._condition:
            self._renewals_enabled = False
            if self._lease is not None:
                self._lease = dataclasses.replace(self._lease, expires_at=0.0)
            self._condition.notify_all()
        return self.state(port)

    def disconnect(self, port: int) -> dict[str, Any]:
        """Disconnect only the read-only control client, preserving the target pane."""
        self._ensure_started(port)
        self._adapter.stop_read_only_stream()
        with self._condition:
            self._stream_connected = False
        return self.state(port)

    def reconnect(self, port: int) -> dict[str, Any]:
        """Reattach read-only control mode to the same registered pane."""
        self._ensure_started(port)
        with self._condition:
            lease, refusal = self._resolve_registered(time.monotonic())
        if refusal is not None:
            return refusal
        if lease is None:
            return {"state": "refused", "reason": "unregistered-origin"}
        try:
            self._adapter.start_read_only_stream(
                lease.origin,
                self._on_stream_output,
                self._on_stream_disconnect,
            )
        except OriginUnavailableError:
            return {"state": "unknown", "reason": "origin-disconnected"}
        with self._condition:
            self._stream_connected = True
        return {
            "state": "reconnected",
            "reason": "same-registered-origin",
            "origin_id_hint": lease.origin_id[:8],
        }

    def reset(self, port: int) -> dict[str, Any]:
        """Create a new disposable origin; the old origin is never reused."""
        self._adapter.stop()
        with self._condition:
            self._expected_origin = None
            self._expected_session_id = self._external_session_id or ""
            self._lease = None
            self._registration_token = secrets.token_urlsafe(24)
            self._registration_consumed = False
            self._renewals_enabled = True
            self._started = False
            self._start_error = ""
            self._stream_text = ""
            self._capture_sequence = 0
            self._stream_frames.clear()
            self._stream_connected = False
        return self.state(port)

    def stop(self) -> None:
        """Stop only the disposable tmux server owned by this prototype."""
        self._remove_registration_file()
        self._adapter.stop()

    def start(self, port: int) -> None:
        """Publish this server generation's bootstrap before readiness."""
        self._ensure_started(port)
        if self._start_error:
            raise OriginUnavailableError(self._start_error)

    def _ensure_started(self, port: int) -> None:
        with self._condition:
            if self._started:
                return
            self._started = True
            try:
                self._server_generation = secrets.token_urlsafe(16)
                if self._external_session_id is not None:
                    self._generation += 1
                    self._write_registration_file(port)
                    self._condition.notify_all()
                    return
                origin = self._adapter.prepare()
                self._expected_origin = origin
                self._generation += 1
                self._expected_session_id = f"codex:disposable-tmux-origin:{self._generation}"
                self._stream_connected = True
                self._adapter.start_read_only_stream(
                    origin,
                    self._on_stream_output,
                    self._on_stream_disconnect,
                )
                self._adapter.start_client(
                    port,
                    self._registration_token,
                    self._expected_session_id,
                    self._lease_sec,
                    origin,
                )
            except OriginUnavailableError as exc:
                self._start_error = str(exc)
                self._condition.notify_all()

    def _write_registration_file(self, port: int) -> None:
        path = self._registration_file
        if path is None:
            raise OriginUnavailableError("external registration file is missing")
        temporary = path.with_name(f".{path.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp")
        try:
            path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            payload = json.dumps(
                {
                    "port": port,
                    "registration_token": self._registration_token,
                    "compass_session_id": self._expected_session_id,
                    "lease_sec": self._lease_sec,
                    "require_session_environment": True,
                    "server_generation": self._server_generation,
                },
                separators=(",", ":"),
            )
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        except OSError as exc:
            raise OriginUnavailableError("cannot write external registration file") from exc
        finally:
            with contextlib.suppress(OSError):
                temporary.unlink()

    def _remove_registration_file(self) -> None:
        path = self._registration_file
        generation = self._server_generation
        if path is None or not generation:
            return
        try:
            if _read_registration_generation(path) != generation:
                return
            path.unlink()
        except (OSError, ValueError, TypeError, json.JSONDecodeError, RecursionError):
            return

    def _on_stream_output(self, pane_id: str, text: str) -> None:
        if len(text) > MAX_STREAM_BYTES or len(text.encode("utf-8", "replace")) > MAX_STREAM_BYTES:
            self._on_stream_disconnect()
            return
        with self._condition:
            origin = self._expected_origin
        if origin is None or pane_id != origin.pane_id:
            return
        try:
            inspected = self._adapter.inspect(origin)
        except OriginUnavailableError:
            return
        if not inspected.same_identity(origin):
            return
        with self._condition:
            origin = self._expected_origin
            if origin is None or pane_id != origin.pane_id or not inspected.same_identity(origin):
                return
            self._expected_origin = inspected
            if self._lease is not None:
                self._lease = dataclasses.replace(self._lease, origin=inspected)
            self._stream_text = (self._stream_text + text)[-MAX_CAPTURE_CHARS:]
            self._capture_sequence += 1
            self._stream_frames.append(
                (
                    self._capture_sequence,
                    text,
                    int(inspected.pane_cols),
                    int(inspected.pane_rows),
                )
            )
            while (
                sum(len(frame[1].encode("utf-8", "replace")) for frame in self._stream_frames)
                > MAX_STREAM_BYTES
            ):
                self._stream_frames.popleft()
            self._stream_connected = True
            self._condition.notify_all()

    def _on_stream_disconnect(self) -> None:
        with self._condition:
            self._stream_connected = False
            self._condition.notify_all()

    def _resolve_registered(
        self,
        now: float,
    ) -> tuple[OriginLease | None, dict[str, str] | None]:
        lease = self._lease
        if lease is None:
            return None, {"state": "refused", "reason": "unregistered-origin"}
        if not self._renewals_enabled or now >= lease.expires_at:
            return None, {"state": "refused", "reason": "stale-registration"}
        return lease, None

    def _refresh_origin_metadata(
        self,
        lease: OriginLease,
        inspected: TmuxOrigin,
    ) -> OriginLease:
        """Publish current labels and indexes while preserving stable identity and consent."""
        with self._condition:
            current = self._lease
            if current is None or current.origin_id != lease.origin_id:
                return dataclasses.replace(lease, origin=inspected)
            refreshed = dataclasses.replace(current, origin=inspected)
            self._lease = refreshed
            self._expected_origin = inspected
            return refreshed


def _discover_origin() -> TmuxOrigin:
    tmux_value = os.environ.get("TMUX", "")
    pane_id = os.environ.get("TMUX_PANE", "")
    server_socket = tmux_value.split(",", 1)[0]
    if not server_socket or not pane_id:
        raise OriginUnavailableError("the registration client is not running inside tmux")
    executable = shutil.which("tmux") or "tmux"
    adapter = TmuxAdapter(executable)
    adapter._socket = server_socket  # noqa: SLF001 - client-side adapter bootstrap
    return adapter._inspect(pane_id)  # noqa: SLF001 - one bounded discovery operation


def _run_tmux_client(
    port: int,
    registration_token: str,
    compass_session_id: str,
    lease_sec: float,
) -> int:
    """Register and renew from inside the disposable pane, as a skill would."""
    try:
        origin = _discover_origin()
        status, registered = request(
            port,
            "POST",
            "/api/interaction/register",
            {
                "registration_token": registration_token,
                "compass_session_id": compass_session_id,
                "origin": origin.as_dict(),
            },
        )
    except (OSError, ValueError, OriginUnavailableError, DashboardBusyError) as exc:
        print(f"registration failed: {type(exc).__name__}", flush=True)
        return 1
    if status != 200 or registered.get("state") != "registered":
        print(f"registration refused: {registered.get('reason', 'unknown')}", flush=True)
        return 1
    origin_id = registered.get("origin_id")
    lease_token = registered.get("lease_token")
    if not isinstance(origin_id, str) or not isinstance(lease_token, str):
        print("registration failed: incomplete lease", flush=True)
        return 1
    print("Compass skill-shaped origin client", flush=True)
    print(
        f"registered {origin.session_name}:{origin.window_index}.{origin.pane_index} "
        f"({origin.session_id}/{origin.window_id}/{origin.pane_id})",
        flush=True,
    )
    renewal_count = 0
    interval = max(0.05, lease_sec / 3)
    renewed_at = time.monotonic()
    while True:
        time.sleep(interval)
        try:
            _status, renewed = request(
                port,
                "POST",
                "/api/interaction/renew",
                {"origin_id": origin_id, "lease_token": lease_token},
            )
        except DashboardBusyError:
            # Busy is not a refusal: only the dashboard ends the lease. Keep trying until it
            # would have lapsed, after which a renewal could only be refused.
            if time.monotonic() - renewed_at >= lease_sec:
                print("renewal stopped: dashboard busy", flush=True)
                return 0
            continue
        except (OSError, ValueError):
            print("renewal stopped: dashboard disconnected", flush=True)
            return 0
        if renewed.get("state") != "renewed":
            print(f"renewal refused: {renewed.get('reason', 'unknown')}", flush=True)
            return 0
        renewal_count += 1
        renewed_at = time.monotonic()
        print(f"lease renewed {renewal_count}", flush=True)


def _read_registration_generation(path: Path) -> str | None:
    """Read only the cleanup guard, without trusting any capability in the file."""
    if not stat.S_ISREG(path.lstat().st_mode):
        raise ValueError("registration file must be regular")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    descriptor = os.open(path, flags | getattr(os, "O_BINARY", 0))
    with os.fdopen(descriptor, "rb") as handle:
        info = os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_REGISTRATION_BYTES:
            raise ValueError("registration file must be regular and bounded")
        raw = handle.read(MAX_REGISTRATION_BYTES + 1)
    if len(raw) > MAX_REGISTRATION_BYTES:
        raise ValueError("registration file exceeds byte limit")
    value = json.loads(raw)
    generation = value.get("server_generation") if isinstance(value, dict) else None
    return generation if isinstance(generation, str) else None


class RegistrationUnsupportedError(ValueError):
    """The platform cannot verify private registration capabilities."""


def _read_registration_file(path: Path) -> dict[str, Any]:
    """Read capabilities only from a private, owned, bounded regular file."""
    if not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "getuid"):
        raise RegistrationUnsupportedError(
            "private registration files require POSIX ownership checks"
        )
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as handle:
        info = os.fstat(handle.fileno())
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) != 0o600
            or info.st_size > MAX_REGISTRATION_BYTES
        ):
            raise ValueError("registration file must be owned, regular, bounded and mode 0600")
        raw = handle.read(MAX_REGISTRATION_BYTES + 1)
    if len(raw) > MAX_REGISTRATION_BYTES:
        raise ValueError("registration file exceeds byte limit")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise TypeError("registration file must be an object")
    return value


def _run_waiting_tmux_client(config_path: Path) -> int:
    """Wait inside one stable pane until the server publishes client capabilities."""
    deadline = time.monotonic() + REGISTER_TIMEOUT_SEC
    while not config_path.is_file():
        if time.monotonic() >= deadline:
            print("registration failed: client configuration timeout", flush=True)
            return 1
        time.sleep(0.02)
    try:
        value = _read_registration_file(config_path)
        port = value["port"]
        registration_token = value["registration_token"]
        compass_session_id = value["compass_session_id"]
        lease_sec = value["lease_sec"]
        require_session_environment = value["require_session_environment"]
    except RegistrationUnsupportedError as exc:
        print(f"terminal registration unsupported: {exc}", flush=True)
        return 1
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        print("registration failed: malformed client configuration", flush=True)
        return 1
    if not all(
        (
            isinstance(port, int),
            isinstance(registration_token, str),
            isinstance(compass_session_id, str),
            isinstance(lease_sec, (int, float)),
            isinstance(require_session_environment, bool),
        )
    ):
        print("registration failed: malformed client configuration", flush=True)
        return 1
    if require_session_environment and not _session_environment_matches(compass_session_id):
        print("registration failed: collected session identity mismatch", flush=True)
        return 1
    return _run_tmux_client(
        port,
        registration_token,
        compass_session_id,
        float(lease_sec),
    )


def _session_environment_matches(compass_session_id: str) -> bool:
    harness, separator, sid = compass_session_id.partition(":")
    variable = SESSION_ENVIRONMENT.get(harness)
    return bool(separator and sid and variable and os.environ.get(variable) == sid)


def _client_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tmux-client", action="store_true")
    parser.add_argument("--tmux-wait-client", action="store_true")
    parser.add_argument("--config", type=Path)
    parser.add_argument("--port", type=int)
    parser.add_argument("--registration-token")
    parser.add_argument("--compass-session-id")
    parser.add_argument("--lease-sec", type=float)
    return parser


if __name__ == "__main__":
    client_args = _client_parser().parse_args()
    if client_args.tmux_wait_client and client_args.config is not None:
        raise SystemExit(_run_waiting_tmux_client(client_args.config))
    if (
        client_args.tmux_client
        and client_args.port is not None
        and client_args.registration_token is not None
        and client_args.compass_session_id is not None
        and client_args.lease_sec is not None
    ):
        raise SystemExit(
            _run_tmux_client(
                client_args.port,
                client_args.registration_token,
                client_args.compass_session_id,
                client_args.lease_sec,
            )
        )
    raise SystemExit("incomplete tmux client arguments")
