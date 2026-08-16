"""In-process stand-ins for aiohttp's WebSocket, so the client can be tested without a socket.

These fake at the `ClientSession.ws_connect` boundary — the same seam the real integration uses
when Home Assistant hands the client its managed session — rather than mocking aiohttp
internals. That keeps the tests honest about the contract the client actually depends on:
`ws_connect` returns an async context manager, `receive()` yields typed messages, and
`send_str` is how text goes out.

Nothing here sleeps. Delays are recorded, not waited on.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from aiohttp import WSMsgType


@dataclass
class FakeMessage:
    type: WSMsgType
    data: Any = None


def text(payload: str) -> FakeMessage:
    return FakeMessage(WSMsgType.TEXT, payload)


CLOSED = FakeMessage(WSMsgType.CLOSED)
ERROR = FakeMessage(WSMsgType.ERROR)


class FakeWebSocket:
    """One connection's worth of scripted traffic."""

    def __init__(self, incoming: list[FakeMessage] | None = None) -> None:
        self._incoming: list[FakeMessage] = list(incoming or [])
        self.sent: list[str] = []
        self.closed = False
        # Set to hold the read loop open after the script runs out, instead of reporting a
        # disconnect. Used to test a connection that is up but quiet.
        self.hold_open = False
        self._gate = asyncio.Event()

    def feed(self, message: FakeMessage) -> None:
        self._incoming.append(message)
        self._gate.set()

    async def send_str(self, payload: str) -> None:
        if self.closed:
            raise ConnectionResetError("socket is closed")
        self.sent.append(payload)

    async def receive(self) -> FakeMessage:
        while not self._incoming:
            # A closed socket reports the disconnect even when it was holding open, or a test
            # that closes one would simply hang instead of exercising the reconnect.
            if self.closed or not self.hold_open:
                return CLOSED
            self._gate.clear()
            await self._gate.wait()
        return self._incoming.pop(0)

    async def close(self) -> None:
        self.closed = True
        self._gate.set()


class _Connection:
    """What `ws_connect` returns: an async context manager yielding the socket."""

    def __init__(self, socket: FakeWebSocket) -> None:
        self._socket = socket

    async def __aenter__(self) -> FakeWebSocket:
        return self._socket

    async def __aexit__(self, *exc: object) -> None:
        await self._socket.close()


@dataclass
class FakeSession:
    """A `ClientSession` stand-in that hands out scripted connections in order.

    `sockets` is consumed one per connect. When it runs dry the last one repeats, so a
    reconnect test does not have to enumerate every future attempt.
    """

    sockets: list[FakeWebSocket] = field(default_factory=list)
    fail_with: BaseException | None = None
    hang: bool = False
    calls: list[dict[str, Any]] = field(default_factory=list)

    def ws_connect(self, url: str, **kwargs: Any) -> _Connection:
        self.calls.append({"url": url, **kwargs})
        if self.fail_with is not None:
            raise self.fail_with
        if self.hang:
            return _HangingConnection()
        if not self.sockets:
            self.sockets.append(FakeWebSocket())
        socket = self.sockets.pop(0) if len(self.sockets) > 1 else self.sockets[0]
        return _Connection(socket)


class _HangingConnection:
    """Accepts the TCP connection and never completes the upgrade.

    This is the failure that wedged an earlier driver permanently: a unit binds port 80 while
    booting, before `/ws/controller` is live. Without a connect timeout nothing can move the
    client out of this state.
    """

    async def __aenter__(self) -> Any:
        await asyncio.Event().wait()  # never set

    async def __aexit__(self, *exc: object) -> None:
        return None


class RecordingSleeper:
    """Records the delays it was asked for instead of waiting them out.

    Delays listed in `hold` block until `release()` is called for them, which is how a test
    keeps a timer from firing without any real waiting. Everything else returns on the next
    event-loop tick, so nothing in this suite sleeps on a wall clock.
    """

    def __init__(self, hold: set[float] | None = None) -> None:
        self.delays: list[float] = []
        self._hold = set(hold or ())
        self._gates: dict[float, asyncio.Event] = {}

    async def __call__(self, delay: float) -> None:
        self.delays.append(delay)
        if delay in self._hold:
            gate = self._gates.setdefault(delay, asyncio.Event())
            await gate.wait()
            gate.clear()
            return
        await asyncio.sleep(0)  # yield, so the supervisor loop stays cooperative

    def release(self, delay: float) -> None:
        """Let a held delay through, once."""
        self._gates.setdefault(delay, asyncio.Event()).set()
