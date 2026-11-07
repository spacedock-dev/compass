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


def exchange(
    method: str,
    port: int,
    path: str,
    body: bytes | None = None,
    *,
    headers: Mapping[str, str] | None = None,
    timeout: float,
    cap: int,
) -> tuple[int, bytes]:
    """Read at most cap + 1 bytes within one monotonic connect/send/headers/body budget."""
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
                return response.status, raw
    finally:
        conn.close()
