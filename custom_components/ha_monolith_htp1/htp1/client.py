"""The HTP-1 client: the only module here that holds a socket, a timer or a task.

Everything above it sees `connected`, a mirror, and (from T6) a change callback.

Two behaviours in this file exist because of specific defects in the Control4 driver for this
same processor, and neither is optional:

**The connect timeout covers the handshake, not just the TCP connect.** The unit binds port 80
while it is still booting, before `/ws/controller` is live. Without a deadline spanning both,
nothing internal can move the client out of the connecting state and it waits forever. That was
a Critical finding there, and it needed a driver reload to clear.

**Backoff jitter comes from a per-client `random.Random`.** Never `random.seed()`: a library
that seeds the global generator mutates state for every other integration in the process.
Unseeded generation is worse still — it is what made two driver instances reconnect in lockstep
after every network blip.

The start contract is deliberately split. `async_start` makes **one** attempt and raises, so
Home Assistant owns setup-time retry through `ConfigEntryNotReady`; the client's own indefinite
ladder begins only once a first document has arrived. Two competing backoff loops that know
nothing about each other is a design smell, not redundancy.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import random
from collections.abc import Awaitable, Callable
from typing import Any

from aiohttp import WSMsgType

from . import protocol
from .mso import MsoMirror

_LOGGER = logging.getLogger(__name__)

DEFAULT_CONNECT_TIMEOUT = 15.0
DEFAULT_HEARTBEAT = 30.0
DEFAULT_BACKOFF: tuple[float, ...] = (2.0, 4.0, 8.0, 16.0, 30.0, 60.0)
DEFAULT_JITTER_RATIO = 0.2

WS_PORT = 80
WS_PATH = "/ws/controller"

_DISCONNECTED = frozenset({WSMsgType.CLOSE, WSMsgType.CLOSING, WSMsgType.CLOSED, WSMsgType.ERROR})


class Htp1Error(Exception):
    """Base for every failure this client reports."""


class Htp1ConnectionError(Htp1Error):
    """The unit could not be reached, or the link dropped."""


class Htp1TimeoutError(Htp1Error):
    """The connection or the WebSocket handshake did not complete in time."""


class Htp1ProtocolError(Htp1Error):
    """The unit said something this client could not decode."""


class Htp1WriteError(Htp1Error):
    """A write was refused before anything was sent."""


class Htp1Client:
    """One connection to one processor."""

    def __init__(
        self,
        session: Any,
        host: str,
        *,
        seed: Any = None,
        allow_writes: bool = False,
        connect_timeout: float = DEFAULT_CONNECT_TIMEOUT,
        heartbeat: float = DEFAULT_HEARTBEAT,
        backoff: tuple[float, ...] = DEFAULT_BACKOFF,
        jitter_ratio: float = DEFAULT_JITTER_RATIO,
        sleep: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        self._session = session
        self._host = host
        self._allow_writes = allow_writes
        self._connect_timeout = connect_timeout
        self._heartbeat = heartbeat
        self._backoff = backoff
        self._jitter_ratio = jitter_ratio
        self._sleep = sleep or asyncio.sleep

        # Per-client generator. Seeding the global one would be a house-wide side effect.
        self._rng = random.Random(seed if seed is not None else host)

        self._mirror = MsoMirror()
        self._connection: Any = None
        self._ws: Any = None
        self._task: asyncio.Task[None] | None = None
        self._running = False
        self._backoff_index = 0

    # -- properties ----------------------------------------------------------------------

    @property
    def host(self) -> str:
        return self._host

    @property
    def url(self) -> str:
        return f"ws://{self._host}:{WS_PORT}{WS_PATH}"

    @property
    def connected(self) -> bool:
        return self._ws is not None

    @property
    def reconnecting(self) -> bool:
        """Whether the supervisor is running, i.e. a drop would be retried."""
        return self._task is not None and not self._task.done()

    @property
    def mirror(self) -> MsoMirror:
        return self._mirror

    @property
    def allow_writes(self) -> bool:
        return self._allow_writes

    # -- lifecycle -----------------------------------------------------------------------

    async def async_start(self, *, wait_for_first_document: bool = True) -> None:
        """Connect once, read the first document, then hand over to the supervisor.

        Raises rather than retrying. Home Assistant maps that onto `ConfigEntryNotReady` and
        owns the retry cadence from there.
        """
        if self._running:
            return
        self._running = True
        try:
            await self._connect()
            if wait_for_first_document:
                await self._read_until_document()
        except BaseException:
            self._running = False
            await self._teardown()
            raise
        self._backoff_index = 0
        self._task = asyncio.create_task(self._supervise())

    async def async_stop(self) -> None:
        """Idempotent. Must never block Home Assistant's shutdown."""
        self._running = False
        task, self._task = self._task, None
        if task is not None and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        await self._teardown()

    # -- backoff -------------------------------------------------------------------------

    def _backoff_schedule(self, count: int) -> list[float]:
        """The next `count` delays, without connecting and **without side effects**.

        The generator is snapshotted and restored, so previewing the ladder cannot change the
        delays a real reconnect will use. That matters because the obvious future caller is a
        diagnostics dump — "next retry in about N seconds" is exactly what belongs in one — and
        a preview that quietly perturbs the thing it is previewing is a trap.
        """
        state = self._rng.getstate()
        try:
            index, delays = self._backoff_index, []
            for _ in range(count):
                delays.append(self._jittered(self._backoff[min(index, len(self._backoff) - 1)]))
                index += 1
            return delays
        finally:
            self._rng.setstate(state)

    def _note_failure(self) -> None:
        self._backoff_index += 1

    def _jittered(self, delay: float) -> float:
        low = 1.0 - self._jitter_ratio
        return delay * (low + self._rng.random() * (self._jitter_ratio * 2))

    def _next_delay(self) -> float:
        delay = self._jittered(self._backoff[min(self._backoff_index, len(self._backoff) - 1)])
        self._backoff_index += 1
        return delay

    # -- connection ----------------------------------------------------------------------

    async def _connect(self) -> None:
        """Open the socket and request the document.

        The timeout spans the connect *and* the upgrade, which is the whole point: a unit that
        accepts TCP and never upgrades is the failure this guards.
        """
        try:
            async with asyncio.timeout(self._connect_timeout):
                self._connection = self._session.ws_connect(self.url, heartbeat=self._heartbeat)
                self._ws = await self._connection.__aenter__()
        except TimeoutError as err:
            self._connection = self._ws = None
            raise Htp1TimeoutError(
                f"no WebSocket upgrade from {self._host} within {self._connect_timeout}s"
            ) from err
        except Htp1Error:
            raise
        except Exception as err:
            self._connection = self._ws = None
            raise Htp1ConnectionError(f"cannot reach {self._host}: {err}") from err

        self._backoff_index = 0
        await self._request_document()

    async def _request_document(self) -> None:
        try:
            await self._ws.send_str(protocol.encode_get_mso())
        except Exception as err:
            raise Htp1ConnectionError(f"cannot talk to {self._host}: {err}") from err

    async def _read_until_document(self) -> None:
        while True:
            message = await self._receive()
            if message is None:
                raise Htp1ConnectionError(
                    f"{self._host} closed the connection before sending a document"
                )
            if message.kind is protocol.MessageKind.DOCUMENT:
                self._mirror.apply_document(message.document)
                return

    async def _receive(self) -> protocol.ParsedMessage | None:
        """One decoded frame, or None when the link is gone."""
        try:
            raw = await self._ws.receive()
        except Exception:
            return None
        if raw.type in _DISCONNECTED:
            return None
        if raw.type is not WSMsgType.TEXT:
            # Binary frames are not part of this protocol.
            return protocol.ParsedMessage(kind=protocol.MessageKind.UNKNOWN)
        return protocol.parse_message(raw.data)

    async def _read_loop(self) -> None:
        """Consume pushes until the link goes away. Extended with the parse budget in T6."""
        while self._running:
            message = await self._receive()
            if message is None:
                return
            if message.kind is protocol.MessageKind.DOCUMENT:
                self._mirror.apply_document(message.document)
            elif message.kind is protocol.MessageKind.UPDATE:
                self._mirror.apply_ops(message.ops)

    async def _supervise(self) -> None:
        """Keep the connection up for the life of the entry."""
        try:
            await self._read_loop()
            while self._running:
                await self._teardown()
                await self._sleep(self._next_delay())
                if not self._running:
                    return
                try:
                    await self._connect()
                except Htp1Error as err:
                    _LOGGER.debug("reconnect to %s failed: %s", self._host, err)
                    continue
                await self._read_loop()
        except asyncio.CancelledError:
            raise
        finally:
            await self._teardown()

    async def _teardown(self) -> None:
        connection, self._connection = self._connection, None
        self._ws = None
        if connection is not None:
            with contextlib.suppress(Exception):
                await connection.__aexit__(None, None, None)
