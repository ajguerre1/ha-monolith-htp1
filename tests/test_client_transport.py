"""Staying connected: handshake timeout, backoff, and the start/stop contract.

The single most important test here is the handshake timeout. The HTP-1 binds port 80 while it
is still booting, before `/ws/controller` is live, so a client can complete a TCP connection and
then wait forever for an upgrade that is never coming. In the Control4 driver for this same
device that was a Critical defect: nothing internal could leave the connecting state, so a unit
rebooting wedged the driver until someone reloaded it by hand.

The second is that `async_start` makes exactly one attempt. Home Assistant already owns
setup-time retry via `ConfigEntryNotReady`, and a client that starts its own ladder during setup
gives the system two competing backoff loops that know nothing about each other.

No test here waits on a real timer. Backoff delays are recorded by an injected sleeper, and the
connect timeout is set small enough to fire immediately while the shipped default stays 15 s.
"""

from __future__ import annotations

import ast
import asyncio
import inspect
import random

import pytest
from fakes import CLOSED, FakeSession, FakeWebSocket, RecordingSleeper, text

from custom_components.ha_monolith_htp1.htp1 import client as client_module
from custom_components.ha_monolith_htp1.htp1.client import (
    Htp1Client,
    Htp1ConnectionError,
    Htp1TimeoutError,
)

DOCUMENT = 'mso {"volume":-25,"muted":false,"powerIsOn":true,"cal":{"vpl":-50,"vph":0}}'


def _client(session, **kwargs) -> Htp1Client:
    kwargs.setdefault("seed", "test")
    kwargs.setdefault("sleep", RecordingSleeper())
    return Htp1Client(session, "10.0.0.1", **kwargs)


async def _quiet_socket(*messages: str) -> FakeWebSocket:
    socket = FakeWebSocket([text(m) for m in messages])
    socket.hold_open = True
    return socket


# --------------------------------------------------------------------------------------
# Connecting
# --------------------------------------------------------------------------------------


async def test_connecting_asks_for_the_document_and_loads_it():
    socket = await _quiet_socket(DOCUMENT)
    client = _client(FakeSession([socket]))

    await client.async_start()

    assert socket.sent == ["getmso"]
    assert client.connected is True
    assert client.mirror.loaded is True
    assert client.mirror.get("volume") == -25
    await client.async_stop()


async def test_the_url_is_the_controller_endpoint_on_port_eighty():
    """No TLS, no auth, and the path is enforced server-side."""
    session = FakeSession([await _quiet_socket(DOCUMENT)])
    client = _client(session)
    await client.async_start()
    assert session.calls[0]["url"] == "ws://10.0.0.1:80/ws/controller"
    await client.async_stop()


async def test_the_heartbeat_is_configured_on_the_socket():
    """aiohttp derives its pong deadline as heartbeat/2, verified in 3.14.3 client_ws.py:93."""
    session = FakeSession([await _quiet_socket(DOCUMENT)])
    client = _client(session, heartbeat=30.0)
    await client.async_start()
    assert session.calls[0]["heartbeat"] == 30.0
    await client.async_stop()


async def test_a_refused_connection_raises_rather_than_retrying():
    session = FakeSession(fail_with=OSError("connection refused"))
    sleeper = RecordingSleeper()
    client = _client(session, sleep=sleeper)

    with pytest.raises(Htp1ConnectionError):
        await client.async_start()

    assert client.connected is False
    assert sleeper.delays == [], "setup must not start a backoff ladder; Home Assistant owns retry"


async def test_a_socket_that_never_upgrades_times_out():
    """The Critical defect from the Control4 driver, reproduced.

    Port 80 accepts while the unit boots; `/ws/controller` is not live yet. Without this
    timeout nothing can move the client out of the connecting state.
    """
    session = FakeSession(hang=True)
    client = _client(session, connect_timeout=0.02)

    with pytest.raises(Htp1TimeoutError):
        await client.async_start()

    assert client.connected is False


async def test_the_shipped_connect_timeout_is_fifteen_seconds():
    """The tests use a small value; the default must remain the measured one."""
    assert client_module.DEFAULT_CONNECT_TIMEOUT == 15.0


async def test_a_connection_that_drops_before_the_document_raises():
    socket = FakeWebSocket([CLOSED])
    client = _client(FakeSession([socket]))

    with pytest.raises(Htp1ConnectionError):
        await client.async_start()

    assert client.connected is False


# --------------------------------------------------------------------------------------
# The start and stop contract
# --------------------------------------------------------------------------------------


async def test_start_makes_one_attempt_and_raises():
    """Two competing backoff loops is a design smell; Home Assistant owns setup retry."""
    session = FakeSession(fail_with=OSError("unreachable"))
    client = _client(session)

    with pytest.raises(Htp1ConnectionError):
        await client.async_start()

    assert len(session.calls) == 1


async def test_the_reconnect_ladder_only_starts_after_the_first_document():
    socket = await _quiet_socket(DOCUMENT)
    session = FakeSession([socket])
    client = _client(session)

    assert client.reconnecting is False
    await client.async_start()
    assert client.reconnecting is True
    await client.async_stop()
    assert client.reconnecting is False


async def test_stop_is_idempotent():
    client = _client(FakeSession([await _quiet_socket(DOCUMENT)]))
    await client.async_start()
    await client.async_stop()
    await client.async_stop()
    assert client.connected is False


async def test_stop_before_start_is_harmless():
    client = _client(FakeSession())
    await client.async_stop()
    assert client.connected is False


async def test_stopping_closes_the_socket():
    socket = await _quiet_socket(DOCUMENT)
    client = _client(FakeSession([socket]))
    await client.async_start()
    await client.async_stop()
    assert socket.closed is True


async def test_stop_leaves_no_task_running():
    """A supervisor that outlives the entry would keep reconnecting to a removed device."""
    client = _client(FakeSession([await _quiet_socket(DOCUMENT)]))
    await client.async_start()
    await client.async_stop()
    await asyncio.sleep(0)
    assert not [t for t in asyncio.all_tasks() if t is not asyncio.current_task() and not t.done()]


# --------------------------------------------------------------------------------------
# Reconnection
# --------------------------------------------------------------------------------------


async def test_a_dropped_connection_is_re_established_and_re_read():
    """The document is requested again: state after a gap cannot be assumed unchanged."""
    first = FakeWebSocket([text(DOCUMENT), CLOSED])
    second = await _quiet_socket(DOCUMENT)
    session = FakeSession([first, second])
    sleeper = RecordingSleeper()
    client = _client(session, sleep=sleeper)

    await client.async_start()
    for _ in range(20):  # let the supervisor notice and reconnect
        await asyncio.sleep(0)

    assert len(session.calls) >= 2
    assert second.sent == ["getmso"]
    assert sleeper.delays, "a reconnect must be delayed, not immediate"
    await client.async_stop()


async def test_the_backoff_ladder_climbs_and_caps():
    delays = _client(FakeSession()).backoff_schedule(8)
    nominal = [2, 4, 8, 16, 30, 60, 60, 60]
    for actual, expected in zip(delays, nominal, strict=True):
        assert 0.8 * expected <= actual <= 1.2 * expected, f"{actual} is outside ±20% of {expected}"


async def test_jitter_actually_varies_the_delay():
    """Fixed delays would make several units reconnect in lockstep after one network blip."""
    delays = _client(FakeSession()).backoff_schedule(20)
    assert len(set(delays)) > 1


async def test_two_clients_do_not_reconnect_in_lockstep():
    """Unseeded RNG made two Control4 driver instances reconnect together after every blip."""
    one = Htp1Client(FakeSession(), "10.0.0.1", seed="unit-one").backoff_schedule(10)
    two = Htp1Client(FakeSession(), "10.0.0.2", seed="unit-two").backoff_schedule(10)
    assert one != two


async def test_the_same_seed_is_reproducible():
    one = Htp1Client(FakeSession(), "10.0.0.1", seed="same").backoff_schedule(10)
    two = Htp1Client(FakeSession(), "10.0.0.1", seed="same").backoff_schedule(10)
    assert one == two


async def test_the_ladder_resets_after_a_successful_connection():
    """Otherwise a unit that flaps once sits at the 60 s cap for the rest of the day."""
    client = _client(FakeSession([await _quiet_socket(DOCUMENT)]))
    client.note_failure()
    client.note_failure()
    assert client.backoff_index == 2
    await client.async_start()
    assert client.backoff_index == 0
    await client.async_stop()


def _calls_in(source: str) -> set[str]:
    """Dotted names of every call in `source`, by AST.

    Not a substring search. This module's own docstring contains the words `random.seed()` as a
    warning, and grepping for them would flag the very comment explaining why they are absent.
    """
    names: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
            names.add(f"{func.value.id}.{func.attr}")
        elif isinstance(func, ast.Name):
            names.add(func.id)
    return names


def test_the_call_detector_actually_detects():
    """Prove the guard below can fail before trusting it."""
    assert "random.seed" in _calls_in("import random\nrandom.seed(1)")
    assert "random.seed" not in _calls_in('"""Never call random.seed() here."""')


def test_the_module_never_seeds_the_global_random_generator():
    """`random.seed()` in a library mutates global state for every other integration in HA."""
    calls = _calls_in(inspect.getsource(client_module))
    assert "random.seed" not in calls
    assert "random.Random" in calls, "backoff jitter must come from a per-client generator"


def test_the_client_does_not_touch_module_level_random():
    """Belt and braces for the test above: exercise it and prove global state is untouched."""
    random.seed(1234)
    expected = random.random()
    random.seed(1234)
    Htp1Client(FakeSession(), "10.0.0.1", seed="anything").backoff_schedule(50)
    assert random.random() == expected
