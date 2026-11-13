"""A bounded stdlib HTTP exchange to literal IPv4 loopback, without proxy or redirect handling."""

from __future__ import annotations

import http.client
import socket
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Buffer, Mapping


class _Socket(socket.socket):
    def __init__(self, deadline: float) -> None:
        super().__init__(socket.AF_INET, socket.SOCK_STREAM)
        self.deadline = deadline

    def remaining(self) -> float:
        left = self.deadline - time.monotonic()
        if left <= 0:
            raise TimeoutError("loopback exchange deadline")
        return left

    def recv_into(self, buffer: object, nbytes: int = 0, flags: int = 0) -> int:
        # SocketIO (and therefore HTTPResponse's buffered header/chunk reads) calls this for
        # every receive. Setting a timeout just before read() would only bound inactivity.
        self.settimeout(self.remaining())
        return super().recv_into(buffer, nbytes, flags)  # type: ignore[arg-type]

    def sendall(self, data: Buffer, flags: int = 0) -> None:
        self.settimeout(self.remaining())
        super().sendall(data, flags)


# Between two tries at a dashboard that said it is at its connection cap. Short, because a
# probe's whole budget is about a second and a slot comes free when any connection ends.
BUSY_PAUSE_SEC = 0.05


class Busy(Exception):  # noqa: N818 - a state the caller names, not a failure
    """Every try within the budget met the dashboard's connection-cap refusal."""


def exchange(
    method: str,
    port: int,
    path: str,
    body: bytes | None = None,
    *,
    headers: Mapping[str, str] | None = None,
    timeout: float,
    cap: int,
    wait_when_busy: bool = False,
) -> tuple[int, bytes]:
    """Read at most cap + 1 bytes within one monotonic connect/send/headers/body budget.

    With `wait_when_busy`, a dashboard at its connection cap is tried again within the same
    budget. Its refusal is a 503 carrying Retry-After, written before the request is read, so it
    says nothing about the route, only that every connection is in use; Busy is raised if the
    budget runs out with every answer that refusal, or if a later try fails outright after
    one: a dashboard that said it is busy and then timed out is still there.
    """
    deadline = time.monotonic() + timeout
    refused = False
    while True:
        try:
            status, raw, retry = _exchange(
                method,
                port,
                path,
                body,
                headers=headers,
                timeout=max(deadline - time.monotonic(), 0.001),
                cap=cap,
            )
        except (OSError, http.client.HTTPException) as error:
            # The cap writes its 503 and closes before reading, so a request still being sent
            # can meet a broken pipe or a reset instead: that is the cap, and is waited out.
            # A refused connect is no dashboard at all.
            if wait_when_busy and isinstance(error, (BrokenPipeError, ConnectionResetError)):
                refused = True
                if deadline - time.monotonic() <= BUSY_PAUSE_SEC:
                    raise Busy(port) from error
                time.sleep(BUSY_PAUSE_SEC)
                continue
            if refused:
                raise Busy(port) from error
            raise
        if not wait_when_busy or status != 503 or retry is None:
            return status, raw
        refused = True
        if deadline - time.monotonic() <= BUSY_PAUSE_SEC:
            raise Busy(port)
        time.sleep(BUSY_PAUSE_SEC)


def _exchange(
    method: str,
    port: int,
    path: str,
    body: bytes | None = None,
    *,
    headers: Mapping[str, str] | None = None,
    timeout: float,
    cap: int,
) -> tuple[int, bytes, str | None]:
    deadline = time.monotonic() + timeout
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    try:
        with _Socket(deadline) as sock:
            sock.settimeout(sock.remaining())
            sock.connect(("127.0.0.1", port))
            conn.sock = sock
            conn.request(method, path, body=body, headers=dict(headers or {}))
            response = conn.getresponse()
            with response:
                raw = response.read(cap + 1)
                sock.remaining()
                return response.status, raw, response.getheader("Retry-After")
    finally:
        conn.close()
