"""A bounded stdlib HTTPS exchange: one monotonic deadline from DNS to the last body byte.

Shared by the daily release lookup in `update_check` and the vendor quota fetch in `quota`. The
caller supplies the opener, which is `reach.build_reach_opener()` for both (no proxy handler that
reads the environment or the macOS system settings, and no redirect followed), and a DNS slot of
its own.
"""

from __future__ import annotations

import contextlib
import http.client
import socket
import ssl
import threading
import time
import urllib.parse
import urllib.request
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterator


def _remaining(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("HTTPS exchange deadline")
    return remaining


def _resolve(host: str, port: int, deadline: float, slot: threading.BoundedSemaphore) -> list[Any]:
    # A hung system resolver may outlive its caller, but cannot accumulate more resolver threads
    # than the caller's slot admits.
    if not slot.acquire(blocking=False):
        raise TimeoutError("HTTPS exchange resolver busy")
    ready = threading.Event()
    answers: list[Any] = []
    errors: list[OSError] = []

    def resolve() -> None:
        try:
            answers.extend(socket.getaddrinfo(host, port, type=socket.SOCK_STREAM))
        except OSError as exc:
            errors.append(exc)
        finally:
            slot.release()
            ready.set()

    worker = threading.Thread(target=resolve, daemon=True)
    try:
        worker.start()
    except RuntimeError:
        slot.release()
        raise
    if not ready.wait(_remaining(deadline)):
        raise TimeoutError("HTTPS exchange DNS deadline")
    _remaining(deadline)
    if errors:
        raise errors[0]
    return answers


class _DeadlineConnection(http.client.HTTPSConnection):
    def __init__(
        self,
        host: str,
        *,
        deadline: float,
        slot: threading.BoundedSemaphore,
        **kwargs: Any,
    ) -> None:
        super().__init__(host, **kwargs)
        self.deadline = deadline
        self.slot = slot
        self.transport: socket.socket | None = None
        self._create_connection = self._connect

    def _connect(self, address: tuple[str, int], *_args: Any) -> socket.socket:
        error: OSError = OSError("HTTPS exchange has no addresses")
        for family, kind, protocol, _, target in _resolve(*address, self.deadline, self.slot):
            _remaining(self.deadline)
            sock = socket.socket(family, kind, protocol)
            self.transport = sock
            try:
                sock.settimeout(_remaining(self.deadline))
                sock.connect(target)
                sock.settimeout(_remaining(self.deadline))
            except OSError as exc:
                sock.close()
                error = exc
            else:
                return sock
        raise error

    def connect(self) -> None:
        super().connect()
        self.transport = self.sock
        _remaining(self.deadline)

    def interrupt(self) -> None:
        if self.transport is not None:
            # A whole-exchange watchdog interrupts HTTP's internal header and body reads,
            # including chunk parsing; inactivity timeouts alone permit an endless drip.
            with contextlib.suppress(OSError):
                self.transport.shutdown(socket.SHUT_RDWR)


class _DeadlineHTTPS(urllib.request.HTTPSHandler):
    handler_order = 499  # Before urllib's default HTTPS handler, retaining the no-redirect opener.

    def __init__(self, deadline: float, slot: threading.BoundedSemaphore) -> None:
        self.context = ssl.create_default_context()
        super().__init__(context=self.context)
        self.deadline = deadline
        self.slot = slot
        self.connections: list[_DeadlineConnection] = []

    def https_open(self, req: urllib.request.Request) -> http.client.HTTPResponse:
        def connection(host: str, **kwargs: Any) -> _DeadlineConnection:
            conn = _DeadlineConnection(host, deadline=self.deadline, slot=self.slot, **kwargs)
            self.connections.append(conn)
            return conn

        return self.do_open(connection, req, context=self.context)

    def interrupt(self) -> None:
        for conn in self.connections:
            conn.interrupt()


class BoundedResponse:
    """The opened response, whose every read is held to the exchange's deadline."""

    def __init__(self, response: Any, deadline: float) -> None:
        self._response = response
        self._deadline = deadline

    @property
    def status(self) -> int:
        return int(self._response.status)

    def read(self, amt: int | None = None) -> bytes:
        raw: bytes = self._response.read(amt)
        # The watchdog ends a drip by shutting the socket, which a body read can see as a short,
        # clean end of data. The deadline check is what turns that into a failure.
        _remaining(self._deadline)
        return raw


@contextlib.contextmanager
def open_bounded(
    opener: urllib.request.OpenerDirector,
    request: urllib.request.Request,
    *,
    timeout: float,
    dns_slot: threading.BoundedSemaphore,
) -> Iterator[BoundedResponse]:
    """Open an HTTPS request with one deadline across DNS, connect, headers and every read.

    A non-HTTPS URL is refused before anything is resolved or connected, so a header the request
    carries never travels in clear text. The opener must not follow redirects or read ambient proxy
    settings; `reach.build_reach_opener` builds one that does neither.
    """
    if urllib.parse.urlsplit(request.full_url).scheme != "https":
        raise ValueError("HTTPS exchange requires an https URL")
    deadline = time.monotonic() + timeout
    handler = _DeadlineHTTPS(deadline, dns_slot)
    opener.add_handler(handler)
    watchdog = threading.Timer(_remaining(deadline), handler.interrupt)
    watchdog.daemon = True
    watchdog.start()
    try:
        with opener.open(request, timeout=_remaining(deadline)) as response:
            yield BoundedResponse(response, deadline)
    finally:
        watchdog.cancel()
        watchdog.join()
