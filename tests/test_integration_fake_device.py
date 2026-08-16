"""The client against a real socket, with a real aiohttp session and a fake processor.

Everything else in this suite fakes at the `ws_connect` boundary, which is fast and precise but
proves nothing about the parts aiohttp actually performs: the HTTP upgrade, framing, the path,
and how a genuine disconnect surfaces. These tests close that gap by speaking the real protocol
over loopback.

`test_the_handshake_timeout_fires_against_a_socket_that_never_upgrades` is the reason this file
exists. It is the only end-to-end proof of AC-01, and the defect it models — a unit that binds
port 80 while it is still booting, before `/ws/controller` is live — wedged the earlier driver
for this same processor until someone reloaded it by hand. An in-process fake can imitate that;
only a real socket demonstrates it.

These tests use short real timeouts (hundredths of a second) rather than an injected clock,
because the thing under test is aiohttp's own behaviour. The whole file still runs in well under
a second.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import aiohttp
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from fake_htp1 import FakeHtp1

from custom_components.ha_monolith_htp1.htp1.client import (
    Htp1Client,
    Htp1ProtocolError,
    Htp1TimeoutError,
)

# These are the only tests in the suite that open a real socket, and that needs saying out loud.
# `pytest-homeassistant-custom-component` pulls in `pytest-socket`, which blocks socket use by
# default — a good default, since it stops a unit test quietly reaching the network. It also
# means these thirteen tests fail on CI while passing locally, where that plugin is absent.
# Requesting `socket_enabled` re-permits it for this module only, so the block stays in force
# everywhere else.
pytestmark = pytest.mark.enable_socket


@pytest.fixture
async def session(socket_enabled):
    async with aiohttp.ClientSession() as client_session:
        yield client_session


async def _connected(session, fake: FakeHtp1, **kwargs) -> Htp1Client:
    client = Htp1Client(
        session,
        "127.0.0.1",
        port=fake.port,
        seed="integration",
        connect_timeout=2.0,
        flush_delay=0.01,
        **kwargs,
    )
    await client.async_start()
    return client


async def _until(predicate, timeout: float = 2.0) -> bool:
    """Poll a condition without sleeping longer than it takes."""
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(0.005)
    return False


# --------------------------------------------------------------------------------------
# The happy path
# --------------------------------------------------------------------------------------


async def test_connect_get_document_and_disconnect(session):
    async with FakeHtp1() as fake:
        client = await _connected(session, fake)

        assert client.connected is True
        assert client.mirror.loaded is True
        assert client.mirror.get("volume") == -25
        assert client.mirror.get("serial") == "TESTSN9999"
        assert fake.received[0] == "getmso"

        await client.async_stop()
        assert client.connected is False


async def test_a_write_comes_back_as_a_push(session):
    """The real unit echoes every applied change to every connected client."""
    async with FakeHtp1() as fake:
        client = await _connected(session, fake, allow_writes=True)

        await client.async_write("/volume", -33)
        assert await _until(lambda: client.mirror.get("volume") == -33)
        assert client.pending_paths == (), "the echo should have confirmed it"

        await client.async_stop()


async def test_a_front_panel_change_arrives_unrequested(session):
    """Nothing is asked for; the unit simply says what happened. This is why we never poll."""
    async with FakeHtp1() as fake:
        client = await _connected(session, fake)
        heard: list[frozenset[str]] = []
        client.add_listener(heard.append)

        await fake.broadcast([{"op": "replace", "path": "/input", "value": "h2"}])

        assert await _until(lambda: client.mirror.get("input") == "h2")
        assert heard and "input" in heard[0]
        await client.async_stop()


async def test_junk_input_is_rejected_and_the_connection_survives(session):
    async with FakeHtp1() as fake:
        client = await _connected(session, fake)

        await client._ws.send_str("wibble")
        assert await _until(lambda: any(m == "wibble" for m in fake.received))
        await asyncio.sleep(0.05)

        assert client.connected is True, "an error frame must not cost the connection"
        await client.async_stop()


# --------------------------------------------------------------------------------------
# The failure that wedged the previous driver
# --------------------------------------------------------------------------------------


async def test_the_handshake_timeout_fires_against_a_socket_that_never_upgrades(session):
    """AC-01, end to end. The only proof that matters for this defect.

    The port accepts. The upgrade never comes. Without a deadline spanning both, nothing
    internal can move the client out of the connecting state.
    """
    async with FakeHtp1(faults={"accept-tcp-no-upgrade"}) as fake:
        client = Htp1Client(session, "127.0.0.1", port=fake.port, seed="t", connect_timeout=0.25)

        with pytest.raises(Htp1TimeoutError):
            await client.async_start()

        assert client.connected is False
        assert client.reconnecting is False, "a failed setup must not leave a ladder running"


async def test_the_wrong_path_is_refused(session):
    """The unit serves its web UI on the same port; only `/ws/controller` is the control path."""
    async with FakeHtp1() as fake:
        async with session.ws_connect(f"ws://127.0.0.1:{fake.port}/nope") as ws:
            message = await ws.receive()
        assert message.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSED)


# --------------------------------------------------------------------------------------
# Faults
# --------------------------------------------------------------------------------------


async def test_a_document_that_never_decodes_exhausts_the_budget_and_goes_quiet(session):
    """Three re-reads at most, then silence — rather than hammering a unit at line rate."""
    async with FakeHtp1(faults={"garbage"}) as fake:
        client = Htp1Client(session, "127.0.0.1", port=fake.port, seed="t", connect_timeout=2.0)

        with pytest.raises(Htp1ProtocolError):
            # Setup must fail rather than wait for a reply that will never decode. Before the
            # budget was applied here, this hung until Home Assistant's own timeout noticed.
            await asyncio.wait_for(client.async_start(), timeout=2.0)

        await asyncio.sleep(0.1)
        assert fake.received.count("getmso") <= 3, (
            f"expected the budget to cap re-reads, saw {fake.received.count('getmso')}"
        )
        await client.async_stop()


async def test_bare_json_payloads_are_understood(session):
    """Newer firmware reportedly drops the verb prefix. Tolerated, not merely survived."""
    async with FakeHtp1(faults={"bare-json"}) as fake:
        client = await _connected(session, fake)
        assert client.mirror.loaded is True
        assert client.mirror.get("volume") == -25
        await client.async_stop()


async def test_a_container_replace_from_the_wire_rederives_leaves(session):
    async with FakeHtp1(faults={"container-replace"}) as fake:
        client = await _connected(session, fake, allow_writes=True)

        await client.async_write("/cal/lipsync", 120)

        assert await _until(lambda: client.mirror.get("lip_sync") == 120)
        assert client.mirror.get("vpl") == -50, "sibling leaves must survive the container"
        await client.async_stop()


async def test_an_unconfirmed_write_is_rolled_back(session):
    """The unit accepts the change and says nothing. The watchdog is what notices."""
    async with FakeHtp1(faults={"never-confirm"}) as fake:
        client = await _connected(session, fake, allow_writes=True, reconcile_delay=0.15)

        await client.async_write("/volume", -40)
        assert await _until(lambda: client.optimistic("/volume") == -40)

        # The overlay clears first and the re-read lands a moment later, so wait for the
        # corrected value rather than for the rollback alone.
        assert await _until(lambda: client.optimistic("/volume") == -25), (
            "the optimistic value must be given up once the unit says otherwise"
        )
        assert client.pending_paths == ()
        await client.async_stop()


async def test_firmware_without_a_video_block_loses_only_those_fields(session):
    async with FakeHtp1(faults={"no-videostat"}) as fake:
        client = await _connected(session, fake)
        assert client.mirror.has("video_resolution") is False
        assert client.mirror.get("volume") == -25, "everything else must still work"
        await client.async_stop()


async def test_a_unit_without_a_serial_still_connects(session):
    """A missing serial must not refuse a unit that otherwise works."""
    async with FakeHtp1(faults={"no-serial"}) as fake:
        client = await _connected(session, fake)
        assert client.mirror.loaded is True
        assert client.mirror.get("serial") is None
        await client.async_stop()


async def test_a_dropped_connection_is_re_established(session):
    """The fake hangs up after answering; the client must come back on its own."""
    async with FakeHtp1(faults={"close-after-document"}) as fake:
        client = Htp1Client(
            session,
            "127.0.0.1",
            port=fake.port,
            seed="t",
            connect_timeout=2.0,
            backoff=(0.05,),
            jitter_ratio=0.0,
        )
        await client.async_start()

        assert await _until(lambda: fake.received.count("getmso") >= 3, timeout=3.0), (
            f"expected repeated reconnects, saw {fake.received.count('getmso')}"
        )
        await client.async_stop()
